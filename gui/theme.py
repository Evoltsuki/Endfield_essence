"""主界面和编辑窗口共用的浅色主题与按钮交互。"""
import tkinter as tk
from tkinter import ttk

BG = "#F5F3EF"
SURFACE = "#FFFFFF"
INK = "#243247"
MUTED = "#64748B"
GREEN = "#278456"


def apply_theme(widget):
    """保留结果文字的颜色语义，统一容器、输入框及按钮。"""
    if getattr(widget, 'keep_style', False):
        return
    kind = widget.winfo_class()
    if kind in ("Tk", "Toplevel"):
        style = ttk.Style(widget)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=SURFACE, background="#DCE7F4",
                        foreground=INK, padding=4, bordercolor="#DCE3EC")
        style.map("TCombobox", fieldbackground=[("readonly", SURFACE)],
                  foreground=[("readonly", INK)])
        style.configure("TScrollbar", background="#C4CEDA", troughcolor=BG, borderwidth=0)
    if kind in ("Tk", "Toplevel", "Frame", "Canvas"):
        widget.configure(bg=getattr(widget, "surface_color", BG))
    elif kind == "Labelframe":
        widget.configure(bg=getattr(widget, "input_color", SURFACE), fg=INK, relief="solid", bd=1,
                         font=("Microsoft YaHei UI", 10, "bold"))
    elif kind in ("Label", "Checkbutton"):
        parent_bg = widget.master.cget("bg")
        widget.configure(bg=parent_bg)
        if kind == "Checkbutton":
            widget.configure(activebackground=parent_bg, fg=INK, selectcolor=SURFACE,
                             highlightthickness=0, cursor="hand2")
    elif kind in ("Entry", "Spinbox"):
        widget.configure(bg=SURFACE, fg=INK, relief="solid", bd=1,
                         highlightthickness=1, highlightcolor="#4F8CC9", highlightbackground="#DCE3EC")
    elif kind == "Button":
        current_bg = widget.cget("bg").lower()
        role = getattr(widget, "theme_role", None)
        if role is None:
            role = ("primary" if current_bg in ("#2e7d32", GREEN.lower()) else
                    "danger" if current_bg in ("#d32f2f", "#ffebee") or widget.cget("fg").lower() in ("#b71c1c", "#c62828") else
                    "warning" if current_bg == "#ff9800" else "secondary")
            widget.theme_role = role
        base, hover, foreground = {
            "primary": (GREEN, "#216F49", "white"),
            "danger": ("#F9DBDC", "#F3BFC1", "#A3222C"),
            "warning": ("#FBE5B7", "#F3D18A", "#865509"),
            "secondary": ("#DCE7F4", "#C5D8EE", "#2E557F"),
        }[role]
        widget.configure(bg=base, fg=foreground,
                         activebackground=hover, activeforeground=foreground,
                         disabledforeground="#96A0AE", relief="flat", bd=0,
                         highlightthickness=1, highlightbackground=base, highlightcolor="#4F8CC9",
                         cursor="hand2", takefocus=True)
        widget.bind("<Enter>", lambda event: widget.configure(bg=hover) if str(widget['state']) != 'disabled' else None)
        widget.bind("<Leave>", lambda event: widget.configure(bg=base))
    for child in widget.winfo_children():
        apply_theme(child)
