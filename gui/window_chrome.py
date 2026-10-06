"""自绘标题栏、拖动及八方向缩放。"""
import tkinter as tk
import win32con
import win32gui
from utils.version import APP_TITLE


class CaptionButton(tk.Canvas):
    """使用同一像素坐标绘制图标，避免字体字形造成视觉尺寸差异。"""
    def __init__(self, parent, symbol, command, hover):
        super().__init__(parent, width=42, height=32, bg='#29384A', highlightthickness=0,
                         bd=0, takefocus=True, cursor='hand2')
        self.symbol, self.command = symbol, command
        self.keep_style = True
        if symbol == '×':
            self.create_line(16, 11, 26, 21, fill='white', width=1)
            self.create_line(16, 21, 26, 11, fill='white', width=1)
        elif symbol == '□':
            self.create_rectangle(16, 11, 26, 21, outline='white', width=1)
        else:
            self.create_line(16, 16, 26, 16, fill='white', width=1)
        for event in ('<Enter>', '<FocusIn>'):
            self.bind(event, lambda event: self.configure(bg=hover))
        for event in ('<Leave>', '<FocusOut>'):
            self.bind(event, lambda event: self.configure(bg='#29384A'))
        self.bind('<ButtonRelease-1>', lambda event: self.invoke() if 0 <= event.x < 42 and 0 <= event.y < 32 else None)
        self.bind('<Return>', lambda event: self.invoke())
        self.bind('<space>', lambda event: self.invoke())

    def invoke(self):
        self.command()


class WindowChrome:
    def __init__(self, root, on_close):
        self.root = root
        self.restore_geometry = None
        root.overrideredirect(True)
        root.minsize(240, 160)
        self.bar = tk.Frame(root, bg="#29384A", height=32)
        self.bar.surface_color = "#29384A"
        self.bar.pack(fill="x")
        self.bar.pack_propagate(False)
        self.buttons = []
        for text, command in (("×", on_close), ("□", self.maximize), ("—", self.minimize)):
            slot = tk.Frame(self.bar, width=42, height=32, bg="#29384A")
            slot.keep_style = True
            slot.pack(side="right")
            slot.pack_propagate(False)
            hover = "#BE3945" if text == '×' else '#41556E'
            button = CaptionButton(slot, text, command, hover)
            button.pack(fill="both", expand=True)
            self.buttons.append(button)
        title = tk.Label(self.bar, text=APP_TITLE, bg="#29384A", fg="white",
                         font=("Microsoft YaHei UI", 9, "bold"), anchor="w", padx=8)
        title.pack(side="left", fill="both", expand=True)
        for widget in (title, self.bar):
            widget.bind("<ButtonPress-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.drag)
            widget.bind("<Double-Button-1>", lambda event: self.maximize())
        self.resizing = False
        self.edge = ''
        root.bind('<Motion>', self.edge_motion, add='+')
        root.bind('<ButtonPress-1>', self.edge_press, add='+')
        root.bind('<B1-Motion>', self.edge_drag, add='+')
        root.bind('<ButtonRelease-1>', self.edge_release, add='+')
        root.after_idle(self.taskbar)

    def edge_at(self, event):
        x, y = event.x_root-self.root.winfo_rootx(), event.y_root-self.root.winfo_rooty()
        return ('n' if y < 5 else 's' if y >= self.root.winfo_height()-5 else '') + ('w' if x < 5 else 'e' if x >= self.root.winfo_width()-5 else '')

    def edge_motion(self, event):
        if self.resizing:
            return
        edge = self.edge_at(event)
        cursors = {'n': 'size_ns', 's': 'size_ns', 'w': 'size_we', 'e': 'size_we',
                   'nw': 'size_nw_se', 'se': 'size_nw_se', 'ne': 'size_ne_sw', 'sw': 'size_ne_sw'}
        if edge:
            if not hasattr(event.widget, '_original_cursor'):
                event.widget._original_cursor = event.widget.cget('cursor')
            event.widget.configure(cursor=cursors[edge])
        elif hasattr(event.widget, '_original_cursor'):
            event.widget.configure(cursor=event.widget._original_cursor)

    def edge_press(self, event):
        edge = self.edge_at(event)
        if edge:
            self.start_resize(event, edge)
            self.resizing = True
            self.root.grab_set()
            return 'break'

    def edge_drag(self, event):
        if self.resizing:
            self.resize(event)
            return 'break'

    def edge_release(self, event):
        if self.resizing:
            self.resizing = False
            self.root.grab_release()
            return 'break'

    def taskbar(self):
        self.root.update_idletasks()
        self.hwnd = win32gui.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
        win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE,
                              (style | win32con.WS_EX_APPWINDOW) & ~win32con.WS_EX_TOOLWINDOW)

    def minimize(self):
        self.taskbar()
        win32gui.ShowWindow(self.hwnd, win32con.SW_MINIMIZE)

    def maximize(self):
        if self.restore_geometry:
            self.root.geometry(self.restore_geometry)
            self.restore_geometry = None
        else:
            self.restore_geometry = self.root.geometry()
            x, y, right, bottom = win32gui.SystemParametersInfo(win32con.SPI_GETWORKAREA)
            self.root.geometry(f'{right-x}x{bottom-y}{x:+d}{y:+d}')

    def start_drag(self, event):
        self.drag_origin = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def drag(self, event):
        if self.restore_geometry or self.resizing:
            return
        x, y, left, top = self.drag_origin
        self.root.geometry(f'{left+event.x_root-x:+d}{top+event.y_root-y:+d}')

    def start_resize(self, event, edge):
        self.restore_geometry = None
        self.resize_origin = (edge, event.x_root, event.y_root, self.root.winfo_x(),
                              self.root.winfo_y(), self.root.winfo_width(), self.root.winfo_height())

    def resize(self, event):
        edge, x, y, left, top, width, height = self.resize_origin
        dx, dy = event.x_root-x, event.y_root-y
        new_width = max(240, width + (dx if 'e' in edge else -dx if 'w' in edge else 0))
        new_height = max(160, height + (dy if 's' in edge else -dy if 'n' in edge else 0))
        if 'w' in edge:
            left += width-new_width
        if 'n' in edge:
            top += height-new_height
        self.root.geometry(f'{new_width}x{new_height}{left:+d}{top:+d}')
