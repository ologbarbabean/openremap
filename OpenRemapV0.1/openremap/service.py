"""The frontend API. Every UI (Tk, HTML, CLI, ...) talks to OpenRemap only through here.

Rules that keep frontends swappable:
  * Arguments and return values are plain JSON types (dict, list, str, int, bool, None).
  * User-facing problems raise ApiError(message, code); `code` lets a UI react
    (e.g. "exists" -> ask before overwriting).
  * Nothing here blocks for long; long-running work (learn mode) runs in the background
    and is polled, which suits both a Tk timer and an HTTP fetch loop.
  * `dispatch(method, params)` exposes the public methods by name, so a web/IPC
    frontend is a thin adapter. See docs/FRONTENDS.md.

The service writes config and device files; the running engine notices the changes,
so no direct link between a frontend and the engine is needed.
"""
import itertools
import threading

from .core import actions, config as cfgmod, devices as devmod, foreground, instance, paths
from .core.learn import LearnRecorder

PUBLIC_METHODS = (
    "list_profiles", "create_profile", "rename_profile", "delete_profile", "set_profile_apps",
    "foreground_app",
    "list_devices", "delete_device", "list_hid_devices",
    "get_bindings", "set_binding", "clear_binding",
    "action_types", "validate_action", "describe_action",
    "start_learning", "learn_poll", "learn_set_next_name", "learn_rename_key",
    "learn_remove_key", "save_learned_device", "stop_learning",
    "engine_status", "set_paused", "start_engine", "open_folder",
)


class ApiError(Exception):
    def __init__(self, message, code="error"):
        super().__init__(message)
        self.message = message
        self.code = code

    def to_json(self):
        return {"error": self.message, "code": self.code}


