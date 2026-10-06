"""Observe selection animation for two cells without OCR or mark actions."""
import json
import time
import traceback
import threading
from datetime import datetime
from pathlib import Path
import os
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import win32gui
from pynput import keyboard

from core.analyzer import VisionAnalyzer
from core.page_grid import GridPage
from device.controller import DeviceController
from utils.data_manager import DataManager
from utils.sys_helper import run_as_admin


def main():
    output = Path("Output") / ("selection-probe-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    output.mkdir(parents=True)
    controller = DeviceController()
    report = {"observations": []}
    frames = []
    stopped = threading.Event()
    listener = keyboard.Listener(on_press=lambda key: stopped.set() if (getattr(key, "char", "") or "").lower() == "b" else None)
    listener.start()
    try:
        analyzer = VisionAnalyzer(DataManager())
        if not controller.activate_game():
            raise RuntimeError(controller.activation_error)
        layout = controller.get_scaled_layout()
        env = layout["env"]
        report["environment"] = env
        ready = lambda: not stopped.is_set() and controller._same_window(env) and win32gui.GetForegroundWindow() == env["hwnd"]
        image = controller.wait_grid_stable(env, layout["roi_final"], ready)
        if image is None or not analyzer.is_on_essence_page(image, layout["inventory_tab_roi"], env["ui_scale"]):
            raise RuntimeError("Essence inventory is not ready")
        page = GridPage.build(image, analyzer.find_essences_with_mask(image, layout["roi_final"], env["ui_scale"]))
        for col in (2, 4):
            box = page.rows[0][col]
            if not ready():
                raise RuntimeError("Window changed or foreground lost")
            controller.click_at((box[0]+box[2])//2 + env["abs_x"],
                                (box[1]+box[3])//2 + env["abs_y"], delay=.2)
            start = time.perf_counter()
            last_id = controller.wgc_frame_id
            observations = []
            failures = 0
            while time.perf_counter() - start < 4:
                if not ready():
                    raise RuntimeError("Window changed or foreground lost")
                sample = controller.capture_window_bg(env, after_frame=last_id, with_metadata=True)
                if sample is not None and sample[1] > last_id:
                    image, last_id, _ = sample
                    selected = analyzer.is_target_selected(image, box, env["ui_scale"])
                    observations.append({"ms": round((time.perf_counter()-start)*1000), "selected": selected})
                    if not selected and failures < 5:
                        filename = f"col-{col+1}-failure-{failures+1}.png"
                        frames.append((filename, image))
                        failures += 1
                time.sleep(.03)
            report["observations"].append({"column": col+1, "box": box, "frames": observations})
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        controller.stop_capture()
        listener.stop()
        for filename, image in frames:
            cv2.imencode(".png", image)[1].tofile(str(output / filename))
        (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    if run_as_admin():
        main()
