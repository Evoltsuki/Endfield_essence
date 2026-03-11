import cv2
import numpy as np
import pygetwindow as gw
import win32gui
import win32ui
import ctypes
import pydirectinput
import pyautogui
import time

from core.layout import BASE_LAYOUT

pydirectinput.PAUSE = 0.01
pyautogui.FAILSAFE = False


class DeviceController:
    def get_window_env(self):
        hwnd = win32gui.FindWindow(None, 'Endfield') or win32gui.FindWindow(None, '终末地')
        if not hwnd: return None

        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        res_w, res_h = right - left, bottom - top
        if res_w == 0 or res_h == 0: return None

        pt = win32gui.ClientToScreen(hwnd, (0, 0))
        abs_x, abs_y = pt[0], pt[1]

        return {
            "hwnd": hwnd,
            "res_w": res_w,
            "res_h": res_h,
            "abs_x": abs_x,
            "abs_y": abs_y,
            "scale_x": res_w / 1280.0,
            "scale_y": res_h / 720.0
        }

    def get_scaled_layout(self):
        env = self.get_window_env()
        if not env: return None

        sx, sy = env["scale_x"], env["scale_y"]
        abs_x, abs_y = env["abs_x"], env["abs_y"]

        def scale_pt(pt):
            return (int(abs_x + pt[0] * sx), int(abs_y + pt[1] * sy))

        def scale_size(size):
            return (int(size[0] * sx), int(size[1] * sy))

        b = BASE_LAYOUT
        return {
            "env": env,
            "grid_p11": scale_pt(b["grid_p11"]),
            "grid_dx": int(b["grid_delta"][0] * sx),
            "grid_dy": int(b["grid_delta"][1] * sy),
            "matrix_size": scale_size(b["matrix_size"]),
            "roi": (int(b["roi"][0] * sx), int(b["roi"][1] * sy), int(b["roi"][2] * sx), int(b["roi"][3] * sy)),
            "lock_btn": scale_pt(b["lock_btn"]),
            "discard_btn": scale_pt(b["discard_btn"]),
            "swipe_start": scale_pt(b["swipe_start"]),
            "swipe_dist": int(b["swipe_dist"] * sy)
        }

    def capture_window_bg(self, hwnd, res_w, res_h):
        try:
            hDC = win32gui.GetWindowDC(hwnd)
            mDC = win32ui.CreateDCFromHandle(hDC)
            sDC = mDC.CreateCompatibleDC()
            sBM = win32ui.CreateBitmap()
            sBM.CreateCompatibleBitmap(mDC, res_w, res_h)
            sDC.SelectObject(sBM)
            ctypes.windll.user32.PrintWindow(hwnd, sDC.GetSafeHdc(), 3)
            bits = sBM.GetBitmapBits(True)
            img = np.frombuffer(bits, dtype='uint8')
            img.shape = (res_h, res_w, 4)
            win32gui.DeleteObject(sBM.GetHandle())
            sDC.DeleteDC()
            mDC.DeleteDC()
            win32gui.ReleaseDC(hwnd, hDC)
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        except:
            return None

    def click_at(self, x, y, delay=0.0):
        pydirectinput.click(int(x), int(y))
        if delay > 0: time.sleep(delay)

    def move_rel(self, x_offset, y_offset):
        pydirectinput.moveRel(x_offset, y_offset)

    def swipe_up(self, start_x, start_y, distance):
        """带有 MAA 级别防惯性刹车机制的拖拽算法"""
        pydirectinput.moveTo(start_x, start_y)
        pydirectinput.mouseDown()
        time.sleep(0.05)

        # 增加插值步数，让滑动更平滑
        steps = 20
        for s in range(steps):
            pydirectinput.moveTo(start_x, int(start_y - (distance * (s / steps))))
            time.sleep(0.01)

        # 【核心修正】：模拟 MAA 的 "end_hold: 1500" 来杀死游戏引擎的滑动惯性！
        time.sleep(1.5)

        pydirectinput.mouseUp()
        time.sleep(0.5)