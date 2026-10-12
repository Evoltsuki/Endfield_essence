import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np
import cv2
from core.analyzer import VisionAnalyzer, cv_imread
from core.page_grid import GridPage, PageTracker, PageScrollFeedback, align_pages, page_swipe_plan
from core.scanner import AutoScanner


def page(start=0, cols=9, scale=1, y=20, rows=5, identical=False):
    boxes, features = [], []
    for row in range(rows):
        boxes.append([(int(c*60*scale), int((y+row*60)*scale), int((c*60+50)*scale), int((y+row*60+50)*scale)) for c in range(cols)])
        features.append([(np.full((24,24,3),100,np.float32) if identical else np.random.default_rng((start+row)*100+c).integers(0,255,(24,24,3)).astype(np.float32)) for c in range(cols)])
    return GridPage(boxes, features, cols, 60*scale)


class PageGridTests(unittest.TestCase):
    def test_dynamic_columns_and_global_coordinates(self):
        for cols in (7,9,11,13):
            with self.subTest(cols=cols):
                tracker = PageTracker()
                first, _, _ = tracker.observe(page(cols=cols))
                second, alignment, _ = tracker.observe(page(3, cols=cols))
                self.assertEqual(len(first), 5*cols)
                self.assertEqual(len(second), 3*cols)
                self.assertEqual(alignment['offset'], 3)
                self.assertEqual(second[0][1:], (6,1))

    def test_repeated_identical_art_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '唯一'):
            align_pages(page(identical=True),page(identical=True))

    def test_requires_two_repeated_swipes_to_finish(self):
        tracker = PageTracker()
        self.assertFalse(tracker.observe(page())[2])
        self.assertFalse(tracker.observe(page())[2])
        self.assertTrue(tracker.observe(page())[2])

    def test_inertia_pixel_shift_not_end(self):
        tracker = PageTracker()
        tracker.observe(page())
        tracker.observe(page(y=12))
        self.assertEqual(tracker.repeats,0)

    def test_changed_column_count_rejected(self):
        with self.assertRaisesRegex(ValueError, '列数'):
            align_pages(page(),page(cols=11))

    def test_disjoint_page_rejected(self):
        with self.assertRaises(ValueError):
            align_pages(page(),page(20))

    def test_plan_scales_with_measured_pitch(self):
        for scale in (1,1.5,2):
            plan = page_swipe_plan(page(scale=scale), (0,0,800*scale,400*scale), scale)
            self.assertEqual(plan['distance'], 256*scale)

    def test_one_row_overlap_advances_four_without_duplicate_cells(self):
        tracker = PageTracker(minimum_rows=1)
        tracker.observe(page())
        fresh, alignment, _ = tracker.observe(page(4))
        self.assertEqual(alignment['offset'], 4)
        self.assertEqual(alignment['overlap_rows'], 1)
        self.assertEqual(len(fresh), 36)
        self.assertEqual(fresh[0][1:], (6, 1))

    def test_ambiguous_or_narrow_last_row_keeps_two_rows(self):
        for p in (page(identical=True), page(cols=5)):
            self.assertEqual(page_swipe_plan(p, (0,0,800,400), 1)['overlap_rows'], 2)
        repeated = page()
        repeated.features[-1] = repeated.features[0]
        self.assertEqual(page_swipe_plan(repeated, (0,0,800,400), 1)['overlap_rows'], 2)

    def test_one_row_rejects_one_mismatched_column(self):
        before, after = page(), page(4)
        after.features[0][3] = page(20).features[0][3]
        with self.assertRaises(ValueError):
            align_pages(before, after, minimum_rows=1)

    def test_build_detects_eleven_columns(self):
        p = page(cols=11)
        image = np.full((400,700,3),128,np.uint8)
        built = GridPage.build(image,[box for row in p.rows for box in row])
        self.assertEqual(built.columns,11)
        self.assertEqual(len(built.rows),5)

    def test_trailing_empty_slots_are_not_compressed(self):
        p = page(cols=9)
        boxes = [box for row in p.rows[:-1] for box in row] + p.rows[-1][:3]
        image = np.zeros((400,700,3),np.uint8)
        built = GridPage.build(image,boxes)
        self.assertEqual(len(built.rows[-1]),9)
        image[260:310,180:230]=255
        with self.assertRaisesRegex(ValueError, '非空'):
            GridPage.build(image,boxes)

    def test_real_bottom_background_does_not_add_columns(self):
        image = cv_imread(str(Path(__file__).parent / 'fixtures' / 'grid-bottom.png'))
        analyzer = VisionAnalyzer.__new__(VisionAnalyzer)
        for scale in (1, 1.5, 2):
            with self.subTest(scale=scale):
                frame = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
                boxes = analyzer.find_essences_with_mask(frame, (0,0,frame.shape[1],frame.shape[0]), scale)
                built = GridPage.build(frame, boxes)
                self.assertEqual(len(boxes), 39)
                self.assertEqual(built.columns, 9)
                self.assertEqual(built.row_counts, [9,9,9,9,3])
                self.assertTrue(built.has_empty_tail)
                fresh, _, _ = PageTracker().observe(built)
                self.assertEqual(len(fresh), 39)

    def test_missing_middle_cell_still_rejected(self):
        p = page()
        boxes = [box for r, row in enumerate(p.rows) for c, box in enumerate(row) if (r,c)!=(2,4)]
        with self.assertRaisesRegex(ValueError, '中间缺格'):
            GridPage.build(np.zeros((400,700,3),np.uint8), boxes)

    def test_clipped_bottom_is_deferred_until_overlap_is_visible(self):
        tracker = PageTracker(minimum_rows=1)
        first, _, _ = tracker.observe(page(y=66), visible_bottom=360, selection_margin=12)
        self.assertEqual(len(first), 36)
        self.assertEqual(tracker.deferred, 9)
        self.assertNotIn((4,0), tracker.seen)
        second, alignment, _ = tracker.observe(page(4), visible_bottom=360, selection_margin=12)
        self.assertEqual(alignment['offset'], 4)
        self.assertEqual(len(second), 45)
        coordinates = [item[1:] for item in first+second]
        self.assertEqual(len(set(coordinates)), 81)
        self.assertIn((5,1), coordinates)

    def test_scanner_sweeps_short_bottom_once_without_clicking_empty_slots(self):
        controller, analyzer = Mock(), Mock()
        controller.get_scaled_layout.return_value = {
            'env': {'res_w':1000,'res_h':800,'ui_scale':1},
            'roi_final': (0,0,900,400), 'inventory_tab_roi':(0,0,1,1)}
        controller.wait_grid_stable.return_value = np.full((800,1000,3),255,np.uint8)
        analyzer.is_on_essence_page.return_value = True
        analyzer.is_gold.return_value = True
        tail = page(3, y=42)
        tail.row_counts = [9,9,9,9,3]
        scanner = AutoScanner(SimpleNamespace(data={}),controller,analyzer,{})
        visited = []
        scanner._scan_one = lambda layout, box, gold, row, col: visited.append((row,col)) or True
        with patch('core.scanner.GridPage.build', side_effect=[page(),tail]):
            scanner.start()
        self.assertEqual(len(visited), 66)
        self.assertEqual(len(set(visited)), 66)
        self.assertEqual(visited[-3:], [(8,1),(8,2),(8,3)])
        controller.swipe_page.assert_called_once()
        visited.clear()
        controller.reset_mock()
        scanner = AutoScanner(SimpleNamespace(data={}),controller,analyzer,{},
                              preview=True, sample_pattern='first_column')
        scanner._scan_one = lambda layout, box, gold, row, col: visited.append((row,col)) or True
        with patch('core.scanner.GridPage.build', side_effect=[page(),tail]):
            scanner.start()
        self.assertEqual(visited, [(row,1) for row in range(1,9)])
        controller.swipe_page.assert_called_once()

    def test_cross_sample_order_and_no_swipe(self):
        controller, analyzer = Mock(), Mock()
        controller.get_scaled_layout.return_value = {
            'env': {'res_w':1000,'res_h':800,'ui_scale':1},
            'roi_final':(0,0,900,400),'inventory_tab_roi':(0,0,1,1)}
        controller.wait_grid_stable.return_value = np.full((800,1000,3),255,np.uint8)
        analyzer.is_on_essence_page.return_value = True
        analyzer.is_gold.return_value = True
        scanner = AutoScanner(SimpleNamespace(data={}),controller,analyzer,{},max_items=10,sample_pattern='cross')
        visited=[]
        def scan_one(layout,box,gold,row,col):
            visited.append((row,col))
            scanner.processed_items += 1
            return True
        scanner._scan_one = scan_one
        with patch('core.scanner.GridPage.build',return_value=page()):
            scanner.start()
        self.assertEqual(visited,[(1,c) for c in range(1,6)]+[(r,1) for r in range(1,6)])
        controller.swipe_page.assert_not_called()

    def test_scanner_consumes_page_before_swiping(self):
        for cols, limit, swipes in ((9,10,0),(11,10,0),(9,50,1),(11,60,1)):
            with self.subTest(cols=cols,limit=limit):
                controller, analyzer = Mock(), Mock()
                controller.get_scaled_layout.return_value = {
                    'env': {'res_w':1000,'res_h':800,'ui_scale':1},
                    'roi_final': (0,0,900,400), 'inventory_tab_roi':(0,0,1,1)}
                controller.wait_grid_stable.return_value = np.full((800,1000,3),255,np.uint8)
                analyzer.is_on_essence_page.return_value = True
                analyzer.is_gold.return_value = True
                scanner = AutoScanner(SimpleNamespace(data={}),controller,analyzer,{},max_items=limit)
                visited=[]
                def scan_one(layout, box, gold, row, col):
                    visited.append((row,col))
                    scanner.processed_items += 1
                    return True
                scanner._scan_one = scan_one
                with patch('core.scanner.GridPage.build',side_effect=[page(cols=cols),page(3,cols=cols)]):
                    scanner.start()
                self.assertEqual(len(visited),limit)
                self.assertEqual(len(set(visited)),limit)
                self.assertEqual(controller.swipe_page.call_count,swipes)


