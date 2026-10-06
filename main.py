import sys
import os
from pathlib import Path
import traceback
import threading
import tkinter as tk
from tkinter import messagebox
from utils.sys_helper import run_as_admin, setup_dpi_awareness
from utils.session_log import SessionLog

def handle_exception(exc_type, exc_value, exc_traceback, diagnostics=None):
    """全局异常捕获处理器"""
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    if diagnostics:
        diagnostics.exception(exc_type, exc_value, exc_traceback)
    messagebox.showerror("运行错误", error_msg)

def main():
    """主程序入口配置及启动逻辑"""
    os.chdir(Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent)
    self_check = '--self-check' in sys.argv
    setup_dpi_awareness()
    if not run_as_admin():
        return

    try:
        diagnostics = SessionLog()
    except OSError as exc:
        messagebox.showerror("日志目录不可写", f"无法创建 Output/logs：{exc}\n请将项目放在可写目录后重试。")
        return
    previous_sys, previous_thread = sys.excepthook, threading.excepthook
    sys.excepthook = lambda *args: handle_exception(*args, diagnostics=diagnostics)
    threading.excepthook = lambda args: diagnostics.exception(args.exc_type, args.exc_value, args.exc_traceback)
    try:
        # 在创建日志之后加载运行依赖，初始化错误也能留档。
        from utils.data_manager import DataManager
        from device.controller import DeviceController
        from core.analyzer import VisionAnalyzer
        from gui.app import MatrixAssistantApp
        root = tk.Tk()
        if self_check:
            root.withdraw()
        root.report_callback_exception = sys.excepthook
        dm = DataManager()
        app = MatrixAssistantApp(root, dm, DeviceController(), VisionAnalyzer(dm), diagnostics=diagnostics)
        if self_check:
            root.update_idletasks()
            app.kb.stop()
            root.destroy()
            diagnostics.write('[启动自检] UI、OCR模型和资源加载成功；未操作游戏')
        else:
            root.mainloop()
    except Exception:
        if self_check:
            diagnostics.exception(*sys.exc_info())
            raise
        handle_exception(*sys.exc_info(), diagnostics=diagnostics)
    finally:
        diagnostics.close()
        sys.excepthook, threading.excepthook = previous_sys, previous_thread

if __name__ == "__main__":
    main()
