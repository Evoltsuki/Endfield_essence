"""细长主窗口布局；扫描与数据回调由 app.py 管理。"""
import os
import tkinter as tk
from tkinter import scrolledtext
from PIL import Image, ImageTk
from gui.windows import show_add_correction_popup, show_weapon_editor_popup
from utils.sys_helper import resource_path
from gui.theme import apply_theme
from gui.window_chrome import WindowChrome
from gui.potential_editor import show_potential_editor


def build_main_view(app):
    root = app.root
    root.configure(bg="#F4F4F4")
    root.resizable(True, True)
    app.chrome = WindowChrome(root, app.on_close)
    font = ("Microsoft YaHei UI", 9)
    icon_path = resource_path(os.path.join("img", "jizhi.ico"))
    if os.path.exists(icon_path):
        try:
            with Image.open(icon_path) as icon:
                app.tk_icon = ImageTk.PhotoImage(icon)
            root.iconphoto(True, app.tk_icon)
        except (OSError, tk.TclError):
            pass
    app.settings_widgets = []
    app.locked_history = []
    info = tk.Frame(root, bg="#F4F4F4")
    info.pack(fill="x", padx=8, pady=(2, 0))
    tk.Label(info, text="本工具完全免费 · 群号: 1006580737", fg="#A26D20",
             font=("Microsoft YaHei UI", 8)).pack(side="right")
    header = tk.Frame(root, bg="#F4F4F4")
    header.pack(fill="x", padx=8, pady=(0, 3))
    for col in range(3):
        header.columnconfigure(col, weight=1, uniform="header")
    filters = tk.LabelFrame(header, text=" 扫描过滤 ", padx=6, pady=6,
                            font=("Microsoft YaHei UI", 10, "bold"), fg="#424242", labelanchor='n')
    filters.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
    filter_contents = tk.Frame(filters)
    filter_contents.surface_color = '#FFFFFF'
    filter_contents.pack(anchor='center')
    for attr, key, text, default in (
            ("skip_marked_var", "skip_marked", "跳过已标记基质", False),
            ("ignore_5star_var", "ignore_5star", "不锁定五星武器", True),
            ("debug_gold_var", "debug_gold", "识别紫色基质", False)):
        variable = tk.BooleanVar(value=app.dm.data.get(key, default))
        setattr(app, attr, variable)
        widget = tk.Checkbutton(filter_contents, text=text, variable=variable,
                                command=app.save_ui_config, font=font, anchor="w")
        widget.pack(fill="x", pady=2)
        app.settings_widgets.append(widget)
    actions = tk.Frame(header)
    actions.grid(row=0, column=1, sticky="nsew", padx=3, pady=(8, 0))
    app.run_btn = tk.Button(actions, text="▶ 开始扫描", command=app.start_thread,
                            bg="#2E7D32", fg="white", activebackground="#388E3C",
                            activeforeground="white", font=("Microsoft YaHei UI", 11, "bold"),
                            relief="raised", bd=1, pady=5)
    app.run_btn.pack(fill="x", pady=(6, 4))
    app.stop_btn = tk.Button(actions, text="停止 · B", command=app.stop_scan,
                             state="disabled", font=font, fg="#B71C1C", pady=3)
    app.stop_btn.pack(fill="x")
    app.status_var = tk.StringVar(value="就绪 · 0 件\n0.0 秒")
    app.status_label = tk.Label(actions, textvariable=app.status_var, font=("Microsoft YaHei UI", 8),
                                fg="#64748B", pady=2)
    app.status_label.pack(fill="x")
    data = tk.LabelFrame(header, text=" 数据管理 ", padx=8, pady=8,
                         font=("Microsoft YaHei UI", 10, "bold"), fg="#424242", labelanchor='n')
    data.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
    for text, command in (
            ("添加错字纠正", lambda: show_add_correction_popup(root, app.dm)),
            ("修改武器数据", lambda: show_weapon_editor_popup(root, app.dm)),
            ("锁定基质规则", lambda: show_potential_editor(root, app.dm))):
        widget = tk.Button(data, text=text, command=command, font=font, bg="#FAFAFA", pady=1)
        widget.pack(fill="x", pady=1)
        app.settings_widgets.append(widget)
    app.paned_window = tk.PanedWindow(root, orient=tk.VERTICAL, sashwidth=7,
                                     sashrelief=tk.RAISED, bg="#DEDEDE", bd=0)
    app.paned_window.pack(fill="both", expand=True, padx=12, pady=(0, 12))
    app.log_pane = tk.Frame(app.paned_window)
    app.paned_window.add(app.log_pane, stretch="always", minsize=45)
    title = tk.Frame(app.log_pane)
    title.pack(fill="x")
    tk.Label(title, text="识别结果", font=("Microsoft YaHei UI", 11, "bold"),
             fg="#333333").pack(side="left")
    app.review_count = 0
    app.review_var = tk.StringVar(value="需复核 0 件")
    tk.Label(title, textvariable=app.review_var, fg="#B71C1C", font=("Microsoft YaHei UI", 8)).pack(side="left", padx=8)
    if app.diagnostics:
        tk.Button(title, text="日志目录", command=lambda: os.startfile(app.diagnostics.directory),
                  font=("Microsoft YaHei UI", 8)).pack(side="left", padx=(0, 4))
    app.details_var = tk.BooleanVar(value=False)
    details = tk.Frame(app.log_pane)
    def toggle_details():
        if app.details_var.get():
            details.pack(fill="x", before=app.log_area.master)
        else:
            details.pack_forget()
    app.toggle_details = toggle_details
    tk.Checkbutton(title, text="显示图片预览", variable=app.details_var, command=toggle_details,
                   font=font).pack(side="right")
    app.preview_label = tk.Label(details, text="当前词条预览 · 等待扫描", anchor="w", font=font)
    app.preview_label.pack(fill="x")
    app.log_area = scrolledtext.ScrolledText(app.log_pane, height=10, font=("Microsoft YaHei UI", 10),
                                            bg="white", relief="solid", bd=1, wrap="word")
    app.log_area.pack(fill="both", expand=True, pady=(3, 0))
    app.log_area.configure(state="disabled", padx=9, pady=8)
    for tag, color in (("black", "black"), ("green", "#2E7D32"), ("gold", "#FF9800"),
                       ("red", "#B71C1C"), ("blue", "blue"), ("gray", "#757575"), ("orange", "#E65100")):
        app.log_area.tag_config(tag, foreground=color)
    history = tk.Frame(app.paned_window)
    app.paned_window.add(history, stretch="never", minsize=40, height=215)
    history_header = tk.Frame(history)
    history_header.pack(fill="x")
    tk.Label(history_header, text="已锁定", font=("Microsoft YaHei UI", 11, "bold"),
             fg="#B71C1C").pack(side="left")
    app.lock_count_var = tk.StringVar(value="0 件")
    tk.Label(history_header, textvariable=app.lock_count_var, fg="#64748B", font=font).pack(side="right", padx=8)
    app.lock_list_area = scrolledtext.ScrolledText(history, height=7, font=("Microsoft YaHei UI", 10),
                                                  bg="#F9F9F9", relief="solid", bd=1, wrap="word")
    app.lock_list_area.pack(fill="both", expand=True, pady=(3, 0))
    app.lock_list_area.configure(state="disabled", padx=9, pady=8)
    for tag, color in (("red_text", "#B71C1C"), ("gold_text", "#FF9800"),
                       ("green_text", "#2E7D32"), ("black_text", "black")):
        app.lock_list_area.tag_config(tag, foreground=color)
    apply_theme(root)
    filters.configure(fg="#315F91")
    data.configure(fg="#78559C")
