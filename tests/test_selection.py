import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from core.analyzer import VisionAnalyzer, cv_imread
from core.scanner import AutoScanner, ScanCancelled
from device.controller import DeviceController


class SelectionImageTests(unittest.TestCase):
    def test_row_neighbor_highlight_matches_at_multiple_scales(self):
        image = cv_imread(str(Path(__file__).parent / 'fixtures' / 'selected-row-neighbor.png'))
        analyzer = VisionAnalyzer.__new__(VisionAnalyzer)
        for scale in (1, 1.5, 2):
            frame = cv2.resize(image, None, fx=scale/2, fy=scale/2, interpolation=cv2.INTER_AREA)
            box = tuple(round(v*scale/2) for v in (47,44,239,236))
            with self.subTest(scale=scale):
                self.assertTrue(analyzer.is_target_selected(frame, box, scale))

    def test_adjacent_card_highlight_does_not_hide_selected_corner(self):
        image = cv_imread(str(Path(__file__).parent / 'fixtures' / 'selected-neighbor-highlight.png'))
        analyzer = VisionAnalyzer.__new__(VisionAnalyzer)
        for scale in (1, 1.5, 2):
            frame = cv2.resize(image, None, fx=scale/2, fy=scale/2, interpolation=cv2.INTER_AREA)
            box = tuple(round(v*scale/2) for v in (49,59,241,251))
            self.assertTrue(analyzer.is_target_selected(frame, box, scale))

    def test_dim_phase_of_selection_animation_still_matches(self):
        image = cv_imread(str(Path(__file__).parent / 'fixtures' / 'selected-pulse-dim.png'))
        analyzer = VisionAnalyzer.__new__(VisionAnalyzer)
        self.assertTrue(analyzer.is_target_selected(image, (40, 40, 232, 232), 2))

    def test_only_selected_cell_matches_at_multiple_scales(self):
        image = cv_imread(str(Path(__file__).parent / 'fixtures' / 'selected-grid.png'))
        analyzer = VisionAnalyzer.__new__(VisionAnalyzer)
        boxes = [(18, 8, 114, 104), (122, 8, 218, 104),
                 (18, 112, 114, 208), (122, 112, 218, 208)]
        for scale in (1, 1.5, 2):
            with self.subTest(scale=scale):
                frame = cv2.resize(image, None, fx=scale / 2, fy=scale / 2,
                                   interpolation=cv2.INTER_AREA)
                hits = [analyzer.is_target_selected(frame, tuple(round(v * scale) for v in b), scale)
                        for b in boxes]
                self.assertEqual(hits, [True, False, False, False])

    def test_missing_template_and_clipped_corner_are_rejected(self):
        image = cv_imread(str(Path(__file__).parent / 'fixtures' / 'selected-grid.png'))
        analyzer = VisionAnalyzer.__new__(VisionAnalyzer)
        with patch.object(analyzer, '_template', return_value=None):
            self.assertFalse(analyzer.is_target_selected(image, (18, 8, 114, 104), 1))
        image = cv2.resize(image, None, fx=.5, fy=.5, interpolation=cv2.INTER_AREA)
        image[:25, :30] = 0
        self.assertFalse(analyzer.is_target_selected(image, (18, 8, 114, 104), 1))


class SelectionWaitTests(unittest.TestCase):
    def setUp(self):
        self.controller = DeviceController()
        self.env = {'hwnd': 200}
        self.image = np.zeros((30, 30, 3), np.uint8)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(self.controller, '_same_window', return_value=True))
        self.stack.enter_context(patch('device.controller.win32gui.GetForegroundWindow', return_value=200))
        self.stack.enter_context(patch('device.controller.time.sleep'))

    def test_duplicate_frames_and_transient_selection_do_not_confirm(self):
        samples = [(self.image, i, i) for i in (1, 1, 2, 3, 4)]
        predicate = Mock(side_effect=[True, False, True, True])
        with patch.object(self.controller, 'capture_window_bg', side_effect=samples) as capture:
            result = self.controller.wait_target_selected(self.env, predicate, lambda: True)
        self.assertIs(result, self.image)
        self.assertEqual(capture.call_count, 5)
        self.assertEqual(predicate.call_count, 4)
        self.assertEqual(self.controller.last_selection_wait['frames'], 4)

    def test_stable_wrong_target_times_out(self):
        with patch.object(self.controller, 'capture_window_bg', return_value=(self.image, 1, 1)), \
                patch('device.controller.time.perf_counter', side_effect=[0, .1, .2, 3, 3]):
            result = self.controller.wait_target_selected(self.env, lambda _: False, lambda: True)
        self.assertIsNone(result)
        self.assertEqual(self.controller.last_selection_wait['reason'], 'target_timeout')

    def test_stop_and_foreground_loss_prevent_capture(self):
        with patch.object(self.controller, 'capture_window_bg') as capture:
            self.assertIsNone(self.controller.wait_target_selected(self.env, lambda _: True, lambda: False))
            self.assertEqual(self.controller.last_selection_wait['reason'], 'stopped')
            with patch('device.controller.win32gui.GetForegroundWindow', return_value=201):
                self.assertIsNone(self.controller.wait_target_selected(self.env, lambda _: True, lambda: True))
                self.assertEqual(self.controller.last_selection_wait['reason'], 'foreground_lost')
            capture.assert_not_called()

    def test_losing_selection_during_detail_wait_stops(self):
        with patch.object(self.controller, 'capture_window_bg', return_value=(self.image, 1, 1)):
            result = self.controller.wait_detail_stable(
                self.env, (0, 0, 30, 30), lambda: True, target_selected=lambda _: False)
        self.assertIsNone(result)
        self.assertEqual(self.controller.last_wait['reason'], 'target_lost')