class ScrollFeedbackTests(unittest.TestCase):
    def test_repeated_drag_loss_does_not_accumulate_at_multiple_scales(self):
        for scale in (1, 1.5, 2):
            with self.subTest(scale=scale):
                feedback = PageScrollFeedback(scale)
                current = page(scale=scale)
                feedback.observe(current, None)
                origin = 0
                errors = []
                for step in range(30):
                    plan = feedback.plan(current, (0,0,800*scale,400*scale))
                    loss = (20 + (step % 3 - 1))*scale
                    actual = plan['distance']-loss
                    origin += plan['advance_rows']
                    y = (current.rows[0][0][1]+plan['advance_rows']*current.pitch-actual)/scale
                    following = page(origin, scale=scale, y=y)
                    alignment = align_pages(current, following, minimum_rows=1)
                    feedback.observe(following, alignment)
                    errors.append(abs(following.rows[0][0][1]-20*scale))
                    current = following
                self.assertLessEqual(max(errors), 5*scale)
                self.assertLessEqual(errors[-1], 3*scale)
                self.assertGreater(np.median(feedback.losses), 16*scale)

    def test_bottom_clamping_and_repeated_page_are_not_learned_as_drag_loss(self):
        feedback = PageScrollFeedback(1)
        for after in (page(1, y=12), page()):
            before = page()
            feedback.plan(before, (0,0,800,400))
            feedback.observe(after, align_pages(before, after))
            self.assertFalse(feedback.losses)
        tail = page(4)
        tail.row_counts = [9,9,9,9,3]
        feedback.plan(page(), (0,0,800,400))
        feedback.observe(tail, align_pages(page(), tail, minimum_rows=1))
        self.assertFalse(feedback.losses)

    def test_correction_falls_back_to_two_rows_when_drag_would_leave_grid(self):
        plan = page_swipe_plan(page(y=0), (0,0,800,400), 1, compensation=20, drift=15)
        self.assertEqual(plan['overlap_rows'], 2)
        self.assertGreaterEqual(plan['y']-plan['distance'], 15)

    def test_phase_wrap_does_not_add_an_entire_row_to_drag(self):
        feedback = PageScrollFeedback(1)
        feedback.observe(page(y=0), None)
        plan = feedback.plan(page(y=58), (0,0,800,400))
        self.assertEqual(plan['drift_correction'], -2)
