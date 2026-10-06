"""整页几何与重叠行跟踪。相同缩略图不能独立证明物品相同。"""
from dataclasses import dataclass
import cv2
import numpy as np


@dataclass
class GridPage:
    rows: list
    features: list
    columns: int
    pitch: float

    @classmethod
    def build(cls, image, boxes):
        if not boxes:
            raise ValueError("未识别到完整基质格子")
        height = float(np.median([b[3]-b[1] for b in boxes]))
        rows = []
        for box in sorted(boxes, key=lambda b: (b[1], b[0])):
            if not rows or abs(box[1]-np.median([b[1] for b in rows[-1]])) > height*.3:
                rows.append([])
            rows[-1].append(tuple(int(v) for v in box))
        for row in rows:
            row.sort(key=lambda b: b[0])
        columns = max(map(len, rows))
        # 只允许最后一行右侧缺格，且缺格位置必须确认为暗色空白。
        # 中间漏检不得被压缩成更少列。
        reference = next(row for row in rows if len(row)==columns)
        for index,row in enumerate(rows):
            if len(row)==columns:
                continue
            if index!=len(rows)-1 or any(abs(b[0]-reference[c][0])>height*.2 for c,b in enumerate(row)):
                raise ValueError("网格中间缺格，无法可靠对齐")
            y = int(np.median([b[1] for b in row]))
            for ref in reference[len(row):]:
                x1,x2 = ref[0],ref[2]
                h,w = int(height),x2-x1
                crop = image[y+int(h*.3):y+int(h*.7), x1+int(w*.3):x1+int(w*.7)]
                if not crop.size:
                    raise ValueError("末行空白位置超出截图")
                mean,std = cv2.meanStdDev(cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY))
                if mean[0,0]>=60 or std[0,0]>=15:
                    raise ValueError("末行缺格位置非空，可能漏检，停止")
                row.append((x1,y,x2,y+h))
        centers = np.array([[(b[0]+b[2])/2 for b in row] for row in rows])
        if np.max(np.abs(centers-centers[0])) > height*.2:
            raise ValueError("网格列位置不一致")
        ys = [np.median([b[1] for b in row]) for row in rows]
        pitch = float(np.median(np.diff(ys))) if len(rows)>1 else height*1.1
        if len(rows)>2 and max(abs(np.diff(ys)-pitch)) > height*.2:
            raise ValueError("网格行间距不一致")
        # 模板阈值会让不同图案的框偏移数像素；以整行/整列中位数校正，
        # 避免把检测框抖动当成物品变化。
        lefts = np.median([[b[0] for b in row] for row in rows], axis=0)
        width = int(np.median([b[2]-b[0] for row in rows for b in row]))
        rows = [[(int(x),int(y),int(x)+width,int(y)+int(height)) for x in lefts] for y in ys]
        features = []
        for row in rows:
            values = []
            for x1,y1,x2,y2 in row:
                w,h = x2-x1,y2-y1
                # 避开选中边框、左下角标记与右上角装备标记。
                crop = image[y1+int(h*.2):y1+int(h*.8), x1+int(w*.2):x1+int(w*.8)]
                values.append(cv2.resize(crop, (24,24), interpolation=cv2.INTER_AREA).astype(np.float32))
            features.append(values)
        return cls(rows, features, columns, pitch)


def describe_feature(feature):
    gray = cv2.cvtColor(feature, cv2.COLOR_BGR2GRAY)
    coefficients = cv2.dct(cv2.resize(gray, (32,32)))[:8,:8].ravel()[1:]
    return coefficients > np.median(coefficients), feature.mean(axis=(0,1))


def similar_features(a, b):
    return np.count_nonzero(a[0] != b[0]) <= 12 and np.mean(np.abs(a[1]-b[1])) < 6


