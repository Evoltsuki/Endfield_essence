import cv2
import traceback
import time
from core.page_grid import GridPage, PageTracker, page_swipe_plan


class ScanCancelled(Exception):
    """用户停止扫描；中断当前操作，不作为运行故障。"""


class AutoScanner:
    def __init__(self, dm, controller, analyzer, callbacks, max_items=None, sample_pattern=None,
                 preview=False):
        if max_items is not None and (type(max_items) is not int or max_items < 1):
            raise ValueError("max_items 必须是正整数或 None")
        if sample_pattern not in (None, "cross"):
            raise ValueError("未知抽样模式")
        self.sample_pattern = sample_pattern
        self.preview = preview
        self.max_items = max_items
        self.processed_items = 0
        self.dm = dm
        self.controller = controller
        self.analyzer = analyzer

        self.log_cb = callbacks.get('log', lambda m, t="black": None)
        self.lock_cb = callbacks.get('lock', lambda data: None)
        self.result_cb = callbacks.get('result', lambda data: None)
        self.finish_cb = callbacks.get('finish', lambda: None)

        self.running = False

    def stop(self):
        """主动中断扫描"""
        self.running = False
        self.controller.stop_capture()

    def start(self):
        """启动扫描控制线程"""
        self.processed_items = 0
        self.running = True
        try:
            self._run_loop()
        except ScanCancelled as e:
            self.log_cb(f"[停止] {e}", "orange")
        except Exception as e:
            self.log_cb(f"[异常] {e}\n{traceback.format_exc()}", "red")
        finally:
            if not self.running:
                self.log_cb("[系统] 扫描已终止", "blue")

            self.running = False
            self.controller.stop_capture()
            self.finish_cb()

    def _mark_verified(self, layout, kind):
        """单次标记后观察新帧确认状态；失败不重复点击切换按钮。"""
        env = layout["env"]
        if not self.running:
            raise ScanCancelled("扫描已停止，未发送本次标记")
        if not self.controller._same_window(env):
            raise RuntimeError("标记前窗口变化，已停止")
        pos = layout[kind + "_btn"]
        relative = (pos[0]-env["abs_x"], pos[1]-env["abs_y"])
        check = (self.analyzer.is_already_locked_bg if kind == "lock"
                 else self.analyzer.is_already_discarded_bg)
        self.controller.click_at(*pos, delay=.2)
        if not self.controller.wait_mark_state(env, lambda image: check(image, relative, env["ui_scale"]),
                                               lambda: self.running):
            if not self.running:
                raise ScanCancelled("用户停止了标记确认；已发送标记，但当前基质最终状态未确认，请复核；不会自动重试")
            raise RuntimeError("标记结果未确认，已停止；请复核当前基质")
        self.log_cb(f"[校验] {'锁定' if kind == 'lock' else '废弃'}状态已确认", "blue")

    def _flush_logs(self, logs):
        """批量推送日志至 UI 面板"""
        for msg, tag in logs:
            self.log_cb(msg, tag)

    def _run_loop(self):
        if self.dm.data.get("scan_mode", "page") == "row":
            return self._run_row_loop()
        return self._run_page_loop()

    def _run_row_loop(self):
        """核心扫描逻辑主循环"""
        layout = self.controller.get_scaled_layout()
        if not layout:
            self.log_cb("[错误] 未找到游戏窗口，请确保游戏正在运行！", "red")
            return

        env = layout["env"]
        self.log_cb(f"[系统] 分辨率 {env['res_w']}x{env['res_h']} (缩放系数: {env['ui_scale']:.2f})", "blue")

        total_rows = 0
        final_sweep_mode = False
        target_row_y = None  # 记录首行基准Y坐标

        cfg_skip_marked = self.dm.data.get("skip_marked", False)
        cfg_ignore_5star = self.dm.data.get("ignore_5star", True)
        cfg_debug_gold = self.dm.data.get("debug_gold", False)

        win_img = self.controller.capture_window_bg(env)
        if win_img is None:
            self.log_cb("[错误] 截图失败，请确保游戏窗口未处于最小化状态", "red")
            return

        if not self.analyzer.is_on_essence_page(win_img, layout["inventory_tab_roi"], env["ui_scale"]):
            self.log_cb("[错误] 未检测到基质界面，请按N键打开游戏内的基质背包！", "red")
            return

        self.log_cb("[系统] 确认当前处于基质界面", "blue")

        if win_img is not None:
            total_count = self.analyzer.get_inventory_count(win_img, layout["inventory_count_roi"])
            self.log_cb(f"[系统] 当前有 {total_count} 个基质", "blue")

            if total_count <= 45:
                self.log_cb("[系统] 基质不足一页，直接进入全局尾扫模式...", "blue")
                final_sweep_mode = True

        while self.running:
            win_img = self.controller.capture_window_bg(env)
            if win_img is None:
                self.log_cb("[错误] 截图失败，扫描中断", "red")
                break

            current_roi = layout["roi_final"] if final_sweep_mode else layout["roi_row1"]
            boxes = self.analyzer.find_essences_with_mask(win_img, current_roi, env["ui_scale"])

            physical_items_count = 0
            gold_items_count = 0
            valid_boxes = []
            all_physical_boxes = []  # 记录所有非空物理基质用于坐标参照

            # 过滤无效或非目标品质的物品框
            for b in boxes:
                bx1, by1, bx2, by2 = b
                box_img = win_img[by1:by2, bx1:bx2]

                # 通过中心区域亮度判定来过滤掉空位
                ch, cw = box_img.shape[:2]
                center_roi = box_img[int(ch * 0.3):int(ch * 0.7), int(cw * 0.3):int(cw * 0.7)]
                if center_roi.size > 0:
                    gray_center = cv2.cvtColor(center_roi, cv2.COLOR_BGR2GRAY)
                    mean_val, stddev = cv2.meanStdDev(gray_center)
                    if mean_val[0][0] < 60 and stddev[0][0] < 15.0:
                        continue

                physical_items_count += 1
                all_physical_boxes.append(b)  # 记录有效参照物

                # 扩大判定框以检测基质稀有度
                extra_h = int(12 * env["ui_scale"])
                gold_by2 = min(win_img.shape[0], by2 + extra_h)
                gold_box_img = win_img[by1:gold_by2, bx1:bx2]
                is_gold_item = self.analyzer.is_gold(gold_box_img)

                if is_gold_item:
                    gold_items_count += 1

                # 扩大判定框以检测左下角的锁/废弃标记
                margin = int(10 * env["ui_scale"])
                ex1 = max(0, bx1 - margin)
                ey1 = max(0, by1 - margin)
                ex2 = min(win_img.shape[1], bx2 + margin)
                ey2 = min(win_img.shape[0], by2 + margin)
                expanded_box_img = win_img[ey1:ey2, ex1:ex2]

                # 前置过滤已标记的基质
                if cfg_skip_marked and self.analyzer.is_thumb_marked(expanded_box_img, env["ui_scale"], self.log_cb):
                    continue

                if cfg_debug_gold or is_gold_item:
                    valid_boxes.append((b, is_gold_item, physical_items_count))

            # 动态计算Y轴偏移量
            drift_y = 0
            if all_physical_boxes and not final_sweep_mode:
                current_avg_y = sum((b[1] + b[3]) / 2 for b in all_physical_boxes) / len(all_physical_boxes)

                if target_row_y is None:
                    target_row_y = current_avg_y
                else:
                    drift_y = current_avg_y - target_row_y
                    drift_y = max(-15, min(15, drift_y))

            # 翻页结束条件判定
            if physical_items_count == 0:
                if not final_sweep_mode:
                    self.log_cb("[系统] 探测行未发现基质，触发全局尾扫模式...", "blue")
                    final_sweep_mode = True
                    continue
                else:
                    self.log_cb("[系统] 基质扫描结束！", "blue")
                    break
            elif physical_items_count == 9 and len(valid_boxes) == 0:
                if cfg_debug_gold or physical_items_count == gold_items_count:
                    self.log_cb(f"[系统] 第 {total_rows + 1} 行已全部标记，跳过", "green")

            for item in valid_boxes:
                if self.max_items is not None and self.processed_items >= self.max_items:
                    self.log_cb(f"[测试] 已检查 {self.processed_items} 个基质，达到上限，自动停止", "blue")
                    return
                b, is_gold_item, physical_col = item
                if not self.running:
                    break

                logic_row = total_rows + 1 + (physical_col - 1) // 9
                logic_col = (physical_col - 1) % 9 + 1
                if not self._scan_one(layout, b, is_gold_item, logic_row, logic_col):
                    return

            if not self.running:
                break

            if self.max_items is not None and self.processed_items >= self.max_items:
                self.log_cb(f"[测试] 已检查 {self.processed_items} 个基质，达到上限，自动停止", "blue")
                return

            if final_sweep_mode:
                self.log_cb("[系统] 基质扫描结束！", "blue")
                break

            if not cfg_debug_gold and physical_items_count > gold_items_count:
                self.log_cb("[系统] 识别到紫色基质，扫描结束！", "blue")
                break

            if physical_items_count == 9:
                self.log_cb("[操作] 正在向下滑动...", "black")
                base_dist = layout["swipe_dist_first"] if total_rows == 0 else layout["swipe_dist_next"]
                actual_dist = int(base_dist + drift_y)  # 应用误差补偿
                if not self.controller._same_window(env):
                    self.log_cb("[系统] 翻页前窗口变化，已停止", "blue")
                    return
                self.controller.swipe_up(layout["swipe_start"][0], layout["swipe_start"][1], actual_dist)
                total_rows += 1
            else:
                self.log_cb("[系统] 基质扫描结束！", "blue")
                break

    def _scan_one(self, layout, b, is_gold_item, logic_row, logic_col):
        env = layout["env"]
        cfg_skip_marked = self.dm.data.get("skip_marked", False)
        cfg_ignore_5star = self.dm.data.get("ignore_5star", True)
        batch_logs = []

        def quick_log(m, t="black"):
            batch_logs.append((m, t))

        bx1, by1, bx2, by2 = b
        cx, cy = (bx1 + bx2) // 2, (by1 + by2) // 2


        abs_cx, abs_cy = cx + env["abs_x"], cy + env["abs_y"]

        # 执行物理点击，弹出词条详情面板
        current_env = self.controller.get_window_env()
        if current_env is None or any(current_env[k] != env[k] for k in
                                       ("hwnd", "res_w", "res_h", "abs_x", "abs_y")):
            self.log_cb("[系统] 游戏窗口位置或分辨率变化，请重新开始扫描", "blue")
            return False
        click_delay = 0.20
        self.processed_items += 1
        phase_started = time.perf_counter()
        self.controller.click_at(abs_cx, abs_cy, delay=click_delay)
        click_ms = (time.perf_counter()-phase_started)*1000

        target_selected = lambda image: self.analyzer.is_target_selected(image, b, env["ui_scale"])
        phase_started = time.perf_counter()
        scr = self.controller.wait_target_selected(env, target_selected, lambda: self.running)
        selection_ms = (time.perf_counter()-phase_started)*1000
        wait = self.controller.last_selection_wait
        self.log_cb(f"[选中校验] {logic_row}-{logic_col}: {wait['elapsed_ms']:.0f}ms / {wait['frames']}帧 / {wait['reason']}", "gray")
        if scr is None:
            self.log_cb("[错误] 未确认目标基质选中，停止扫描；未执行该件的识别和标记", "red")
            return False
        if self.dm.data.get("verify_detail_stability", False):
            scr = self.controller.wait_detail_stable(
                env, layout["roi"], lambda: self.running, target_selected=target_selected)
            wait = self.controller.last_wait
            self.log_cb(f"[等待] {logic_row}-{logic_col}: {wait['elapsed_ms']:.0f}ms / {wait['frames']}帧 / {wait['reason']}", "gray")

        if scr is None:
            self.log_cb("[错误] 详情截图失败、画面未稳定或窗口变化，停止扫描", "red")
            return False
        if not self.running:
            return False

        lock_rel_pos = (layout["lock_btn"][0] - env["abs_x"], layout["lock_btn"][1] - env["abs_y"])
        discard_rel_pos = (layout["discard_btn"][0] - env["abs_x"], layout["discard_btn"][1] - env["abs_y"])

        # 同一张截图的状态结果按需复用，下一件基质重新检测。
        state_cache = {}
        def locked():
            if "lock" not in state_cache:
                state_cache["lock"] = self.analyzer.is_already_locked_bg(scr, lock_rel_pos, env["ui_scale"])
            return state_cache["lock"]

        def discarded():
            if "discard" not in state_cache:
                state_cache["discard"] = self.analyzer.is_already_discarded_bg(scr, discard_rel_pos, env["ui_scale"])
            return state_cache["discard"]

        # 二次校验
        if cfg_skip_marked:
            is_locked = locked()
            is_discarded = discarded()
            if is_locked or is_discarded:
                quick_log(f"---------- 检查: {logic_row}-{logic_col} ----------", "black")
                quick_log(f"-> 该基质已{'锁定' if is_locked else '废弃'}，跳过", "gray")
                self._flush_logs(batch_logs)
                return True

        roi_x, roi_y, roi_w, roi_h = layout["roi"]
        o_img = scr[roi_y: roi_y + roi_h, roi_x: roi_x + roi_w]

        # 识别当前点击的基质词条
        phase_started = time.perf_counter()
        display_str, skills, levels = self.analyzer.recognize_and_parse(o_img)
        ocr_ms = (time.perf_counter()-phase_started)*1000
        timings = dict(click_ms=round(click_ms,2), selection_ms=round(selection_ms,2), ocr_ms=round(ocr_ms,2))
        ocr_path = str(getattr(self.analyzer, "last_ocr_path", "detector"))
        self.log_cb(f"[耗时] {logic_row}-{logic_col}: 点击{click_ms:.0f}ms / 选中{selection_ms:.0f}ms / OCR {ocr_ms:.0f}ms ({ocr_path})", "gray")

        if not self.running:
            return False

        issue = getattr(self.analyzer, "last_ocr_issue", "")
        if issue or len(skills) != 3 or len(levels) != 3 or any(v < 1 or v > 6 for v in levels):
            self.result_cb(dict(row=logic_row, col=logic_col, display_str=display_str,
                                category="需复核", issue=issue or "词条不完整", image=o_img.copy(), timings=timings))
            quick_log(f"[识别待复核] {logic_row}-{logic_col}: {display_str}；{issue or '词条不完整'}，跳过标记", "red")
            self._flush_logs(batch_logs)
            return True

        if display_str:
            quick_log(f"---------- 检查: {logic_row}-{logic_col} ----------", "black")
            quick_log(f"识别结果: {display_str}", "green")
            is_keep, matched_weapons, match_type = self.analyzer.check_all_attributes(
                self.dm.weapon_list, skills, levels, is_gold_item, cfg_ignore_5star
            )

            category = {"graduation": "毕业", "potential": "潜力"}.get(match_type, match_type) if is_keep else "未匹配"
            self.result_cb(dict(row=logic_row, col=logic_col, display_str=display_str,
                                category=category, issue="", image=o_img.copy(), timings=timings))
            if self.preview:
                quick_log(f"[预览] 规则匹配：{category}；不执行标记或更新毕业记录", "blue")
                self._flush_logs(batch_logs)
                return True

            if is_keep:
                if match_type == "graduation":
                    is_6star = any("6" in w_star for _, w_star in matched_weapons)
                    grad_color = "red" if is_6star else "gold"

                    # 毕业基质数量限制
                    is_locked_now = locked()
                    current_score = sum(levels)
                    enable_limit = self.dm.data.get("enable_grad_limit", False)
                    keep_limit = self.dm.data.get("grad_keep_limit", 1)

                    is_qualify = not enable_limit  # 未开启限制时默认直接保留
                    records_updated = False
                    is_tied_with_board = False

                    for w_name, w_star in matched_weapons:
                        if w_name not in self.dm.best_records:
                            self.dm.best_records[w_name] = []

                        w_records = self.dm.best_records[w_name]

                        if len(w_records) > keep_limit:
                            w_records[:] = w_records[:keep_limit]
                            records_updated = True

                        if is_locked_now and current_score in w_records:
                            is_tied_with_board = True
                            continue

                        if len(w_records) < keep_limit:
                            w_records.append(current_score)
                            w_records.sort(reverse=True)
                            is_qualify = True
                            records_updated = True
                        elif current_score > w_records[-1]:
                            w_records[-1] = current_score
                            w_records.sort(reverse=True)
                            is_qualify = True
                            records_updated = True
                        elif current_score >= w_records[-1]:
                            is_tied_with_board = True

                    if records_updated:
                        self.dm.save_records()

                    if is_qualify:
                        quick_log([("⭐ 识别到", "gold"), (f"毕业基质！(总等级:{current_score})", grad_color)])
                        if not locked():
                            self._mark_verified(layout, "lock")
                            quick_log("-> 已执行锁定指令", "blue")
                        else:
                            quick_log("-> 该基质已锁定，跳过", "gray")

                        self.lock_cb({
                            "weapons": matched_weapons,
                            "display_str": display_str,
                            "row": logic_row,
                            "col": logic_col
                        })

                    elif is_tied_with_board and locked():
                        quick_log(
                            [("⭐ 识别到", "gold"), (f"毕业基质！(总等级:{current_score} 最高记录)", grad_color)])
                        quick_log("-> 该基质已锁定，跳过", "gray")

                        self.lock_cb({
                            "weapons": matched_weapons,
                            "display_str": display_str,
                            "row": logic_row,
                            "col": logic_col
                        })
                    else:
                        quick_log([("⭐ 识别到", "gold"), (f"毕业基质！(总等级:{current_score})", grad_color)])
                        quick_log("-> 等级低于最高记录，准备废弃", "black")
                        if not discarded():
                            self._mark_verified(layout, "discard")
                            quick_log("-> 已执行废弃指令", "gray")
                        else:
                            quick_log("-> 该基质已废弃，跳过", "gray")
                else:
                    quick_log("⭐ 识别到潜力基质！", "gold")

                    if not locked():
                        self._mark_verified(layout, "lock")
                        quick_log("-> 已执行锁定指令", "blue")
                    else:
                        quick_log("-> 该基质已锁定，跳过", "gray")

                    self.lock_cb({
                        "weapons": matched_weapons,
                        "display_str": display_str,
                        "row": logic_row,
                        "col": logic_col
                    })
            else:
                quick_log("判定为无用基质，准备废弃", "black")

                if not discarded():
                    self._mark_verified(layout, "discard")
                    quick_log("-> 已执行废弃指令", "gray")
                else:
                    quick_log("-> 该基质已废弃，跳过", "gray")
        else:
            quick_log(f"---------- 检查: {logic_row}-{logic_col} ----------", "black")
            quick_log("-> 未读到词条", "red")

        self._flush_logs(batch_logs)

        return True

    def _run_page_loop(self):
        layout = self.controller.get_scaled_layout()
        if not layout:
            self.log_cb("[错误] 未找到游戏窗口", "red")
            return
        env, roi = layout["env"], layout["roi_final"]
        tracker = PageTracker(minimum_rows=1)
        page_number = 0
        self.log_cb(f"[整页] 分辨率 {env['res_w']}x{env['res_h']}，按实际网格列数扫描", "blue")
        while self.running:
            image = self.controller.wait_grid_stable(env, roi, lambda: self.running)
            if image is None:
                self.log_cb(f"[错误] 网格未稳定或窗口变化: {self.controller.last_wait}", "red")
                return
            if not self.analyzer.is_on_essence_page(image, layout["inventory_tab_roi"], env["ui_scale"]):
                self.log_cb("[错误] 未处于基质背包，停止", "red")
                return
            boxes = self.analyzer.find_essences_with_mask(image, roi, env["ui_scale"])
            try:
                page = GridPage.build(image, boxes)
                fresh, alignment, ended = tracker.observe(page)
            except ValueError as exc:
                self.log_cb(f"[错误] {exc}", "red")
                return
            page_number += 1
            self.log_cb(f"[整页] 第 {page_number} 屏：{len(page.rows)} 行 × {page.columns} 列，新增 {len(fresh)} 格，行距 {page.pitch:.1f}px", "blue")
            if alignment:
                self.log_cb(f"[翻页校验] 推进 {alignment['offset']} 行，重叠 {alignment['overlap_rows']} 行，匹配 {alignment['match_ratio']:.0%}，位移 {alignment['displacement']:.1f}px", "gray")
            if self.sample_pattern == "cross":
                if page.columns<5 or len(page.rows)<5:
                    self.log_cb("[测试] 当前完整网格不足5行5列，停止", "red")
                    return
                fresh = ([(page.rows[0][col],1,col+1) for col in range(5)] +
                         [(page.rows[row][0],row+1,1) for row in range(5)])
                self.log_cb("[测试] 第一行5个 → 第一列5个；左上角重复一次，不翻页", "blue")
            for box, row, col in fresh:
                if not self.running:
                    return
                if self._limit_reached():
                    return
                x1,y1,x2,y2 = box
                crop = image[y1:y2,x1:x2]
                h,w = crop.shape[:2]
                center = cv2.cvtColor(crop[int(h*.3):int(h*.7),int(w*.3):int(w*.7)], cv2.COLOR_BGR2GRAY)
                mean, deviation = cv2.meanStdDev(center)
                if mean[0,0]<60 and deviation[0,0]<15:
                    continue
                scale = env["ui_scale"]
                gold = self.analyzer.is_gold(image[y1:min(image.shape[0],y2+int(12*scale)),x1:x2])
                if not gold and not self.dm.data.get("debug_gold", False):
                    continue
                margin = int(10*scale)
                expanded = image[max(0,y1-margin):y2+margin,max(0,x1-margin):x2+margin]
                if self.dm.data.get("skip_marked", False) and self.analyzer.is_thumb_marked(expanded,scale,self.log_cb):
                    continue
                if not self._scan_one(layout, box, gold, row, col):
                    return
            if self._limit_reached():
                return
            if self.sample_pattern == "cross":
                self.log_cb("[测试] 横纵抽样已完成，不翻页", "blue")
                return
            if ended:
                self.log_cb("[整页] 连续两次翻页无新行，扫描结束", "blue")
                return
            try:
                plan = page_swipe_plan(page, roi, env["ui_scale"])
            except ValueError as exc:
                self.log_cb(f"[整页] {exc}，当前可见基质已处理，停止", "blue")
                return
            self.log_cb(f"[整页滑动] 距离 {plan['distance']}px，计划推进{plan['advance_rows']}行，保留{plan['overlap_rows']}行重叠，终点按住700ms", "gray")
            self.controller.swipe_page(env, plan, lambda: self.running)

    def _limit_reached(self):
        if self.max_items is not None and self.processed_items >= self.max_items:
            self.log_cb(f"[测试] 已检查 {self.processed_items} 个基质，达到上限，自动停止", "blue")
            return True
        return False
