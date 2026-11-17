<div align="center">

# OpenRemap

**Give the extra keys on your keyboard real actions, without the vendor's software.**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776AB.svg)
![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6.svg)
![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)

</div>

OpenRemap reads G-keys, macro keys and other extra keys straight from your keyboard over USB HID.
You can assign each one a hotkey, a block of text or a program to launch. No iCUE, Synapse or
G HUB is needed.

It started as a way to use the six G-keys on a Corsair K95 RGB Platinum XT without installing
iCUE. It grew into a general tool: if your keyboard isn't supported yet, **learn mode** works
out its keys in a minute and saves a profile you can share.

<p align="center">
  <img src="docs/images/settings-bindings.png" alt="OpenRemap settings window showing G1 to G6 bindings" width="720">
</p>

## Features

- **Learn mode.** Press each extra key once and OpenRemap detects which bits of the HID report
  it changes. The result is a small JSON device profile.
- **Actions.** Send a hotkey (`win+shift+s`), type text, run a program, disable a key, or just log it.
- **Per-app profiles.** Use different key layouts for different programs, for example one for
  Remote Desktop and one for everything else. Keys a profile leaves unset fall back to **Default**.
- **Tray app.** Runs in the background with Settings, Pause, Log and Quit in the tray menu.
- **Live reload.** Changes made in the settings window apply within about a second, with no restart.
- **Swappable frontend.** The settings window is just one client of a plain JSON API. You can
  build an HTML, CLI or other frontend without touching the backend.

## Supported devices

| Device | Keys | Profile |
|---|---|---|
| Corsair K95 RGB Platinum XT | G1 to G6 | built-in |

Not listed? Use [learn mode](#learn-a-new-keyboard), then [contribute the profile](#contributing).

## Installation

Requires Windows and Python 3.9 or newer.

```powershell
git clone https://github.com/<your-username>/OpenRemap.git
cd OpenRemap
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

> [!IMPORTANT]
> Close your keyboard's vendor software (iCUE, Synapse, G HUB, ...) before using OpenRemap.
> It can hold the same interface, and both programs would react to the same keys.

## Usage

```powershell
pythonw -m openremap              # start the engine with a tray icon
python  -m openremap --console    # engine only, logs every key press to the terminal
python  -m openremap.ui.tk        # open the settings window
```

After `pip install -e .`, the `openremap` and `openremap-settings` commands do the same.

### Assign an action

1. Open **Settings** from the tray icon.
2. Choose your device, double-click a key, and pick an action.
3. It's saved immediately and the engine picks it up on its own.

### Per-app profiles

Click **New...** next to the profile list, name the profile, and add the programs it applies
to (for example `msrdc.exe` for Remote Desktop). **Detect app** fills in the exe name of
whatever window you switch to. Anything the profile doesn't set comes from **Default**, and a
key set to **Do nothing** is disabled in that app.

### Learn a new keyboard

1. Go to **Devices > Learn new device...** and pick your keyboard.
2. Click **Start listening** and keep your hands off the keyboard for two seconds.
   OpenRemap uses that time to ignore bytes that change on their own.
3. Press each extra key once, in order. Rename keys as you go if you like.
4. Click **Save profile**. The keys show up in the Bindings tab.

### Start with Windows

Press <kbd>Win</kbd>+<kbd>R</kbd>, open `shell:startup`, and create a shortcut with:

- **Target:** `<path to OpenRemap>\.venv\Scripts\pythonw.exe -m openremap`
- **Start in:** `<path to OpenRemap>`

## How it works

Most extra keys don't send normal keystrokes. They report on a vendor-specific HID interface
that only the vendor's software listens to. OpenRemap opens that interface with
[hidapi](https://github.com/trezor/cython-hidapi), watches the bytes of each report, and runs
your action when a key's bit turns on.

```
openremap/
├── core/         engine, device profiles, config, actions, learn mode (no UI code)
├── service.py    the frontend API: plain JSON in and out
├── ui/tk/        the Tkinter settings window
├── devices/      built-in device profiles (JSON)
└── tray.py       background app with tray icon
```

A device profile looks like this:

```json
{
  "format": 1,
  "name": "Corsair K95 RGB Platinum XT",
  "vid": "0x1B1C", "pid": "0x1B89",
  "usage_page": "0xFF42", "usage": "0x0002", "interface": 2,
  "match": {"1": "0x02"},
  "keys": [
    {"name": "G1", "byte": 18, "mask": "0x08"},
    {"name": "G6", "byte": 19, "mask": "0x01"}
  ]
}
```

Want a different settings UI? See [docs/FRONTENDS.md](docs/FRONTENDS.md) for the full API and a
working example of an HTML frontend served locally.

## Files

Everything lives in `%APPDATA%\OpenRemap\`:

| File | Contents |
|---|---|
| `config.json` | Profiles and key bindings |
| `devices\*.json` | Device profiles you learned (they override built-ins with the same name) |
| `openremap.log` | Every key press and action, the first place to look when a key "does nothing" |
| `paused.flag` | Present while OpenRemap is paused |

## Limitations

- **Adds actions, doesn't block keys.** That's fine for G-keys and macro keys, which send
  nothing on their own. A remapped regular key like F5 would still also send F5.
- **Main keyboard interface is off-limits.** Windows doesn't let programs read it, so learn
  mode finds keys on vendor, media and consumer-control interfaces only.
- **No "software mode" init yet.** Some keyboards only report extra keys after the vendor
  software sends a special command. Per-device init commands aren't supported yet.
- **Windows only for now.** Per-app detection and the single-instance check are Windows-specific.

## Contributing

Device profiles are the most useful contribution:

1. Learn your keyboard with **Devices > Learn new device...**.
2. Check that every key triggers the right action.
3. Copy the JSON from `%APPDATA%\OpenRemap\devices\` into `openremap/devices/`.
4. Open a pull request with the keyboard's full name and model number.

Code changes are welcome too. Run the tests before opening a pull request:

```powershell
python -m unittest discover -s tests
```

## License

Copyright (C) 2026 Logan J

OpenRemap is free software: you can redistribute it and/or modify it under the terms of the
GNU General Public License as published by the Free Software Foundation, either version 3 of
the License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY.
See [LICENSE](LICENSE) for the full text.

OpenRemap is not affiliated with or endorsed by Corsair or any other keyboard maker.
