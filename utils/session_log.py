"""Durable local diagnostics, independent of the bounded GUI log buffer."""
import json
import os
import platform
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from utils.log_retention import prune_logs


def timestamp():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class SessionLog:
    def __init__(self, base="Output/logs"):
        name = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}-{uuid4().hex[:6]}"
        self.directory = Path(base).resolve() / name
        self.directory.mkdir(parents=True, exist_ok=False)
        self.lock = threading.RLock()
        self.error = ""
        self.closed = False
        self.sequence = 0
        self.scan = None
        self.scan_stream = None
        self.result_stream = None
        self.stream = (self.directory / "app.log").open("a", encoding="utf-8")
        self.write("[启动] " + json.dumps({"python": sys.version, "platform": platform.platform(),
                   "pid": os.getpid(), "entry": sys.argv[0]}, ensure_ascii=False))
        skipped = prune_logs(self.directory.parent)
        if skipped:
            self.write('[日志] 旧日志占用中，稍后清理：' + ', '.join(skipped), 'gray')

    def _failed(self, exc):
        self.error = f"日志保存失败：{exc}"

    def write(self, message, tag="black"):
        plain = "".join(str(part[0]) for part in message) if isinstance(message, list) else str(message)
        with self.lock:
            if self.closed:
                return
            if self.scan is not None:
                self.scan["last_message"] = plain
                if "[错误]" in plain or "[异常]" in plain:
                    self.scan["last_error"] = plain
            line = f"{timestamp()} [{tag}] [{threading.current_thread().name}] {plain}\n"
            for stream in (self.stream, self.scan_stream):
                if stream is not None:
                    try:
                        stream.write(line)
                        stream.flush()
                    except OSError as exc:
                        self._failed(exc)

    def _summary(self):
        try:
            destination = self.scan_directory / "summary.json"
            temporary = destination.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.scan, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(destination)
        except OSError as exc:
            self._failed(exc)

    def begin_scan(self, config):
        with self.lock:
            if self.scan is not None:
                self.finish_scan("interrupted")
            self.sequence += 1
            self.scan_directory = self.directory / f"scan-{self.sequence:03d}"
            self.scan = {"started_at": timestamp(), "status": "running", "config": dict(config),
                         "ocr_results": 0, "review_results": 0, "last_message": "", "last_error": ""}
            self.started = time.perf_counter()
            try:
                self.scan_directory.mkdir()
                self.scan_stream = (self.scan_directory / "scan.log").open("a", encoding="utf-8")
                self.result_stream = (self.scan_directory / "results.jsonl").open("a", encoding="utf-8")
            except OSError as exc:
                self._failed(exc)
            self._summary()
            self.write("[开始] " + json.dumps(config, ensure_ascii=False))

    def record(self, kind, data):
        # Images are deliberately excluded from normal-run diagnostics.
        record = {key: value for key, value in data.items() if key != "image"}
        with self.lock:
            if self.scan is None:
                return
            if kind == "ocr":
                self.scan["ocr_results"] += 1
                self.scan["review_results"] += bool(data.get("issue"))
            try:
                if self.result_stream is not None:
                    self.result_stream.write(json.dumps(dict(time=timestamp(), kind=kind, data=record),
                                                        ensure_ascii=False) + "\n")
                    self.result_stream.flush()
            except (OSError, TypeError, ValueError) as exc:
                self._failed(exc)

    def finish_scan(self, status="finished", checked_items=None, scan_seconds=None):
        with self.lock:
            if self.scan is None:
                return
            if status == "finished" and self.scan["last_error"]:
                status = "ended_with_errors"
            self.scan.update(status=status, ended_at=timestamp(), checked_items=checked_items,
                             scan_seconds=scan_seconds, total_seconds=round(time.perf_counter()-self.started, 3))
            self._summary()
            self.write(f"[结束摘要] 状态={status} 检查={checked_items} 扫描秒数={scan_seconds}")
            for stream in (self.scan_stream, self.result_stream):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError as exc:
                        self._failed(exc)
            self.scan_stream = self.result_stream = self.scan = None

    def exception(self, exc_type, exc_value, exc_traceback):
        self.write("[异常] " + "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)), "red")

    def close(self, checked_items=None, scan_seconds=None):
        with self.lock:
            if self.closed:
                return
            self.finish_scan("window_closed", checked_items, scan_seconds)
            self.write("[退出] 程序关闭")
            try:
                self.stream.close()
            except OSError as exc:
                self._failed(exc)
            self.closed = True
            prune_logs(self.directory.parent)
