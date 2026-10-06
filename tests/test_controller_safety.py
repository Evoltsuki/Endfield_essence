import unittest
from unittest.mock import patch
import numpy as np
from device.controller import DeviceController


class ControllerSafetyTests(unittest.TestCase):
    def test_activation_denied_returns_false(self):
        c = DeviceController()
        with patch.object(c, 'get_window_env', return_value={'hwnd': 200}), patch('device.controller.win32gui.GetForegroundWindow', return_value=100), patch('device.controller.win32gui.SetForegroundWindow', side_effect=RuntimeError('denied')), patch('device.controller.win32gui.BringWindowToTop'), patch('device.controller.ctypes.windll.user32'):
            self.assertFalse(c.activate_game())
            self.assertIn('target=200', c.activation_error)

    def test_mark_needs_two_consecutive_new_matches(self):
        c = DeviceController()
        image = np.zeros((2, 2, 3), np.uint8)
        with patch.object(c, '_same_window', return_value=True), patch.object(c, 'capture_window_bg', side_effect=[(image, i, i) for i in range(1, 5)]) as capture, patch('device.controller.time.sleep'):
            matches = iter([True, False, True, True])
            self.assertTrue(c.wait_mark_state({}, lambda _: next(matches), lambda: True))
            self.assertEqual(capture.call_count, 4)

    def test_stop_prevents_mark_wait_capture(self):
        c = DeviceController()
        with patch.object(c, 'capture_window_bg') as capture:
            self.assertFalse(c.wait_mark_state({}, lambda _: True, lambda: False))
            capture.assert_not_called()

    def test_input_refuses_other_foreground(self):
        c = DeviceController()
        with patch.object(c, 'get_window_env', return_value={'hwnd': 200}), patch('device.controller.win32gui.GetForegroundWindow', return_value=100):
            with self.assertRaisesRegex(RuntimeError, '前台'):
                c.click_at(1, 1)
            with self.assertRaisesRegex(RuntimeError, '前台'):
                c.swipe_up(1, 1, 10)