class RemapService:
    def __init__(self):
        self._sessions = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    # ---- generic entry point --------------------------------------------------
    def dispatch(self, method, params=None):
        if method not in PUBLIC_METHODS:
            raise ApiError("Unknown method %r" % method, "unknown_method")
        try:
            return getattr(self, method)(**(params or {}))
        except TypeError as e:
            raise ApiError("Bad parameters for %s: %s" % (method, e), "bad_params")

    # ---- internals ----------------------------------------------------------
    def _cfg(self):
        try:
            return cfgmod.load()
        except cfgmod.ConfigError as e:
            raise ApiError("The config file is invalid: %s" % e, "bad_config")

    def _profile(self, cfg, name):
        p = cfgmod.get_profile(cfg, name)
        if p is None:
            raise ApiError("No profile named %r" % name, "not_found")
        return p

    def _device(self, device_id):
        devs, _ = devmod.load_all()
        dev = devs.get(device_id)
        if dev is None:
            raise ApiError("No device profile %r" % device_id, "not_found")
        return dev

    # ---- profiles -------------------------------------------------------------
    def list_profiles(self):
        cfg = self._cfg()
        return [{"name": p["name"], "apps": list(p["apps"]), "is_default": i == 0}
                for i, p in enumerate(cfg["profiles"])]

    def create_profile(self, name, apps=None):
        name = str(name or "").strip()
        if not name:
            raise ApiError("Enter a profile name", "invalid")
        cfg = self._cfg()
        if cfgmod.get_profile(cfg, name):
            raise ApiError("A profile called %r already exists" % name, "exists")
        cfg["profiles"].append({"name": name, "apps": cfgmod.clean_apps(apps), "bindings": {}})
        cfgmod.save(cfg)
        return self.list_profiles()

    def rename_profile(self, name, new_name):
        new_name = str(new_name or "").strip()
        cfg = self._cfg()
        p = self._profile(cfg, name)
        if p is cfg["profiles"][0]:
            raise ApiError("The Default profile can't be renamed", "invalid")
        if not new_name:
            raise ApiError("Enter a profile name", "invalid")
        if new_name != name and cfgmod.get_profile(cfg, new_name):
            raise ApiError("A profile called %r already exists" % new_name, "exists")
        p["name"] = new_name
        cfgmod.save(cfg)
        return self.list_profiles()

    def delete_profile(self, name):
        cfg = self._cfg()
        p = self._profile(cfg, name)
        if p is cfg["profiles"][0]:
            raise ApiError("The Default profile can't be deleted", "invalid")
        cfg["profiles"].remove(p)
        cfgmod.save(cfg)
        return self.list_profiles()

    def set_profile_apps(self, name, apps):
        cfg = self._cfg()
        p = self._profile(cfg, name)
        if p is cfg["profiles"][0]:
            raise ApiError("The Default profile applies everywhere; it has no app list", "invalid")
        p["apps"] = cfgmod.clean_apps(apps)
        conflicts = []
        for app in p["apps"]:
            first = cfgmod.profile_for_app(cfg, app)
            if first is not p:
                conflicts.append({"app": app, "profile": first["name"]})
        cfgmod.save(cfg)
        return {"apps": p["apps"], "conflicts": conflicts}

    def foreground_app(self):
        return foreground.foreground_app()

    # ---- devices --------------------------------------------------------------
    def list_devices(self):
        devs, errors = devmod.load_all()
        try:
            import hid
            infos = hid.enumerate()
        except Exception:
            infos = None
        out = []
        for dev in sorted(devs.values(), key=lambda d: d.name.lower()):
            item = dev.summary()
            item["connected"] = None if infos is None else any(dev.matches(i) for i in infos)
            out.append(item)
        return out

    def delete_device(self, device_id):
        dev = self._device(device_id)
        if dev.source != "user":
            raise ApiError("Built-in profiles can't be deleted (learn one with the same name to override it)", "invalid")
        devmod.delete_user(device_id)
        return self.list_devices()

    def list_hid_devices(self):
        try:
            import hid
        except ImportError:
            raise ApiError("The hidapi package isn't installed (pip install hidapi)", "missing_dependency")
        seen = {}
        for info in hid.enumerate():
            key = (info["vendor_id"], info["product_id"])
            if key in seen:
                continue
            product = (info.get("product_string") or "").strip() or "Unknown device"
            maker = (info.get("manufacturer_string") or "").strip()
            seen[key] = {
                "vid": key[0], "pid": key[1], "product": product, "manufacturer": maker,
                "label": "%s%s  [%04X:%04X]" % (product, " - " + maker if maker and maker.lower() not in product.lower() else "", key[0], key[1]),
            }
        return sorted(seen.values(), key=lambda d: d["label"].lower())

    # ---- bindings -------------------------------------------------------------
    def get_bindings(self, profile, device_id):
        cfg = self._cfg()
        p = self._profile(cfg, profile)
        default = cfg["profiles"][0]
        dev = self._device(device_id)
        rows = []
        for key in dev.keys:
            own = p["bindings"].get(device_id, {}).get(key.name)
            inherited = None
            if own is None and p is not default:
                inherited = default["bindings"].get(device_id, {}).get(key.name)
            effective = own if own is not None else inherited
            if own is not None:
                display = actions.describe(own)
            elif inherited is not None:
                display = actions.describe(inherited) + "   (from Default)"
            else:
                display = "(not set)"
            rows.append({"key": key.name, "own": own is not None, "action": own,
                         "effective": effective, "inherited_from": "Default" if inherited is not None else None,
                         "display": display})
        return rows

    def set_binding(self, profile, device_id, key, action):
        dev = self._device(device_id)
        if key not in {k.name for k in dev.keys}:
            raise ApiError("%s has no key %r" % (dev.name, key), "not_found")
        action = self.validate_action(action)
        cfg = self._cfg()
        p = self._profile(cfg, profile)
        p["bindings"].setdefault(device_id, {})[key] = action
        cfgmod.save(cfg)
        return action

    def clear_binding(self, profile, device_id, key):
        cfg = self._cfg()
        p = self._profile(cfg, profile)
        dev_bindings = p["bindings"].get(device_id, {})
        dev_bindings.pop(key, None)
        if not dev_bindings:
            p["bindings"].pop(device_id, None)
        cfgmod.save(cfg)
        return True

    def action_types(self):
        return [dict(t, fields=[dict(f) for f in t["fields"]]) for t in actions.ACTION_TYPES]

    def validate_action(self, action):
        try:
            return actions.normalize(action)
        except ValueError as e:
            raise ApiError(str(e), "invalid")

    def describe_action(self, action):
        return actions.describe(action)

    # ---- learn mode -----------------------------------------------------------
    def start_learning(self, vid, pid, product="", quiet_seconds=2.0):
        rec = LearnRecorder(int(vid), int(pid), quiet_seconds=float(quiet_seconds), product=product)
        with self._lock:
            sid = "learn-%d" % next(self._ids)
            self._sessions[sid] = rec
        rec.start()
        return dict(rec.snapshot(), session=sid)

    def _rec(self, session):
        rec = self._sessions.get(session)
        if rec is None:
            raise ApiError("Learn session %r isn't active" % session, "not_found")
        return rec

    def learn_poll(self, session):
        return dict(self._rec(session).snapshot(), session=session)

    def learn_set_next_name(self, session, name):
        self._rec(session).set_next_name(str(name))
        return True

    def learn_rename_key(self, session, index, name):
        try:
            self._rec(session).rename(int(index), str(name))
        except (ValueError, IndexError) as e:
            raise ApiError(str(e), "invalid")
        return self.learn_poll(session)

    def learn_remove_key(self, session, index):
        try:
            self._rec(session).remove(int(index))
        except IndexError:
            raise ApiError("No key at position %s" % index, "invalid")
        return self.learn_poll(session)

    def save_learned_device(self, session, name, overwrite=False):
        name = str(name or "").strip()
        if not name:
            raise ApiError("Enter a name for the device profile", "invalid")
        try:
            profile = self._rec(session).build_profile(name)
        except ValueError as e:
            raise ApiError(str(e), "invalid")
        existing, _ = devmod.load_all()
        if profile.id in existing and not overwrite:
            src = existing[profile.id].source
            raise ApiError("A %s device profile called %r already exists. Replace it?" % (src, existing[profile.id].name), "exists")
        devmod.save_user(profile)
        return profile.summary()

    def stop_learning(self, session):
        with self._lock:
            rec = self._sessions.pop(session, None)
        if rec:
            rec.stop()
        return True

    # ---- engine ---------------------------------------------------------------
    def engine_status(self):
        return {"running": instance.engine_running(), "paused": instance.is_paused()}

    def set_paused(self, paused):
        instance.set_paused(bool(paused))
        return self.engine_status()

    def start_engine(self):
        if instance.engine_running():
            return self.engine_status()
        instance.launch_module("openremap")
        return self.engine_status()

    def open_folder(self, which="data"):
        targets = {"data": paths.data_dir(), "devices": paths.user_devices_dir(), "log": paths.log_path()}
        if which not in targets:
            raise ApiError("Unknown folder %r" % which, "invalid")
        paths.open_path(targets[which])
        return True
