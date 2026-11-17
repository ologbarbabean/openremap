"""The background engine: reads device reports and runs bound actions.

Config and device profile files are re-read automatically when they change, so any
frontend just saves files (through the service) and the engine picks them up.
"""
import logging
import queue
import threading
import time

from . import actions, config as cfgmod, devices as devmod, foreground, instance
from .paths import config_path

log = logging.getLogger("openremap.engine")


class Engine:
    def __init__(self, on_status=None):
        self.on_status = on_status
        self.status = "Starting..."
        self.config_error = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._config = cfgmod.default_config()
        self._devices = {}
        self._cfg_mtime = object()  # forces first load
        self._dev_sig = None
        self._runners = {}
        self._retry_after = {}
        self._connected = set()
        self._actions = queue.Queue()
        self._hid_warned = False

    # ---- lifecycle ------------------------------------------------------
    def start(self):
        threading.Thread(target=self._dispatch_loop, name="actions", daemon=True).start()
        threading.Thread(target=self._supervise_loop, name="supervisor", daemon=True).start()

    def stop(self):
        self._stop.set()
        self._actions.put(None)

    def refresh_status(self):
        self._update_status()

    # ---- supervision ------------------------------------------------------
    def _supervise_loop(self):
        while not self._stop.is_set():
            try:
                self._reload_config()
                self._reload_devices()
                self._start_runners()
            except Exception:
                log.exception("Supervisor error")
            self._update_status()
            self._stop.wait(1.0)

    def _reload_config(self):
        path = config_path()
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            mtime = None
        if mtime is not None and mtime == self._cfg_mtime:
            return
        try:
            cfg = cfgmod.load()
        except cfgmod.ConfigError as e:
            if self.config_error != str(e):
                log.error("Config error, keeping previous settings: %s", e)
            self.config_error = str(e)
            self._cfg_mtime = mtime
            return
        with self._lock:
            self._config = cfg
        self.config_error = None
        try:
            self._cfg_mtime = path.stat().st_mtime
        except OSError:
            self._cfg_mtime = None
        log.info("Config loaded: %s", ", ".join(p["name"] for p in cfg["profiles"]))

    def _reload_devices(self):
        sig = devmod.signature()
        if sig == self._dev_sig:
            return
        self._dev_sig = sig
        devs, errors = devmod.load_all()
        for e in errors:
            log.warning("Bad device profile %s", e)
        with self._lock:
            self._devices = devs
        log.info("Device profiles: %s", ", ".join(sorted(devs)) or "none")

    def _start_runners(self):
        try:
            import hid
        except ImportError:
            if not self._hid_warned:
                log.error("hidapi is not installed: pip install hidapi")
                self._hid_warned = True
            return
        infos = hid.enumerate()
        now = time.monotonic()
        with self._lock:
            devices = list(self._devices.values())
        for dev in devices:
            t = self._runners.get(dev.id)
            if (t and t.is_alive()) or self._retry_after.get(dev.id, 0) > now:
                continue
            info = next((i for i in infos if dev.matches(i)), None)
            if info is None:
                continue
            t = threading.Thread(target=self._run_device, args=(dev, info["path"]),
                                 name="dev-" + dev.id, daemon=True)
            self._runners[dev.id] = t
            t.start()

    def _update_status(self):
        n = len(self._connected)
        text = ("%d device%s active" % (n, "" if n == 1 else "s")) if n else "No known devices connected"
        if self.config_error:
            text = "Config error (see log)"
        if instance.is_paused():
            text = "Paused - " + text
        if text != self.status:
            self.status = text
            log.info("Status: %s", text)
            if self.on_status:
                try:
                    self.on_status(text)
                except Exception:
                    log.exception("Status callback failed")

    # ---- device reading --------------------------------------------------
    def _run_device(self, dev, path):
        import hid
        h = hid.device()
        try:
            h.open_path(path)
        except (OSError, IOError) as e:
            log.warning("Can't open %s: %s (retrying in 10 s)", dev.name, e)
            self._retry_after[dev.id] = time.monotonic() + 10
            return
        log.info("Connected: %s", dev.name)
        self._connected.add(dev.id)
        held = set()
        try:
            # stop when quitting or when the profile file was edited (a new runner takes over)
            while not self._stop.is_set() and self._devices.get(dev.id) is dev:
                report = h.read(256, 200)
                if not report:
                    continue
                now = dev.pressed(report)
                if now is None:
                    continue
                for key in sorted(now - held):
                    self._on_press(dev, key)
                held = now
        except (OSError, IOError) as e:
            log.warning("Lost %s: %s", dev.name, e)
        finally:
            self._connected.discard(dev.id)
            try:
                h.close()
            except Exception:
                pass
            log.info("Disconnected: %s", dev.name)

    def _on_press(self, dev, key):
        if instance.is_paused():
            log.info("%s %s pressed (paused)", dev.id, key)
            return
        app = foreground.foreground_app()
        with self._lock:
            action = cfgmod.resolve_action(self._config, dev.id, key, app)
        if action is None:
            log.info("%s %s pressed in %s (not bound)", dev.id, key, app or "?")
            return
        log.info("%s %s pressed in %s -> %s", dev.id, key, app or "?", actions.describe(action))
        self._actions.put(action)

    def _dispatch_loop(self):
        # one worker keeps actions in press order without blocking device reads
        while True:
            action = self._actions.get()
            if action is None:
                return
            try:
                actions.run(action)
            except Exception:
                log.exception("Action failed: %s", actions.describe(action))
