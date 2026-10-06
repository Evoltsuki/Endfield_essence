"""Resolution-relative text regions for the three-row essence detail panel."""
import cv2
import numpy as np


def text_regions(image):
    if image is None or image.ndim != 3:
        return None
    h, w = image.shape[:2]
    if h < 100 or abs(w / h - 2) > .08:
        return None
    crops, boxes = [], []
    for row in range(3):
        for left, top, right, bottom in (
            (.055, .065 + row * .288, .815, .218 + row * .288),
            (.875, .20 + row * .288, .98, .36 + row * .288),
        ):
            x1, y1, x2, y2 = round(left*w), round(top*h), round(right*w), round(bottom*h)
            gray = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
            ink = gray > 80
            # Empty or vertically clipped text must fall back to detection.
            if not ink.size or np.count_nonzero(ink) < 5 or np.any(ink[0]) or np.any(ink[-1]):
                return None
            # Do not pad short names and single digits to the full name-column width.
            columns = np.flatnonzero(ink.any(axis=0))
            gray = gray[:, max(0, int(columns[0])-3):min(gray.shape[1], int(columns[-1])+4)]
            crop = cv2.cvtColor(255-gray, cv2.COLOR_GRAY2BGR)
            crops.append(cv2.copyMakeBorder(crop, 3, 3, 3, 3, cv2.BORDER_CONSTANT, value=(255,255,255)))
            boxes.append([[x1,y1],[x2,y1],[x2,y2],[x1,y2]])
    return crops, boxes
