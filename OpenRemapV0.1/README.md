# OpenRemap

Give the extra keys on your keyboard (G-keys, macro keys and similar) real actions without
the vendor's software. OpenRemap reads the keys straight from the keyboard over USB HID.
It learns new keyboards with a guided wizard and lets each app have its own key layout.

- **Learn mode.** Press each extra key once, and OpenRemap works out which bits of the
  HID report it changes. The result is saved as a small JSON device profile you can share.
- **Actions.** Send a hotkey, type text, run a program, do nothing, or log only.
- **Per-app profiles.** A Remote Desktop profile can use different keys from your
  Default profile. Keys a profile leaves unset fall back to Default.
- **Tray app.** Runs quietly in the background, with pause, settings and log in the tray menu.
- **Swappable frontend.** The settings window is one frontend on a plain JSON API. See
  [docs/FRONTENDS.md](docs/FRONTENDS.md) to build an HTML (or any other) frontend.

Built-in device profiles: Corsair K95 RGB Platinum XT (G1 to G6).

## Install (Windows)

```powershell
cd OpenRemap
pip install -e .
```

or `pip install -r requirements.txt` to install only the dependencies.

Close the vendor software (iCUE, Synapse, ...) first, since it can grab the same interface.

## Run

```powershell
pythonw -m openremap              # tray icon + engine
python  -m openremap --console    # engine with log output in the terminal (debugging)
python  -m openremap.ui.tk        # settings window
```

After `pip install -e .` you can also use the `openremap` and `openremap-settings` commands.

### Start with Windows

Create a shortcut in `shell:startup` that runs
`<your venv>\Scripts\pythonw.exe -m openremap`, with the project folder as the
"Start in" folder.

## Where things are stored

`%APPDATA%\OpenRemap\`
- `config.json`: profiles and bindings
- `devices\*.json`: device profiles you learned (these override built-ins with the same name)
- `openremap.log`: what the engine did (useful when a key "does nothing")
- `paused.flag`: present while paused

## Limitations

- OpenRemap **adds** actions. It can't stop a key's normal function. That works perfectly
  for keys that send nothing on their own (G-keys, macro keys). A normal key like F5 would
  still send F5 as well.
- Windows doesn't let apps read the main keyboard interface, so learn mode finds keys on
  vendor interfaces, and on media and consumer-control interfaces.
- Some keyboards only report their extra keys after the vendor software switches them
  into a "software mode". Support for sending such init commands per device isn't built yet.
- Per-app detection and the single-instance check are Windows-only for now.

## Contributing a device

1. Learn it in **Devices > Learn new device...**.
2. Check that every key fires the right action.
3. Copy the JSON file from `%APPDATA%\OpenRemap\devices\` into `openremap/devices/` and open a pull request.

## License

Copyright (C) 2026 Logan J

OpenRemap is free software: you can redistribute it and/or modify it under the terms of
the GNU General Public License as published by the Free Software Foundation, either
version 3 of the License, or (at your option) any later version. It is distributed WITHOUT
ANY WARRANTY. See [LICENSE](LICENSE) for the full text.
