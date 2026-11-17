# Writing a frontend

OpenRemap is split into three layers:

```
openremap/core/      backend: engine, device profiles, config, actions, learn logic (no UI code)
openremap/service.py the frontend API: RemapService (plain JSON in and out)
openremap/ui/        frontends: ui/tk is the built-in one
```

A frontend only imports `openremap.service`. It never talks to the engine directly:
the service saves `config.json` and device profile files, and the running engine
reloads them within about a second.

## Rules the API follows

- Every argument and return value is a JSON type, so it can be sent over HTTP,
  a pipe, a WebSocket, and so on, unchanged.
- Problems the user should see raise `ApiError(message, code)`. `ApiError.to_json()`
  gives `{"error": ..., "code": ...}`. Useful codes: `exists` (ask before overwriting),
  `invalid`, `not_found`, `bad_config`, `missing_dependency`.
- Nothing blocks for long. Learn mode runs in the background and is polled.
- `service.dispatch(method, params)` calls any public method by name
  (see `PUBLIC_METHODS`), so an adapter needs no per-method code.

## Methods

| Area | Method | Returns |
|---|---|---|
| Profiles | `list_profiles()` | `[{name, apps, is_default}]` (first is always Default) |
| | `create_profile(name, apps=None)`, `rename_profile(name, new_name)`, `delete_profile(name)` | updated list |
| | `set_profile_apps(name, apps)` | `{apps, conflicts: [{app, profile}]}` |
| | `foreground_app()` | e.g. `"chrome.exe"` or `null` |
| Devices | `list_devices()` | `[{id, name, vid, pid, usage_page, usage, interface, keys, source, file, connected}]` |
| | `delete_device(device_id)` | updated list (user profiles only) |
| | `list_hid_devices()` | `[{vid, pid, product, manufacturer, label}]` for the learn picker |
| Bindings | `get_bindings(profile, device_id)` | `[{key, own, action, effective, inherited_from, display}]` |
| | `set_binding(profile, device_id, key, action)` | the normalized action |
| | `clear_binding(profile, device_id, key)` | `true` |
| Actions | `action_types()` | `[{type, label, help, fields: [{name, kind, label, hint?, default?}]}]` |
| | `validate_action(action)`, `describe_action(action)` | normalized action / text |
| Learn | `start_learning(vid, pid, product="", quiet_seconds=2.0)` | snapshot + `session` |
| | `learn_poll(session)` | `{phase: quiet\|listening\|error, error, opened, next_name, events, captures}` |
| | `learn_set_next_name(session, name)`, `learn_rename_key(session, index, name)`, `learn_remove_key(session, index)` | |
| | `save_learned_device(session, name, overwrite=False)` | device summary (raises `exists` first time if taken) |
| | `stop_learning(session)` | `true` |
| Engine | `engine_status()` | `{running: bool\|null, paused}` |
| | `set_paused(paused)`, `start_engine()`, `open_folder(which)` | |

`action_types()` describes each action's fields with a `kind` of `hotkey`, `string`, `bool`
or `command`. Build the action editor from that list instead of hard-coding the types,
and a new action type added to the backend shows up in every frontend.

Learn events (`learn_poll()["events"]`) are drained on each poll. Each has a `type` of
`captured`, `duplicate` or `wrong_interface`, plus a `message` ready to display.

## Example: an HTML frontend over HTTP

A minimal adapter using only the standard library. Serve your HTML/JS from it and call
`POST /api/<method>` with a JSON body of parameters:

```python
# openremap/ui/web/__main__.py  (example, not shipped)
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from openremap.service import ApiError, RemapService

service = RemapService()

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not self.path.startswith("/api/"):
            return self.send_error(404)
        params = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        try:
            status, body = 200, {"result": service.dispatch(self.path[5:], params)}
        except ApiError as e:
            status, body = 400, e.to_json()
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
```

```js
const call = async (method, params = {}) => {
  const r = await fetch(`/api/${method}`, {method: "POST", body: JSON.stringify(params)});
  const j = await r.json();
  if (!r.ok) throw Object.assign(new Error(j.error), {code: j.code});
  return j.result;
};
const profiles = await call("list_profiles");
```

Bind to `127.0.0.1` only. The API can launch programs, so it must never be reachable
from the network. A real web frontend should also check a random token that it
generates at startup.

## Registering a frontend

Add it to `FRONTENDS` in `openremap/ui/__init__.py` (for example `"web": "openremap.ui.web"`),
or set `"ui"` in `config.json` to any module path that runs with `python -m`. The tray's
**Settings...** item opens whichever one is configured.
