"""从当前位置向下只读验证第一列直到底部；B 键可停止，不保存个人配置。"""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
from pynput import keyboard
from core.analyzer import VisionAnalyzer
from core.scanner import AutoScanner
from device.controller import DeviceController
from utils.data_manager import DataManager
from utils.sys_helper import run_as_admin, setup_dpi_awareness


def main():
    output = Path('Output') / ('column-test-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    output.mkdir(parents=True)
    controller = DeviceController()
    dm = DataManager()
    dm.data = dict(dm.data, scan_mode='page', skip_marked=False, debug_gold=True)
    analyzer = VisionAnalyzer(dm)
    running = [True]
    report = dict(preview=True, sample_pattern='first_column', max_items=None,
                  status='preparing', results=[], selection_waits=[], swipes=[], error=None)
    protected = [Path('data/config.json'), Path('data/best_records.json')]
    def hashes():
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected if p.exists()}
    report['files_before'] = hashes()
    def log(message, tag='black'):
        with (output/'scan.log').open('a', encoding='utf-8') as stream:
            stream.write(f'{datetime.now().isoformat(timespec="milliseconds")} {message}\n')
        if message.startswith(('[错误]', '[异常]')):
            report['error'] = message
        if '扫描结束' in message:
            report['status'] = 'completed'
    def result(data):
        index = len(report['results'])+1
        record = {k:v for k,v in data.items() if k != 'image'}
        record.update(tokens=analyzer.last_ocr_tokens, ocr_path=analyzer.last_ocr_path)
        report['results'].append(record)
        cv2.imencode('.png', data['image'])[1].tofile(str(output/f'item-{index:03d}.png'))
        with (output/'results.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(kind='ocr', data=record), ensure_ascii=False)+'\n')
    scanner = AutoScanner(dm, controller, analyzer, dict(log=log, result=result),
                          preview=True, sample_pattern='first_column')
    def stop(key):
        if getattr(key, 'char', '') == 'b':
            running[0] = False
            scanner.stop()
    listener = keyboard.Listener(on_press=stop)
    listener.start()
    started = time.perf_counter()
    try:
        if not controller.activate_game():
            raise RuntimeError('激活失败: '+getattr(controller, 'activation_error', '窗口不可用'))
        layout = controller.get_scaled_layout()
        env, roi = layout['env'], layout['roi_final']
        report['env'] = env
        if not running[0]:
            return
        original_grid = controller.wait_grid_stable
        def grid(*args, **kwargs):
            frame = original_grid(*args, **kwargs)
            if frame is not None:
                index = len(report['swipes'])
                cv2.imencode('.png', frame)[1].tofile(str(output/f'page-{index:03d}.png'))
            return frame
        controller.wait_grid_stable = grid
        original_swipe = controller.swipe_page
        def swipe(env, plan, keep_running):
            report['swipes'].append(dict(plan))
            return original_swipe(env, plan, keep_running)
        controller.swipe_page = swipe
        original_selection = controller.wait_target_selected
        def selection(*args, **kwargs):
            frame = original_selection(*args, **kwargs)
            report['selection_waits'].append(dict(controller.last_selection_wait))
            if frame is None and running[0]:
                failed = controller.capture_window_bg(env)
                if failed is not None:
                    cv2.imencode('.png', failed)[1].tofile(str(output/'selection-failed.png'))
            return frame
        controller.wait_target_selected = selection
        report['status'] = 'running'
        log('[测试] 从当前位置向下检查第一列，直到底部；不回顶、不执行标记')
        scanner.start()
    except Exception:
        report['error'] = traceback.format_exc()
        log('[异常] '+report['error'])
    finally:
        controller.stop_capture()
        listener.stop()
        if not running[0]:
            report['status'] = 'user_stopped'
        elif report['error']:
            report['status'] = 'failed'
        report['checked_items'] = scanner.processed_items
        report['elapsed_seconds'] = round(time.perf_counter()-started, 3)
        report['files_after'] = hashes()
        report['personal_files_unchanged'] = report['files_before'] == report['files_after']
        (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        log(f"[测试结束] 状态={report['status']}，检查={scanner.processed_items}，耗时={report['elapsed_seconds']}s")


if __name__ == '__main__':
    os.chdir(PROJECT_ROOT)
    setup_dpi_awareness()
    if run_as_admin():
        main()
