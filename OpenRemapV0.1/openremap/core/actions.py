"""Action types: validation, descriptions, metadata for frontends, and execution."""
import logging
import shlex
import subprocess
import sys

log = logging.getLogger("openremap.actions")

# Metadata frontends use to build their editors generically. Field kinds:
# "hotkey" (text like "ctrl+shift+m"), "string", "bool", "command" (program + args).
ACTION_TYPES = [
    {"type": "hotkey", "label": "Send hotkey",
     "help": "Presses a key combination.",
     "fields": [{"name": "keys", "kind": "hotkey", "label": "Keys",
                 "hint": "Join keys with +, e.g. win+shift+s, ctrl+v, enter, f13"}]},
    {"type": "text", "label": "Type text",
     "help": "Types the text as if you typed it (plain ASCII characters).",
     "fields": [{"name": "text", "kind": "string", "label": "Text"},
                {"name": "enter", "kind": "bool", "label": "Press Enter afterwards", "default": False}]},
    {"type": "run", "label": "Run program",
     "help": "Starts a program, script or document.",
     "fields": [{"name": "command", "kind": "command", "label": "Command",
                 "hint": 'Program and arguments, e.g. notepad.exe or "C:\\Tools\\my app.exe" --flag'}]},
    {"type": "none", "label": "Do nothing",
     "help": "Disables the key (useful to override the Default profile for one app).", "fields": []},
    {"type": "log", "label": "Log only",
     "help": "Only writes the press to the log. Handy for testing.", "fields": []},
]
TYPE_NAMES = {t["type"] for t in ACTION_TYPES}

_pg = None


def _pyautogui():
    global _pg
    if _pg is None:
        import pyautogui
        pyautogui.FAILSAFE = False  # otherwise actions fail while the mouse is in a screen corner
        pyautogui.PAUSE = 0
        _pg = pyautogui
    return _pg


def parse_hotkey(value) -> list:
    keys = value if isinstance(value, list) else str(value or "").replace(" ", "").split("+")
    keys = [str(k).strip().lower() for k in keys if str(k).strip()]
    if not keys:
        raise ValueError("Enter at least one key, e.g. ctrl+v")
    try:
        valid = set(_pyautogui().KEYBOARD_KEYS)
    except Exception:  # pyautogui missing or no display: skip name checking
        valid = None
    if valid:
        bad = [k for k in keys if k not in valid]
        if bad:
            raise ValueError("Unknown key name(s): %s" % ", ".join(bad))
    return keys


def normalize(action: dict) -> dict:
    """Validate an action from a frontend and return its canonical form."""
    if not isinstance(action, dict):
        raise ValueError("Action must be an object")
    kind = action.get("type")
    if kind not in TYPE_NAMES:
        raise ValueError("Unknown action type %r" % kind)
    if kind == "hotkey":
        return {"type": "hotkey", "keys": parse_hotkey(action.get("keys"))}
    if kind == "text":
        text = str(action.get("text") or "")
        if not text:
            raise ValueError("Enter the text to type")
        return {"type": "text", "text": text, "enter": bool(action.get("enter"))}
    if kind == "run":
        cmd = action.get("command") or action.get("args")
        if isinstance(cmd, list):
            cmd = subprocess.list2cmdline([str(c) for c in cmd])
        cmd = str(cmd or "").strip()
        if not cmd:
            raise ValueError("Enter a program to run")
        return {"type": "run", "command": cmd}
    return {"type": kind}


def describe(action: dict) -> str:
    if not action:
        return "(not set)"
    kind = action.get("type")
    if kind == "hotkey":
        return "Hotkey: " + "+".join(action.get("keys", []))
    if kind == "text":
        text = action.get("text", "")
        short = text if len(text) <= 40 else text[:37] + "..."
        return 'Type: "%s"%s' % (short, " + Enter" if action.get("enter") else "")
    if kind == "run":
        return "Run: " + str(action.get("command") or action.get("args"))
    if kind == "none":
        return "Do nothing"
    if kind == "log":
        return "Log only"
    return "Unknown action %r" % kind


def run(action: dict) -> None:
    kind = action.get("type", "log")
    if kind in ("none", "log"):
        return
    if kind == "hotkey":
        _pyautogui().hotkey(*action["keys"])
    elif kind == "text":
        pg = _pyautogui()
        pg.write(action.get("text", ""), interval=0.005)
        if action.get("enter"):
            pg.press("enter")
    elif kind == "run":
        cmd = action.get("command") or action.get("args")
        if isinstance(cmd, str) and sys.platform != "win32":
            cmd = shlex.split(cmd)
        subprocess.Popen(cmd, cwd=action.get("cwd") or None)
    else:
        raise ValueError("Unknown action type %r" % kind)
