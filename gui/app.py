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

        self.root.title("毕业基质自动识别工具beta v2.0 -by洁柔厨")
        self.root.geometry("540x600")
        self.root.attributes("-topmost", True)

        self.running = False
        self.setup_ui()

        self.kb = keyboard.Listener(on_press=self.on_press)
        self.kb.start()

    def setup_ui(self):
        icon_path = resource_path(os.path.join("img", "jizhi.ico"))
        if os.path.exists(icon_path):
            try:
                img = Image.open(icon_path)
                self.tk_icon = ImageTk.PhotoImage(img)
                self.root.iconphoto(True, self.tk_icon)
            except:
                pass

        MUTED_RED = "#B71C1C"
        header = tk.Frame(self.root)
        header.pack(anchor="nw", padx=10, pady=5, fill="x")

        lf = tk.Frame(header)
        lf.pack(side="left", anchor="nw")
        tk.Button(lf, text="添加错字纠正", command=lambda: show_add_correction_popup(self.root, self.dm),
                  font=("微软雅黑", 8), bg="#F5F5F5", padx=2).pack(anchor="w", pady=(2, 0))
        tk.Button(lf, text="修改武器数据", command=lambda: show_weapon_editor_popup(self.root, self.dm),
                  font=("微软雅黑", 8), bg="#F5F5F5", padx=2).pack(anchor="w", pady=(2, 0))
        self.debug_gold_var = tk.BooleanVar(value=False)
        tk.Checkbutton(lf, text="关闭金色识别", variable=self.debug_gold_var, font=("微软雅黑", 8)).pack(anchor="w",
                                                                                                         pady=(2, 0))

        rf = tk.Frame(header)
        rf.pack(side="left", anchor="nw", padx=(35, 0))

        r1 = tk.Frame(rf)
        r1.pack(anchor="w")
        tk.Label(r1, text="| 扫描速度:").pack(side="left")
        self.speed_var = tk.StringVar(value=self.dm.data.get("speed", "0.2"))
        tk.Entry(r1, textvariable=self.speed_var, width=5).pack(side="left", padx=0)

        self.run_btn = tk.Button(rf, text="▶ 开始全自动扫描", command=self.start_thread, bg="#2E7D32", fg="white",
                                 font=("微软雅黑", 12, "bold"), width=15, height=1)
        self.run_btn.pack(anchor="center", pady=(5, 0))
        tk.Label(rf, text="（自动适配分辨率，按 'B' 停止）", font=("微软雅黑", 9), fg=MUTED_RED).pack(anchor="center")

        tk.Label(self.root, text="实时日志:", font=("微软雅黑", 11, "bold")).pack(anchor="w", padx=10, pady=(10, 0))
        self.log_area = scrolledtext.ScrolledText(self.root, height=10, width=60, font=("微软雅黑", 12))
        self.log_area.pack(padx=10, pady=5)
        for t, c in [("black", "black"), ("green", "#2E7D32"), ("gold", "#FF9800"), ("red", "#B71C1C"), ("blue", "blue"), ("gray", "#757575")]:
            self.log_area.tag_config(t, foreground=c)

        tk.Label(self.root, text="已锁定列表:", font=("微软雅黑", 11, "bold"), fg=MUTED_RED).pack(anchor="w", padx=10)
        self.lock_list_area = scrolledtext.ScrolledText(self.root, height=8, width=60, font=("微软雅黑", 12),
                                                        bg="#F9F9F9")
        self.lock_list_area.pack(padx=10, pady=5, fill="x")
        for t, c in [("red_text", "#B71C1C"), ("gold_text", "#FF9800"), ("green_text", "#2E7D32"),
                     ("black_text", "black")]:
            self.lock_list_area.tag_config(t, foreground=c)

        tk.Label(self.root, text="群号: 1006580737\n本工具完全免费", font=("微软雅黑", 9, "bold"), fg="#FF5722",
                 justify="right").place(relx=1.0, x=-10, y=10, anchor="ne")

    def gui_log(self, m, tag="black"):
        self.log_area.insert(tk.END, m + "\n", tag)
        self.log_area.see(tk.END)

    def on_press(self, k):
        if hasattr(k, 'char') and k.char == 'b' and self.running:
            self.gui_log("[停止] 任务已中止", "red")
            self.running = False

    def start_thread(self):
        self.dm.data["speed"] = self.speed_var.get()
        self.dm.save_config()
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

            curr_row = 0
            while self.running:
                time.sleep(0.01)
                spd = float(self.speed_var.get() or 0.3)

                win_img = self.controller.capture_window_bg(env["hwnd"], env["res_w"], env["res_h"])
                if win_img is None:
                    self.gui_log("[错误] 后台截图失败", "red")
                    break

                for c in range(9):
                    if not self.running: break

                    rx = layout["grid_p11"][0] + c * layout["grid_dx"]
                    ry = layout["grid_p11"][1] + min(curr_row, 4) * layout["grid_dy"]

                    img_x = int(rx - env["abs_x"])
                    img_y = int(ry - env["abs_y"])
                    mw, mh = layout["matrix_size"]

                    is_gold_res = self.analyzer.is_gold(
                        win_img[max(0, img_y - mh // 2):img_y + mh // 2, max(0, img_x - mw // 2):img_x + mw // 2])

                    if self.debug_gold_var.get() or is_gold_res:
                        self.gui_log(f"--- 检查: {curr_row + 1}-{c + 1} ---")

                        self.controller.click_at(rx, ry, delay=spd)

                        scr = self.controller.capture_window_bg(env["hwnd"], env["res_w"], env["res_h"])
                        roi_x, roi_y, roi_w, roi_h = layout["roi"]
                        o_img = scr[roi_y: roi_y + roi_h, roi_x: roi_x + roi_w]

                        gray_scaled = cv2.resize(cv2.cvtColor(o_img, cv2.COLOR_BGR2GRAY), None, fx=1.5, fy=1.5,
                                                 interpolation=cv2.INTER_NEAREST)
                        res, _ = self.analyzer.ocr(cv2.cvtColor(gray_scaled, cv2.COLOR_GRAY2BGR))

                        display_str, skills, levels = self.analyzer.parse_ocr_lines(res)

                        if display_str:
                            self.gui_log(f"识别结果: {display_str}", "green")

                            is_keep, weapon_name, match_type = self.analyzer.check_all_attributes(self.dm.weapon_list,
                                                                                                  skills, levels)

                            if is_keep:
                                if match_type == "graduation":
                                    self.gui_log("⭐ 识别到毕业基质！", "gold")
                                else:
                                    self.gui_log("⭐ 识别到潜力基质！", "gold")

                                lock_rel_pos = (layout["lock_btn"][0] - env["abs_x"],
                                                layout["lock_btn"][1] - env["abs_y"])

                                if self.analyzer.is_already_locked_bg(scr, lock_rel_pos, env["scale_x"],
                                                                      env["scale_y"]):
                                    self.gui_log("该基质已锁定，跳过", "red")
                                else:
                                    self.controller.click_at(layout["lock_btn"][0], layout["lock_btn"][1], delay=0.4)
                                    self.gui_log("-> 已执行锁定指令", "blue")
                                    self.controller.move_rel(50, 50)

                                name_color = "gold_text" if weapon_name == "潜力基质" else "red_text"
                                self.lock_list_area.insert(tk.END, f"{weapon_name} ", name_color)
                                self.lock_list_area.insert(tk.END, f"{display_str} ", "green_text")
                                self.lock_list_area.insert(tk.END, f"坐标{curr_row + 1}-{c + 1}\n", "black_text")
                                self.lock_list_area.see(tk.END)

                                # 【核心新增】：不符合保留条件的基质，执行废弃逻辑！
                            else:
                                self.gui_log("判定为垃圾基质，准备废弃", "gray")
                                discard_rel_pos = (layout["discard_btn"][0] - env["abs_x"],
                                                   layout["discard_btn"][1] - env["abs_y"])

                                if self.analyzer.is_already_discarded_bg(scr, discard_rel_pos, env["scale_x"],
                                                                         env["scale_y"]):
                                    self.gui_log("该基质已废弃，跳过", "gray")
                                else:
                                    self.controller.click_at(layout["discard_btn"][0], layout["discard_btn"][1],
                                                             delay=0.4)
                                    self.gui_log("-> 已执行废弃指令", "gray")
                                    self.controller.move_rel(50, 50)
                        else:
                            self.gui_log("-> 未读到词条")
                    else:
                        self.gui_log(f"非金色基质，停止扫描")
                        self.running = False
                        break

                if not self.running: break

                if curr_row >= 4:
                    self.gui_log(f"[翻页] 向上滑动...", "black")
                    self.controller.swipe_up(layout["swipe_start"][0], layout["swipe_start"][1], layout["swipe_dist"])

                curr_row += 1

        except Exception as e:
            self.gui_log(f"[异常] {e}", "red")
        finally:
            self.root.after(0, lambda: self.run_btn.config(state="normal", text="▶ 开始全自动扫描"))