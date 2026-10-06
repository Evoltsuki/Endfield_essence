import cv2
import win32gui
import ctypes
import random
import time
import threading
import platform
from ctypes.wintypes import HWND, RECT, DWORD, POINT
from tkinter import messagebox

from utils.sys_helper import setup_dpi_awareness
setup_dpi_awareness()

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
        self.wgc_stop_event = threading.Event()
        self.wgc_frame_id = 0
        self.wgc_frame_time = 0.0

    def get_window_env(self):
        """获取目标游戏窗口句柄及坐标信息"""
        setup_dpi_awareness()
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
            "roi_final": (int(18*scale), int(72*scale), int(res_w-324*scale), int(res_h-150*scale)),
            "inventory_tab_roi": scale_rect(b["inventory_tab_roi"]),
            "inventory_count_roi": scale_rect(b["inventory_count_roi"])
        }

    def activate_game(self):
        """尝试前台激活游戏，并验证结果；失败时由界面提示手动切换。"""
        env = self.get_window_env()
        if env is None:
            return False
        if win32gui.GetForegroundWindow() == env["hwnd"]:
            return True
        self.activation_error = ""
        try:
            win32gui.SetForegroundWindow(env["hwnd"])
        except Exception as exc:
            self.activation_error = str(exc)
        if win32gui.GetForegroundWindow() == env["hwnd"]:
            return True
        # 临时连接当前与前台输入队列，结束后必定解除；不修改系统设置。
        user32 = ctypes.windll.user32
        current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        foreground = win32gui.GetForegroundWindow()
        foreground_thread = user32.GetWindowThreadProcessId(HWND(foreground), None)
        attached = False
        try:
            if foreground_thread and foreground_thread != current_thread:
                attached = bool(user32.AttachThreadInput(current_thread, foreground_thread, True))
            win32gui.BringWindowToTop(env["hwnd"])
            win32gui.SetForegroundWindow(env["hwnd"])
        except Exception as exc:
            self.activation_error = str(exc)
        finally:
            if attached:
                user32.AttachThreadInput(current_thread, foreground_thread, False)
        success = win32gui.GetForegroundWindow() == env["hwnd"]
        if not success:
            self.activation_error = f"{self.activation_error}; foreground={win32gui.GetForegroundWindow()}, target={env['hwnd']}"
        return success

    def _start_wgc_engine(self, title, stop_event, hide_border=True):
        """启动WGC引擎获取后台画面"""
        try:
            if hide_border:
                capture = WindowsCapture(window_name=title, cursor_capture=False, draw_border=False)
            else:
                capture = WindowsCapture(window_name=title, cursor_capture=False)

            @capture.event
            def on_frame_arrived(frame, capture_control):
                if stop_event.is_set():
                    capture_control.stop()
                    return
                with self.wgc_lock:
                    self.wgc_frame = frame.frame_buffer.copy()
                    self.wgc_frame_id += 1
                    self.wgc_frame_time = time.perf_counter()

            @capture.event
            def on_closed():
                if not stop_event.is_set():
                    self.wgc_error = "WGC 捕获异常关闭"

            capture.start()

        except Exception as e:
            error_msg = str(e)
            if "Toggling the capture border is not supported" in error_msg and hide_border:
                self._start_wgc_engine(title, stop_event, hide_border=False)
            else:
                self.wgc_error = f"引擎启动失败: {e}"

    def stop_capture(self):
        """通知 WGC 引擎安全停止，防止挂起主线程"""
        self.wgc_stop_event.set()

    def capture_window_bg(self, env, after_frame=None, with_metadata=False):
        """执行截图"""
        hwnd = env["hwnd"]
        res_w, res_h = env["res_w"], env["res_h"]

        #防止最小化时卡死
        if win32gui.IsIconic(hwnd):
            return None


        if not HAS_WGC:
            messagebox.showerror("依赖缺失", f"缺失 windows-capture 库。\n{WGC_IMPORT_ERROR}")
            return None

        try:
            title = win32gui.GetWindowText(hwnd)

            if self.wgc_title != title or self.wgc_stop_event.is_set():
                self.wgc_stop_event.set()
                if self.wgc_thread is not None and self.wgc_thread.is_alive():
                    self.wgc_thread.join(timeout=1.0)
                    if self.wgc_thread.is_alive():
                        return None
                self.wgc_thread = None
            # 标题变化或引擎未启动时重拉 WGC
            if self.wgc_title != title or self.wgc_thread is None or not self.wgc_thread.is_alive():
                self.wgc_title = title
                self.wgc_frame = None
                self.wgc_error = ""
                self.wgc_stop_event = threading.Event()
                self.wgc_thread = threading.Thread(target=self._start_wgc_engine, args=(title, self.wgc_stop_event), daemon=True)
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
                    # 回调只替换数组，不修改已发布的数组；持有引用即可。
                    frame = self.wgc_frame
                frame_id, frame_time = self.wgc_frame_id, self.wgc_frame_time

            if after_frame is not None and frame_id <= after_frame:
                return None

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

            result = cv2.cvtColor(client_frame, cv2.COLOR_BGRA2BGR)
            return (result, frame_id, frame_time) if with_metadata else result

        except Exception as e:
            messagebox.showerror("异常", f"捕获过程出错：\n{e}")
            return None

    def _same_window(self, env):
        current = self.get_window_env()
        return current is not None and all(current[k] == env[k] for k in
            ("hwnd", "res_w", "res_h", "abs_x", "abs_y"))

    def wait_target_selected(self, env, predicate, keep_running, timeout=2.0):
        """点击等待后，连续两张新帧必须在目标位置出现选中框。"""
        started = time.perf_counter()
        self.last_selection_wait = {"frames": 0, "reason": "target_timeout", "elapsed_ms": 0}
        with self.wgc_lock:
            last_id = self.wgc_frame_id
        hits = 0
        try:
            while time.perf_counter() - started < timeout:
                if not keep_running():
                    self.last_selection_wait["reason"] = "stopped"
                    return None
                if not self._same_window(env):
                    self.last_selection_wait["reason"] = "window_changed"
                    return None
                if win32gui.GetForegroundWindow() != env["hwnd"]:
                    self.last_selection_wait["reason"] = "foreground_lost"
                    return None
                sample = self.capture_window_bg(env, after_frame=last_id, with_metadata=True)
                if sample is not None:
                    image, frame_id, _ = sample
                    if frame_id > last_id:
                        last_id = frame_id
                        self.last_selection_wait["frames"] += 1
                        hits = hits + 1 if predicate(image) else 0
                        if hits >= 2:
                            self.last_selection_wait["reason"] = "target_selected"
                            return image
                time.sleep(.03)
            return None
        finally:
            self.last_selection_wait["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)

    def wait_detail_stable(self, env, roi, keep_running, timeout=2.0, stable_seconds=.10,
                           target_selected=None):
        """额外稳定校验，不能单凭稳定性缩短原点击等待。"""
        from core.frame_wait import StableRegion
        detector = StableRegion(stable_seconds=stable_seconds)
        started = time.perf_counter()
        self.last_wait = {"frames": 0, "reason": "timeout", "elapsed_ms": 0}
        with self.wgc_lock:
            last_id = self.wgc_frame_id
        x, y, w, h = roi
        try:
            while time.perf_counter() - started < timeout:
                if not keep_running():
                    self.last_wait["reason"] = "stopped"
                    return None
                if not self._same_window(env):
                    self.last_wait["reason"] = "window_changed"
                    return None
                if target_selected is not None and win32gui.GetForegroundWindow() != env["hwnd"]:
                    self.last_wait["reason"] = "foreground_lost"
                    return None
                sample = self.capture_window_bg(env, after_frame=last_id, with_metadata=True)
                if sample is not None:
                    image, last_id, timestamp = sample
                    self.last_wait["frames"] += 1
                    if target_selected is not None and not target_selected(image):
                        self.last_wait["reason"] = "target_lost"
                        return None
                    if detector.observe(last_id, timestamp, image[y:y+h, x:x+w]):
                        self.last_wait["reason"] = "stable"
                        return image
                time.sleep(.03)
            return None
        finally:
            self.last_wait["elapsed_ms"] = round((time.perf_counter()-started)*1000, 2)

    def wait_mark_state(self, env, predicate, keep_running, timeout=2.0):
        # 连续两张新帧确认，避免瞬时模板命中；不自动重试切换操作。
        with self.wgc_lock:
            last_id = self.wgc_frame_id
        deadline = time.perf_counter() + timeout
        hits = 0
        while keep_running() and time.perf_counter() < deadline:
            if not self._same_window(env):
                return False
            sample = self.capture_window_bg(env, after_frame=last_id, with_metadata=True)
            if sample is not None:
                image, last_id, _ = sample
                hits = hits + 1 if predicate(image) else 0
                if hits >= 2:
                    return True
            time.sleep(.03)
        return False

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
        if win32gui.GetForegroundWindow() != hwnd:
            raise RuntimeError("游戏失去前台焦点，停止输入")
        user32 = ctypes.windll.user32

        # 保存并记录物理鼠标位置
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        original_x, original_y = pt.x, pt.y

        # 引入轻微随机偏移，防止点到边缘死角
        offset_x = random.randint(-5, 5)
        offset_y = random.randint(-5, 5)
        target_x = x + offset_x
        target_y = y + offset_y

        client_x = target_x - env["abs_x"]
        client_y = target_y - env["abs_y"]
        lparam = self._make_lparam(client_x, client_y)

        self._send_activate_bg(hwnd)

        # 瞬移物理鼠标以应对游戏引擎的安全校验
        user32.SetCursorPos(int(target_x), int(target_y))
        time.sleep(0.02)  # 移过去后稍微停顿，让游戏引擎确认鼠标悬停

        user32.SendMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON, lparam)
        time.sleep(0.01)

        user32.SendMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)

        time.sleep(random.uniform(0.05, 0.08))

        user32.SendMessageW(hwnd, WM_LBUTTONUP, 0, lparam)

        time.sleep(0.05)

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
        if win32gui.GetForegroundWindow() != hwnd:
            raise RuntimeError("游戏失去前台焦点，停止输入")
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

    def swipe_page(self, env, plan, keep_running=lambda: True):
        """按实测行距拖动；终点停留抑制惯性，释放后另做稳定校验。"""
        if not self._same_window(env) or win32gui.GetForegroundWindow()!=env["hwnd"]:
            raise RuntimeError("翻页前窗口或前台变化")
        user32 = ctypes.windll.user32
        x, y = plan["x"], plan["y"]
        distance = plan["distance"]
        if not (0<=x<env["res_w"] and 0<=y<env["res_h"] and 0<=y-distance<env["res_h"]):
            raise ValueError("翻页坐标超出客户区")
        point = POINT()
        user32.GetCursorPos(ctypes.byref(point))
        hwnd = env["hwnd"]
        current_y = y
        pressed = False
        try:
            if not keep_running():
                return
            user32.SetCursorPos(int(x+env["abs_x"]), int(y+env["abs_y"]))
            time.sleep(.02)
            user32.SendMessageW(hwnd, WM_MOUSEMOVE, 0, self._make_lparam(x,y))
            user32.SendMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, self._make_lparam(x,y))
            pressed = True
            time.sleep(.05)
            for step in range(1,21):
                if not keep_running() or not self._same_window(env) or win32gui.GetForegroundWindow()!=hwnd:
                    raise RuntimeError("翻页中断，停止或窗口环境变化")
                current_y = y-distance*step/20
                user32.SetCursorPos(int(x+env["abs_x"]), int(current_y+env["abs_y"]))
                user32.SendMessageW(hwnd, WM_MOUSEMOVE, MK_LBUTTON, self._make_lparam(x,current_y))
                time.sleep(.02)
            # 与原滑动一样保留 700ms 按住等待，减少释放后的惯性。
            time.sleep(.7)
        finally:
            if pressed:
                user32.SendMessageW(hwnd, WM_LBUTTONUP, 0, self._make_lparam(x,current_y))
            user32.SetCursorPos(point.x,point.y)
        time.sleep(.15)

    def wait_grid_stable(self, env, roi, keep_running, timeout=4.0):
        return self.wait_detail_stable(env, roi, keep_running, timeout=timeout, stable_seconds=.30)
