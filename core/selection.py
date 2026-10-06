"""核对目标格子的四角选中框，不使用缩略图或词条内容作为物品身份。"""
import cv2
import numpy as np


def target_is_selected(image, box, corner_template, scale):
    if image is None or corner_template is None or scale <= 0:
        return False
    x1, y1, x2, y2 = box
    if x2 <= x1 or y2 <= y1:
        return False
    radius = max(1, round(20 * scale))
    # 只匹配外侧弧线，排除卡片内侧白底/品质色条的呼吸动画。
    base_mask = (np.indices(corner_template.shape[:2]).sum(axis=0)
                 < corner_template.shape[0]).astype(np.uint8) * 255
    # 模板最外侧约4px（1440p）是背景，横纵相邻卡片的亮边会进入这里。
    # 排除这两条外沿背景带，保留选中弧线；阈值和四角矩形约束不变。
    edge = max(1, round(corner_template.shape[0] / 6))
    base_mask[:edge, :] = 0
    base_mask[:, :edge] = 0
    positions = []
    for index, (x, y) in enumerate(((x1, y1), (x2, y1), (x1, y2), (x2, y2))):
        template = corner_template if index == 0 else cv2.flip(
            corner_template, {1: 1, 2: 0, 3: -1}[index])
        mask = base_mask if index == 0 else cv2.flip(base_mask, {1: 1, 2: 0, 3: -1}[index])
        left, top = max(0, x - radius), max(0, y - radius)
        area = image[top:min(image.shape[0], y + radius),
                     left:min(image.shape[1], x + radius)]
        if area.shape[0] < template.shape[0] or area.shape[1] < template.shape[1]:
            return False
        result = cv2.matchTemplate(area, template, cv2.TM_CCOEFF_NORMED, mask=mask)
        result = np.nan_to_num(result, nan=-1, posinf=-1, neginf=-1)
        _, score, _, point = cv2.minMaxLoc(result)
        if not score >= .85:
            return False
        positions.append((left + point[0], top + point[1]))
    tl, tr, bl, br = positions
    tolerance = max(2, round(5 * scale))
    if (abs(tl[1] - tr[1]) > tolerance or abs(bl[1] - br[1]) > tolerance
            or abs(tl[0] - bl[0]) > tolerance or abs(tr[0] - br[0]) > tolerance):
        return False
    # 四个命中必须围住当前格子，不能拼接邻格或装饰图案。
    return (.85 * (x2 - x1) <= tr[0] - tl[0] <= 1.2 * (x2 - x1)
            and .85 * (y2 - y1) <= bl[1] - tl[1] <= 1.2 * (y2 - y1))
