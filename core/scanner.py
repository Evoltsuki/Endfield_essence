import time
import cv2
import traceback


class AutoScanner:
    def __init__(self, dm, controller, analyzer, callbacks):
        self.dm = dm
        self.controller = controller
        self.analyzer = analyzer

        self.log_cb = callbacks.get('log', lambda m, t="black": None)
        self.lock_cb = callbacks.get('lock', lambda data: None)
        self.finish_cb = callbacks.get('finish', lambda: None)

        self.running = False

    def stop(self):
        self.running = False

    def start(self):
        self.running = True
        try:
            self._run_loop()
        except Exception as e:
            self.log_cb(f"[异常] {e}\n{traceback.format_exc()}", "red")
        finally:
            self.running = False
            self.finish_cb()

    def _run_loop(self):
        layout = self.controller.get_scaled_layout()
        if not layout:
            self.log_cb("[错误] 未找到游戏窗口，请确保游戏正在运行！", "red")
            return

        env = layout["env"]
        self.log_cb(f"[适配] 分辨率 {env['res_w']}x{env['res_h']} (缩放系数: {env['ui_scale']:.2f})", "blue")

        total_rows = 0
        final_sweep_mode = False

        cfg_skip_marked = self.dm.data.get("skip_marked", False)
        cfg_ignore_5star = self.dm.data.get("ignore_5star", True)
        cfg_debug_gold = self.dm.data.get("debug_gold", False)

        while self.running:
            win_img = self.controller.capture_window_bg(env["hwnd"], env["res_w"], env["res_h"])
            if win_img is None:
                self.log_cb("[错误] 后台截图失败", "red")
                break

            current_roi = layout["roi_final"] if final_sweep_mode else layout["roi_row1"]
            boxes = self.analyzer.find_essences_with_mask(win_img, current_roi, env["ui_scale"])

            physical_items_count = 0
            valid_boxes = []

            for b in boxes:
                bx1, by1, bx2, by2 = b
                box_img = win_img[by1:by2, bx1:bx2]

                ch, cw = box_img.shape[:2]
                center_roi = box_img[int(ch * 0.3):int(ch * 0.7), int(cw * 0.3):int(cw * 0.7)]
                if center_roi.size > 0:
                    gray_center = cv2.cvtColor(center_roi, cv2.COLOR_BGR2GRAY)
                    mean_val, stddev = cv2.meanStdDev(gray_center)
                    if mean_val[0][0] < 60 and stddev[0][0] < 15.0:
                        continue

                physical_items_count += 1
                if cfg_debug_gold or self.analyzer.is_gold(box_img):
                    valid_boxes.append(b)

            if physical_items_count == 0:
                if not final_sweep_mode:
                    self.log_cb("[系统] 探测行未发现基质，触发全局尾扫模式...", "blue")
                    final_sweep_mode = True
                    continue
                else:
                    self.log_cb("[系统] 基质扫描结束！", "blue")
                    break

            for idx, b in enumerate(valid_boxes):
                if not self.running: break
                bx1, by1, bx2, by2 = b
                cx, cy = (bx1 + bx2) // 2, (by1 + by2) // 2

                logic_row = total_rows + (idx // 9) + 1
                logic_col = (idx % 9) + 1
                self.log_cb(f"--- 检查: {logic_row}-{logic_col} ---")

                abs_cx, abs_cy = cx + env["abs_x"], cy + env["abs_y"]
                # 恢复你原本优秀的 delay=0.2 缓冲设计，不作额外等待
                self.controller.click_at(abs_cx, abs_cy, delay=0.2)

                scr = self.controller.capture_window_bg(env["hwnd"], env["res_w"], env["res_h"])
                lock_rel_pos = (layout["lock_btn"][0] - env["abs_x"], layout["lock_btn"][1] - env["abs_y"])
                discard_rel_pos = (layout["discard_btn"][0] - env["abs_x"], layout["discard_btn"][1] - env["abs_y"])

                if cfg_skip_marked:
                    is_locked = self.analyzer.is_already_locked_bg(scr, lock_rel_pos, env["ui_scale"])
                    is_discarded = self.analyzer.is_already_discarded_bg(scr, discard_rel_pos, env["ui_scale"])
                    if is_locked or is_discarded:
                        self.log_cb(f"-> 该基质已{'锁定' if is_locked else '废弃'}，跳过", "gray")
                        continue

                roi_x, roi_y, roi_w, roi_h = layout["roi"]
                o_img = scr[roi_y: roi_y + roi_h, roi_x: roi_x + roi_w]

                # 调用优化后的新 OCR 方法
                display_str, skills, levels = self.analyzer.recognize_and_parse(o_img)

                if display_str:
                    self.log_cb(f"识别结果: {display_str}", "green")
                    is_keep, matched_weapons, match_type = self.analyzer.check_all_attributes(self.dm.weapon_list,
                                                                                              skills, levels)

                    if is_keep and cfg_ignore_5star:
                        if match_type == "graduation":
                            matched_weapons = [w for w in matched_weapons if "5" not in w[1]]
                            if not matched_weapons:
                                is_keep = False

                    if is_keep:
                        self.log_cb("⭐ 识别到毕业基质！" if match_type == "graduation" else "⭐ 识别到潜力基质！", "gold")
                        if not self.analyzer.is_already_locked_bg(scr, lock_rel_pos, env["ui_scale"]):
                            self.controller.click_at(layout["lock_btn"][0], layout["lock_btn"][1], delay=0.4)
                            self.log_cb("-> 已执行锁定指令", "blue")
                            self.controller.move_rel(50, 50)

                        self.lock_cb({"weapons": matched_weapons, "display_str": display_str, "row": logic_row,
                                      "col": logic_col})
                    else:
                        self.log_cb("判定为垃圾基质，准备废弃", "gray")
                        if not self.analyzer.is_already_discarded_bg(scr, discard_rel_pos, env["ui_scale"]):
                            self.controller.click_at(layout["discard_btn"][0], layout["discard_btn"][1], delay=0.4)
                            self.log_cb("-> 已执行废弃指令", "gray")
                            self.controller.move_rel(50, 50)
                else:
                    self.log_cb("-> 未读到词条")

            if not self.running: break

            if final_sweep_mode:
                self.log_cb("[系统] 基质扫描结束！", "blue")
                break

            if physical_items_count > len(valid_boxes):
                self.log_cb("[系统] 识别到紫色基质，扫描结束！", "blue")
                break

            if physical_items_count == 9:
                self.log_cb("[翻页] 正在向上滑动...", "black")
                dist = layout["swipe_dist_first"] if total_rows == 0 else layout["swipe_dist_next"]
                self.controller.swipe_up(layout["swipe_start"][0], layout["swipe_start"][1], dist)
                total_rows += 1
                time.sleep(0.5)
            else:
                self.log_cb("[系统] 基质扫描结束！", "blue")
                break