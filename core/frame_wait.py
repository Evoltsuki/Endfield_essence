"""只对不同捕获帧进行稳定性判断，不把重复读取缓存当作新画面。"""
import cv2
import numpy as np


class StableRegion:
    def __init__(self, stable_seconds=0.10):
        self.stable_seconds = stable_seconds
        self.last_id = -1
        self.anchor = None
        self.since = None
        self.samples = 0

    def observe(self, frame_id, timestamp, image):
        if frame_id <= self.last_id or image is None or image.size == 0:
            return False
        self.last_id = frame_id
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (260, 130), interpolation=cv2.INTER_AREA)
        if self.anchor is None or np.mean(cv2.absdiff(gray, self.anchor) > 12) > 0.005:
            self.anchor = gray
            self.since = timestamp
            self.samples = 1
            return False
        self.samples += 1
        return self.samples >= 3 and timestamp - self.since >= self.stable_seconds
