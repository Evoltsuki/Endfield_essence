import os
import threading
import queue
import time
import sys
import tkinter as tk
from PIL import Image, ImageTk
from pynput import keyboard
from core.scanner import AutoScanner
from core.update import UpdateWeapon
from gui.output import display_message
from utils.version import APP_TITLE


class MatrixAssistantApp:
    def __init__(self, root, dm, controller, analyzer, diagnostics=None):
        self.updateWeapon = None
        self.root = root
        self.dm = dm
        self.controller = controller
        self.analyzer = analyzer
        self.scanner = None
        self.diagnostics = diagnostics
        self.scan_end_status = "finished"
        self.reported_log_error = ""
        self.log_queue = queue.SimpleQueue()
        self.preparing = False
        self.cancel_prepare = False
        self.scan_started = None
        self.last_checked = 0
        self.last_elapsed = 0

        self.app_width = 580
        self.app_height = 740

        self.root.title(APP_TITLE)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.setup_ui()
        from tkinter import font as tkfont
        sample = "识别结果: 敏捷提升3 终结技充能效率提升6 迸发3"
        self.app_width = max(540, tkfont.Font(font=self.log_area.cget('font')).measure(sample) + 60)
        self.app_width = min(self.app_width, self.root.winfo_screenwidth()-40)
        self.restore_window_position()
        self.root.update_idletasks()
        self._geometry_save_timer = None
        self._last_window_geometry = None
        self.root.bind('<Configure>', self._queue_window_geometry, add='+')
        self.root.after(50, self._refresh_ui)

        self.kb = keyboard.Listener(on_press=self.on_press)
        self.kb.start()
        if self.diagnostics:
            self.gui_log(f"[日志] 自动保存到 {self.diagnostics.directory}", "blue")
        self.gui_log("打开游戏的基质背包，选择扫描方式后点击开始。", "gray")

    def restore_window_position(self):
        """恢复主窗口上一次记录的屏幕坐标"""
        self.root.update_idletasks()

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        default_x = (sw - self.app_width) // 2
        default_y = (sh - self.app_height) // 2

        pos_x = self.dm.data.get("window_x")
        pos_y = self.dm.data.get("window_y")

        if pos_x is None or pos_y is None:
            pos_x, pos_y = default_x, default_y
        else:
            if pos_x < 0 or pos_x > sw - 100:
                pos_x = default_x
            if pos_y < 0 or pos_y > sh - 100:
                pos_y = default_y

        width = max(240, self.dm.data.get('window_width', self.app_width))
        height = max(160, self.dm.data.get('window_height', self.app_height))
        self.root.geometry(f"{width}x{height}+{pos_x}+{pos_y}")

    def _queue_window_geometry(self, event):
        if event.widget is not self.root:
            return
        if self._geometry_save_timer:
            self.root.after_cancel(self._geometry_save_timer)
        self._geometry_save_timer = self.root.after(500, self._save_window_geometry)

    def _save_window_geometry(self):
        self._geometry_save_timer = None
        # 原生最小化和自绘最大化期间不覆盖普通窗口的坐标和尺寸。
        import win32gui
        if self.chrome.restore_geometry or (hasattr(self.chrome, 'hwnd') and win32gui.IsIconic(self.chrome.hwnd)):
            return
        geometry = (self.root.winfo_x(), self.root.winfo_y(), self.root.winfo_width(), self.root.winfo_height())
        if geometry[2] < 240 or geometry[3] < 160 or geometry == self._last_window_geometry:
            return
        self.dm.data.update(zip(('window_x', 'window_y', 'window_width', 'window_height'), geometry))
        self.dm.save_config()
        self._last_window_geometry = geometry

    def on_close(self):
        """处理窗口关闭事件并清理线程"""
        self.root.update_idletasks()
        if self._geometry_save_timer:
            self.root.after_cancel(self._geometry_save_timer)
        self._save_window_geometry()
        if self.scanner:
            self.scanner.stop()
        if self.diagnostics:
            elapsed = time.perf_counter()-self.scan_started if self.scan_started else None
            self.diagnostics.close(self.scanner.processed_items if self.scanner else None, elapsed)

        if self.kb:
            self.kb.stop()

        self.root.destroy()
        os._exit(0)

    def setup_ui(self):
        from gui.main_view import build_main_view
        build_main_view(self)

    def gui_log(self, m, tag="black"):
        """工作线程只入队，主线程批量渲染。"""
        if self.diagnostics:
            self.diagnostics.write(m, tag)
        visible = display_message(m, tag)
        if visible is not None:
            self.log_queue.put(visible)

    def _refresh_ui(self):
        if self.diagnostics and self.diagnostics.error != self.reported_log_error:
            self.reported_log_error = self.diagnostics.error
            if self.reported_log_error:
                self.log_queue.put((self.reported_log_error, "red"))
        follow = self.log_area.yview()[1] >= .99
        for _ in range(200):
            try:
                m, tag = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self._gui_log_safe(m, tag)
        lines = int(self.log_area.index("end-1c").split(".")[0])
        if lines > 2001:
            self.log_area.config(state="normal")
            self.log_area.delete("1.0", f"{lines - 2000}.0")
            self.log_area.config(state="disabled")
        if follow:
            self.log_area.see(tk.END)
        if self.scanner:
            self.last_checked = self.scanner.processed_items
            if self.scan_started:
                self.last_elapsed = time.perf_counter() - self.scan_started
        state = "正在准备" if self.preparing else ("扫描中" if self.scanner and self.scanner.running else
                ("已停止" if self.scan_end_status == "user_stopped" else "就绪"))
        self.status_var.set(f"{state} · {self.last_checked} 件\n{self.last_elapsed:.1f} 秒")
        self.root.after(50, self._refresh_ui)

    def _set_settings_enabled(self, enabled):
        for widget in self.settings_widgets:
            widget.config(state="normal" if enabled else "disabled")

    def stop_scan(self):
        if self.scan_end_status == "user_stopped" and (self.preparing or self.scanner):
            return
        if self.preparing or self.scanner:
            self.scan_end_status = "user_stopped"
            self.gui_log("[停止请求] 用户点击停止或按下B键", "blue")
        if self.preparing:
            self.cancel_prepare = True
            self.stop_btn.config(state="disabled")
            self.gui_log("[系统] 已取消启动，等待武器更新结束", "blue")
        if self.scanner:
            self.stop_btn.config(state="disabled", text="正在停止…")
            self.scanner.stop()

    def _gui_log_safe(self, m, tag):
        """解析日志内容，支持单行多色文本渲染"""
        self.log_area.config(state="normal")
        if isinstance(m, list):
            for text, color_tag in m:
                self.log_area.insert(tk.END, text, color_tag)
            self.log_area.insert(tk.END, "\n")
        else:
            self.log_area.insert(tk.END, str(m) + "\n", tag)
        self.log_area.config(state="disabled")

    def add_to_lock_list(self, data):
        """更新已锁定列表记录"""
        if self.diagnostics:
            self.diagnostics.record("locked", data)
        self.root.after(0, self._add_to_lock_list_safe, data)

    def add_scan_result(self, data):
        if self.diagnostics:
            self.diagnostics.record("ocr", dict(data, tokens=getattr(self.analyzer, "last_ocr_tokens", []),
                                               ocr_path=getattr(self.analyzer, "last_ocr_path", "unknown")))
        self.root.after(0, self._add_scan_result_safe, data)

    def _add_scan_result_safe(self, data):
        if data.get("issue"):
            self.review_count += 1
            self.review_var.set(f"需复核 {self.review_count} 件")
        # 只保留当前预览图片，历史表格保留文字，避免扫描整个背包时积累图像。
        frame = data.get("image")
        if frame is not None:
            preview = Image.fromarray(frame[:, :, ::-1])
            preview.thumbnail((330, 105), Image.Resampling.LANCZOS)
            self.current_preview = ImageTk.PhotoImage(preview)
            self.preview_label.config(image=self.current_preview, text="")

    def _add_to_lock_list_safe(self, data):
        self.locked_history.append(data)
        self.lock_count_var.set(f"{len(self.locked_history)} 件")
        self.lock_list_area.config(state="normal")

        def sort_key(item):
            weapons = item.get("weapons", [])
            max_star = 0
            primary_name = ""
            if weapons:
                primary_name = weapons[0][0]
                for _, w_star in weapons:
                    stars = [int(s) for s in w_star if s.isdigit()]
                    if stars:
                        max_star = max(max_star, stars[0])
            return (-max_star, primary_name)

        self.locked_history.sort(key=sort_key)
        index = next(i for i, item in enumerate(self.locked_history) if item is data)
        # 每件记录占一行，仅插入新增行，避免反复重绘全部历史。
        insert_at = f"{index + 1}.0"
        self.lock_list_area.mark_set("new_record", insert_at)
        self.lock_list_area.mark_gravity("new_record", tk.RIGHT)
        for item in (data,):
            matched_weapons = item.get("weapons", [])
            for w_idx, (w_name, w_star) in enumerate(matched_weapons):
                name_color = "red_text" if "6" in w_star else "gold_text"
                self.lock_list_area.insert("new_record", w_name, name_color)
                if w_idx < len(matched_weapons) - 1:
                    self.lock_list_area.insert("new_record", "|", "black_text")

            self.lock_list_area.insert("new_record", f" {item.get('display_str', '')} ", "green_text")
            self.lock_list_area.insert("new_record", f"坐标{item.get('row', '?')}-{item.get('col', '?')}\n", "black_text")
        self.lock_list_area.config(state="disabled")

    def on_scan_finish(self):
        """处理扫描结束后的 UI 恢复"""
        if self.diagnostics:
            self.diagnostics.finish_scan(self.scan_end_status, self.scanner.processed_items,
                                         round(time.perf_counter()-self.scan_started, 3))
        self.root.after(0, self._on_scan_finish_safe)

    def _on_scan_finish_safe(self):
        if self.diagnostics:
            self.diagnostics.finish_scan(self.scan_end_status)
        if self.scanner:
            self.last_checked = self.scanner.processed_items
            if self.scan_started:
                self.last_elapsed = time.perf_counter() - self.scan_started
        self.preparing = False
        self.stop_btn.config(state="disabled", text="停止 · B")
        self._set_settings_enabled(True)
        self.run_btn.config(state="normal", text="▶ 开始扫描")
        self.scanner = None

    def on_press(self, k):
        """监听快捷键事件"""
        if (getattr(k, 'char', '') or '').lower() == 'b':
            self.root.after(0, self.stop_scan)

    def save_ui_config(self):
        """保存用户界面勾选配置"""
        self.dm.data["skip_marked"] = self.skip_marked_var.get()
        self.dm.data["ignore_5star"] = self.ignore_5star_var.get()
        self.dm.data["debug_gold"] = self.debug_gold_var.get()
        self.dm.save_config()

    def start_thread(self):
        """初始化配置并拉起扫描执行线程"""
        if self.scanner or self.run_btn["state"] == "disabled":
            return
        self.run_btn.config(state="disabled", text="正在准备...")
        self.preparing = True
        self.cancel_prepare = False
        self.stop_btn.config(state="normal", text="取消准备 · B")
        self._set_settings_enabled(False)
        self.last_checked = 0
        self.last_elapsed = 0
        self.scan_started = None
        self.review_count = 0
        self.review_var.set("需复核 0 件")
        self.scan_end_status = "finished"
        self.save_ui_config()
        if self.diagnostics:
            keys = ("skip_marked", "ignore_5star", "debug_gold", "keep_potential", "enable_grad_limit",
                    "grad_keep_limit", "potential_rules", "scan_mode", "verify_detail_stability")
            config = {key: self.dm.data.get(key) for key in keys}
            config.update(preview=False, skip_marked=self.skip_marked_var.get(),
                          ignore_5star=self.ignore_5star_var.get(), debug_gold=self.debug_gold_var.get(),
                          ocr_mode=self.dm.data.get("ocr_mode", "auto"), scan_mode=self.dm.data.get("scan_mode", "page"))
            self.diagnostics.begin_scan(config)

        self.dm.corrections = self.dm.load_corrections()
        for area in (self.log_area, self.lock_list_area):
            area.config(state="normal")
            area.delete('1.0', tk.END)
            area.config(state="disabled")
        self.locked_history.clear()
        self.lock_count_var.set("0 件")
        self.current_preview = None
        self.preview_label.config(image="", text="当前词条预览 · 等待扫描")

        callbacks = {
            "log": self.gui_log,
            "lock": self.add_to_lock_list,
            "result": self.add_scan_result,
            "finish": self.on_scan_finish
        }
        self.updateWeapon = UpdateWeapon(self.dm, callbacks)

        def run_update_weapon_and_continue():
            try:
                self.updateWeapon.__run__()
            except Exception as exc:
                if self.diagnostics:
                    self.diagnostics.exception(*sys.exc_info())
                self.scan_end_status = "preparation_failed"
                self.gui_log(f"[错误] 武器数据更新失败: {exc}", "red")
                self.root.after(0, self._on_scan_finish_safe)
                return
            self.root.after(0, lambda: self.after_update_weapon(callbacks))

        threading.Thread(target=run_update_weapon_and_continue, daemon=True).start()

    def after_update_weapon(self,callbacks):
        if self.cancel_prepare:
            self._on_scan_finish_safe()
            return
        self.preparing = False
        if not self.controller.activate_game():
            self.scan_end_status = "activation_failed"
            self.gui_log(f"[激活诊断] {getattr(self.controller, 'activation_error', '')}", "red")
            self.gui_log("[系统] 无法自动激活游戏，请切回游戏后重试", "red")
            self._on_scan_finish_safe()
            return
        self.gui_log("[系统] 开始启动扫描，按 'B' 键停止", "blue")
        self.run_btn.config(state="disabled", text="正在扫描...")
        self.stop_btn.config(text="停止 · B")

        self.scanner = AutoScanner(self.dm, self.controller, self.analyzer, callbacks, preview=False)
        self.scan_started = time.perf_counter()
        threading.Thread(target=self.scanner.start, daemon=True).start()
