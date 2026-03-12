import os
import cv2
import numpy as np
import re
import difflib
from rapidocr_onnxruntime import RapidOCR
from opencc import OpenCC
from tkinter import messagebox
from utils.sys_helper import resource_path


class VisionAnalyzer:
    def __init__(self, data_manager):
        self.dm = data_manager
        try:
            self.ocr = RapidOCR(intra_op_num_threads=4)
            self.cc = OpenCC('t2s')
        except Exception as e:
            messagebox.showerror("初始化失败", str(e))

    def parse_ocr_lines(self, res):
        if not res: return "", [], []
        skills, levels = [], []
        for line in res:
            txt = self.cc.convert(str(line[1]))
            if self.dm.corrections:
                for w in sorted(self.dm.corrections.keys(), key=len, reverse=True):
                    txt = txt.replace(w, self.dm.corrections[w])
            skill_name = re.sub(r'[^\u4e00-\u9fff]', '', txt)
            if skill_name: skills.append(skill_name)
            nums = re.findall(r'[+＋]?(\d)', txt)
            for n in nums:
                if 1 <= int(n) <= 6: levels.append(int(n))
        display_parts = []
        for i in range(max(len(skills), len(levels))):
            s, l = (skills[i] if i < len(skills) else ""), (str(levels[i]) if i < len(levels) else "")
            if s or l: display_parts.append(f"{s}{l}")
        return " ".join(display_parts), skills, levels

    def recognize_and_parse(self, roi_img):
        """【核心优化】：OCR 极速预处理，去除了累赘的灰度转换，采用三次插值抗锯齿"""
        if roi_img is None or roi_img.size == 0:
            return "", [], []
        # 直接对彩图进行三次插值放大，文字边缘更平滑，显著提升 RapidOCR 的精准度
        upscaled = cv2.resize(roi_img, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
        res, _ = self.ocr(upscaled)
        return self.parse_ocr_lines(res)

    def clean_csv_text(self, raw):
        if not raw: return ""
        txt = self.cc.convert(str(raw))
        return re.sub(r'[^\u4e00-\u9fff]', '', txt)

    def check_all_attributes(self, weapon_list, skills, levels):
        if not skills: return False, [], ""
        matched_weapons = []

        # 预先清理当前技能名称，去除“提升”，加快比对速度
        cleaned_skills = [s.replace("提升", "") for s in skills]

        # 1. 遍历匹配所有毕业武器
        for weapon in weapon_list:
            ts = [self.clean_csv_text(weapon.get(f'毕业词条{i}', '')).replace("提升", "")
                  for i in range(1, 4) if weapon.get(f'毕业词条{i}', '')]
            if not ts: continue

            h_hits, p_hits = 0, 0
            m_idx = set()

            for t_c in ts:
                best_r, b_idx = 0, -1
                for i, p in enumerate(cleaned_skills):
                    if i in m_idx: continue
                    # 【核心优化】：先使用极速子串匹配
                    if t_c in p or p in t_c:
                        best_r, b_idx = 1.0, i
                        break
                    # 如果没有直接包含，再使用 difflib 进行兜底运算
                    r = difflib.SequenceMatcher(None, t_c, p).ratio()
                    if r > best_r: best_r, b_idx = r, i

                if best_r >= 0.85:
                    h_hits += 1;
                    m_idx.add(b_idx)
                elif best_r >= 0.6:
                    p_hits += 1;
                    m_idx.add(b_idx)

            if (h_hits == len(ts)) or (h_hits >= len(ts) - 1 and (h_hits + p_hits) >= len(ts)):
                matched_weapons.append((weapon.get('武器', '未知'), str(weapon.get('星级', '6星'))))

        if matched_weapons:
            return True, matched_weapons, "graduation"

        # 2. 如果不是毕业武器，再进行潜力判定
        has_two_char_skill = any(len(s) == 2 for s in skills)
        if sum(levels) >= 6 and has_two_char_skill:
            return True, [("潜力基质", "5星")], "potential"

        for s, l in zip(skills, levels):
            if len(s) == 2 and l == 3:
                return True, [("潜力基质", "5星")], "potential"

        return False, [], ""

    def is_gold(self, bgr):
        try:
            h, w = bgr.shape[:2]
            strip = bgr[int(h * 0.75):, :]
            hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([15, 100, 100]), np.array([35, 255, 255]))
            return (np.sum(mask > 0) / mask.size) > 0.05
        except:
            return False

    def _template_match(self, window_img, pos, template_name, scale):
        try:
            template_path = resource_path(os.path.join("img", template_name))
            template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
            if template is None: return False
            if scale != 1.0:
                template = cv2.resize(template, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)

            th, tw = template.shape[:2]
            lx, ly = int(pos[0]), int(pos[1])
            search_margin = int(40 * scale)
            y1, y2 = max(0, ly - search_margin), min(window_img.shape[0], ly + search_margin)
            x1, x2 = max(0, lx - search_margin), min(window_img.shape[1], lx + search_margin)

            scope_gray = cv2.cvtColor(window_img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
            if scope_gray.shape[0] < th or scope_gray.shape[1] < tw: return False

            res = cv2.matchTemplate(scope_gray, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            return max_val > 0.85
        except:
            return False

    def find_essences_with_mask(self, window_img, roi, scale):
        try:
            template_path = resource_path(os.path.join("img", "EssenceGeneral.png"))
            template_bgr = cv2.imread(template_path, cv2.IMREAD_COLOR)
            if template_bgr is None: return []

            if scale != 1.0:
                template_bgr = cv2.resize(template_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)

            lower_green, upper_green = np.array([0, 240, 0]), np.array([10, 255, 10])
            green_mask = cv2.inRange(template_bgr, lower_green, upper_green)
            valid_mask = cv2.bitwise_not(green_mask)

            rx, ry, rw, rh = roi
            sh, sw = window_img.shape[:2]
            search_area = window_img[max(0, ry):min(sh, ry + rh), max(0, rx):min(sw, rx + rw)]

            if search_area.shape[0] < template_bgr.shape[0] or search_area.shape[1] < template_bgr.shape[1]:
                return []

            res = cv2.matchTemplate(search_area, template_bgr, cv2.TM_CCORR_NORMED, mask=valid_mask)
            threshold = 0.90
            loc = np.where(res >= threshold)

            th, tw = template_bgr.shape[:2]
            boxes = [[pt[0] + rx, pt[1] + ry, pt[0] + rx + tw, pt[1] + ry + th] for pt in zip(*loc[::-1])]

            boxes = sorted(boxes, key=lambda x: (x[1], x[0]))
            final_boxes = []
            for b in boxes:
                cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
                keep = True
                for fb in final_boxes:
                    fcx, fcy = (fb[0] + fb[2]) // 2, (fb[1] + fb[3]) // 2
                    if abs(cx - fcx) < tw // 2 and abs(cy - fcy) < th // 2:
                        keep = False
                        break
                if keep: final_boxes.append(b)

            final_boxes.sort(key=lambda b: (b[1] // (th // 2), b[0]))
            return final_boxes

        except Exception as e:
            print(f"模板匹配出错: {e}")
            return []

    def is_already_locked_bg(self, window_img, lock_pos, scale):
        return self._template_match(window_img, lock_pos, "LockButtonLocked.png", scale)

    def is_already_discarded_bg(self, window_img, discard_pos, scale):
        return self._template_match(window_img, discard_pos, "DiscardButtonDiscarded.png", scale)