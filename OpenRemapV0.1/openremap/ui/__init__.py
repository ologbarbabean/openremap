"""Frontend registry.

A frontend is any module runnable with `python -m <module>` that uses
openremap.service.RemapService. The tray's "Settings" item opens the one named by the
"ui" key in config.json: a short name from FRONTENDS, or a full module path, so a
third-party frontend works without changing this file.
"""
FRONTENDS = {
    "tk": "openremap.ui.tk",
}


def module_for(name: str) -> str:
    return FRONTENDS.get(name, name)


def launch(name: str = None):
    from ..core import config, instance
    if name is None:
        try:
            name = config.load().get("ui") or config.DEFAULT_UI
        except config.ConfigError:
            name = config.DEFAULT_UI
    return instance.launch_module(module_for(name))