def single_row_is_unique(page, index):
    """One-row alignment needs a wide, diverse row unique within this page."""
    if page.columns < 6:
        return False
    rows = [[describe_feature(f) for f in row] for row in page.features]
    target = rows[index]
    representatives = []
    for feature in target:
        if not any(similar_features(feature, other) for other in representatives):
            representatives.append(feature)
    if len(representatives) < 3:
        return False
    return sum(all(similar_features(a,b) for a,b in zip(target,row)) for row in rows) == 1


def align_pages(previous, current, minimum_rows=2):
    """返回唯一可靠行偏移；重复图案产生歧义时拒绝，不按单件图像去重。"""
    if previous.columns != current.columns:
        raise ValueError("翻页后列数变化，须重新开始")
    before = [[describe_feature(f) for f in row] for row in previous.features]
    after = [[describe_feature(f) for f in row] for row in current.features]
    candidates = []
    for offset in range(len(previous.rows)):
        count = min(len(previous.rows)-offset, len(current.rows))
        if count < minimum_rows:
            continue
        if count == 1 and (not single_row_is_unique(previous, offset) or not single_row_is_unique(current, 0)):
            continue
        distances = [(int(np.count_nonzero(a[0]!=b[0])), float(np.mean(np.abs(a[1]-b[1]))))
                     for old,new in zip(before[offset:offset+count], after[:count])
                     for a,b in zip(old,new)]
        ratio = sum(bits<=12 and color<6 for bits,color in distances)/len(distances)
        if ratio >= (1.0 if count == 1 else .95):
            candidates.append((offset, count, ratio, float(np.mean([bits+color for bits,color in distances]))))
    if len(candidates) != 1:
        raise ValueError(f"重叠行无法唯一对齐（候选数 {len(candidates)}），停止以避免漏扫")
    offset, count, ratio, distance = candidates[0]
    displacement = float(np.median([a[1]-b[1] for old,new in
        zip(previous.rows[offset:offset+count], current.rows[:count]) for a,b in zip(old,new)]))
    return dict(offset=offset, overlap_rows=count, match_ratio=ratio,
                feature_distance=distance, displacement=displacement)


class PageTracker:
    def __init__(self, minimum_rows=2):
        self.minimum_rows = minimum_rows
        self.previous = None
        self.origin = 0
        self.seen = set()
        self.repeats = 0

    def observe(self, page):
        alignment = None
        if self.previous is not None:
            alignment = align_pages(self.previous, page, self.minimum_rows)
            offset = alignment['offset']
            same_shape = len(self.previous.rows)==len(page.rows)
            # 零行偏移但物理画面仍在滑动不能作为到底证据。
            repeated = offset==0 and same_shape and abs(alignment['displacement'])<page.pitch*.03
            self.repeats = self.repeats+1 if repeated else 0
            self.origin += offset
        fresh = []
        for row, boxes in enumerate(page.rows):
            for col, box in enumerate(boxes):
                key = (self.origin+row, col)
                if key not in self.seen:
                    fresh.append((box, key[0]+1, col+1))
                    self.seen.add(key)
        self.previous = page
        return fresh, alignment, self.repeats>=2


def page_swipe_plan(page, roi, scale, overlap_rows=None):
    if overlap_rows is None:
        overlap_rows = 1 if single_row_is_unique(page, len(page.rows)-1) else 2
    if overlap_rows not in (1, 2):
        raise ValueError("重叠行数必须为1或2")
    if len(page.rows)<3:
        raise ValueError("完整可见行不足三行，无法保留两行重叠翻页")
    advance = len(page.rows)-overlap_rows
    distance = round(advance*page.pitch + 16*scale)
    x,y,w,h = roi
    start_y = min(y+h-round(25*scale), page.rows[-1][0][3]-round(10*scale))
    if start_y-distance < y+round(15*scale):
        raise ValueError("滑动轨迹超出网格可视区域")
    start_x = (page.rows[0][0][0]+page.rows[0][0][2])//2
    return dict(x=start_x, y=start_y, distance=distance, advance_rows=advance, overlap_rows=overlap_rows)
