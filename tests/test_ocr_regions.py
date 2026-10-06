import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from core.analyzer import VisionAnalyzer, cv_imread
from core.ocr_regions import text_regions


class RegionOCRTests(unittest.TestCase):
    def setUp(self):
        self.image = cv_imread(str(Path(__file__).parent / "fixtures" / "ocr-detail.png"))
        self.v = VisionAnalyzer.__new__(VisionAnalyzer)
        self.v.dm = SimpleNamespace(data={}, corrections={})
        self.v.cc = SimpleNamespace(convert=lambda s: s)
        self.v.ocr = Mock()
        self.values = [("智识提升", .99), ("+6", .99), ("攻击提升", .99), ("+6", .99), ("夜幕", .99), ("+3", .99)]
        self.v.ocr.text_rec.return_value = (self.values, .1)
        crops, boxes = text_regions(self.image)
        self.tokens = [[box, value[0], value[1]] for box, value in zip(boxes, self.values)]
        self.v.ocr.return_value = (self.tokens, [])

    def test_batch_path_skips_detector_and_preserves_pairing(self):
        _, names, levels = self.v.recognize_and_parse(self.image)
        self.assertEqual(names, ["智识提升", "攻击提升", "夜幕"])
        self.assertEqual(levels, [6,6,3])
        self.assertEqual(self.v.last_ocr_path, "regions")
        self.v.ocr.assert_not_called()

    def test_low_confidence_or_malformed_grade_falls_back(self):
        for bad in (("+6", .7), ("1 +6", .99), ("+16", .99)):
            with self.subTest(bad=bad):
                values = list(self.values)
                values[1] = bad
                self.v.ocr.text_rec.return_value = (values, .1)
                self.v.recognize_and_parse(self.image)
                self.assertEqual(self.v.last_ocr_path, "detector")
                self.assertFalse(self.v.last_ocr_issue)

    def test_legacy_mode_does_not_use_regions(self):
        self.v.dm.data["ocr_mode"] = "legacy"
        self.v.recognize_and_parse(self.image)
        self.v.ocr.text_rec.assert_not_called()

    def test_region_geometry_rejects_empty_shifted_and_wrong_aspect(self):
        self.assertIsNone(text_regions(np.zeros_like(self.image)))
        self.assertIsNone(text_regions(self.image[:, :200]))
        shifted = np.roll(self.image, -10, axis=0)
        self.assertIsNone(text_regions(shifted))

    def test_regions_scale_with_roi(self):
        for ratio in (.5, .75, 1):
            resized = cv2.resize(self.image, None, fx=ratio, fy=ratio, interpolation=cv2.INTER_AREA)
            regions = text_regions(resized)
            self.assertIsNotNone(regions)
            self.assertEqual(len(regions[0]), 6)
