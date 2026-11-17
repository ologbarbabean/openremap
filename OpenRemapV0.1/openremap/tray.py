"""Background app: runs the engine with a system tray icon.

    python -m openremap              tray icon + engine (use pythonw for no console)
    python -m openremap --console    engine only, logs to the console (debugging)
    python -m openremap --settings   open the settings frontend
"""
import argparse
import logging
import sys
import time
from logging.handlers import RotatingFileHandler

from .core import instance
from .core.engine import Engine
from .core.paths import data_dir, log_path, open_path

log = logging.getLogger("openremap")


def setup_logging(console: bool):
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(log_path(), maxBytes=512_000, backupCount=2, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)
    if console and sys.stderr:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(sh)


def make_icon_image(paused=False):
    from PIL import Image, ImageDraw
    fg = (25, 25, 25, 255)
    bg = (150, 150, 150, 255) if paused else (250, 190, 0, 255)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2, 2, 61, 61), radius=12, fill=bg)
    d.ellipse((13, 13, 51, 51), outline=fg, width=7)       # a bold "G"
    d.rectangle((33, 7, 56, 30), fill=bg)                   # open the top-right of the ring
    d.rectangle((32, 29, 51, 36), fill=fg)                  # the G's bar
    return img


def _show_error(text):
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "OpenRemap", 0x40)
    else:
        print(text, file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="openremap", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--console", action="store_true", help="run without the tray icon, log to the console")
    parser.add_argument("--settings", action="store_true", help="open the settings window and exit")
    args = parser.parse_args(argv)

    if args.settings:
        from . import ui
        ui.launch()
        return 0

    setup_logging(console=args.console)
    if not instance.acquire_engine_lock():
        log.warning("Another OpenRemap engine is already running; exiting.")
        if not args.console:
            _show_error("OpenRemap is already running. Look for its icon in the system tray.")
        return 1

    engine = Engine()
    if args.console:
        engine.start()
        log.info("Running in console mode. Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            engine.stop()
        return 0

    try:
        import pystray
    except ImportError:
        _show_error("The tray icon needs pystray and pillow:\n\npip install pystray pillow")
        return 1

    from . import ui

    def on_status(text):
        icon.title = "OpenRemap: " + text
        icon.icon = make_icon_image(paused=instance.is_paused())
        try:
            icon.update_menu()
        except Exception:
            pass

    def open_settings(icon_, item):
        ui.launch()

    def toggle_pause(icon_, item):
        instance.set_paused(not instance.is_paused())
        engine.refresh_status()

    def quit_app(icon_, item):
        engine.stop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(lambda item: engine.status, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Settings...", open_settings, default=True),
        pystray.MenuItem("Pause", toggle_pause, checked=lambda item: instance.is_paused()),
        pystray.MenuItem("Open log", lambda icon_, item: open_path(log_path())),
        pystray.MenuItem("Open data folder", lambda icon_, item: open_path(data_dir())),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon("openremap", make_icon_image(instance.is_paused()), "OpenRemap", menu)
    engine.on_status = on_status
    engine.start()
    log.info("OpenRemap started (tray).")
    icon.run()
    engine.stop()
    log.info("OpenRemap stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
