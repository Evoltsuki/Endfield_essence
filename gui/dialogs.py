"""将工具弹窗置于所属窗口中心，并限制在当前显示器工作区。"""
import win32api


def center_dialog(popup, parent, width=None, height=None, *, screen_center=False):
    popup.update_idletasks()
    parent.update_idletasks()
    width = width or popup.winfo_reqwidth()
    height = height or popup.winfo_reqheight()
    cx = parent.winfo_rootx() + parent.winfo_width() // 2
    cy = parent.winfo_rooty() + parent.winfo_height() // 2
    monitor = win32api.MonitorFromPoint((cx, cy), 2)
    left, top, right, bottom = win32api.GetMonitorInfo(monitor)['Work']
    if screen_center:
        cx, cy = (left+right)//2, (top+bottom)//2
    width, height = min(width, right-left), min(height, bottom-top)
    x = max(left, min(cx-width//2, right-width))
    y = max(top, min(cy-height//2, bottom-height))
    popup.geometry(f'{width}x{height}{x:+d}{y:+d}')
    return x, y, width, height
