import unittest
from unittest.mock import Mock, patch
from gui.dialogs import center_dialog


class DialogPositionTests(unittest.TestCase):
    def test_screen_center_uses_parents_monitor_work_area(self):
        parent, popup = Mock(), Mock()
        parent.winfo_rootx.return_value = 2200
        parent.winfo_rooty.return_value = 300
        parent.winfo_width.return_value = 540
        parent.winfo_height.return_value = 700
        with patch('gui.dialogs.win32api.MonitorFromPoint', return_value=2) as monitor, \
                patch('gui.dialogs.win32api.GetMonitorInfo', return_value={'Work': (1920, 0, 3840, 1040)}):
            self.assertEqual(center_dialog(popup, parent, 1180, 700, screen_center=True), (2290, 170, 1180, 700))
            monitor.assert_called_once_with((2470, 650), 2)
            popup.geometry.assert_called_once_with('1180x700+2290+170')