class SelectionScannerTests(unittest.TestCase):
    def test_stop_during_mark_is_cancellation_without_retry_or_success(self):
        scanner, layout = self.make_scanner()
        def cancel(*args):
            scanner.running = False
            return False
        scanner.controller.wait_mark_state.side_effect = cancel
        scanner.log_cb = Mock()
        scanner._run_loop = lambda: scanner._mark_verified(layout, 'discard')
        scanner.start()
        self.assertEqual(scanner.controller.click_at.call_count, 1)
        messages = [call.args[0] for call in scanner.log_cb.call_args_list]
        self.assertTrue(any('最终状态未确认' in message for message in messages))
        self.assertFalse(any('[异常]' in message or '[校验]' in message for message in messages))

    def test_mark_timeout_remains_error_when_not_cancelled(self):
        scanner, layout = self.make_scanner()
        scanner.controller.wait_mark_state.return_value = False
        with self.assertRaisesRegex(RuntimeError, '标记结果未确认'):
            scanner._mark_verified(layout, 'discard')
        self.assertEqual(scanner.controller.click_at.call_count, 1)

    def test_cancelled_before_mark_does_not_click(self):
        scanner, layout = self.make_scanner()
        scanner.running = False
        with self.assertRaises(ScanCancelled):
            scanner._mark_verified(layout, 'discard')
        scanner.controller.click_at.assert_not_called()

    def make_scanner(self, preview=False):
        controller, analyzer = Mock(), Mock()
        env = dict(hwnd=1, res_w=100, res_h=100, abs_x=0, abs_y=0, ui_scale=1)
        layout = dict(env=env, roi=(0, 0, 30, 30), lock_btn=(90, 10), discard_btn=(80, 10))
        controller.get_window_env.return_value = env
        controller.wait_target_selected.return_value = np.zeros((100, 100, 3), np.uint8)
        controller.last_selection_wait = dict(elapsed_ms=30, frames=2, reason='target_selected')
        analyzer.recognize_and_parse.return_value = ('力量6 攻击6 夜幕3', ['力量', '攻击', '夜幕'], [6, 6, 3])
        analyzer.last_ocr_issue = ''
        analyzer.check_all_attributes.return_value = (True, [('测试武器', '6星')], 'graduation')
        dm = SimpleNamespace(data={}, weapon_list=[], best_records={}, save_records=Mock())
        scanner = AutoScanner(dm, controller, analyzer, {}, preview=preview)
        scanner.running = True
        return scanner, layout

    def test_failed_selection_never_reads_ocr_or_marks(self):
        scanner, layout = self.make_scanner()
        scanner.controller.wait_target_selected.return_value = None
        self.assertFalse(scanner._scan_one(layout, (0, 0, 10, 10), True, 1, 1))
        scanner.analyzer.recognize_and_parse.assert_not_called()
        self.assertEqual(scanner.controller.click_at.call_count, 1)
        self.assertEqual(scanner.processed_items, 1)

    def test_preview_does_not_mark_or_update_graduation_records(self):
        for keep, kind in ((True, 'graduation'), (True, 'potential'), (False, '')):
            with self.subTest(kind=kind):
                scanner, layout = self.make_scanner(preview=True)
                scanner.analyzer.check_all_attributes.return_value = (keep, [('测试武器', '6星')], kind)
                scanner.result_cb = Mock()
                self.assertTrue(scanner._scan_one(layout, (0, 0, 10, 10), True, 1, 1))
                self.assertEqual(scanner.result_cb.call_count, 1)
                self.assertEqual(scanner.result_cb.call_args.args[0]['category'],
                                 {'graduation': '毕业', 'potential': '潜力', '': '未匹配'}[kind])
                self.assertEqual(scanner.controller.click_at.call_count, 1)
                self.assertEqual(scanner.dm.best_records, {})
                scanner.dm.save_records.assert_not_called()
