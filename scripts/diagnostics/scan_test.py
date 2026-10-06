"""使用现有界面及扫描逻辑进行最多 10 个基质的实机测试。"""
import json
import sys
import cv2
import threading
import time
from datetime import datetime
from pathlib import Path
import os
import tkinter as tk

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.sys_helper import setup_dpi_awareness, run_as_admin
from utils.data_manager import DataManager
from device.controller import DeviceController
from core.analyzer import VisionAnalyzer
from core.scanner import AutoScanner
from gui.app import MatrixAssistantApp


class ScanTestApp(MatrixAssistantApp):
    def __init__(self, *args):
        super().__init__(*args)
        self.preview_var.set("--preview" in sys.argv)
        self.root.title("基质实机测试 - 最多10个")
        self.root.attributes("-topmost", True)
        self.output = Path("Output") / ("scan-test-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        self.output.mkdir(parents=True, exist_ok=True)
        self.timings = {}
        self.waits = []
        self.selection_waits = []
        self.samples = []
        self.selection_failures = {}
        self.artifacts = []
        self.last_frame = None
        self.log_file = self.output / "scan.log"
        self.pending = False
        self.done = False
        self.started = None
        self.original_scan_mode = self.dm.data.get("scan_mode")
        self.original_ocr_mode = self.dm.data.get("ocr_mode")
        if "--legacy-ocr" in sys.argv:
            self.dm.data["ocr_mode"] = "legacy"
        if "--row-mode" in sys.argv:
            self.dm.data["scan_mode"] = "row"
        self.original_stability = self.dm.data.get("verify_detail_stability")
        self.stability_var = tk.BooleanVar(value=True)
        tk.Checkbutton(self.root, text="实验：保留原等待，并检查详情新帧稳定性",
                       variable=self.stability_var).pack(fill="x")
        for obj, names in (
            (self.controller, ("click_at", "swipe_up", "swipe_page", "capture_window_bg", "wait_target_selected", "wait_detail_stable", "wait_mark_state")),
            (self.analyzer, ("recognize_and_parse", "find_essences_with_mask", "is_thumb_marked",
                             "is_already_locked_bg", "is_already_discarded_bg", "check_all_attributes",
                             "is_target_selected")),
        ):
            for name in names:
                self.instrument(obj, name)
        self.gui_log("[测试] 最多点击检查10个基质；可勾选只读预览，未勾选时沿用标记规则。")
        self.gui_log("[测试] 点击开始后自动激活游戏并扫描；B可停止。使用本地武器库。")

    def instrument(self, obj, name):
        original = getattr(obj, name)
        def measured(*args, **kwargs):
            start = time.perf_counter()
            result = None
            try:
                result = original(*args, **kwargs)
                if name == "capture_window_bg" and result is not None:
                    self.last_frame = result[0] if isinstance(result, tuple) else result
                if name == "is_target_selected" and not result:
                    box = tuple(int(v) for v in args[1])
                    if box not in self.selection_failures and len(self.selection_failures) < 10:
                        self.selection_failures[box] = (args[0], float(args[2]))
                if name == "recognize_and_parse":
                    index = len(self.samples) + 1
                    self.artifacts.append((f"item-{index:02d}.png", args[0].copy()))
                    self.samples.append({"display": result[0], "skills": result[1], "levels": result[2],
                                         "ocr_path": self.analyzer.last_ocr_path,
                                         "tokens": self.analyzer.last_ocr_tokens,
                                         "issue": self.analyzer.last_ocr_issue})
                return result
            finally:
                if name == "wait_detail_stable":
                    self.waits.append(dict(self.controller.last_wait))
                if name == "wait_target_selected":
                    self.selection_waits.append(dict(self.controller.last_selection_wait))
                    index = len(self.selection_waits)
                    if result is not None:
                        self.artifacts.append((f"selection-{index:02d}.png", result))
                self.timings.setdefault(name, []).append(time.perf_counter() - start)
        setattr(obj, name, measured)

    def on_close(self):
        # 实验选项不写回普通入口的配置。
        if self.original_ocr_mode is None:
            self.dm.data.pop("ocr_mode", None)
        else:
            self.dm.data["ocr_mode"] = self.original_ocr_mode
        if self.original_scan_mode is None:
            self.dm.data.pop("scan_mode", None)
        else:
            self.dm.data["scan_mode"] = self.original_scan_mode
        if self.original_stability is None:
            self.dm.data.pop("verify_detail_stability", None)
        else:
            self.dm.data["verify_detail_stability"] = self.original_stability
        super().on_close()

    def gui_log(self, message, tag="black"):
        if hasattr(self, "log_file"):
            plain = "".join(str(part[0]) for part in message) if isinstance(message, list) else str(message)
            with self.log_file.open("a", encoding="utf-8") as stream:
                stream.write(plain + "\n")
        super().gui_log(message, tag)

    def start_thread(self):
        if self.pending or self.done or self.scanner:
            return
        self.pending = True
        self._set_settings_enabled(False)
        self.run_btn.config(state="disabled", text="正在启动")
        self.gui_log("[测试] 正在激活游戏；扫描期间独占鼠标。", "blue")
        self.begin_test()

    def begin_test(self):
        if not self.pending:
            return
        self.pending = False
        if not self.controller.activate_game():
            self.gui_log("[测试] 无法自动激活游戏，请将游戏切到前台后重新开始。", "red")
            self.gui_log(f"[激活诊断] {getattr(self.controller, 'activation_error', '窗口不可用')}", "red")
            self.run_btn.config(state="normal", text="重新开始测试")
            self._set_settings_enabled(True)
            if "--auto-close" in sys.argv:
                self.root.after(500, self.on_close)
            return
        self.dm.data.update(skip_marked=self.skip_marked_var.get(),
                            verify_detail_stability=self.stability_var.get(),
                            ignore_5star=self.ignore_5star_var.get(),
                            debug_gold=self.debug_gold_var.get())
        self.scanner = AutoScanner(self.dm, self.controller, self.analyzer,
                                   {"log": self.gui_log, "lock": self.add_to_lock_list,
                                    "result": self.add_scan_result,
                                    "finish": self.on_scan_finish}, max_items=10,
                                   sample_pattern="cross" if "--cross-sample" in sys.argv else None,
                                   preview=self.preview_var.get())
        self.run_btn.config(text="测试运行中")
        self.stop_btn.config(state="normal")
        self.started = time.perf_counter()
        self.scan_started = self.started
        threading.Thread(target=self.scanner.start, daemon=True).start()

    def on_press(self, key):
        if getattr(key, "char", None) == "b" and self.pending:
            self.pending = False
            self.root.after(0, lambda: self.run_btn.config(state="normal", text="开始测试"))
        super().on_press(key)

    def on_scan_finish(self):
        self.done = True
        elapsed = time.perf_counter() - self.started
        artifact_started = time.perf_counter()
        if self.last_frame is not None:
            self.artifacts.append(("last-frame.png", self.last_frame))
            self.last_frame = None
        for filename, frame in self.artifacts:
            cv2.imencode(".png", frame)[1].tofile(str(self.output / filename))
        self.artifacts.clear()
        failure_records = []
        for index, (box, (frame, scale)) in enumerate(self.selection_failures.items(), 1):
            filename = f"selection-failed-{index:02d}.png"
            cv2.imencode(".png", frame)[1].tofile(str(self.output / filename))
            failure_records.append({"image": filename, "box": box, "scale": scale})
        report = {"elapsed_seconds": elapsed, "checked_items": self.scanner.processed_items,
                  "artifact_write_ms": round((time.perf_counter() - artifact_started) * 1000, 2),
                  "timing_note": "PNG encoding and writes occur after elapsed_seconds; function timings may be nested.",
                  "ocr_mode": self.dm.data.get("ocr_mode", "auto"),
                  "selection_failures": failure_records,
                  "verify_detail_stability": self.dm.data.get("verify_detail_stability", False),
                  "preview": self.scanner.preview, "selection_waits": self.selection_waits,
                  "sample_pattern": self.scanner.sample_pattern, "scan_mode": self.dm.data.get("scan_mode", "page"), "max_items": 10, "samples": self.samples, "waits": self.waits, "timings": {
                      name: {"calls": len(values), "total_ms": sum(values) * 1000,
                             "mean_ms": sum(values) * 1000 / len(values),
                             "max_ms": max(values) * 1000}
                      for name, values in self.timings.items()}}
        (self.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        self.gui_log(f"[测试] 自动结束，检查 {self.scanner.processed_items} 个，用时 {elapsed:.2f} 秒", "blue")
        self.root.after(0, lambda: self.run_btn.config(state="disabled", text="测试已结束"))
        self.root.after(0, lambda: self.stop_btn.config(state="disabled"))
        self.scan_started = None
        self.last_elapsed = elapsed
        self.selection_failures.clear()
        if "--auto-close" in sys.argv:
            self.root.after(500, self.on_close)


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    setup_dpi_awareness()
    if run_as_admin():
        root = tk.Tk()
        dm = DataManager()
        app = ScanTestApp(root, dm, DeviceController(), VisionAnalyzer(dm))
        if "--no-stability" in sys.argv:
            app.stability_var.set(False)
        if "--auto-start" in sys.argv:
            root.withdraw()
            root.after_idle(app.start_thread)
        root.mainloop()
