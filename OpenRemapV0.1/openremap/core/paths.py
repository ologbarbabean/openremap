"""File locations and small OS helpers shared by the backend."""
import os
import subprocess
import sys
from pathlib import Path

APP_NAME = "OpenRemap"
PACKAGE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = PACKAGE_DIR.parent
BUILTIN_DEVICES_DIR = PACKAGE_DIR / "devices"


def data_dir() -> Path:
    """Per-user data folder. Override with the OPENREMAP_HOME environment variable."""
    override = os.environ.get("OPENREMAP_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "openremap"
    base.mkdir(parents=True, exist_ok=True)
    return base


def user_devices_dir() -> Path:
    d = data_dir() / "devices"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return data_dir() / "config.json"


def pause_flag_path() -> Path:
    return data_dir() / "paused.flag"


def log_path() -> Path:
    return data_dir() / "openremap.log"


def open_path(path) -> None:
    """Open a file or folder with the OS default handler."""
    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - local user action
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def gui_python() -> str:
    """Python executable for background processes (pythonw on Windows: no console window)."""
    exe = sys.executable
    if sys.platform == "win32" and exe.lower().endswith("python.exe"):
        candidate = exe[: -len("python.exe")] + "pythonw.exe"
        if os.path.exists(candidate):
            return candidate
    return exe
