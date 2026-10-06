"""Exercise the real Tk controls without game input or configuration writes."""
import tkinter as tk
import unittest
import tempfile
import json
from unittest.mock import Mock, patch

from gui.app import MatrixAssistantApp
from utils.session_log import SessionLog
from gui.windows import show_weapon_editor_popup
from gui.output import display_message
from gui.potential_editor import show_potential_editor


class GuiWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.dm = Mock(data={})
        self.controller = Mock()
        with patch("gui.app.keyboard.Listener"):
            self.app = MatrixAssistantApp(self.root, self.dm, self.controller, Mock())

    def tearDown(self):
        for timer in self.root.tk.call("after", "info"):
            self.root.after_cancel(timer)
        self.root.destroy()

    def test_cancel_preparation_never_activates_game(self):
        with patch("gui.app.threading.Thread"):
            self.app.start_thread()
        self.app.stop_scan()
        self.app.after_update_weapon({})
        self.controller.activate_game.assert_not_called()
        self.assertEqual(str(self.app.run_btn["state"]), "normal")
        self.assertFalse(self.app.preparing)

    def test_detailed_logs_saved_but_user_output_is_concise(self):
        with tempfile.TemporaryDirectory() as folder:
            log = SessionLog(folder)
            self.app.diagnostics = log
            try:
                log.begin_scan({})
                self.app.gui_log("[耗时] 1-1: OCR 123ms (regions)", "gray")
                self.app.gui_log("[翻页校验] 推进4行，匹配100%", "gray")
                self.app.gui_log("[测试] 诊断参数", "blue")
                self.app.gui_log("识别结果: 力量提升6 攻击提升6 夜幕3", "green")
                self.app.gui_log("[异常] 标记未确认\nTraceback (most recent call last):\n  internal.py:42", "red")
                self.app._refresh_ui()
                visible = self.app.log_area.get("1.0", "end")
                stored = (log.directory / "scan-001" / "scan.log").read_text(encoding="utf8")
                for detail in ("OCR 123ms", "[翻页校验]", "诊断参数", "internal.py:42"):
                    self.assertNotIn(detail, visible)
                    self.assertIn(detail, stored)
                self.assertIn("力量提升6", visible)
                self.assertIn("标记未确认", visible)
                self.assertEqual(str(self.app.log_area['state']), 'disabled')
                self.assertEqual(self.app.log_area.tag_cget('green', 'foreground'), '#2E7D32')
            finally:
                log.close()
                self.app.diagnostics = None

    def test_stop_request_is_not_repeated(self):
        self.app.scanner = Mock()
        self.app.stop_scan()
        self.app.stop_scan()
        self.app.scanner.stop.assert_called_once()
        self.assertEqual(str(self.app.stop_btn['state']), 'disabled')

    def test_compact_separator_and_small_borderless_window(self):
        self.assertEqual(display_message('---------- 检查: 1-6 ----------')[0], '--------------------1-6--------------------')
        self.root.geometry('340x360')
        self.root.deiconify()
        self.root.update()
        self.assertTrue(self.root.overrideredirect())
        self.assertFalse(hasattr(self.app, 'settings_visible'))
        self.assertFalse(hasattr(self.app, 'topmost_var'))
        self.assertEqual(self.root.place_slaves(), [])
        self.assertTrue(all(w.winfo_ismapped() for w in self.app.settings_widgets))
        self.assertTrue(self.app.run_btn.winfo_ismapped())
        self.assertTrue(self.app.stop_btn.winfo_ismapped())
        self.assertTrue(self.app.log_area.winfo_ismapped())
        self.assertTrue(self.app.lock_list_area.winfo_ismapped())
        self.assertEqual(self.app.log_area.cget('wrap'), 'word')

    def test_editor_deferred_and_new_rows_share_styles(self):
        self.dm.weapon_list = [{"武器": f"武器{i}", "星级": "6星"} for i in range(25)]
        editor = show_weapon_editor_popup(self.root, self.dm)
        self.root.after(100, self.root.quit)
        self.root.mainloop()
        def widgets(parent):
            for child in parent.winfo_children():
                yield child
                yield from widgets(child)
        buttons = [w for w in widgets(editor) if isinstance(w, tk.Button)]
        enabled = [w for w in buttons if w.cget('text') == '屏蔽']
        self.assertEqual(len(enabled), 25)
        self.assertEqual(len({w.cget('bg') for w in enabled}), 1)
        enabled[-1].invoke()
        self.assertEqual(enabled[-1].cget('text'), '取消屏蔽')
        self.assertNotEqual(enabled[-1].cget('bg'), enabled[0].cget('bg'))
        next(w for w in buttons if w.cget('text') == '+ 新增一行').invoke()
        enabled = [w for w in widgets(editor) if isinstance(w, tk.Button) and w.cget('text') == '屏蔽']
        self.assertEqual(len(enabled), 25)
        self.assertEqual(len({w.cget('bg') for w in enabled}), 1)
        self.assertFalse(any(isinstance(w, tk.Checkbutton) and '潜力' in w.cget('text') for w in widgets(editor)))
        editor.destroy()

    def test_title_buttons_equal_size_and_hover_feedback(self):
        self.root.deiconify()
        self.root.update()
        buttons = self.app.chrome.buttons
        self.assertEqual([(w.winfo_width(), w.winfo_height()) for w in buttons], [(42, 32)] * 3)
        for button in buttons:
            button.event_generate('<Enter>')
            self.root.update_idletasks()
            self.assertEqual(button.cget('bg'), '#BE3945' if button.symbol == '×' else '#41556E')
            button.event_generate('<Leave>')
            self.assertEqual(button.cget('bg'), '#29384A')

    def test_saved_rules_reach_scanner_and_settings_restore(self):
        self.dm.data.update(enable_grad_limit=True, keep_potential=False, grad_keep_limit=3)
        with patch("gui.app.threading.Thread"), patch("gui.app.AutoScanner") as scanner:
            self.app.start_thread()
            self.assertTrue(all(str(w["state"]) == "disabled" for w in self.app.settings_widgets))
            self.app.after_update_weapon({})
            self.assertFalse(scanner.call_args.kwargs["preview"])
            self.assertEqual(self.dm.data['grad_keep_limit'], 3)
            self.assertFalse(self.dm.data['keep_potential'])
            scanner.return_value.processed_items = 7
            self.app._on_scan_finish_safe()
        self.assertEqual(self.app.last_checked, 7)
        self.assertTrue(all(str(w["state"]) == "normal" for w in self.app.settings_widgets))

    def test_lock_rules_dialog_centers_and_saves_all_rules(self):
        self.root.geometry('620x700+200+100')
        self.root.deiconify()
        self.root.update()
        popup = show_potential_editor(self.root, self.dm)
        popup.update()
        self.assertEqual(popup.title(), '锁定基质规则')
        self.assertLess(abs(popup.winfo_x()+popup.winfo_width()/2 -
                            self.root.winfo_rootx()-self.root.winfo_width()/2), 12)
        general = next(w for w in popup.winfo_children() if isinstance(w, tk.LabelFrame))
        checks = [w for w in general.winfo_children() if isinstance(w, tk.Checkbutton)]
        checks[0].invoke()
        checks[1].invoke()
        count = next(w for w in general.winfo_children() if isinstance(w, tk.Spinbox))
        count.delete(0, 'end'); count.insert(0, '3')
        frame = next(w for w in popup.winfo_children() if type(w) is tk.Frame)
        next(w for w in frame.winfo_children() if isinstance(w, tk.Button) and w.cget('text') == '保存规则').invoke()
        self.assertFalse(self.dm.data['keep_potential'])
        self.assertTrue(self.dm.data['enable_grad_limit'])
        self.assertEqual(self.dm.data['grad_keep_limit'], 3)
        self.assertIn('potential_rules', self.dm.data)
        self.app.save_ui_config()
        self.assertEqual(self.dm.data['grad_keep_limit'], 3)

    def test_activation_failure_restores_controls(self):
        self.controller.activate_game.return_value = False
        with patch("gui.app.threading.Thread"), patch("gui.app.AutoScanner") as scanner:
            self.app.start_thread()
            self.app.after_update_weapon({})
            scanner.assert_not_called()
        self.assertEqual(str(self.app.stop_btn["state"]), "disabled")
        self.assertEqual(str(self.app.run_btn["state"]), "normal")

    def test_log_retention_and_permanent_output(self):
        self.app.gui_log("line\n" * 2300)
        self.app._refresh_ui()
        self.assertLessEqual(int(self.app.log_area.index("end-1c").split(".")[0]), 2001)
        self.assertFalse(hasattr(self.app, 'show_logs_var'))
        self.assertEqual(len(self.app.paned_window.panes()), 2)

    def test_geometry_saved_after_resize_and_restored_on_next_window(self):
        with tempfile.TemporaryDirectory() as folder:
            path = __import__('pathlib').Path(folder) / 'config.json'
            self.dm.save_config.side_effect = lambda: path.write_text(json.dumps(self.dm.data), encoding='utf8')
            self.root.deiconify()
            self.root.geometry('590x680+150+130')
            self.root.update()
            self.root.after(650, self.root.quit)
            self.root.mainloop()
            saved = json.loads(path.read_text(encoding='utf8'))
            self.assertEqual([saved[k] for k in ('window_x', 'window_y', 'window_width', 'window_height')],
                             [150, 130, 590, 680])
            second = tk.Toplevel(self.root)
            try:
                other = MatrixAssistantApp.__new__(MatrixAssistantApp)
                other.root = second
                other.dm = Mock(data=saved)
                other.app_width, other.app_height = 540, 740
                other.restore_window_position()
                second.update_idletasks()
                self.assertEqual((second.winfo_x(), second.winfo_y(), second.winfo_width(), second.winfo_height()),
                                 (150, 130, 590, 680))
            finally:
                second.destroy()
            self.app.chrome.restore_geometry = '590x680+150+130'
            self.root.geometry('800x900+0+0')
            self.root.update()
            self.app._save_window_geometry()
            self.assertEqual(json.loads(path.read_text(encoding='utf8')), saved)
            self.dm.save_config.side_effect = None

    def test_non_character_key_and_stop_button(self):
        self.app.on_press(Mock(char=None))
        self.app.scanner = Mock()
        self.app.stop_scan()
        self.app.scanner.stop.assert_called_once()

    def test_review_count_without_result_table(self):
        for category, issue in (("毕业", ""), ("需复核", "等级不完整")):
            self.app._add_scan_result_safe(dict(row=1, col=1, display_str="示例", category=category, issue=issue))
        self.assertFalse(hasattr(self.app, 'results_table'))
        self.assertFalse(hasattr(self.app, 'preview_var'))
        self.assertEqual(self.app.review_var.get(), "需复核 1 件")

    def test_output_and_locked_list_visible_in_narrow_window(self):
        self.root.geometry("620x700")
        self.root.deiconify()
        self.root.update()
        self.assertEqual(len(self.app.paned_window.panes()), 2)
        self.root.update_idletasks()
        self.assertGreater(self.app.log_area.winfo_height(), 70)
        self.assertGreater(self.app.lock_list_area.winfo_height(), 70)
        for widget in (self.app.run_btn, self.app.stop_btn, self.app.log_area, self.app.lock_list_area,
                       *self.app.settings_widgets):
            self.assertTrue(widget.winfo_ismapped(), str(widget))
            self.assertGreater(widget.winfo_width(), 40)
            self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                 self.root.winfo_rootx() + self.root.winfo_width())
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                 self.root.winfo_rooty() + self.root.winfo_height())
        self.app.details_var.set(True)
        self.app.toggle_details()
        self.root.update_idletasks()
        self.assertTrue(self.app.preview_label.winfo_ismapped())
        self.assertEqual(len(self.app.preview_label.master.winfo_children()), 1)
        self.assertTrue(self.app.lock_list_area.winfo_ismapped())

    def test_normal_gui_persists_logs_after_buffer_is_cleared(self):
        with tempfile.TemporaryDirectory() as folder:
            log = SessionLog(folder)
            self.app.diagnostics = log
            try:
                with patch("gui.app.threading.Thread"), patch("gui.app.AutoScanner") as scanner:
                    self.app.start_thread()
                    self.app.gui_log([("保留完整日志", "green")])
                    self.app.log_area.delete("1.0", "end")
                    self.app.after_update_weapon({})
                    scanner.return_value.processed_items = 5
                    self.app.stop_scan()
                    self.app.on_scan_finish()
                    self.root.update()
                directory = log.directory / "scan-001"
                self.assertIn("保留完整日志", (directory / "scan.log").read_text(encoding="utf-8"))
                summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
                self.assertEqual(summary["status"], "user_stopped")
                self.assertEqual(summary["checked_items"], 5)
                self.assertIsNotNone(summary["scan_seconds"])
            finally:
                log.close()
                self.app.diagnostics = None


if __name__ == "__main__":
    unittest.main()
