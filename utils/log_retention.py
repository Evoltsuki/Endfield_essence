"""仅清理本工具生成的会话目录，保留最近五次运行。"""
import re
import os
import shutil
from pathlib import Path

SESSION_NAME = re.compile(r'\d{8}-\d{6}-\d+-[0-9a-f]{6}')


def log_in_use(path):
    if os.name != 'nt':
        return False
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0, None)
    if handle == wintypes.HANDLE(-1).value:
        return True
    kernel.CloseHandle(handle)
    return False


def prune_logs(base, keep=5):
    base = Path(base).resolve()
    if not base.exists():
        return []
    sessions = sorted((p for p in base.iterdir() if p.is_dir() and not p.is_symlink()
                       and SESSION_NAME.fullmatch(p.name) and (p/'app.log').is_file()),
                      key=lambda p: (p.stat().st_ctime_ns, p.name), reverse=True)
    skipped = []
    for session in sessions[keep:]:
        resolved = session.resolve()
        if resolved.parent != base:
            continue
        if log_in_use(session/'app.log'):
            skipped.append(session.name)
            continue
        try:
            shutil.rmtree(resolved)
        except OSError:
            # 正在运行的旧进程可能持有文件句柄；下次启动时再次清理。
            skipped.append(session.name)
    return skipped
