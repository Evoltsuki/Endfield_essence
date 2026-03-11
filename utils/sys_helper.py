import os
import sys
import ctypes


def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


def run_as_admin():
    try:
        if ctypes.windll.shell32.IsUserAnAdmin(): return True
        executable = sys.executable
        if executable.endswith("python.exe"): executable = executable.replace("python.exe", "pythonw.exe")

        # 核心修复：把 __file__ 改为 sys.argv[0]的绝对路径，确保提权重启的是 main.py
        script_path = os.path.abspath(sys.argv[0])
        ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, f'"{script_path}"', None, 1)
        return False
    except:
        return False


def setup_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except:
            pass