import os
import sys
import ctypes

def resource_path(relative_path):
    """获取资源绝对路径"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def run_as_admin():
    """检测当前权限并尝试以管理员身份重新运行程序"""
    try:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return True

        executable = sys.executable
        if executable.endswith("python.exe"):
            executable = executable.replace("python.exe", "pythonw.exe")

        script_path = os.path.abspath(sys.argv[0])
        ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, f'"{script_path}"', None, 1)
        return False
    except Exception:
        return False

def setup_dpi_awareness():
    """开启 Windows 高 DPI 适配"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass