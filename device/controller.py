import cv2
import win32gui
import ctypes
import time
import threading
import platform
from ctypes.wintypes import HWND, RECT, DWORD, POINT
from tkinter import messagebox

"""强制获取当前系统的 DPI 配置"""
if platform.system() == "Windows":
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except Exception:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass

from core.layout import BASE_LAYOUT

try:
    from windows_capture import WindowsCapture

    HAS_WGC = True
    WGC_IMPORT_ERROR = ""
except ImportError as e:
    HAS_WGC = False
    WGC_IMPORT_ERROR = str(e)

# Windows API 消息常量
WM_ACTIVATE = 0x0006
WA_ACTIVE = 1
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001


class DeviceController:
    def __init__(self):
        self.wgc_frame = None
        self.wgc_lock = threading.Lock()
        self.wgc_title = ""
        self.wgc_thread = None
        self.wgc_error = ""
        self.wgc_should_stop = False

    def get_window_env(self):
        """获取目标游戏窗口句柄及坐标信息"""
        # 寻找游戏窗口
        hwnd = win32gui.FindWindow(None, 'Endfield') or win32gui.FindWindow(None, '终末地')
        if not hwnd:
            return None

        # 拦截最小化状态
        if win32gui.IsIconic(hwnd):
            return None

        # 获取窗口客户区大小
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        res_w, res_h = right - left, bottom - top
        if res_w == 0 or res_h == 0:
            return None

        # 获取窗口在屏幕中的绝对坐标
        pt = win32gui.ClientToScreen(hwnd, (0, 0))
        abs_x, abs_y = pt[0], pt[1]

        # 计算 UI 缩放比例
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
            "roi_final": scale_rect(b["roi_final"]),
            "inventory_tab_roi": scale_rect(b["inventory_tab_roi"]),
            "inventory_count_roi": scale_rect(b["inventory_count_roi"])
        }

    def _start_wgc_engine(self, title, hide_border=True):
        """启动WGC引擎获取后台画面"""
        try:
            if hide_border:
                capture = WindowsCapture(window_name=title, cursor_capture=False, draw_border=False)
            else:
                capture = WindowsCapture(window_name=title, cursor_capture=False)

            @capture.event
            def on_frame_arrived(frame, capture_control):
                if self.wgc_should_stop:
                    capture_control.stop()
                    return
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

    def stop_capture(self):
        """通知 WGC 引擎安全停止，防止挂起主线程"""
        self.wgc_should_stop = True

    def capture_window_bg(self, env):
        """执行截图"""
        hwnd = env["hwnd"]
        res_w, res_h = env["res_w"], env["res_h"]

        #防止最小化时卡死
        if win32gui.IsIconic(hwnd):
            return None

        self.wgc_should_stop = False

        if not HAS_WGC:
            messagebox.showerror("依赖缺失", f"缺失 windows-capture 库。\n{WGC_IMPORT_ERROR}")
            return None

        try:
            title = win32gui.GetWindowText(hwnd)

            # 标题变化或引擎未启动时重拉 WGC
            if self.wgc_title != title or self.wgc_thread is None or not self.wgc_thread.is_alive():
                self.wgc_title = title
                self.wgc_frame = None
                self.wgc_error = ""
                self.wgc_thread = threading.Thread(target=self._start_wgc_engine, args=(title,), daemon=True)
                self.wgc_thread.start()

            # 等待画面获取
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

            # DWM 计算游戏客户区大小并裁切边框
            rect = RECT()
            ctypes.windll.dwmapi.DwmGetWindowAttribute(HWND(hwnd), DWORD(9), ctypes.byref(rect), ctypes.sizeof(rect))

            # 计算 WGC物理画面 与 win32gui逻辑坐标 之间的误差比例
            logical_w = rect.right - rect.left
            logical_h = rect.bottom - rect.top
            h, w = frame.shape[:2]

            ratio_x = w / logical_w if logical_w > 0 else 1.0
            ratio_y = h / logical_h if logical_h > 0 else 1.0

            # 按比例映射真正的物理裁剪坐标
            crop_x = int((env["abs_x"] - rect.left) * ratio_x)
            crop_y = int((env["abs_y"] - rect.top) * ratio_y)
            physical_res_w = int(env["res_w"] * ratio_x)
            physical_res_h = int(env["res_h"] * ratio_y)

            y1, y2 = max(0, crop_y), min(h, crop_y + physical_res_h)
            x1, x2 = max(0, crop_x), min(w, crop_x + physical_res_w)

            client_frame = frame[y1:y2, x1:x2]
            if client_frame.size == 0:
                return None

            # 修正画面缩放
            if client_frame.shape[1] != env["res_w"] or client_frame.shape[0] != env["res_h"]:
                client_frame = cv2.resize(client_frame, (env["res_w"], env["res_h"]), interpolation=cv2.INTER_AREA)

            return cv2.cvtColor(client_frame, cv2.COLOR_BGRA2BGR)

        except Exception as e:
            messagebox.showerror("异常", f"捕获过程出错：\n{e}")
            return None

    def _send_activate_bg(self, hwnd):
        """发送激活消息，保持窗口接收输入状态"""
        if not hwnd:
            return
        ctypes.windll.user32.SendMessageW(hwnd, WM_ACTIVATE, WA_ACTIVE, 0)
        time.sleep(0.01)

    def _make_lparam(self, x, y):
        """打包相对坐标为 lParam 结构"""
        return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)

    def click_at(self, x, y, delay=0.0):
        """执行点击操作"""
        env = self.get_window_env()
        if not env:
            return

        hwnd = env["hwnd"]
        user32 = ctypes.windll.user32

        # 保存并记录物理鼠标位置
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        original_x, original_y = pt.x, pt.y

        client_x = x - env["abs_x"]
        client_y = y - env["abs_y"]
        lparam = self._make_lparam(client_x, client_y)

        self._send_activate_bg(hwnd)

        # 瞬移物理鼠标以应对游戏引擎的安全校验
        user32.SetCursorPos(int(x), int(y))
        time.sleep(0.01)

        user32.SendMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON, lparam)
        user32.SendMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
        time.sleep(0.03)
        user32.SendMessageW(hwnd, WM_LBUTTONUP, 0, lparam)

        # 点击结束恢复原位置
        user32.SetCursorPos(original_x, original_y)

        if delay > 0:
            time.sleep(delay)

    def move_rel(self, x_offset, y_offset):
        pass

    def swipe_up(self, start_x, start_y, distance):
        """执行滑动操作"""
        env = self.get_window_env()
        if not env:
            return

        hwnd = env["hwnd"]
        user32 = ctypes.windll.user32

        # 保存并记录物理鼠标位置
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        original_x, original_y = pt.x, pt.y

        client_x = start_x - env["abs_x"]
        client_y = start_y - env["abs_y"]

        self._send_activate_bg(hwnd)

        user32.SetCursorPos(int(start_x), int(start_y))
        time.sleep(0.01)

        lparam_start = self._make_lparam(client_x, client_y)
        user32.SendMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam_start)
        time.sleep(0.05)

        steps = 10
        for s in range(1, steps + 1):
            current_y_client = client_y - (distance * (s / steps))
            current_y_screen = start_y - (distance * (s / steps))

            lparam_move = self._make_lparam(client_x, current_y_client)

            user32.SetCursorPos(int(start_x), int(current_y_screen))
            user32.SendMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON, lparam_move)
            time.sleep(0.02)

        time.sleep(0.7)

        lparam_end = self._make_lparam(client_x, client_y - distance)
        user32.SendMessageW(hwnd, WM_LBUTTONUP, 0, lparam_end)
        time.sleep(0.05)

        # 恢复原位置
        user32.SetCursorPos(original_x, original_y)
        time.sleep(0.1)