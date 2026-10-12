"""离线重放已保存的 OCR token 和滑动日志；不创建窗口、不发送游戏输入。"""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from opencc import OpenCC
import core.analyzer as analyzer_module
from core.analyzer import VisionAnalyzer
from core.page_grid import GridPage, PageScrollFeedback


def replay_ocr(paths, analyzer):
    records, counts = [], Counter()
    for path in paths:
        for line_number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            entry = json.loads(line)
            if entry.get('kind') != 'ocr':
                continue
            data = entry['data']
            if 'tokens' not in data:
                counts['missing_tokens'] += 1
                continue
            parsed = analyzer.parse_ocr_lines(data['tokens'])
            issue = analyzer.last_ocr_issue
            # 对同一份 token 做阈值对照，不重新运行 OCR 模型或猜测原图。
            threshold = analyzer_module.OCR_MIN_CONFIDENCE
            try:
                analyzer_module.OCR_MIN_CONFIDENCE = .80
                old_parsed = analyzer.parse_ocr_lines(data['tokens'])
                old_issue = analyzer.last_ocr_issue
            finally:
                analyzer_module.OCR_MIN_CONFIDENCE = threshold
            old_accepted, accepted = not old_issue, not issue
            counts['replayed'] += 1
            counts['old_accepted'] += old_accepted
            counts['new_accepted'] += accepted
            counts['newly_accepted'] += accepted and not old_accepted
            counts['still_review'] += not accepted
            counts['regressions'] += old_accepted and not accepted
            counts['parsed_content_changes'] += parsed != old_parsed
            counts['saved_display_changes'] += parsed[0] != data.get('display_str', parsed[0])
            records.append(dict(source=str(path), line=line_number,
                                row=data.get('row'), col=data.get('col'),
                                display=parsed[0], old_issue=old_issue, new_issue=issue,
                                saved_issue=data.get('issue', '')))
    return dict(counts), records


PAGE = re.compile(r'第 (\d+) 屏：(\d+) 行 × (\d+) 列，新增 \d+ 格，行距 ([\d.]+)px')
SWIPE = re.compile(r'距离 (\d+)px，计划推进(\d+)行，保留(\d+)行重叠')
ALIGN = re.compile(r'推进 (\d+) 行，重叠 (\d+) 行，匹配 (\d+)%?，位移 ([-\d.]+)px')


def replay_scroll(path):
    """日志位移是事实；新距离的移动量只是保持起步损失不变的模型预测。"""
    shape = pending = feedback = None
    scale, width, height = 2., 2560, 1440
    measured_drift = predicted_drift = 0.
    records = []
    for line in path.read_text(encoding='utf-8').splitlines():
        resolution = re.search(r'\[整页\] 分辨率 (\d+)x(\d+)', line)
        if resolution:
            width, height = map(int, resolution.groups())
            scale = height/720
        match = PAGE.search(line)
        if match:
            _, rows, columns, pitch = match.groups()
            shape = (int(rows), int(columns), float(pitch))
        match = SWIPE.search(line)
        if match and shape:
            pending = (*map(int, match.groups()), shape)
        match = ALIGN.search(line)
        if not match or pending is None:
            continue
        offset, overlap, ratio, displacement = map(float, match.groups())
        distance, advance, _, (rows, columns, pitch) = pending
        pending = None
        loss = distance-displacement
        measured_drift += advance*pitch-displacement
        record = dict(logged_distance=distance, logged_displacement=displacement,
                      logged_advance=int(offset), measured_loss=loss,
                      inferred_cumulative_drift=round(measured_drift, 2))
        # 只模拟完整推进且损失合理的样本；到底截短的拖动不能这样外推。
        if offset == advance and ratio == 100 and 0 <= loss <= pitch*.35:
            if feedback is None:
                feedback = PageScrollFeedback(scale)
            roi = (round(18*scale), round(72*scale), round(width-324*scale), round(height-150*scale))
            def model_page(drift):
                boxes = [[(round(36*scale+c*pitch), round(78*scale+r*pitch+drift),
                           round(36*scale+c*pitch+pitch*.92), round(78*scale+r*pitch+drift+pitch*.92))
                          for c in range(columns)] for r in range(rows)]
                # 不填充虚构的缩略图；重叠行数使用日志记录。
                return GridPage(boxes, [], columns, pitch)
            current = model_page(predicted_drift)
            # 只比较距离反馈；日志没有原始网格图像，不重新判断重叠唯一性。
            plan = feedback.plan(current, roi, overlap_rows=int(overlap))
            predicted_move = plan['distance']-loss
            predicted_drift += plan['advance_rows']*pitch-predicted_move
            feedback.observe(model_page(predicted_drift), dict(
                offset=plan['advance_rows'], displacement=predicted_move))
            record.update(model_distance=plan['distance'], model_compensation=plan['compensation'],
                          model_drift_correction=plan['drift_correction'], model_residual=round(predicted_drift, 2))
        records.append(record)
    return dict(source=str(path), observations=records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--logs', type=Path, default=PROJECT_ROOT/'Output/logs')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    results = sorted(args.logs.rglob('results.jsonl'))
    scans = sorted(args.logs.rglob('scan.log'))  # 不重复读取 app.log 中的副本。
    if not results:
        parser.error('未找到 results.jsonl，无法重放 OCR 原始 token')
    output = args.output or PROJECT_ROOT/'Output'/('log-replay-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    output.mkdir(parents=True, exist_ok=True)
    analyzer = VisionAnalyzer.__new__(VisionAnalyzer)
    analyzer.cc = OpenCC('t2s')
    analyzer.dm = SimpleNamespace(corrections=json.loads((PROJECT_ROOT/'data/Jiucuo.json').read_text(encoding='utf-8')))
    counts, records = replay_ocr(results, analyzer)
    scroll = [replay_scroll(path) for path in scans]
    report = dict(ocr=counts, scroll=[item for item in scroll if item['observations']],
                  inputs={str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in results+scans},
                  limits=['OCR 为已保存 token 重放，无原图人工真值，不能据此声称识别准确率。',
                          '滑动预测假设日志中的起步损失在新距离下不变；网格坐标及后续位移为模型值，不是实机结果。',
                          '普通日志没有保存网格/选中截图，无法直接重放选中框及图像对齐。'])
    (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (output/'ocr-records.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(output=str(output), ocr=counts,
                          scroll_observations=sum(len(item['observations']) for item in scroll)), ensure_ascii=False))
    return int(bool(counts.get('regressions') or counts.get('parsed_content_changes')))


if __name__ == '__main__':
    raise SystemExit(main())
