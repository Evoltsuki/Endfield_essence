import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np
from core.page_grid import GridPage, PageTracker, align_pages, page_swipe_plan
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
