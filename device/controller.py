import cv2
import win32gui
import win32con
import ctypes
import time
import threading
from ctypes.wintypes import HWND, RECT, DWORD
from tkinter import messagebox
import pydirectinput

# 取消 pydirectinput 默认延迟和安全控制
pydirectinput.PAUSE = 0.01
pydirectinput.FAILSAFE = False

from core.layout import BASE_LAYOUT

try:
    from windows_capture import WindowsCapture

    HAS_WGC = True
    WGC_IMPORT_ERROR = ""
except ImportError as e:
    HAS_WGC = False
    WGC_IMPORT_ERROR = str(e)


class DeviceController:
    def __init__(self):
        self.wgc_frame = None
        self.wgc_lock = threading.Lock()
        self.wgc_title = ""
        self.wgc_thread = None
        self.wgc_error = ""

    def get_window_env(self):
        """获取目标游戏窗口句柄及坐标信息"""
        hwnd = win32gui.FindWindow(None, 'Endfield') or win32gui.FindWindow(None, '终末地')
        if not hwnd:
            return None

        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        res_w, res_h = right - left, bottom - top
        if res_w == 0 or res_h == 0:
            return None

        pt = win32gui.ClientToScreen(hwnd, (0, 0))
        abs_x, abs_y = pt[0], pt[1]

        base_w, base_h = 1280.0, 720.0
        ui_scale = min(res_w / base_w, res_h / base_h)

        offset_x = (res_w - base_w * ui_scale) / 2.0
        offset_y = (res_h - base_h * ui_scale) / 2.0

        return {
            "hwnd": hwnd,
            "res_w": res_w,
            "res_h": res_h,
            "abs_x": abs_x,
            "abs_y": abs_y,
            "ui_scale": ui_scale,
            "offset_x": offset_x,
            "offset_y": offset_y
        }

    def get_scaled_layout(self):
        """根据当前分辨率计算 UI 缩放后的组件坐标"""
        env = self.get_window_env()
        if not env:
            return None

        res_w, res_h = env["res_w"], env["res_h"]
        scale = env["ui_scale"]
        abs_x, abs_y = env["abs_x"], env["abs_y"]
        base_w, base_h = 1280.0, 720.0

        def scale_pt(pt):
            x, y = pt
            new_x = x * scale if x < base_w / 2.0 else res_w - (base_w - x) * scale
            new_y = y * scale if y < base_h / 2.0 else res_h - (base_h - y) * scale
            return (int(abs_x + new_x), int(abs_y + new_y))

        def scale_rect(rect):
            rx, ry, rw, rh = rect
            cx, cy = rx + rw / 2.0, ry + rh / 2.0
            new_x = rx * scale if cx < base_w / 2.0 else res_w - (base_w - rx) * scale
            new_y = ry * scale if cy < base_h / 2.0 else res_h - (base_h - ry) * scale
            return (int(new_x), int(new_y), int(rw * scale), int(rh * scale))

        b = BASE_LAYOUT
        return {
            "env": env,
            "grid_p11": scale_pt(b["grid_p11"]),
            "grid_dx": int(b["grid_delta"][0] * scale),
            "grid_dy": int(b["grid_delta"][1] * scale),
            "matrix_size": (int(b["matrix_size"][0] * scale), int(b["matrix_size"][1] * scale)),
            "roi": scale_rect(b["roi"]),
            "lock_btn": scale_pt(b["lock_btn"]),
            "discard_btn": scale_pt(b["discard_btn"]),
            "swipe_start": scale_pt(b["swipe_start"]),
            "swipe_dist_first": int(b["swipe_dist_first"] * scale),
            "swipe_dist_next": int(b["swipe_dist_next"] * scale),
            "roi_row1": scale_rect(b["roi_row1"]),
            "roi_final": scale_rect(b["roi_final"])
        }

    def _start_wgc_engine(self, title, hide_border=True):
        """启动 Windows Graphics Capture 引擎以获取后台画面"""
        try:
            if hide_border:
                capture = WindowsCapture(window_name=title, cursor_capture=False, draw_border=False)
            else:
                capture = WindowsCapture(window_name=title, cursor_capture=False)

            @capture.event
            def on_frame_arrived(frame, capture_control):
                with self.wgc_lock:
                    self.wgc_frame = frame.frame_buffer.copy()

            @capture.event
            def on_closed():
                self.wgc_error = "WGC 捕获异常关闭"

            capture.start()

        except Exception as e:
            error_msg = str(e)
            if "Toggling the capture border is not supported" in error_msg and hide_border:
                self._start_wgc_engine(title, hide_border=False)
            else:
                self.wgc_error = f"引擎启动失败: {e}"

    def capture_window_bg(self, env):
        """执行后台截图"""
        hwnd = env["hwnd"]
        res_w, res_h = env["res_w"], env["res_h"]

        if not HAS_WGC:
            messagebox.showerror("依赖缺失", f"缺失 windows-capture 库。\n{WGC_IMPORT_ERROR}")
            return None

        try:
            title = win32gui.GetWindowText(hwnd)

            if self.wgc_title != title or self.wgc_thread is None or not self.wgc_thread.is_alive():
                self.wgc_title = title
                self.wgc_frame = None
                self.wgc_error = ""
                self.wgc_thread = threading.Thread(target=self._start_wgc_engine, args=(title,), daemon=True)
                self.wgc_thread.start()

            timeout = 2.5
            start_t = time.time()
            while self.wgc_frame is None and time.time() - start_t < timeout:
                if self.wgc_error:
                    break
                time.sleep(0.05)

            if self.wgc_error:
                messagebox.showerror("捕获错误", f"截图引擎报错：\n{self.wgc_error}")
                return None

            frame = None
            with self.wgc_lock:
                if self.wgc_frame is not None:
                    frame = self.wgc_frame.copy()

            if frame is None:
                messagebox.showerror("超时", "画面获取超时，请检查游戏窗口状态。")
                return None

            rect = RECT()
            ctypes.windll.dwmapi.DwmGetWindowAttribute(HWND(hwnd), DWORD(9), ctypes.byref(rect), ctypes.sizeof(rect))

            crop_x = env["abs_x"] - rect.left
            crop_y = env["abs_y"] - rect.top

            h, w = frame.shape[:2]
            y1, y2 = max(0, crop_y), min(h, crop_y + res_h)
            x1, x2 = max(0, crop_x), min(w, crop_x + res_w)

            client_frame = frame[y1:y2, x1:x2]
            if client_frame.size == 0:
                return None

            return cv2.cvtColor(client_frame, cv2.COLOR_BGRA2BGR)

        except Exception as e:
            messagebox.showerror("异常", f"捕获过程出错：\n{e}")
            return None

    def _ensure_foreground(self, hwnd):
        """确保游戏窗口置顶以接收鼠标事件"""
        if win32gui.GetForegroundWindow() != hwnd:
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass

    def click_at(self, x, y, delay=0.0):
        """执行鼠标点击操作"""
        env = self.get_window_env()
        if not env:
            return

        self._ensure_foreground(env["hwnd"])
        pydirectinput.click(int(x), int(y))

        if delay > 0:
            time.sleep(delay)

    def move_rel(self, x_offset, y_offset):
        """执行鼠标相对移动操作"""
        pydirectinput.moveRel(int(x_offset), int(y_offset))

    def swipe_up(self, start_x, start_y, distance):
        """执行平滑的向上滑动操作"""
        env = self.get_window_env()
        if not env:
            return

        self._ensure_foreground(env["hwnd"])

        pydirectinput.moveTo(int(start_x), int(start_y))
        pydirectinput.mouseDown()

        steps = 10
        for s in range(1, steps + 1):
            pydirectinput.moveTo(int(start_x), int(start_y - (distance * (s / steps))))
            time.sleep(0.01)

        time.sleep(0.7)
        pydirectinput.mouseUp()
        time.sleep(0.1)