import os
import json
import threading
import tkinter as tk
from tkinter import scrolledtext
from PIL import Image, ImageTk
from pynput import keyboard
from utils.sys_helper import resource_path
from gui.windows import show_add_correction_popup, show_weapon_editor_popup
from core.scanner import AutoScanner


class MatrixAssistantApp:
    def __init__(self, root, dm, controller, analyzer):
        self.root = root
        self.dm = dm
        self.controller = controller
        self.analyzer = analyzer
        self.scanner = None

        # 定义主窗口尺寸
        self.app_width = 530
        self.app_height = 800

        self.root.title("毕业基质自动识别工具beta v2.5 -by洁柔厨")
        self.root.attributes("-topmost", True)

        # 拦截关闭事件，绑定到自定义的保存逻辑
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.setup_ui()

        # 恢复上次窗口位置或默认居中
        self.restore_window_position()

        self.kb = keyboard.Listener(on_press=self.on_press)
        self.kb.start()

    def restore_window_position(self):
        """恢复上一次位置，如果没有记录则屏幕居中"""
        self.root.update_idletasks()

        # 默认居中坐标
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        default_x = (sw - self.app_width) // 2
        default_y = (sh - self.app_height) // 2

        # 从 dm 统一的配置中读取坐标
        pos_x = self.dm.data.get("window_x")
        pos_y = self.dm.data.get("window_y")

        # 如果是没有保存过位置（第一次打开），就使用默认居中
        if pos_x is None or pos_y is None:
            pos_x, pos_y = default_x, default_y
        else:
            # 确保窗口不会因为显示器分辨率变化跑到屏幕外面
            if pos_x < 0 or pos_x > sw - 100: pos_x = default_x
            if pos_y < 0 or pos_y > sh - 100: pos_y = default_y

        self.root.geometry(f"{self.app_width}x{self.app_height}+{pos_x}+{pos_y}")

    def on_close(self):
        """窗口关闭前保存坐标到统一 config 中，并清理后台线程"""
        self.root.update_idletasks()

        # 将当前坐标存入 data 字典，并调用 dm 的方法统一保存
        self.dm.data["window_x"] = self.root.winfo_x()
        self.dm.data["window_y"] = self.root.winfo_y()
        self.dm.save_config()

        # 停止键盘监听，防止线程残留
        if self.kb:
            self.kb.stop()

        self.root.destroy()
        os._exit(0)

    def setup_ui(self):
        self.root.resizable(True, True)
        self.root.pack_propagate(False)
        self.root.grid_propagate(False)
        self.locked_history = []

        icon_path = resource_path(os.path.join("img", "jizhi.ico"))
        if os.path.exists(icon_path):
            try:
                img = Image.open(icon_path)
                self.tk_icon = ImageTk.PhotoImage(img)
                self.root.iconphoto(True, self.tk_icon)
            except:
                pass

        MUTED_RED = "#B71C1C"

        top_info_frame = tk.Frame(self.root)
        top_info_frame.pack(fill="x", padx=10, pady=(10, 0))

        tk.Label(top_info_frame, text="群号: 1006580737", font=("微软雅黑", 9, "bold"), fg="#FF5722").pack(side="left")
        tk.Label(top_info_frame, text="本工具完全免费", font=("微软雅黑", 9, "bold"), fg="#FF5722").pack(side="right")

        header = tk.Frame(self.root)
        header.pack(fill="x", padx=10, pady=(5, 10))
        header.columnconfigure(0, weight=1, uniform="col")
        header.columnconfigure(1, weight=1, uniform="col")
        header.columnconfigure(2, weight=1, uniform="col")

        filter_lf = tk.LabelFrame(header, text="  ⚙扫描过滤 ", font=("微软雅黑", 10, "bold"), fg="#424242", padx=5,
                                  pady=5)
        filter_lf.grid(row=0, column=0, sticky="nsew", padx=(0, 2))

        self.skip_marked_var = tk.BooleanVar(value=self.dm.data.get("skip_marked", False))
        tk.Checkbutton(filter_lf, text="跳过已标记基质", variable=self.skip_marked_var,
                       command=self.save_ui_config, font=("微软雅黑", 8)).pack(anchor="w", pady=1)

        self.ignore_5star_var = tk.BooleanVar(value=self.dm.data.get("ignore_5star", True))
        tk.Checkbutton(filter_lf, text="不锁定五星武器", variable=self.ignore_5star_var,
                       command=self.save_ui_config, font=("微软雅黑", 8)).pack(anchor="w", pady=1)

        self.debug_gold_var = tk.BooleanVar(value=self.dm.data.get("debug_gold", False))
        tk.Checkbutton(filter_lf, text="识别紫色基质", variable=self.debug_gold_var,
                       command=self.save_ui_config, font=("微软雅黑", 8)).pack(anchor="w", pady=1)

        action_f = tk.Frame(header)
        action_f.grid(row=0, column=1, sticky="nsew")

        center_box = tk.Frame(action_f)
        center_box.place(relx=0.5, rely=0.5, anchor="center")

        self.run_btn = tk.Button(center_box, text="▶ 开始扫描", command=self.start_thread, bg="#2E7D32",
                                 fg="white", font=("微软雅黑", 10, "bold"), width=14, height=2, relief="ridge",
                                 borderwidth=2)
        self.run_btn.pack(pady=(0, 5))
        tk.Label(center_box, text="（按 'B' 停止）", font=("微软雅黑", 8), fg=MUTED_RED).pack()

        data_lf = tk.LabelFrame(header, text="  🗃数据管理 ", font=("微软雅黑", 10, "bold"), fg="#424242", padx=5,
                                pady=5)
        data_lf.grid(row=0, column=2, sticky="nsew", padx=(2, 0))

        data_inner = tk.Frame(data_lf)
        data_inner.pack(expand=True, fill="both", pady=(2, 0))

        tk.Button(data_inner, text="✍添加错字纠正", command=lambda: show_add_correction_popup(self.root, self.dm),
                  font=("微软雅黑", 8), bg="#F5F5F5").pack(fill="x", pady=(2, 6), ipady=1)
        tk.Button(data_inner, text="⚔修改武器数据", command=lambda: show_weapon_editor_popup(self.root, self.dm),
                  font=("微软雅黑", 8), bg="#F5F5F5").pack(fill="x", pady=(0, 2), ipady=1)

        # ---------------- 核心修改区：引入 PanedWindow 实现可拖拽 ----------------
        content_frame = tk.Frame(self.root)
        content_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # 创建一个垂直布局的 PanedWindow，sashwidth 控制拖动条宽度，sashrelief 增加拖动条立体感
        self.paned_window = tk.PanedWindow(content_frame, orient=tk.VERTICAL, sashwidth=6, sashrelief=tk.RAISED, bg="#E0E0E0")
        self.paned_window.pack(fill="both", expand=True)

        # === 拖拽区域 1：实时日志 ===
        log_pane = tk.Frame(self.paned_window)
        # minsize 防止拖拽得太小导致控件消失
        self.paned_window.add(log_pane, stretch="always", minsize=100)

        tk.Label(log_pane, text="实时日志:", font=("微软雅黑", 11, "bold")).pack(anchor="w")
        # 移除了固定 height 属性，让布局管理器接管高度
        self.log_area = scrolledtext.ScrolledText(log_pane, height=5, font=("微软雅黑", 10), relief="solid",
                                                  borderwidth=1)
        self.log_area.pack(pady=(2, 5), fill="both", expand=True)
        for t, c in [("black", "black"), ("green", "#2E7D32"), ("gold", "#FF9800"),
                     ("red", "#B71C1C"), ("blue", "blue"), ("gray", "#757575")]:
            self.log_area.tag_config(t, foreground=c)

        # === 拖拽区域 2：已锁定列表 ===
        lock_pane = tk.Frame(self.paned_window)
        # 默认给它更多的初始空间，相当于原来的 height=12 的感觉
        self.paned_window.add(lock_pane, stretch="always", minsize=150)

        tk.Label(lock_pane, text="已锁定列表:", font=("微软雅黑", 11, "bold"), fg=MUTED_RED).pack(anchor="w")
        self.lock_list_area = scrolledtext.ScrolledText(lock_pane, height=11, font=("微软雅黑", 10), bg="#F9F9F9",
                                                        relief="solid", borderwidth=1)
        self.lock_list_area.pack(pady=(2, 0), fill="both", expand=True)
        for t, c in [("red_text", "#B71C1C"), ("gold_text", "#FF9800"), ("green_text", "#2E7D32"),
                     ("black_text", "black")]:
            self.lock_list_area.tag_config(t, foreground=c)
        # -------------------------------------------------------------------------

    def gui_log(self, m, tag="black"):
        self.root.after(0, self._gui_log_safe, m, tag)

    def _gui_log_safe(self, m, tag):
        self.log_area.insert(tk.END, m + "\n", tag)
        self.log_area.see(tk.END)

    def add_to_lock_list(self, data):
        self.root.after(0, self._add_to_lock_list_safe, data)

    def _add_to_lock_list_safe(self, data):
        self.locked_history.append(data)

        def sort_key(item):
            weapons = item.get("weapons", [])
            max_star = 0
            primary_name = ""
            if weapons:
                primary_name = weapons[0][0]
                for w_name, w_star in weapons:
                    stars = [int(s) for s in w_star if s.isdigit()]
                    if stars:
                        max_star = max(max_star, stars[0])
            return (-max_star, primary_name)

        self.locked_history.sort(key=sort_key)
        self.lock_list_area.delete('1.0', tk.END)

        for item in self.locked_history:
            matched_weapons = item.get("weapons", [])
            for w_idx, (w_name, w_star) in enumerate(matched_weapons):
                name_color = "red_text" if "6" in w_star else "gold_text"
                self.lock_list_area.insert(tk.END, w_name, name_color)
                if w_idx < len(matched_weapons) - 1:
                    self.lock_list_area.insert(tk.END, "|", "black_text")

            self.lock_list_area.insert(tk.END, f" {item.get('display_str', '')} ", "green_text")
            self.lock_list_area.insert(tk.END, f"坐标{item.get('row', '?')}-{item.get('col', '?')}\n", "black_text")

    def on_scan_finish(self):
        self.root.after(0, self._on_scan_finish_safe)

    def _on_scan_finish_safe(self):
        self.run_btn.config(state="normal", text="▶ 开始扫描")
        self.scanner = None

    def on_press(self, k):
        if hasattr(k, 'char') and k.char == 'b':
            if self.scanner and self.scanner.running:
                self.gui_log("[停止] 已发送停止指令，请等待当前操作完成...", "red")
                self.scanner.stop()

    def save_ui_config(self):
        self.dm.data["skip_marked"] = self.skip_marked_var.get()
        self.dm.data["ignore_5star"] = self.ignore_5star_var.get()
        self.dm.data["debug_gold"] = self.debug_gold_var.get()
        self.dm.save_config()

    def start_thread(self):
        if self.scanner and self.scanner.running: return
        self.save_ui_config()
        self.dm.corrections = self.dm.load_corrections()
        self.log_area.delete('1.0', tk.END)
        self.lock_list_area.delete('1.0', tk.END)
        self.locked_history.clear()
        self.gui_log("[系统] 全自动扫描启动，按 'B' 键停止", "blue")
        self.run_btn.config(state="disabled", text="正在扫描...")

        callbacks = {
            "log": self.gui_log,
            "lock": self.add_to_lock_list,
            "finish": self.on_scan_finish
        }
        self.scanner = AutoScanner(self.dm, self.controller, self.analyzer, callbacks)
        threading.Thread(target=self.scanner.start, daemon=True).start()