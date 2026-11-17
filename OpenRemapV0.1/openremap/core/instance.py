"""Engine single-instance lock, pause flag, and launching background processes."""
import subprocess
import sys

from .paths import PROJECT_ROOT, gui_python, pause_flag_path

MUTEX_NAME = "Local\\OpenRemapEngine"
_mutex = None


def _kernel32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k.OpenMutexW.restype = wintypes.HANDLE
    k.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return ctypes, k


def acquire_engine_lock() -> bool:
    """False if another engine is already running (two engines would fire every action twice)."""
    global _mutex
    if sys.platform != "win32":
        return True
    ctypes, k = _kernel32()
    _mutex = k.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def engine_running():
    """True/False on Windows, None where we can't tell."""
    if sys.platform != "win32":
        return None
    _, k = _kernel32()
    handle = k.OpenMutexW(0x00100000, False, MUTEX_NAME)  # SYNCHRONIZE
    if handle:
        k.CloseHandle(handle)
        return True
    return False


def is_paused() -> bool:
    return pause_flag_path().exists()


def set_paused(paused: bool) -> None:
    flag = pause_flag_path()
    if paused:
        flag.write_text("paused\n", encoding="utf-8")
    elif flag.exists():
        flag.unlink()


def launch_module(module: str, *args: str) -> subprocess.Popen:
    """Start `python -m module` in the background (no console window on Windows)."""
    return subprocess.Popen([gui_python(), "-m", module, *args], cwd=str(PROJECT_ROOT))
