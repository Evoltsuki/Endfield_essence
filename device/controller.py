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
pydirectinput.FAILSAFE = False


class DeviceController:
    def get_window_env(self):
        hwnd = win32gui.FindWindow(None, 'Endfield') or win32gui.FindWindow(None, '终末地')
        if not hwnd: return None

        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        res_w, res_h = right - left, bottom - top
        if res_w == 0 or res_h == 0: return None

        pt = win32gui.ClientToScreen(hwnd, (0, 0))
        abs_x, abs_y = pt[0], pt[1]

        # 【核心优化】：带鱼屏与异形屏自适应比例计算
        base_w, base_h = 1280.0, 720.0
        # 获取最小缩放比，保证 UI 等比缩放
        ui_scale = min(res_w / base_w, res_h / base_h)

        # 计算为了保持 16:9 居中，X轴或Y轴产生的黑边/FOV偏移量
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
        env = self.get_window_env()
        if not env: return None

        scale = env["ui_scale"]
        ox, oy = env["offset_x"], env["offset_y"]
        abs_x, abs_y = env["abs_x"], env["abs_y"]

        def scale_pt(pt):
            # 转换为屏幕绝对坐标：基础偏移 + 居中偏移 + 缩放后的UI坐标
            return (int(abs_x + ox + pt[0] * scale), int(abs_y + oy + pt[1] * scale))

        def scale_size(size):
            return (int(size[0] * scale), int(size[1] * scale))

        def scale_rect(rect):
            # 转换为截图内部的相对坐标：居中偏移 + 缩放后的UI坐标
            return (int(ox + rect[0] * scale), int(oy + rect[1] * scale),
                    int(rect[2] * scale), int(rect[3] * scale))

        b = BASE_LAYOUT
        return {
            "env": env,
            "grid_p11": scale_pt(b["grid_p11"]),
            "grid_dx": int(b["grid_delta"][0] * scale),
            "grid_dy": int(b["grid_delta"][1] * scale),
            "matrix_size": scale_size(b["matrix_size"]),
            "roi": scale_rect(b["roi"]),
            "lock_btn": scale_pt(b["lock_btn"]),
            "discard_btn": scale_pt(b["discard_btn"]),
            "swipe_start": scale_pt(b["swipe_start"]),
            "swipe_dist_first": int(b["swipe_dist_first"] * scale),
            "swipe_dist_next": int(b["swipe_dist_next"] * scale),
            "roi_row1": scale_rect(b["roi_row1"]),
            "roi_final": scale_rect(b["roi_final"])
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
        pydirectinput.moveTo(start_x, start_y)
        pydirectinput.mouseDown()
        time.sleep(0.05)
        steps = 30
        for s in range(steps):
            pydirectinput.moveTo(start_x, int(start_y - (distance * (s / steps))))
            time.sleep(0.01)
        time.sleep(0.5)
        pydirectinput.mouseUp()
        time.sleep(0.1)