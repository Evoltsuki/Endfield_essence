import unittest
from types import SimpleNamespace
from core.analyzer import VisionAnalyzer


def token(text, x, y, confidence=.99):
    return [[[x, y], [x+45, y], [x+45, y+15], [x, y+15]], text, confidence]


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.v = VisionAnalyzer.__new__(VisionAnalyzer)
        self.v.cc = SimpleNamespace(convert=lambda text: text)
        self.v.dm = SimpleNamespace(corrections={})
        self.names = [token('智识提升', 0, 0), token('攻击提升', 0, 40), token('夜幕', 0, 80)]

    def test_shuffled_separate_levels(self):
        _, skills, levels = self.v.parse_ocr_lines([
            token('+3', 180, 95), self.names[1], token('+6', 180, 15),
            self.names[0], token('+2', 180, 55), self.names[2]])
        self.assertEqual(levels, [6, 2, 3])
        self.assertEqual(skills, ['智识提升', '攻击提升', '夜幕'])
        self.assertFalse(self.v.last_ocr_issue)

    def test_missing_middle_level_does_not_shift(self):
        _, _, levels = self.v.parse_ocr_lines(self.names + [token('+6', 180, 15), token('+3', 180, 95)])
        self.assertEqual(levels, [6, 0, 3])
        self.assertTrue(self.v.last_ocr_issue)

    def test_low_confidence_rejected(self):
        self.v.parse_ocr_lines([token('智识提升+6', 0, 0), token('攻击提升+6', 0, 40), token('夜幕+3', 0, 80, .6)])
        self.assertTrue(self.v.last_ocr_issue)

    def test_duplicate_number_is_ambiguous(self):
        self.v.parse_ocr_lines(self.names + [token('+6', 180, 15), token('+2', 230, 15), token('+6', 180, 55), token('+3', 180, 95)])
        self.assertTrue(self.v.last_ocr_issue)

    def test_two_digit_level_not_truncated(self):
        _, _, levels = self.v.parse_ocr_lines([token('智识提升+16', 0, 0), token('攻击提升+6', 0, 40), token('夜幕+3', 0, 80)])
        self.assertEqual(levels[0], 0)
        self.assertTrue(self.v.last_ocr_issue)

    def test_progress_bar_digit_is_not_an_extra_level(self):
        _, _, levels = self.v.parse_ocr_lines(self.names + [
            token('"1!!', 0, 15, .62), token('+6', 180, 15),
            token('+6', 180, 55), token('+3', 180, 95)])
        self.assertEqual(levels, [6, 6, 3])
        self.assertFalse(self.v.last_ocr_issue)

    def test_progress_bar_cannot_replace_missing_grade(self):
        _, _, levels = self.v.parse_ocr_lines(self.names + [
            token('1', 0, 55), token('+6', 180, 15), token('+3', 180, 95)])
        self.assertEqual(levels, [6, 0, 3])
        self.assertTrue(self.v.last_ocr_issue)

    def test_low_confidence_right_grade_still_rejected(self):
        self.v.parse_ocr_lines(self.names + [
            token('+6', 180, 15, .62), token('+6', 180, 55), token('+3', 180, 95)])
        self.assertTrue(self.v.last_ocr_issue)
