"""只测试整页几何及滑动，不打开详情、不执行标记。"""
import argparse
import json
import time
import traceback
from datetime import datetime
from pathlib import Path
import os
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))
import cv2
import win32gui
import win32con
from core.analyzer import VisionAnalyzer
from core.page_grid import GridPage, PageTracker, page_swipe_plan
from device.controller import DeviceController
from pynput import keyboard
from utils.data_manager import DataManager
from utils.sys_helper import run_as_admin


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--steps', type=int, default=3, choices=range(1, 6))
    parser.add_argument("--size", help="仅测试：调整游戏窗口外框为 WIDTHxHEIGHT，结束后恢复")
    parser.add_argument("--windowed", action="store_true", help="临时用Alt+Enter切换窗口模式，结束后恢复")
    args = parser.parse_args()
    output = Path('Output') / ('page-test-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    output.mkdir(parents=True)
    controller = DeviceController()
    analyzer = VisionAnalyzer(DataManager())
    tracker = PageTracker(minimum_rows=1)
    running = [True]
    def on_press(key):
        if getattr(key, 'char', '') == 'b':
            running[0] = False
    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    report = {'pages': [], 'error': None}
    original_rect = None
    game_hwnd = None
    toggled = False
    def toggle_window_mode():
        keys = keyboard.Controller()
        with keys.pressed(keyboard.Key.alt_l):
            keys.press(keyboard.Key.enter)
            keys.release(keyboard.Key.enter)
        time.sleep(1)
    def log(message):
        with (output/'scan.log').open('a', encoding='utf-8') as stream:
            stream.write(str(message)+'\n')
    try:
        if not controller.activate_game():
            raise RuntimeError('激活失败: '+getattr(controller, 'activation_error', '窗口不可用'))
        if args.size:
            width,height = map(int,args.size.lower().split('x'))
            if not (960<=width<=2560 and 720<=height<=1440):
                raise ValueError("测试尺寸超出允许范围")
            game_hwnd = controller.get_window_env()['hwnd']
            original_rect = win32gui.GetWindowRect(game_hwnd)
            if args.windowed:
                toggle_window_mode()
                toggled = True
            win32gui.SetWindowPos(game_hwnd,0,original_rect[0],original_rect[1],width,height,win32con.SWP_NOZORDER|win32con.SWP_NOACTIVATE)
            time.sleep(1)
        layout = controller.get_scaled_layout()
        env, roi = layout['env'], layout['roi_final']
        report['env'] = env
        if args.size:
            report['requested_size'] = args.size
            report['effective_client_size'] = [env['res_w'],env['res_h']]
            if abs(env['res_w']-width)>50 or abs(env['res_h']-height)>80:
                raise RuntimeError('游戏拒绝调整窗口尺寸，未将本次算作跨分辨率测试')
        report['roi'] = roi
        for step in range(args.steps+1):
            if not running[0]:
                break
            image = controller.wait_grid_stable(env, roi, lambda: running[0])
            if image is None:
                raise RuntimeError('网格未稳定: '+str(controller.last_wait))
            cv2.imencode('.png', image)[1].tofile(str(output/f'page-{step}.png'))
            if not analyzer.is_on_essence_page(image, layout['inventory_tab_roi'], env['ui_scale']):
                raise RuntimeError('未处于基质背包')
            cv2.imencode('.png', image)[1].tofile(str(output/f'page-{step}.png'))
            boxes = analyzer.find_essences_with_mask(image, roi, env['ui_scale'])
            page = GridPage.build(image, boxes)
            fresh, alignment, ended = tracker.observe(page)
            record = dict(rows=len(page.rows), columns=page.columns, pitch=page.pitch,
                          new_cells=len(fresh), alignment=alignment, ended=ended,
                          wait=dict(controller.last_wait), boxes=page.rows)
            report['pages'].append(record)
            log(record)
            if ended or step==args.steps:
                break
            plan = page_swipe_plan(page, roi, env['ui_scale'])
            record['swipe'] = plan
            started = time.perf_counter()
            controller.swipe_page(env, plan, lambda: running[0])
            record['swipe_seconds'] = time.perf_counter()-started
    except Exception:
        report['error'] = traceback.format_exc()
        log(report['error'])
    finally:
        controller.stop_capture()
        if toggled:
            controller.activate_game()
            toggle_window_mode()
        if original_rect is not None:
            x1,y1,x2,y2 = original_rect
            win32gui.SetWindowPos(game_hwnd,0,x1,y1,x2-x1,y2-y1,win32con.SWP_NOZORDER|win32con.SWP_NOACTIVATE)
        listener.stop()
        (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    os.chdir(PROJECT_ROOT)
    if run_as_admin():
        main()
