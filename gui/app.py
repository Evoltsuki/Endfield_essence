import os
import time
import cv2
import threading
import tkinter as tk
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
        filter_lf = tk.LabelFrame(header, text="  ⚙扫描过滤 ", font=("微软雅黑", 10, "bold"), fg="#424242", padx=5,
                                  pady=5)
        filter_lf.grid(row=0, column=0, sticky="nsew", padx=(0, 2))

        self.skip_marked_var = tk.BooleanVar(value=False)
        tk.Checkbutton(filter_lf, text="跳过已标记基质", variable=self.skip_marked_var, font=("微软雅黑", 8)).pack(
            anchor="w", pady=1)

        self.ignore_5star_var = tk.BooleanVar(value=True)
        tk.Checkbutton(filter_lf, text="不锁定五星武器", variable=self.ignore_5star_var, font=("微软雅黑", 8)).pack(
            anchor="w", pady=1)

        self.debug_gold_var = tk.BooleanVar(value=False)
        tk.Checkbutton(filter_lf, text="识别紫色基质", variable=self.debug_gold_var, font=("微软雅黑", 8)).pack(
            anchor="w", pady=1)

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

            while self.running:
                target_ry = layout["grid_p11"][1]
                any_gold_in_row = False

                win_img = self.controller.capture_window_bg(env["hwnd"], env["res_w"], env["res_h"])
                if win_img is None:
                    self.gui_log("[错误] 后台截图失败", "red")
                    break

                for c in range(9):
                    if not self.running: break

                    target_rx = layout["grid_p11"][0] + c * layout["grid_dx"]
                    img_x, img_y = int(target_rx - env["abs_x"]), int(target_ry - env["abs_y"])
                    mw, mh = layout["matrix_size"]

                    is_gold_res = self.analyzer.is_gold(
                        win_img[max(0, img_y - mh // 2):img_y + mh // 2, max(0, img_x - mw // 2):img_x + mw // 2])

                    if self.debug_gold_var.get() or is_gold_res:
                        any_gold_in_row = True

                        self.gui_log(f"--- 检查: {total_rows + 1}-{c + 1} ---")
                        # 核心修改点：速度彻底恒定为 0.2 秒最优解
                        self.controller.click_at(target_rx, target_ry, delay=0.2)

                        scr = self.controller.capture_window_bg(env["hwnd"], env["res_w"], env["res_h"])
                        lock_rel_pos = (layout["lock_btn"][0] - env["abs_x"], layout["lock_btn"][1] - env["abs_y"])
                        discard_rel_pos = (layout["discard_btn"][0] - env["abs_x"],
                                           layout["discard_btn"][1] - env["abs_y"])

                        if self.skip_marked_var.get():
                            is_locked = self.analyzer.is_already_locked_bg(scr, lock_rel_pos, env["scale_x"],
                                                                           env["scale_y"])
                            is_discarded = self.analyzer.is_already_discarded_bg(scr, discard_rel_pos, env["scale_x"],
                                                                                 env["scale_y"])

                            if is_locked or is_discarded:
                                status = "锁定" if is_locked else "废弃"
                                self.gui_log(f"-> 该基质已{status}，秒跳过", "gray")
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

                            # 【核心新增】：如果开启了五星过滤，剔除列表中的五星武器
                            if is_keep and self.ignore_5star_var.get():
                                # 只保留星级里没有 "5" 的武器
                                matched_weapons = [w for w in matched_weapons if "5" not in w[1]]
                                # 如果过滤完之后发现没有值得保留的武器了，直接判定为垃圾
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

                                # 【动态分段渲染颜色】：遍历所有匹配到的武器
                                for idx, (w_name, w_star) in enumerate(matched_weapons):
                                    name_color = "red_text" if "6" in w_star else "gold_text"

                                    # 插入带颜色的武器名
                                    self.lock_list_area.insert(tk.END, w_name, name_color)

                                    # 如果不是最后一把武器，插入一个黑色的 '|' 竖线
                                    if idx < len(matched_weapons) - 1:
                                        self.lock_list_area.insert(tk.END, "|", "black_text")

                                # 武器名字打印完后，再打印词条和坐标
                                self.lock_list_area.insert(tk.END, f" {display_str} ", "green_text")
                                self.lock_list_area.insert(tk.END, f"坐标{total_rows + 1}-{c + 1}\n", "black_text")
                                self.lock_list_area.see(tk.END)

                            else:
                                self.gui_log("判定为垃圾基质，准备废弃", "gray")
                                if not self.analyzer.is_already_discarded_bg(scr, discard_rel_pos, env["scale_x"],
                                                                             env["scale_y"]):
                                    self.controller.click_at(layout["discard_btn"][0], layout["discard_btn"][1],
                                                             delay=0.4)
                                    self.gui_log("-> 已执行废弃指令", "gray")
                                    self.controller.move_rel(50, 50)
                        else:
                            self.gui_log("-> 未读到词条")
                    else:
                        pass

                if not self.running: break

                if any_gold_in_row:
                    self.gui_log(f"[翻页] 向上滑动...", "black")
                    if total_rows == 0:
                        dist = layout["swipe_dist_first"]
                    else:
                        dist = layout["swipe_dist_next"]

                    self.controller.swipe_up(layout["swipe_start"][0], layout["swipe_start"][1], dist)
                    total_rows += 1
                    time.sleep(0.5)
                else:
                    self.gui_log(f"非金色基质，停止扫描", "black")
                    self.running = False
                    break

        except Exception as e:
            self.gui_log(f"[异常] {e}", "red")
        finally:
            self.root.after(0, lambda: self.run_btn.config(state="normal", text="▶ 开始扫描"))