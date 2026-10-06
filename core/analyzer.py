import os
from functools import lru_cache
import cv2
import numpy as np
import re
import difflib
from rapidocr_onnxruntime import RapidOCR
from opencc import OpenCC
from tkinter import messagebox
from utils.sys_helper import resource_path
from core.selection import target_is_selected
from core.ocr_regions import text_regions

def cv_imread(file_path, flags=cv2.IMREAD_COLOR):
    """支持中文路径"""
    try:
        img_data = np.fromfile(file_path, dtype=np.uint8)
        if img_data.size == 0:
            return None
        return cv2.imdecode(img_data, flags)
    except Exception as e:
        print(f"读取图片异常: {e}")
        return None

class VisionAnalyzer:
    def __init__(self, data_manager):
        self.dm = data_manager
        self._cached_weapon_list_id = None
        self._cleaned_weapons_cache = []

        try:
            # 初始化 OCR 引擎并配置底层优化参数
            self.ocr = RapidOCR(
                intra_op_num_threads=4,
                det_limit_side_len=640,
                det_limit_type='max',
                det_unclip_ratio=2.5,
                det_box_thresh=0.3
            )
            self.cc = OpenCC('t2s')
        except Exception as e:
            messagebox.showerror("初始化失败", str(e))

    @lru_cache(maxsize=64)
    def _template(self, name, flags=cv2.IMREAD_GRAYSCALE, scale=1.0,
                  interpolation=cv2.INTER_LINEAR):
        """缓存模板读取和缩放；修改模板后重启程序生效。"""
        template = cv_imread(resource_path(os.path.join("img", name)), flags)
        if template is not None and scale != 1.0:
            template = cv2.resize(template, None, fx=scale, fy=scale, interpolation=interpolation)
        return template

    @lru_cache(maxsize=4)
    def _icon_files(self, prefix):
        return tuple(f for f in os.listdir(resource_path("img"))
                     if f.startswith(prefix) and f.endswith(".png"))

    def is_on_essence_page(self, window_img, roi, scale):
        """检查当前是否停留在基质背包页面"""
        try:
            template = self._template("EssenceSlot.png", scale=scale,
                                      interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR)
            if template is None:
                if hasattr(self, 'log_cb'):
                    self.log_cb("[警告] 未找到 EssenceSlot.png，跳过界面检测", "gold")
                return True


            rx, ry, rw, rh = roi
            margin = int(5 * scale)
            y1, y2 = max(0, ry - margin), min(window_img.shape[0], ry + rh + margin)
            x1, x2 = max(0, rx - margin), min(window_img.shape[1], rx + rw + margin)

            search_area = cv2.cvtColor(window_img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)

            if search_area.shape[0] < template.shape[0] or search_area.shape[1] < template.shape[1]:
                return False

            res = cv2.matchTemplate(search_area, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)

            return max_val > 0.80

        except Exception as e:
            if hasattr(self, 'log_cb'):
                self.log_cb(f"[错误] 界面检测异常: {e}", "red")
            return False

    def is_target_selected(self, window_img, box, scale):
        # 此模板保留示例图的 1440p 原始细节，其他旧模板采用 720p 基准。
        template = self._template("SelectedCorner.png", cv2.IMREAD_COLOR, scale / 2,
                                  interpolation=cv2.INTER_AREA if scale < 2 else cv2.INTER_LINEAR)
        return target_is_selected(window_img, box, template, scale)

    def get_inventory_count(self, window_img, roi):
        """读取左上角基质库存总数"""
        try:
            rx, ry, rw, rh = roi
            crop_img = window_img[max(0, ry):ry + rh, max(0, rx):rx + rw]
            if crop_img.size == 0:
                return 325

            gray = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
            # 三次立方放大，提高小数字 OCR 准确率
            resized = cv2.resize(gray, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)

            res, _ = self.ocr(resized, use_cls=False)
            if res:
                txt = str(res[0][1])
                match = re.search(r'(\d+)', txt)
                if match:
                    return int(match.group(1))
        except Exception:
            pass
        return 325

    def is_thumb_marked(self, box_img, scale, log_cb=None):
        """检测基质左下角是否有上锁/废弃的图标"""
        try:
            h, w = box_img.shape[:2]
            corner = box_img[int(h * 0.65):, :int(w * 0.30)]
            corner_gray = cv2.cvtColor(corner, cv2.COLOR_BGR2GRAY)

            if scale != 1.0:
                inv_scale = 1.0 / scale
                inter = cv2.INTER_AREA if inv_scale < 1.0 else cv2.INTER_CUBIC
                corner_gray = cv2.resize(corner_gray, None, fx=inv_scale, fy=inv_scale, interpolation=inter)

            img_dir = resource_path("img")
            if not os.path.exists(img_dir):
                return False

            def check_icon(prefix):
                files = self._icon_files(prefix)
                if not files:
                    return False

                best_val = 0.0
                for f in files:
                    tpl = self._template(f)
                    if tpl is None:
                        continue

                    if corner_gray.shape[0] < tpl.shape[0] or corner_gray.shape[1] < tpl.shape[1]:
                        if log_cb and not getattr(self, f"_warned_size_{f}", False):
                            log_cb(f"[警告] 模板 {f} 尺寸过大，无法进行缩略图匹配", "red")
                            setattr(self, f"_warned_size_{f}", True)
                        continue

                    res = cv2.matchTemplate(corner_gray, tpl, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, _ = cv2.minMaxLoc(res)
                    if max_val > best_val:
                        best_val = max_val

                return best_val > 0.65

            if check_icon("ThumbDiscard") or check_icon("ThumbLock"):
                return True

            return False

        except Exception as e:
            if log_cb and not getattr(self, "_warned_thumb_err", False):
                log_cb(f"[警告] 缩略图识别异常: {e}", "red")
                self._warned_thumb_err = True
            return False

    def recognize_and_parse(self, roi_img):
        """预处理图像并执行 OCR 识别"""
        self.last_ocr_issue = ""
        self.last_ocr_tokens = []
        self.last_ocr_path = "detector"
        if roi_img is None or roi_img.size == 0:
            self.last_ocr_issue = "词条截图为空"
            return "", [], []

        if self.dm.data.get("ocr_mode", "auto") != "legacy":
            regions = text_regions(roi_img)
            if regions is not None:
                crops, boxes = regions
                # Recognition-only batch: excludes progress bars and grade separators.
                result, _ = self.ocr.text_rec(crops)
                if len(result) == 6 and all(float(item[1]) >= .80 for item in result):
                    names_ok = all(re.fullmatch(r"[\u4e00-\u9fff]{2,12}", str(result[i][0])) for i in (0,2,4))
                    grades_ok = all(re.fullmatch(r"[+＋]?[1-6]", str(result[i][0]).strip()) for i in (1,3,5))
                    if names_ok and grades_ok:
                        parsed = self.parse_ocr_lines([[box, item[0], float(item[1])] for box,item in zip(boxes,result)])
                        if not self.last_ocr_issue:
                            self.last_ocr_path = "regions"
                            return parsed

        # 灰度化处理
        gray = cv2.cvtColor(roi_img, cv2.COLOR_BGR2GRAY)
        # 屏蔽词条左侧圆点，保留图像尺寸与文字位置，避免圆点拉低识别置信度。
        gray[:, :int(gray.shape[1] * .05)] = 0
        # 反色处理
        inverted = cv2.bitwise_not(gray)
        # 边缘填充
        padded = cv2.copyMakeBorder(inverted, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)

        # 标准化缩放
        h, w = padded.shape[:2]
        target_h = 180
        scale = target_h / h

        if scale != 1.0:
            inter = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
            processed_img = cv2.resize(padded, None, fx=scale, fy=scale, interpolation=inter)
        else:
            processed_img = padded

        # 执行文本识别
        res, _ = self.ocr(processed_img, use_cls=False)
        return self.parse_ocr_lines(res)

    def parse_ocr_lines(self, res):
        """解析 OCR 识别结果，提取技能名称与等级"""
        self.last_ocr_issue = ""
        self.last_ocr_tokens = res or []
        if not res:
            self.last_ocr_issue = "未读到词条"
            return "", [], []

        # 名称和等级分属两行时，只按几何位置配对，绝不按返回顺序拼接。
        names, numbers = [], []
        for box, raw, confidence in res:
            txt = self.cc.convert(str(raw))
            for wrong in sorted(self.dm.corrections or {}, key=len, reverse=True):
                txt = txt.replace(wrong, self.dm.corrections[wrong])
            xs, ys = zip(*box)
            token = dict(x=min(xs), right=max(xs), y=(min(ys)+max(ys))/2,
                         height=max(ys)-min(ys), confidence=float(confidence))
            name = re.sub(r'[^\u4e00-\u9fff]', '', txt)
            nums = re.findall(r'(?<!\d)[+＋]?\s*([1-6])(?!\d)', txt)
            if len(name) >= 2:
                names.append(dict(token, name=name, inline=int(nums[0]) if len(nums)==1 else None))
            if nums and len(name) < 2:
                numbers.append(dict(token, value=int(nums[0]) if len(nums)==1 else 0))
        names.sort(key=lambda t: t['y'])
        # 名称下面的等级进度条可能被读成“1”等字符，但位于名称列。
        # 等级数字必须在名称右侧；左侧装饰不参与配对或多余等级判断。
        # 右侧重复/低置信度数字仍保留，交给原来的严格校验拒绝。
        if names:
            name_column_right = min(name['right'] for name in names)
            numbers = [number for number in numbers if number['x'] > name_column_right]
        skills, levels, used = [], [], set()
        for index, name in enumerate(names):
            level = name['inline']
            confidence = name['confidence']
            if level is None:
                # 游戏等级位于名称下方右侧；允许同一文字行拆成两框。
                next_y = names[index+1]['y'] if index+1 < len(names) else float('inf')
                candidates = [(i,n) for i,n in enumerate(numbers) if i not in used
                              and n['x'] > name['right']
                              and name['y']-name['height']*.6 <= n['y'] < next_y-name['height']*.6
                              and n['y']-name['y'] <= name['height']*2.5]
                if len(candidates)==1:
                    i, number = candidates[0]
                    used.add(i)
                    level = number['value']
                    confidence = min(confidence, number['confidence'])
            skills.append(name['name'])
            levels.append(level or 0)
            if confidence < .80:
                self.last_ocr_issue = f"{name['name']}置信度 {confidence:.3f} 低于 0.80"
        if len(skills)!=3 or len(set(skills))!=3 or any(not 1<=v<=6 for v in levels):
            self.last_ocr_issue = "需要完整的三个不同词条及 1–6 级等级"
        if len(used)!=len(numbers):
            self.last_ocr_issue = "存在无法唯一配对的等级"
        display = " ".join(f"{s}{v if v else '?'}" for s,v in zip(skills,levels))
        return display, skills, levels

    def clean_csv_text(self, raw):
        """格式化 CSV 武器数据"""
        if not raw:
            return ""
        txt = self.cc.convert(str(raw))
        return re.sub(r'[^\u4e00-\u9fff]', '', txt)

    def check_all_attributes(self, weapon_list, skills, levels, is_gold_item=True, ignore_5star=False):
        """比对词条是否武器词条库匹配"""
        if not skills:
            return False, [], ""

        matched_weapons = []
        cleaned_skills = [s.replace("提升", "") for s in skills]

        current_list_id = id(weapon_list)

        #跳过已屏蔽的武器
        if current_list_id != self._cached_weapon_list_id:
            self._cleaned_weapons_cache = []
            for weapon in weapon_list:
                if weapon.get('屏蔽', '') == '1':
                    continue

                ts = [self.clean_csv_text(weapon.get(f'毕业词条{i}', '')).replace("提升", "")
                      for i in range(1, 4) if weapon.get(f'毕业词条{i}', '')]
                self._cleaned_weapons_cache.append((weapon.get('武器', '未知'), str(weapon.get('星级', '6星')), ts))
            self._cached_weapon_list_id = current_list_id

        # 执行模糊匹配策略
        for w_name, w_star, ts in self._cleaned_weapons_cache:
            if not ts:
                continue

            if ignore_5star and "5" in w_star:
                continue

            h_hits, p_hits = 0, 0
            m_idx = set()

            for t_c in ts:
                best_r, b_idx = 0, -1
                for i, p in enumerate(cleaned_skills):
                    if i in m_idx:
                        continue

                    # 优先进行子串精确匹配
                    if t_c in p or p in t_c:
                        best_r, b_idx = 1.0, i
                        break

                    # 使用模糊匹配计算相似度
                    r = difflib.SequenceMatcher(None, t_c, p).ratio()
                    if r > best_r:
                        best_r, b_idx = r, i

                if best_r >= 0.85:
                    h_hits += 1
                    m_idx.add(b_idx)
                elif best_r >= 0.6:
                    p_hits += 1
                    m_idx.add(b_idx)

            if (h_hits == len(ts)) or (h_hits >= len(ts) - 1 and (h_hits + p_hits) >= len(ts)):
                if is_gold_item:
                    matched_weapons.append((w_name, w_star))

        if matched_weapons:
            return True, matched_weapons, "graduation"

        # 潜力基质判定
        from core.potential import matches_potential
        if matches_potential(self.dm.data, skills, levels, is_gold_item):
            return True, [("\u6f5c\u529b\u57fa\u8d28", "5\u661f" if is_gold_item else "4\u661f")], "potential"

        return False, [], ""

    def is_gold(self, bgr):
        """判定基质稀有度"""
        try:
            h, w = bgr.shape[:2]
            strip = bgr[int(h * 0.90):, int(w * 0.15):int(w * 0.85)]
            hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
            # 锁定金色基质的特定 HSV 色值段
            mask = cv2.inRange(hsv, np.array([15, 100, 100]), np.array([35, 255, 255]))
            return (np.sum(mask > 0) / mask.size) > 0.1
        except Exception:
            return False

    def _template_match(self, window_img, pos, template_name, scale):
        """基础的局部图像模板匹配方法"""
        try:
            template = self._template(template_name, scale=scale)
            if template is None:
                return False


            th, tw = template.shape[:2]
            lx, ly = int(pos[0]), int(pos[1])
            search_margin = int(40 * scale)
            y1, y2 = max(0, ly - search_margin), min(window_img.shape[0], ly + search_margin)
            x1, x2 = max(0, lx - search_margin), min(window_img.shape[1], lx + search_margin)

            scope_gray = cv2.cvtColor(window_img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
            if scope_gray.shape[0] < th or scope_gray.shape[1] < tw:
                return False

            res = cv2.matchTemplate(scope_gray, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            return max_val > 0.85
        except Exception:
            return False

    def find_essences_with_mask(self, window_img, roi, scale):
        """获取列表内基质的位置"""
        try:
            template_bgr = self._template("EssenceGeneral.png", cv2.IMREAD_COLOR, scale)
            if template_bgr is None:
                return []


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

            # 过滤重叠检测框
            final_boxes = []
            for b in boxes:
                cx, cy = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
                keep = True
                for fb in final_boxes:
                    fcx, fcy = (fb[0] + fb[2]) // 2, (fb[1] + fb[3]) // 2
                    if abs(cx - fcx) < tw // 2 and abs(cy - fcy) < th // 2:
                        keep = False
                        break
                if keep:
                    final_boxes.append(b)

            final_boxes.sort(key=lambda b: (b[1] // (th // 2), b[0]))
            return final_boxes

        except Exception:
            return []

    def is_already_locked_bg(self, window_img, lock_pos, scale):
        """检查基质面板上的锁定按钮是否为激活状态"""
        return self._template_match(window_img, lock_pos, "LockButtonLocked.png", scale)

    def is_already_discarded_bg(self, window_img, discard_pos, scale):
        """检查基质面板上的废弃按钮是否为激活状态"""
        return self._template_match(window_img, discard_pos, "DiscardButtonDiscarded.png", scale)
