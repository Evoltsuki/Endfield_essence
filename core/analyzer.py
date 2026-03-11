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

    def clean_csv_text(self, raw):
        if not raw: return ""
        txt = self.cc.convert(str(raw))
        return re.sub(r'[^\u4e00-\u9fff]', '', txt)

    def check_all_attributes(self, weapon_list, skills, levels):
        # 返回值变更为：(是否保留, [(武器名, 星级), ...], 匹配类型)
        if not skills: return False, [], ""

        matched_weapons = []

        # 1. 遍历匹配所有毕业武器
        for weapon in weapon_list:
            ts = [self.clean_csv_text(weapon.get(f'毕业词条{i}', '')) for i in range(1, 4) if
                  weapon.get(f'毕业词条{i}', '')]
            if not ts: continue
            h_hits, p_hits, m_idx = 0, 0, set()
            for t in ts:
                t_c = t.replace("提升", "")
                best_r, b_idx = 0, -1
                for i, p in enumerate(skills):
                    if i in m_idx: continue
                    r = difflib.SequenceMatcher(None, t_c, p.replace("提升", "")).ratio()
                    if r > best_r: best_r, b_idx = r, i
                if best_r >= 0.85:
                    h_hits += 1; m_idx.add(b_idx)
                elif best_r >= 0.6:
                    p_hits += 1; m_idx.add(b_idx)

            # 如果匹配成功，不再直接 return，而是加入收集列表
            if (h_hits == len(ts)) or (h_hits >= len(ts) - 1 and (h_hits + p_hits) >= len(ts)):
                matched_weapons.append((weapon.get('武器', '未知'), str(weapon.get('星级', '6星'))))

        # 如果收集到了哪怕一把毕业武器，就返回
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
            strip = bgr[int(h * 0.70):, :]
            hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([15, 100, 100]), np.array([35, 255, 255]))
            return (np.sum(mask > 0) / mask.size) > 0.05
        except:
            return False

    def _template_match(self, window_img, pos, template_name, scale_x, scale_y):
        """内部通用模板匹配函数"""
        try:
            template_path = resource_path(os.path.join("img", template_name))
            template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
            if template is None: return False
            if scale_x != 1.0 or scale_y != 1.0:
                template = cv2.resize(template, None, fx=scale_x, fy=scale_y, interpolation=cv2.INTER_LINEAR)

            th, tw = template.shape[:2]
            lx, ly = int(pos[0]), int(pos[1])
            search_margin_x, search_margin_y = int(40 * scale_x), int(40 * scale_y)
            y1, y2 = max(0, ly - search_margin_y), min(window_img.shape[0], ly + search_margin_y)
            x1, x2 = max(0, lx - search_margin_x), min(window_img.shape[1], lx + search_margin_x)

            scope_gray = cv2.cvtColor(window_img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
            if scope_gray.shape[0] < th or scope_gray.shape[1] < tw: return False

            res = cv2.matchTemplate(scope_gray, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            return max_val > 0.85
        except:
            return False

    def is_already_locked_bg(self, window_img, lock_pos, scale_x=1.0, scale_y=1.0):
        return self._template_match(window_img, lock_pos, "LockButtonLocked.png", scale_x, scale_y)

    def is_already_discarded_bg(self, window_img, discard_pos, scale_x=1.0, scale_y=1.0):
        return self._template_match(window_img, discard_pos, "DiscardButtonDiscarded.png", scale_x, scale_y)