import sys
import traceback
import tkinter as tk
from tkinter import messagebox
from utils.sys_helper import run_as_admin, setup_dpi_awareness
from utils.data_manager import DataManager
from device.controller import DeviceController
from core.analyzer import VisionAnalyzer
from gui.app import MatrixAssistantApp


def handle_exception(exc_type, exc_value, exc_traceback):
    """全局异常捕获"""
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    messagebox.showerror("运行错误", error_msg)


def main():
    setup_dpi_awareness()
    if not run_as_admin(): return

    sys.excepthook = handle_exception

    root = tk.Tk()

    # 依赖注入：组装各大核心模块
    dm = DataManager()
    controller = DeviceController()
    analyzer = VisionAnalyzer(dm)

    # 启动应用
    app = MatrixAssistantApp(root, dm, controller, analyzer)
    root.mainloop()


if __name__ == "__main__":
    main()