"""Learn mode: discover which HID report bits a key toggles.

LearnSession is pure logic (testable without hardware). LearnRecorder wraps it with a
background thread that reads every HID interface of one device.

How detection works:
  1. Quiet period: the user keeps hands off; any byte that changes is marked noisy.
  2. On a report, bits that rose since the previous report on that stream (same
     interface + report id) become candidates. Byte 0 is skipped (report id).
  3. A candidate is confirmed when a later report on the same stream clears it, i.e.
     the key was released. This filters out header bytes that are always set.
"""
import re
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .devices import DeviceProfile, KeyDef, slugify

Iface = Tuple[int, int, int]  # (usage_page, usage, interface_number)


@dataclass(frozen=True)
class Capture:
    iface: Iface
    byte: int
    mask: int
    report_id: int


class LearnSession:
    def __init__(self, quiet_seconds: float = 2.0, clock=time.monotonic):
        self.quiet_seconds = quiet_seconds
        self.clock = clock
        self.started = None
        self._prev = {}
        self.noisy = {}
        self._armed = False
        self._pending = None  # (stream, [(byte, mask), ...])

    def start(self):
        self.started = self.clock()
        self._prev.clear()
        self.noisy.clear()
        self._pending = None

    @property
    def in_quiet(self) -> bool:
        return self.started is None or self.clock() - self.started < self.quiet_seconds

    @property
    def armed(self) -> bool:
        return self._armed

    def arm(self):
        self._armed = True
        self._pending = None

    def disarm(self):
        self._armed = False
        self._pending = None

    def feed(self, iface: Iface, report) -> Optional[Capture]:
        report = bytes(report)
        if not report:
            return None
        rid = report[0]
        stream = (iface, rid)
        prev = self._prev.get(stream)
        self._prev[stream] = report

        if self.in_quiet:
            if prev is not None:
                noisy = self.noisy.setdefault(iface, set())
                noisy.update(i for i in range(min(len(prev), len(report))) if prev[i] != report[i])
            return None
        if not self._armed:
            return None

        if self._pending and self._pending[0] == stream:
            confirmed = [(b, m) for b, m in self._pending[1] if b < len(report) and not report[b] & m]
            if confirmed:
                byte, mask = confirmed[0]
                self.disarm()
                return Capture(iface, byte, mask, rid)

        noisy = self.noisy.get(iface, set())
        base = prev if prev is not None else bytes(len(report))
        rising = []
        for i in range(1, len(report)):
            if i in noisy:
                continue
            bits = report[i] & ~(base[i] if i < len(base) else 0) & 0xFF
            for bit in range(8):
                if bits & (1 << bit):
                    rising.append((i, 1 << bit))
        if rising:
            if self._pending is None:
                self._pending = (stream, rising)
            elif self._pending[0] == stream:
                self._pending[1].extend(r for r in rising if r not in self._pending[1])
        return None


def next_key_name(name: str) -> str:
    m = re.match(r"^(.*?)(\d+)$", name)
    return "%s%d" % (m.group(1), int(m.group(2)) + 1) if m else name + "2"


def iface_dict(iface: Iface) -> dict:
    return {"usage_page": iface[0], "usage": iface[1], "interface": iface[2]}


class LearnRecorder:
    """Background capture for one device. All public methods are thread-safe."""

    def __init__(self, vid: int, pid: int, quiet_seconds: float = 2.0, product: str = ""):
        self.vid, self.pid, self.product = vid, pid, product
        self.session = LearnSession(quiet_seconds)
        self.captures: List[dict] = []  # {"name": str, "capture": Capture}
        self.next_name = "G1"
        self.opened = 0
        self.error = None
        self._events = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    # ---- lifecycle ------------------------------------------------------
    def start(self):
        self.session.start()
        self.session.arm()
        self._thread = threading.Thread(target=self._run, name="learn", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        try:
            import hid
        except ImportError:
            self.error = "The hidapi package isn't installed (pip install hidapi)."
            return
        handles = []
        for info in hid.enumerate(self.vid, self.pid):
            h = hid.device()
            try:
                h.open_path(info["path"])
                h.set_nonblocking(1)
                handles.append(((info.get("usage_page", 0), info.get("usage", 0),
                                 info.get("interface_number", -1)), h))
            except (OSError, IOError):
                pass
        self.opened = len(handles)
        if not handles:
            self.error = "Couldn't open any interface of this device. Close other software that controls it and try again."
        while handles and not self._stop.is_set():
            for item in list(handles):
                iface, h = item
                try:
                    data = h.read(256)
                except (OSError, IOError):
                    handles.remove(item)
                    h.close()
                    continue
                if data:
                    self.feed(iface, data)
            time.sleep(0.002)
        for _, h in handles:
            h.close()

    # ---- capture logic ----------------------------------------------------
    def feed(self, iface: Iface, report) -> None:
        with self._lock:
            cap = self.session.feed(iface, report)
            if cap is not None:
                self._accept(cap)
                self.session.arm()

    def _accept(self, cap: Capture):
        if self.captures and self.captures[0]["capture"].iface != cap.iface:
            self._events.append({"type": "wrong_interface", "message":
                "That key reports on a different interface (%s). One profile covers one interface; "
                "save this profile, then learn another for that key." % _iface_text(cap.iface)})
            return
        for c in self.captures:
            if (c["capture"].byte, c["capture"].mask) == (cap.byte, cap.mask):
                self._events.append({"type": "duplicate", "message": "Already captured as %s." % c["name"]})
                return
        name = self._unique(self.next_name)
        self.captures.append({"name": name, "capture": cap})
        self.next_name = next_key_name(name)
        self._events.append({"type": "captured", "message": "Captured %s." % name, "name": name})

    def _unique(self, name):
        names = {c["name"] for c in self.captures}
        while name in names:
            name = next_key_name(name)
        return name

    # ---- frontend helpers ---------------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            events, self._events = self._events, []
            if self.error:
                phase = "error"
            elif self.session.in_quiet:
                phase = "quiet"
            else:
                phase = "listening"
            return {
                "phase": phase,
                "error": self.error,
                "opened": self.opened,
                "next_name": self.next_name,
                "events": events,
                "captures": [{"name": c["name"], "byte": c["capture"].byte, "mask": c["capture"].mask,
                              "iface": iface_dict(c["capture"].iface)} for c in self.captures],
            }

    def set_next_name(self, name: str):
        with self._lock:
            self.next_name = name.strip() or "G1"

    def rename(self, index: int, name: str):
        with self._lock:
            name = name.strip()
            if not name:
                raise ValueError("Key name can't be empty")
            if any(c["name"] == name for i, c in enumerate(self.captures) if i != index):
                raise ValueError("Another key is already called %s" % name)
            self.captures[index]["name"] = name

    def remove(self, index: int):
        with self._lock:
            del self.captures[index]

    def build_profile(self, name: str) -> DeviceProfile:
        with self._lock:
            if not self.captures:
                raise ValueError("Capture at least one key first")
            iface = self.captures[0]["capture"].iface
            rids = {c["capture"].report_id for c in self.captures}
            match = {0: rids.pop()} if len(rids) == 1 and 0 not in rids else {}
            return DeviceProfile(
                id=slugify(name), name=name, vid=self.vid, pid=self.pid,
                usage_page=iface[0], usage=iface[1], interface=iface[2], match=match,
                keys=[KeyDef(c["name"], c["capture"].byte, c["capture"].mask) for c in self.captures],
            )


def _iface_text(iface: Iface) -> str:
    return "usage page 0x%04X, usage 0x%04X, interface %s" % iface
