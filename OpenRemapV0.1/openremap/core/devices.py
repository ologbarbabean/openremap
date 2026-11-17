"""Device profiles: how to read extra keys from one HID interface of one keyboard.

A profile is a small, shareable JSON file:

    {
      "format": 1,
      "name": "Corsair K95 RGB Platinum XT",
      "vid": "0x1B1C", "pid": "0x1B89",
      "usage_page": "0xFF42", "usage": "0x0002", "interface": 2,
      "match": {"1": "0x02"},
      "keys": [{"name": "G1", "byte": 18, "mask": "0x08"}, ...]
    }

`match` (optional) lists report bytes that must have a given value for the report to
count as a key report. Each key is "pressed" while (report[byte] & mask) != 0.
Built-in profiles live in openremap/devices; user profiles in <data dir>/devices and
override built-ins with the same id (file name).
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .paths import BUILTIN_DEVICES_DIR, user_devices_dir

FORMAT_VERSION = 1


def _int(value) -> int:
    return int(value, 0) if isinstance(value, str) else int(value)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "device"


@dataclass
class KeyDef:
    name: str
    byte: int
    mask: int


@dataclass(eq=False)
class DeviceProfile:
    id: str
    name: str
    vid: int
    pid: int
    usage_page: int
    usage: int
    interface: int = -1
    match: Dict[int, int] = field(default_factory=dict)
    keys: List[KeyDef] = field(default_factory=list)
    source: str = "user"  # "built-in" or "user"
    path: Optional[Path] = None

    # ---- runtime -------------------------------------------------------
    def matches(self, info: dict) -> bool:
        """True if a hid.enumerate() entry is the interface this profile reads."""
        if info.get("vendor_id") != self.vid or info.get("product_id") != self.pid:
            return False
        if info.get("usage_page") != self.usage_page or info.get("usage") != self.usage:
            return False
        iface = info.get("interface_number", -1)
        if self.interface >= 0 and iface is not None and iface >= 0 and iface != self.interface:
            return False
        return True

    def pressed(self, report) -> Optional[Set[str]]:
        """Names of keys held in this report, or None if it isn't a key report."""
        for idx, value in self.match.items():
            if idx >= len(report) or report[idx] != value:
                return None
        return {k.name for k in self.keys if k.byte < len(report) and report[k.byte] & k.mask}

    # ---- serialisation -------------------------------------------------
    def to_json(self) -> dict:
        return {
            "format": FORMAT_VERSION,
            "name": self.name,
            "vid": "0x%04X" % self.vid,
            "pid": "0x%04X" % self.pid,
            "usage_page": "0x%04X" % self.usage_page,
            "usage": "0x%04X" % self.usage,
            "interface": self.interface,
            "match": {str(k): "0x%02X" % v for k, v in sorted(self.match.items())},
            "keys": [{"name": k.name, "byte": k.byte, "mask": "0x%02X" % k.mask} for k in self.keys],
        }

    def summary(self) -> dict:
        """JSON-friendly description for frontends."""
        return {
            "id": self.id,
            "name": self.name,
            "vid": self.vid,
            "pid": self.pid,
            "usage_page": self.usage_page,
            "usage": self.usage,
            "interface": self.interface,
            "keys": [k.name for k in self.keys],
            "source": self.source,
            "file": str(self.path) if self.path else None,
        }

    @classmethod
    def from_json(cls, data: dict, id: str, source: str = "user", path: Optional[Path] = None):
        keys = []
        seen = set()
        for k in data.get("keys", []):
            key = KeyDef(str(k["name"]), int(k["byte"]), _int(k["mask"]))
            if not key.name or key.name in seen:
                raise ValueError("duplicate or empty key name %r" % key.name)
            if key.mask <= 0 or key.mask > 0xFF or key.byte < 0:
                raise ValueError("bad byte/mask for key %r" % key.name)
            seen.add(key.name)
            keys.append(key)
        return cls(
            id=id,
            name=str(data.get("name") or id),
            vid=_int(data["vid"]),
            pid=_int(data["pid"]),
            usage_page=_int(data["usage_page"]),
            usage=_int(data["usage"]),
            interface=int(data.get("interface", -1)),
            match={int(k): _int(v) for k, v in (data.get("match") or {}).items()},
            keys=keys,
            source=source,
            path=path,
        )


def _profile_files():
    for source, folder in (("built-in", BUILTIN_DEVICES_DIR), ("user", user_devices_dir())):
        if folder.is_dir():
            for p in sorted(folder.glob("*.json")):
                yield source, p


def load_all() -> Tuple[Dict[str, DeviceProfile], List[str]]:
    """All device profiles by id (user files override built-ins), plus load errors."""
    profiles: Dict[str, DeviceProfile] = {}
    errors: List[str] = []
    for source, path in _profile_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            profiles[path.stem] = DeviceProfile.from_json(data, path.stem, source, path)
        except (OSError, ValueError, KeyError, TypeError) as e:
            errors.append("%s: %s" % (path, e))
    return profiles, errors


def signature() -> tuple:
    """Cheap fingerprint of all profile files, for change detection."""
    sig = []
    for _, p in _profile_files():
        try:
            sig.append((str(p), p.stat().st_mtime))
        except OSError:
            pass
    return tuple(sig)


def save_user(profile: DeviceProfile) -> Path:
    path = user_devices_dir() / ("%s.json" % profile.id)
    path.write_text(json.dumps(profile.to_json(), indent=2) + "\n", encoding="utf-8")
    profile.path = path
    profile.source = "user"
    return path


def delete_user(device_id: str) -> bool:
    path = user_devices_dir() / ("%s.json" % device_id)
    if path.exists():
        path.unlink()
        return True
    return False
