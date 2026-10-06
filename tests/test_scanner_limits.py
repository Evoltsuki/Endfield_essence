import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
from core.scanner import AutoScanner


class ScannerLimitsTests(unittest.TestCase):
    def run_scan(self, limit, incomplete=False, skip=False):
        env = dict(hwnd=1, res_w=100, res_h=100, abs_x=0, abs_y=0, ui_scale=1)
        layout = dict(env=env, roi=(0, 0, 30, 30), roi_row1=(0, 0, 100, 20),
                      roi_final=(0, 0, 100, 100), inventory_tab_roi=(0, 0, 1, 1),
                      inventory_count_roi=(0, 0, 1, 1), lock_btn=(90, 10), discard_btn=(80, 10),
                      swipe_start=(10, 40), swipe_dist_first=10, swipe_dist_next=10)
        controller = Mock()
        controller.get_scaled_layout.return_value = layout
        controller.get_window_env.return_value = env
        controller.capture_window_bg.return_value = np.full((100, 100, 3), 255, np.uint8)
        controller.wait_target_selected.return_value = controller.capture_window_bg.return_value
        controller.last_selection_wait = dict(elapsed_ms=30, frames=2, reason='target_selected')
        analyzer = Mock()
        analyzer.is_on_essence_page.return_value = True
        analyzer.get_inventory_count.return_value = 100
        analyzer.find_essences_with_mask.return_value = [[i*10, 0, i*10+9, 9] for i in range(9)]
        analyzer.is_gold.return_value = True
        analyzer.is_thumb_marked.return_value = False
        analyzer.is_already_locked_bg.return_value = True
        analyzer.is_already_discarded_bg.return_value = False
        analyzer.recognize_and_parse.return_value = ('力量1 攻击1 夜幕3', ['力量', '攻击', '夜幕'], [1, 1, 3])
        analyzer.last_ocr_issue = '漏读' if incomplete else ''
        analyzer.check_all_attributes.return_value = (True, [('潜力', '5星')], 'potential')
        dm = SimpleNamespace(data={'skip_marked': skip, 'scan_mode': 'row'}, weapon_list=[])
        scanner = AutoScanner(dm, controller, analyzer, {}, max_items=limit)
        scanner.start()
        self.assertEqual(scanner.processed_items, limit)
        self.assertEqual(controller.click_at.call_count, limit)
        self.assertEqual(controller.swipe_up.call_count, (limit-1)//9)
        return analyzer

    def test_limits_include_row_boundary(self):
        for limit in (1, 9, 10, 18):
            with self.subTest(limit=limit):
                self.run_scan(limit)

    def test_incomplete_ocr_never_reaches_rules(self):
        analyzer = self.run_scan(10, incomplete=True)
        analyzer.check_all_attributes.assert_not_called()

    def test_detail_skip_still_counts_toward_limit(self):
        analyzer = self.run_scan(10, skip=True)
        analyzer.recognize_and_parse.assert_not_called()
