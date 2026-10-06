import os
import sys
import ctypes
import subprocess

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
        ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, subprocess.list2cmdline([script_path, *sys.argv[1:]]), None, 1)
        return False
    except Exception:
        return False

def setup_dpi_awareness():
    """使用物理像素；显式声明指针参数，兼容 64 位和工作线程。"""
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
