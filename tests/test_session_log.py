import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

from utils.session_log import SessionLog


class SessionLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.log = SessionLog(self.temp.name)
        self.addCleanup(self.log.close)

    def test_full_logs_are_flushed_and_separate_for_each_scan(self):
        self.log.begin_scan({"preview": True})
        self.log.write([("中文", "green"), ("多色日志", "blue")])
        for i in range(2100):
            self.log.write(f"entry-{i}")
        path = self.log.directory / "scan-001" / "scan.log"
        text = path.read_text(encoding="utf-8")
        self.assertIn("中文多色日志", text)
        self.assertIn("entry-0\n", text)
        self.assertIn("entry-2099", text)
        self.log.finish_scan("user_stopped", 91, 55.3)
        self.log.begin_scan({"preview": False})
        self.log.write("第二轮")
        self.log.finish_scan()
        first = json.loads((path.parent / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(first["checked_items"], 91)
        self.assertEqual(first["status"], "user_stopped")
        self.assertEqual(first["scan_seconds"], 55.3)
        self.assertNotIn("第二轮", path.read_text(encoding="utf-8"))

    def test_results_exclude_images_and_keep_review_and_traceback(self):
        self.log.begin_scan({})
        self.log.record("ocr", dict(row=1, issue="需复核", image=object()))
        try:
            raise ValueError("模拟异常")
        except ValueError:
            self.log.exception(*sys.exc_info())
        self.log.finish_scan()
        directory = self.log.directory / "scan-001"
        record = json.loads((directory / "results.jsonl").read_text(encoding="utf-8"))
        self.assertNotIn("image", record["data"])
        summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "ended_with_errors")
        self.assertEqual(summary["review_results"], 1)
        self.assertIn("ValueError: 模拟异常", summary["last_error"])

    def test_concurrent_writes_and_unique_directories(self):
        other = SessionLog(self.temp.name)
        self.addCleanup(other.close)
        self.assertNotEqual(self.log.directory, other.directory)
        self.log.begin_scan({})
        workers = [threading.Thread(target=lambda: [self.log.write("concurrent") for _ in range(50)]) for _ in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual((self.log.directory / "scan-001" / "scan.log").read_text(encoding="utf-8").count("concurrent"), 200)

    def test_write_error_is_visible_without_interrupting_scan(self):
        with patch.object(self.log, "stream", Mock(write=Mock(side_effect=OSError("disk full")))):
            self.log.write("test")
        self.assertIn("disk full", self.log.error)

    def test_close_finishes_pending_scan_and_is_idempotent(self):
        self.log.begin_scan({})
        self.log.close(4, 2.5)
        self.log.close()
        summary = json.loads((self.log.directory / "scan-001" / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "window_closed")
        self.assertEqual(summary["checked_items"], 4)

    def test_main_captures_tk_and_background_exceptions(self):
        import main
        root = Mock()
        def run_loop():
            root.report_callback_exception(ValueError, ValueError("tk callback failed"), None)
            threading.excepthook(SimpleNamespace(exc_type=RuntimeError,
                exc_value=RuntimeError("worker failed"), exc_traceback=None))
        root.mainloop.side_effect = run_loop
        with patch("main.run_as_admin", return_value=True), patch("main.SessionLog", return_value=self.log), \
             patch("main.tk.Tk", return_value=root), patch("main.messagebox.showerror"), \
             patch("utils.data_manager.DataManager"), patch("device.controller.DeviceController"), \
             patch("core.analyzer.VisionAnalyzer"), patch("gui.app.MatrixAssistantApp"):
            main.main()
        text = (self.log.directory / "app.log").read_text(encoding="utf-8")
        self.assertIn("tk callback failed", text)
        self.assertIn("worker failed", text)
