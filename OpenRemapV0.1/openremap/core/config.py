"""User configuration: profiles of key bindings, optionally tied to apps.

config.json:
    {
      "version": 1,
      "ui": "tk",
      "profiles": [
        {"name": "Default", "apps": [], "bindings": {"<device id>": {"G3": {action}}}},
        {"name": "Remote desktop", "apps": ["msrdc.exe"], "bindings": {...}}
      ]
    }

The first profile is always "Default". When a key is pressed, the first other profile
whose `apps` contains the focused program's exe name is used; keys it doesn't set fall
back to Default. An action of {"type": "none"} explicitly disables a key.
"""
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

from .paths import config_path

DEFAULT_PROFILE = "Default"
DEFAULT_UI = "tk"


class ConfigError(Exception):
    pass


def default_config() -> dict:
    return {"version": 1, "ui": DEFAULT_UI, "profiles": [_new_profile(DEFAULT_PROFILE)]}


def _new_profile(name, apps=None) -> dict:
    return {"name": name, "apps": list(apps or []), "bindings": {}}


def clean_apps(apps) -> list:
    out = []
    for a in apps or []:
        a = str(a).strip().strip('"').lower()
        a = a.replace("\\", "/").rsplit("/", 1)[-1]  # accept full paths, keep the exe name
        if a and a not in out:
            out.append(a)
    return out


def normalize(cfg: dict) -> dict:
    profiles = [p for p in cfg.get("profiles", []) if isinstance(p, dict) and p.get("name")]
    default = next((p for p in profiles if p["name"] == DEFAULT_PROFILE), None) or _new_profile(DEFAULT_PROFILE)
    others = [p for p in profiles if p is not default]
    for p in [default] + others:
        p["apps"] = clean_apps(p.get("apps"))
        if not isinstance(p.get("bindings"), dict):
            p["bindings"] = {}
    default["apps"] = []
    return {"version": 1, "ui": str(cfg.get("ui") or DEFAULT_UI), "profiles": [default] + others}


def load(path: Optional[Path] = None) -> dict:
    path = Path(path or config_path())
    if not path.exists():
        cfg = default_config()
        save(cfg, path)
        return cfg
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ConfigError("%s: %s" % (path, e))
    if not isinstance(data, dict):
        raise ConfigError("%s: top level must be an object" % path)
    return normalize(data)


def save(cfg: dict, path: Optional[Path] = None) -> None:
    """Atomic write so the engine never reads a half-written file."""
    path = Path(path or config_path())
    text = json.dumps(normalize(cfg), indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".config-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    for attempt in range(5):  # Windows: retry if a reader briefly holds the file
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 4:
                os.unlink(tmp)
                raise
            time.sleep(0.05)


def get_profile(cfg: dict, name: str) -> Optional[dict]:
    return next((p for p in cfg["profiles"] if p["name"] == name), None)


def profile_for_app(cfg: dict, app: Optional[str]) -> dict:
    if app:
        app = app.lower()
        for p in cfg["profiles"][1:]:
            if app in p["apps"]:
                return p
    return cfg["profiles"][0]


def resolve_action(cfg: dict, device_id: str, key: str, app: Optional[str]) -> Optional[dict]:
    """Action to run for a key press, or None if the key is unbound."""
    default = cfg["profiles"][0]
    chosen = profile_for_app(cfg, app)
    for p in ([chosen] if chosen is not default else []) + [default]:
        action = p["bindings"].get(device_id, {}).get(key)
        if action is not None:
            return action
    return None
