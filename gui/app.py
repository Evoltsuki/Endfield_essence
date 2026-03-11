import os
import time
import cv2
import threading
import tkinter as tk
import numpy as np
from tkinter import scrolledtext
from PIL import Image, ImageTk
from pynput import keyboard
from utils.sys_helper import resource_path
from gui.windows import show_add_correction_popup, show_weapon_editor_popup


class MatrixAssistantApp:
    def __init__(self, root, dm, controller, analyzer):
        self.root = root
        self.dm = dm
        self.controller = controller
        self.analyzer = analyzer

        self.root.title("毕业基质自动识别工具beta v2.1 -by洁柔厨")
        self.root.attributes("-topmost", True)

        self.running = False
        self.setup_ui()

        self.kb = keyboard.Listener(on_press=self.on_press)
        self.kb.start()

    def setup_ui(self):
        # 1. 严格规定你的尺寸
        self.root.geometry("530x768")
        self.root.resizable(True, True)
        self.root.pack_propagate(False)
        self.root.grid_propagate(False)

        icon_path = resource_path(os.path.join("img", "jizhi.ico"))
        if os.path.exists(icon_path):
            try:
                img = Image.open(icon_path)
                self.tk_icon = ImageTk.PhotoImage(img)
                self.root.iconphoto(True, self.tk_icon)
            except:
                pass

        MUTED_RED = "#B71C1C"

        # ==========================================
        # 1. 顶部信息栏 (缩减了两侧边距以适应 539 宽度)
        # ==========================================
        top_info_frame = tk.Frame(self.root)
        top_info_frame.pack(fill="x", padx=10, pady=(10, 0))  # padx 从 15 缩减到 10

        tk.Label(top_info_frame, text="群号: 1006580737", font=("微软雅黑", 9, "bold"), fg="#FF5722").pack(side="left")
        tk.Label(top_info_frame, text="本工具完全免费", font=("微软雅黑", 9, "bold"), fg="#FF5722").pack(side="right")

        # ==========================================
        # 2. 顶部仪表盘区
        # ==========================================
        header = tk.Frame(self.root)
        header.pack(fill="x", padx=10, pady=(5, 10))

        header.columnconfigure(0, weight=1, uniform="col")
        header.columnconfigure(1, weight=1, uniform="col")
        header.columnconfigure(2, weight=1, uniform="col")

        # --- 第一区 (左侧)：扫描过滤模块 ---
        # --- 第一区 (左侧)：扫描过滤模块 ---
        filter_lf = tk.LabelFrame(header, text="  ⚙扫描过滤 ", font=("微软雅黑", 10, "bold"), fg="#424242", padx=5,
                                  pady=5)
        filter_lf.grid(row=0, column=0, sticky="nsew", padx=(0, 2))

        # 读取 config 的值作为初始状态，并绑定 command 触发保存
        self.skip_marked_var = tk.BooleanVar(value=self.dm.data.get("skip_marked", False))
        tk.Checkbutton(filter_lf, text="跳过已标记基质", variable=self.skip_marked_var,
                       command=self.save_ui_config, font=("微软雅黑", 8)).pack(anchor="w", pady=1)

        self.ignore_5star_var = tk.BooleanVar(value=self.dm.data.get("ignore_5star", True))
        tk.Checkbutton(filter_lf, text="不锁定五星武器", variable=self.ignore_5star_var,
                       command=self.save_ui_config, font=("微软雅黑", 8)).pack(anchor="w", pady=1)

        self.debug_gold_var = tk.BooleanVar(value=self.dm.data.get("debug_gold", False))
        tk.Checkbutton(filter_lf, text="识别紫色基质", variable=self.debug_gold_var,
                       command=self.save_ui_config, font=("微软雅黑", 8)).pack(anchor="w", pady=1)

        # --- 第二区 (正中间)：核心控制模块 ---
        action_f = tk.Frame(header)
        action_f.grid(row=0, column=1, sticky="nsew")

        center_box = tk.Frame(action_f)
        center_box.place(relx=0.5, rely=0.5, anchor="center")

        # 为了防止撑开，按钮宽度从 16 微调到 14，字体从 11 微调到 10
        self.run_btn = tk.Button(center_box, text="▶ 开始扫描", command=self.start_thread, bg="#2E7D32",
                                 fg="white",
                                 font=("微软雅黑", 10, "bold"), width=14, height=2, relief="ridge", borderwidth=2)
        self.run_btn.pack(pady=(0, 5))
        tk.Label(center_box, text="（按 'B' 停止）", font=("微软雅黑", 8), fg=MUTED_RED).pack()

        # --- 第三区 (右侧)：数据管理模块 ---
        data_lf = tk.LabelFrame(header, text="  🗃数据管理 ", font=("微软雅黑", 10, "bold"), fg="#424242", padx=5,
                                pady=5)
        data_lf.grid(row=0, column=2, sticky="nsew", padx=(2, 0))

        data_inner = tk.Frame(data_lf)
        data_inner.pack(expand=True, fill="both", pady=(2, 0))

        tk.Button(data_inner, text="✍添加错字纠正", command=lambda: show_add_correction_popup(self.root, self.dm),
                  font=("微软雅黑", 8), bg="#F5F5F5").pack(fill="x", pady=(2, 6), ipady=1)
        tk.Button(data_inner, text="⚔修改武器数据", command=lambda: show_weapon_editor_popup(self.root, self.dm),
                  font=("微软雅黑", 8), bg="#F5F5F5").pack(fill="x", pady=(0, 2), ipady=1)

        # ==========================================
        # 3. 中下部：日志与统计区
        # ==========================================
        content_frame = tk.Frame(self.root)
        content_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        tk.Label(content_frame, text="实时日志:", font=("微软雅黑", 11, "bold")).pack(anchor="w")
        self.log_area = scrolledtext.ScrolledText(content_frame, height=9, font=("微软雅黑", 10), relief="solid",
                                                  borderwidth=1)
        self.log_area.pack(pady=(2, 10), fill="both", expand=True)
        for t, c in [("black", "black"), ("green", "#2E7D32"), ("gold", "#FF9800"),
                     ("red", "#B71C1C"), ("blue", "blue"), ("gray", "#757575")]:
            self.log_area.tag_config(t, foreground=c)

        tk.Label(content_frame, text="已锁定列表:", font=("微软雅黑", 11, "bold"), fg=MUTED_RED).pack(anchor="w")
        # 由于你的高度达到了 768，我把锁定列表的高度稍微调大了一点，让它充分利用下方空间
        self.lock_list_area = scrolledtext.ScrolledText(content_frame, height=8, font=("微软雅黑", 10), bg="#F9F9F9",
                                                        relief="solid", borderwidth=1)
        self.lock_list_area.pack(pady=(2, 0), fill="both", expand=True)
        for t, c in [("red_text", "#B71C1C"), ("gold_text", "#FF9800"), ("green_text", "#2E7D32"),
                     ("black_text", "black")]:
            self.lock_list_area.tag_config(t, foreground=c)

    def gui_log(self, m, tag="black"):
        self.log_area.insert(tk.END, m + "\n", tag)
        self.log_area.see(tk.END)

    def on_press(self, k):
        if hasattr(k, 'char') and k.char == 'b' and self.running:
            self.gui_log("[停止] 任务已中止", "red")
            self.running = False

    def save_ui_config(self):
        """当用户点击复选框时触发，将 UI 状态同步到 dm 并保存"""
        self.dm.data["skip_marked"] = self.skip_marked_var.get()
        self.dm.data["ignore_5star"] = self.ignore_5star_var.get()
        self.dm.data["debug_gold"] = self.debug_gold_var.get()
        self.dm.save_config()

    def start_thread(self):
        # 移除了所有对 dm.save_config() 的调用，不再生成配置文件
        self.dm.corrections = self.dm.load_corrections()

        self.log_area.delete('1.0', tk.END)
        self.lock_list_area.delete('1.0', tk.END)
        self.gui_log("[系统] 全自动扫描启动，按 'B' 键停止", "blue")
        self.running = True
        self.run_btn.config(state="disabled", text="正在扫描...")
        threading.Thread(target=self.run_task, daemon=True).start()

    def run_task(self):
        try:
            layout = self.controller.get_scaled_layout()
            if not layout:
                self.gui_log("[错误] 未找到游戏窗口，请确保游戏正在运行！", "red")
                self.running = False
                return

            env = layout["env"]
            self.gui_log(f"[适配] 游戏内渲染分辨率: {env['res_w']}x{env['res_h']}", "blue")

            total_rows = 0
            final_sweep_mode = False  # 尾扫状态机

            while self.running:
                win_img = self.controller.capture_window_bg(env["hwnd"], env["res_w"], env["res_h"])
                if win_img is None:
                    self.gui_log("[错误] 后台截图失败", "red")
                    break

                # 1. 根据当前模式选择扫描框
                current_roi = layout["roi_final"] if final_sweep_mode else layout["roi_row1"]

                # 2. 绿幕匹配找框
                boxes = self.analyzer.find_essences_with_mask(win_img, current_roi, env["scale_x"], env["scale_y"])

                # 3. 剔除空槽，并分离物理计数与目标筛选
                physical_items_count = 0  # 当前行实际存在的基质数量（无论金紫）
                valid_boxes = []  # 需要点击识别的目标（受金紫过滤影响）

                for b in boxes:
                    bx1, by1, bx2, by2 = b
                    box_img = win_img[by1:by2, bx1:bx2]

                    # 剔除空槽位（通过中心亮度与对比度分析）
                    ch, cw = box_img.shape[:2]
                    center_roi = box_img[int(ch * 0.3):int(ch * 0.7), int(cw * 0.3):int(cw * 0.7)]
                    if center_roi.size > 0:
                        gray_center = cv2.cvtColor(center_roi, cv2.COLOR_BGR2GRAY)
                        mean_val, stddev = cv2.meanStdDev(gray_center)

                        if mean_val[0][0] < 60 and stddev[0][0] < 15.0:
                            continue  # 是空槽，直接跳过

                    physical_items_count += 1

                    # 颜色过滤（金紫判定）
                    if self.debug_gold_var.get() or self.analyzer.is_gold(box_img):
                        valid_boxes.append(b)

                # 4. 触底或空行检测
                if physical_items_count == 0:
                    if not final_sweep_mode:
                        self.gui_log("[系统] 探测行未发现基质，触发全局尾扫模式...", "blue")
                        final_sweep_mode = True
                        continue
                    else:
                        self.gui_log("[系统] 基质扫描结束！", "blue")
                        break

                # 5. 遍历处理有效目标基质
                for idx, b in enumerate(valid_boxes):
                    if not self.running: break
                    bx1, by1, bx2, by2 = b

                    # cx, cy 是相对游戏窗口内部的局部坐标
                    cx, cy = (bx1 + bx2) // 2, (by1 + by2) // 2

                    logic_row = total_rows + (idx // 9) + 1
                    logic_col = (idx % 9) + 1
                    self.gui_log(f"--- 检查: {logic_row}-{logic_col} ---")

                    # 【核心修复】：转换为显示器绝对坐标再点击
                    abs_cx = cx + env["abs_x"]
                    abs_cy = cy + env["abs_y"]
                    self.controller.click_at(abs_cx, abs_cy, delay=0.2)

                    scr = self.controller.capture_window_bg(env["hwnd"], env["res_w"], env["res_h"])
                    lock_rel_pos = (layout["lock_btn"][0] - env["abs_x"], layout["lock_btn"][1] - env["abs_y"])
                    discard_rel_pos = (layout["discard_btn"][0] - env["abs_x"], layout["discard_btn"][1] - env["abs_y"])

                    if self.skip_marked_var.get():
                        is_locked = self.analyzer.is_already_locked_bg(scr, lock_rel_pos, env["scale_x"],
                                                                       env["scale_y"])
                        is_discarded = self.analyzer.is_already_discarded_bg(scr, discard_rel_pos, env["scale_x"],
                                                                             env["scale_y"])

                        if is_locked or is_discarded:
                            status = "锁定" if is_locked else "废弃"
                            self.gui_log(f"-> 该基质已{status}，跳过", "gray")
                            continue

                    roi_x, roi_y, roi_w, roi_h = layout["roi"]
                    o_img = scr[roi_y: roi_y + roi_h, roi_x: roi_x + roi_w]

                    gray_scaled = cv2.resize(cv2.cvtColor(o_img, cv2.COLOR_BGR2GRAY), None, fx=1.5, fy=1.5,
                                             interpolation=cv2.INTER_NEAREST)
                    res, _ = self.analyzer.ocr(cv2.cvtColor(gray_scaled, cv2.COLOR_GRAY2BGR))

                    display_str, skills, levels = self.analyzer.parse_ocr_lines(res)

                    if display_str:
                        self.gui_log(f"识别结果: {display_str}", "green")
                        is_keep, matched_weapons, match_type = self.analyzer.check_all_attributes(
                            self.dm.weapon_list, skills, levels)

                        if is_keep and self.ignore_5star_var.get():
                            if match_type == "graduation":
                                matched_weapons = [w for w in matched_weapons if "5" not in w[1]]
                                if not matched_weapons:
                                    is_keep = False

                        if is_keep:
                            if match_type == "graduation":
                                self.gui_log("⭐ 识别到毕业基质！", "gold")
                            else:
                                self.gui_log("⭐ 识别到潜力基质！", "gold")

                            if not self.analyzer.is_already_locked_bg(scr, lock_rel_pos, env["scale_x"],
                                                                      env["scale_y"]):
                                self.controller.click_at(layout["lock_btn"][0], layout["lock_btn"][1], delay=0.4)
                                self.gui_log("-> 已执行锁定指令", "blue")
                                self.controller.move_rel(50, 50)

                            for w_idx, (w_name, w_star) in enumerate(matched_weapons):
                                name_color = "red_text" if "6" in w_star else "gold_text"
                                self.lock_list_area.insert(tk.END, w_name, name_color)
                                if w_idx < len(matched_weapons) - 1:
                                    self.lock_list_area.insert(tk.END, "|", "black_text")

                            self.lock_list_area.insert(tk.END, f" {display_str} ", "green_text")
                            self.lock_list_area.insert(tk.END, f"坐标{logic_row}-{logic_col}\n", "black_text")
                            self.lock_list_area.see(tk.END)

                        else:
                            self.gui_log("判定为垃圾基质，准备废弃", "gray")
                            if not self.analyzer.is_already_discarded_bg(scr, discard_rel_pos, env["scale_x"],
                                                                         env["scale_y"]):
                                self.controller.click_at(layout["discard_btn"][0], layout["discard_btn"][1], delay=0.4)
                                self.gui_log("-> 已执行废弃指令", "gray")
                                self.controller.move_rel(50, 50)
                    else:
                        self.gui_log("-> 未读到词条")

                if not self.running: break

                # 6. 【核心修复】：翻页与结束决策树
                if final_sweep_mode:
                    self.gui_log("[系统] 基质扫描结束！", "blue")
                    break

                # 防线A：利用游戏排序机制，如果扫到的物理基质里混入了低稀有度（被过滤掉了），直接下班！
                if physical_items_count > len(valid_boxes):
                    self.gui_log("[系统] 识别到紫色基质，扫描结束！", "blue")
                    break

                # 防线B：只有当这 9 个位置不仅全是非空基质，而且全都是目标颜色时，才翻页！
                if physical_items_count == 9:
                    self.gui_log("[翻页] 正在向上滑动...", "black")
                    dist = layout["swipe_dist_first"] if total_rows == 0 else layout["swipe_dist_next"]
                    self.controller.swipe_up(layout["swipe_start"][0], layout["swipe_start"][1], dist)
                    total_rows += 1
                    time.sleep(0.5)
                else:
                    self.gui_log("[系统] 基质扫描结束！", "blue")
                    break

        except Exception as e:
            self.gui_log(f"[异常] {e}", "red")
        finally:
            self.running = False
            self.root.after(0, lambda: self.run_btn.config(state="normal", text="▶ 开始扫描"))