import os
import cv2
import numpy as np
import re
import difflib
from rapidocr_onnxruntime import RapidOCR
from opencc import OpenCC
from tkinter import messagebox

# 引入路径解析，确保能找到 img 文件夹
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
        """智能解析 OCR 结果，分离词条名与等级，并生成规范的展示文本"""
        if not res:
            return "", [], []

        skills = []
        levels = []

        for line in res:
            txt = self.cc.convert(str(line[1]))

            if self.dm.corrections:
                for w in sorted(self.dm.corrections.keys(), key=len, reverse=True):
                    txt = txt.replace(w, self.dm.corrections[w])

            skill_name = re.sub(r'[^\u4e00-\u9fff]', '', txt)
            if skill_name:
                skills.append(skill_name)

            nums = re.findall(r'[+＋]?(\d)', txt)
            for n in nums:
                if 1 <= int(n) <= 6:
                    levels.append(int(n))

        display_parts = []
        for i in range(max(len(skills), len(levels))):
            s = skills[i] if i < len(skills) else ""
            l = str(levels[i]) if i < len(levels) else ""
            if s or l:
                display_parts.append(f"{s}{l}")

        display_str = "，".join(display_parts)
        return display_str, skills, levels

    def clean_csv_text(self, raw):
        if not raw: return ""
        txt = self.cc.convert(str(raw))
        return re.sub(r'[^\u4e00-\u9fff]', '', txt)

    def check_all_attributes(self, weapon_list, skills, levels):
        """综合判定引擎：返回 (是否保留, 武器名/潜力基质, 匹配类型)"""
        if not skills:
            return False, "", ""

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
                    if r > best_r:
                        best_r, b_idx = r, i
                if best_r >= 0.85:
                    h_hits += 1;
                    m_idx.add(b_idx)
                elif best_r >= 0.6:
                    p_hits += 1;
                    m_idx.add(b_idx)

            if (h_hits == len(ts)) or (h_hits >= len(ts) - 1 and (h_hits + p_hits) >= len(ts)):
                return True, weapon.get('武器', '未知'), "graduation"

        if sum(levels) >= 6:
            return True, "潜力基质", "potential"

        if len(levels) >= 3 and levels[-1] >= 3:
            return True, "潜力基质", "potential"

        return False, "", ""

    def is_gold(self, bgr):
        try:
            h, w = bgr.shape[:2]
            strip = bgr[int(h * 0.70):, :]
            hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([15, 100, 100]), np.array([35, 255, 255]))
            return (np.sum(mask > 0) / mask.size) > 0.05
        except:
            return False

    def is_already_locked_bg(self, window_img, lock_pos, scale_x=1.0, scale_y=1.0):
        """采用 MAA 官方模板图，加入动态分辨率缩放的终极判定"""
        try:
            template_path = resource_path(os.path.join("img", "LockButtonLocked.png"))
            if not os.path.exists(template_path):
                print(f"[警告] 找不到锁定模板图: {template_path}")
                return False

            # 以灰度图模式读取模板，降低色彩干扰
            template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
            if template is None:
                return False

            # 【核心】：将 720p 的 MAA 模板放大/缩小至当前游戏分辨率！
            if scale_x != 1.0 or scale_y != 1.0:
                template = cv2.resize(template, None, fx=scale_x, fy=scale_y, interpolation=cv2.INTER_LINEAR)

            th, tw = template.shape[:2]
            lx, ly = int(lock_pos[0]), int(lock_pos[1])

            # 根据缩放比例动态计算搜索边距
            search_margin_x = int(30 * scale_x)
            search_margin_y = int(30 * scale_y)

            # 截取搜索区域，防止越界
            y1, y2 = max(0, ly - search_margin_y), min(window_img.shape[0], ly + search_margin_y)
            x1, x2 = max(0, lx - search_margin_x), min(window_img.shape[1], lx + search_margin_x)

            search_scope = window_img[y1:y2, x1:x2]

            # 如果截出来的区域比模板还小，说明坐标异常，直接返回 False
            if search_scope.shape[0] < th or search_scope.shape[1] < tw:
                return False

            # 将游戏画面也转为灰度图进行模板比对
            search_scope_gray = cv2.cvtColor(search_scope, cv2.COLOR_BGR2GRAY)

            # 采用 TM_CCOEFF_NORMED 算法，该算法对画面整体亮度变化极其宽容
            res = cv2.matchTemplate(search_scope_gray, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)

            # MAA 官方判定标准：相似度超过 0.85 即视为已锁定
            return max_val > 0.85
        except Exception as e:
            print(f"锁定判断异常: {e}")
            return False

    def is_already_discarded_bg(self, window_img, discard_pos, scale_x=1.0, scale_y=1.0):
        """新增：采用 OpenCV 模板匹配判断是否已被标记为废弃"""
        try:
            # 读取已废弃的模板图 DiscardButtonDiscarded.png
            template_path = resource_path(os.path.join("img", "DiscardButtonDiscarded.png"))
            if not os.path.exists(template_path):
                print(f"[警告] 找不到废弃模板图: {template_path}")
                return False

            template = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
            if template is None:
                return False

            if scale_x != 1.0 or scale_y != 1.0:
                template = cv2.resize(template, None, fx=scale_x, fy=scale_y, interpolation=cv2.INTER_LINEAR)

            th, tw = template.shape[:2]
            lx, ly = int(discard_pos[0]), int(discard_pos[1])

            search_margin_x = int(30 * scale_x)
            search_margin_y = int(30 * scale_y)

            y1, y2 = max(0, ly - search_margin_y), min(window_img.shape[0], ly + search_margin_y)
            x1, x2 = max(0, lx - search_margin_x), min(window_img.shape[1], lx + search_margin_x)

            search_scope = window_img[y1:y2, x1:x2]
            if search_scope.shape[0] < th or search_scope.shape[1] < tw:
                return False

            search_scope_gray = cv2.cvtColor(search_scope, cv2.COLOR_BGR2GRAY)
            res = cv2.matchTemplate(search_scope_gray, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)

            # 相似度超过 0.85 即视为已废弃
            return max_val > 0.85
        except Exception as e:
            print(f"废弃判断异常: {e}")
            return False