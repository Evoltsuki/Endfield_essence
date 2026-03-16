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
        """主动中断扫描"""
        self.running = False

    def start(self):
        """启动扫描控制线程"""
        self.running = True
        try:
            self._run_loop()
        except Exception as e:
            self.log_cb(f"[异常] {e}\n{traceback.format_exc()}", "red")
        finally:
            self.running = False
            self.finish_cb()

    def _flush_logs(self, logs):
        """批量推送日志至 UI 面板"""
        for msg, tag in logs:
            self.log_cb(msg, tag)

    def _get_row_signature(self, boxes):
        """计算行签名，用于检测滑动是否有效"""
        if not boxes:
            return None
        centers = [(int((bx1 + bx2) / 2), int((by1 + by2) / 2)) for bx1, by1, bx2, by2 in boxes]
        return tuple(sorted(centers))

    def _signatures_similar(self, sig1, sig2, threshold=20):
        """比较两个签名是否相似"""
        if sig1 is None or sig2 is None:
            return False
        if len(sig1) != len(sig2):
            return False
        for (x1, y1), (x2, y2) in zip(sig1, sig2):
            if abs(x1 - x2) > threshold or abs(y1 - y2) > threshold:
                return False
        return True

    def _run_loop(self):
        """核心扫描逻辑主循环"""
        layout = self.controller.get_scaled_layout()
        if not layout:
            self.log_cb("[错误] 未找到游戏窗口，请确保游戏正在运行！", "red")
            return

        env = layout["env"]
        self.log_cb(f"[适配] 分辨率 {env['res_w']}x{env['res_h']} (缩放系数: {env['ui_scale']:.2f})", "blue")

        total_rows = 0
        final_sweep_mode = False
        last_row_signature = None

        cfg_skip_marked = self.dm.data.get("skip_marked", False)
        cfg_ignore_5star = self.dm.data.get("ignore_5star", True)
        cfg_debug_gold = self.dm.data.get("debug_gold", False)

        win_img = self.controller.capture_window_bg(env)
        if win_img is None:
            self.log_cb("[错误] 后台截图失败，请检查游戏窗口", "red")
            return

        if not self.analyzer.is_on_essence_page(win_img, layout["inventory_tab_roi"], env["ui_scale"]):
            self.log_cb("[错误] 未检测到基质界面，请按N键打开游戏内的基质背包！", "red")
            return

        self.log_cb("[系统] 确认当前处于基质界面", "green")

        if win_img is not None:
            total_count = self.analyzer.get_inventory_count(win_img, layout["inventory_count_roi"])
            self.log_cb(f"[系统] 当前有 {total_count} 个基质", "blue")

            if total_count <= 45:
                self.log_cb("[系统] 基质不足一页，直接进入全局尾扫模式...", "blue")
                final_sweep_mode = True

        while self.running:
            win_img = self.controller.capture_window_bg(env)
            if win_img is None:
                self.log_cb("[错误] 后台截图失败", "red")
                break

            current_roi = layout["roi_final"] if final_sweep_mode else layout["roi_row1"]
            boxes = self.analyzer.find_essences_with_mask(win_img, current_roi, env["ui_scale"])

            physical_items_count = 0
            valid_boxes = []

            # 过滤无效或非目标品质的物品框
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
                is_gold_item = self.analyzer.is_gold(box_img)
                if cfg_debug_gold or is_gold_item:
                    valid_boxes.append((b, is_gold_item))

            if physical_items_count == 0:
                if not final_sweep_mode:
                    self.log_cb("[系统] 探测行未发现基质，触发全局尾扫模式...", "blue")
                    final_sweep_mode = True
                    continue
                else:
                    self.log_cb("[系统] 基质扫描结束！", "blue")
                    break

            for idx, item in enumerate(valid_boxes):
                b, is_gold_item = item
                if not self.running:
                    break

                batch_logs = []

                def quick_log(m, t="black"):
                    batch_logs.append((m, t))

                bx1, by1, bx2, by2 = b
                cx, cy = (bx1 + bx2) // 2, (by1 + by2) // 2

                logic_row = total_rows + (idx // 9) + 1
                logic_col = (idx % 9) + 1
                abs_cx, abs_cy = cx + env["abs_x"], cy + env["abs_y"]

                # 动态计算等待时间：开启跳过标记时，延长等待时间以确保锁定图标加载完毕
                click_delay = 0.2 if cfg_skip_marked else 0.15
                self.controller.click_at(abs_cx, abs_cy, delay=click_delay)

                scr = self.controller.capture_window_bg(env)

                lock_rel_pos = (layout["lock_btn"][0] - env["abs_x"], layout["lock_btn"][1] - env["abs_y"])
                discard_rel_pos = (layout["discard_btn"][0] - env["abs_x"], layout["discard_btn"][1] - env["abs_y"])

                if cfg_skip_marked:
                    is_locked = self.analyzer.is_already_locked_bg(scr, lock_rel_pos, env["ui_scale"])
                    is_discarded = self.analyzer.is_already_discarded_bg(scr, discard_rel_pos, env["ui_scale"])
                    if is_locked or is_discarded:
                        quick_log(f"---------- 检查: {logic_row}-{logic_col} ----------", "black")
                        quick_log(f"-> 该基质已{'锁定' if is_locked else '废弃'}，跳过", "gray")
                        self._flush_logs(batch_logs)
                        continue

                roi_x, roi_y, roi_w, roi_h = layout["roi"]
                o_img = scr[roi_y: roi_y + roi_h, roi_x: roi_x + roi_w]

                display_str, skills, levels = self.analyzer.recognize_and_parse(o_img)

                if display_str:
                    quick_log(f"---------- 检查: {logic_row}-{logic_col} ----------", "black")
                    quick_log(f"识别结果: {display_str}", "green")

                    is_keep, matched_weapons, match_type = self.analyzer.check_all_attributes(
                        self.dm.weapon_list, skills, levels, is_gold_item
                    )

                    if is_keep and cfg_ignore_5star:
                        if match_type == "graduation":
                            matched_weapons = [w for w in matched_weapons if "5" not in w[1]]
                            if not matched_weapons:
                                is_keep = False

                    if is_keep:
                        if match_type == "graduation":
                            is_6star = any("6" in w_star for _, w_star in matched_weapons)
                            grad_color = "red" if is_6star else "gold"
                            quick_log([("⭐ 识别到", "gold"), ("毕业基质！", grad_color)])
                        else:
                            quick_log("⭐ 识别到潜力基质！", "gold")

                        if not self.analyzer.is_already_locked_bg(scr, lock_rel_pos, env["ui_scale"]):
                            self.controller.click_at(layout["lock_btn"][0], layout["lock_btn"][1], delay=0.1)
                            quick_log("-> 已执行锁定指令", "blue")
                            self.controller.move_rel(50, 50)

                        self.lock_cb({
                            "weapons": matched_weapons,
                            "display_str": display_str,
                            "row": logic_row,
                            "col": logic_col
                        })
                    else:
                        quick_log("判定为垃圾基质，准备废弃", "gray")
                        if not self.analyzer.is_already_discarded_bg(scr, discard_rel_pos, env["ui_scale"]):
                            self.controller.click_at(layout["discard_btn"][0], layout["discard_btn"][1], delay=0.1)
                            quick_log("-> 已执行废弃指令", "gray")
                            self.controller.move_rel(50, 50)
                else:
                    quick_log(f"---------- 检查: {logic_row}-{logic_col} ----------", "black")
                    quick_log("-> 未读到词条", "red")

                self._flush_logs(batch_logs)

            if not self.running:
                break

            if final_sweep_mode:
                self.log_cb("[系统] 基质扫描结束！", "blue")
                break

            if physical_items_count > len(valid_boxes):
                self.log_cb("[系统] 识别到紫色基质，扫描结束！", "blue")
                break

            if physical_items_count == 9:
                self.log_cb("[翻页] 正在向下滑动...", "black")
                current_signature = self._get_row_signature([b for b, _ in valid_boxes])
                dist = layout["swipe_dist_first"] if total_rows == 0 else layout["swipe_dist_next"]
                self.controller.swipe_up(layout["swipe_start"][0], layout["swipe_start"][1], dist)
                if last_row_signature is not None and self._signatures_similar(last_row_signature, current_signature):
                    self.log_cb("[系统] 滑动未改变位置，切换到全局尾扫模式...", "blue")
                    final_sweep_mode = True
                last_row_signature = current_signature
                total_rows += 1
            else:
                self.log_cb("[系统] 基质扫描结束！", "blue")
                break