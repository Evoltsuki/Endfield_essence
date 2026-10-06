import unittest
from unittest.mock import patch
import numpy as np
from core.frame_wait import StableRegion
from core.analyzer import VisionAnalyzer


class FrameWaitTests(unittest.TestCase):
    def test_duplicate_frames_never_complete(self):
        wait = StableRegion()
        image = np.zeros((260, 520, 3), np.uint8)
        self.assertFalse(wait.observe(1, 0, image))
        self.assertFalse(wait.observe(1, 5, image))

    def test_new_frames_need_minimum_duration(self):
        wait = StableRegion()
        image = np.zeros((130, 260, 3), np.uint8)
        self.assertFalse(wait.observe(1, 0, image))
        self.assertFalse(wait.observe(2, .03, image))
        self.assertFalse(wait.observe(3, .06, image))
        self.assertTrue(wait.observe(4, .11, image))

    def test_animation_resets_stability_window(self):
        wait = StableRegion()
        image = np.zeros((130, 260, 3), np.uint8)
        changed = image.copy()
        changed[30:50, 30:50] = 255
        self.assertFalse(wait.observe(1, 0, image))
        self.assertFalse(wait.observe(2, .05, changed))
        self.assertFalse(wait.observe(3, .11, changed))
        self.assertTrue(wait.observe(4, .16, changed))

    def test_template_cache_separates_scales(self):
        analyzer = VisionAnalyzer.__new__(VisionAnalyzer)
        with patch('core.analyzer.cv_imread', return_value=np.zeros((10, 10), np.uint8)) as read:
            a = analyzer._template('test.png', scale=1.0)
            self.assertIs(a, analyzer._template('test.png', scale=1.0))
            self.assertEqual(analyzer._template('test.png', scale=2.0).shape, (20, 20))
            self.assertEqual(read.call_count, 2)


if __name__ == '__main__':
    unittest.main()
