# Tempest Weather Station Monitor

A Python desktop app that listens for live weather data broadcast by a [WeatherFlow Tempest](https://weatherflow.com/tempest-weather-system/) hub over UDP and displays it in a compact, dark-themed GUI dashboard.

**Author:** Michael Walker VA3MW &nbsp;·&nbsp; Built with [Claude](https://claude.ai) (Anthropic)

![Python](https://img.shields.io/badge/Python-3.8%2B-blue) ![Version](https://img.shields.io/badge/Version-1.2.0-orange) ![License](https://img.shields.io/badge/License-MIT-green) ![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

---

## Features

- **Live UDP data** — receives broadcasts from the Tempest hub on your local network (port 50222), no cloud account or API key needed
- **All sensor data** — temperature, humidity, dew point, feels-like, pressure, wind (speed / gust / lull / direction), UV index, solar radiation, rain accumulation, and lightning
- **Rapid wind** — updates every few seconds from the `rapid_wind` message type
- **Click to cycle units** — values and units are shown inline on one row; click either to cycle
  - Temperature: °F → °C → K
  - Wind: km/h → mph → m/s → kts
  - Pressure: inHg → hPa → kPa → mmHg
- **Mini bar mode** — collapses to a 300×50 borderless bar showing temp, wind, and lightning. Click anywhere on the bar to expand back to full view. Drag the `≡` handle to reposition it on screen
- **Tempest Map link** — `🌐 Tempest Map` in the title bar opens [tempestwx.com/map](https://tempestwx.com/map) so you can browse other nearby weather stations
- **Persistent settings** — unit choices and window position are saved to `tempest_settings.json` and restored on next launch
- **Desktop shortcut / launcher** — one-click button creates a platform-appropriate launcher:
  - **Windows** → `Tempest Weather.lnk` (PowerShell WScript.Shell)
  - **macOS** → `Tempest Weather.command` (executable shell script)
  - **Linux** → `tempest-weather.desktop` (XDG desktop entry for GNOME/KDE/XFCE)

---

## Requirements

- Python 3.8 or later
- Standard library only — no `pip install` needed (`tkinter`, `socket`, `json`, `threading`, `math`, `subprocess`, `webbrowser`, `platform`)
- Tested on **Windows 10/11**, **macOS 12+**, and **Debian / Ubuntu Linux**
- A WeatherFlow Tempest hub on the same LAN subnet as the machine running this app
- On Linux, `tkinter` may need to be installed separately: `sudo apt install python3-tk`

---

## Installation

```bash
# Clone or download the repository
git clone https://github.com/yourname/tempest-weather-monitor.git
cd tempest-weather-monitor

# Run directly — no dependencies to install
python tempest_weather.py
```

---

## How it works

The Tempest hub broadcasts JSON packets over **UDP port 50222** to all devices on the local network. This app binds a UDP socket on that port and processes each packet type on a background thread, updating the GUI safely on the main thread via tkinter's `after()`.

| Message type | Description |
|---|---|
| `obs_st` | Full Tempest observation — all sensors, ~1 min interval |
| `obs_air` | AIR module — temperature, humidity, pressure, lightning |
| `obs_sky` | SKY module — wind, rain, UV, solar radiation |
| `rapid_wind` | Wind speed and direction, ~3 s interval |
| `evt_strike` | Lightning strike event — distance and energy |
| `evt_precip` | Rain start event |

Full protocol reference: [Tempest UDP Broadcast API](https://apidocs.tempestwx.com/reference/tempest-udp-broadcast)

---

## Usage

| Action | Result |
|---|---|
| Click a **temperature**, **wind**, or **pressure** value | Cycles through all available units |
| Click **⊟ Mini** | Collapses to a 300×50 mini bar |
| Click anywhere on the **mini bar** | Expands back to full view |
| Drag the **≡** handle on the mini bar | Repositions the mini bar on screen |
| Click **🌐 Tempest Map** | Opens tempestwx.com/map in your browser |
| Click **📌 Shortcut** | Creates a desktop launcher for your OS (`.lnk` / `.command` / `.desktop`) |

---

## Settings file

`tempest_settings.json` is created automatically next to the script the first time a unit is changed or the window is closed:

```json
{
  "temp_idx": 0,
  "wind_idx": 0,
  "pres_idx": 0,
  "geometry": "740x400+200+150"
}
```

| Key | Values |
|---|---|
| `temp_idx` | 0 = °F, 1 = °C, 2 = K |
| `wind_idx` | 0 = km/h, 1 = mph, 2 = m/s, 3 = kts |
| `pres_idx` | 0 = inHg, 1 = hPa, 2 = kPa, 3 = mmHg |
| `geometry` | tkinter geometry string — size and position |

Delete the file to reset all settings to defaults.

---

## Changelog

### v1.2.0
- **Cross-platform** — Windows, macOS, and Debian/Ubuntu Linux
  - System font auto-selected per OS (Segoe UI / Helvetica Neue / DejaVu Sans)
  - Desktop launcher created for each platform (`.lnk` / `.command` / `.desktop`)
- **Bottom whitespace fixed** — startup now restores window *position only*; size auto-fits to content
- Copyright updated: Michael Walker VA3MW & Claude (Anthropic)
- Version bump to 1.2.0

### v1.1.0
- Compact layout — reduced font sizes and card padding for a smaller footprint
- Value + unit displayed inline on one row (no more stacked V label)
- Battery and Last Update combined into a single bottom card
- Added **🌐 Tempest Map** hotlink to browse nearby stations

### v1.0.0
- Initial release

---

## Project structure

```
tempest-weather-monitor/
├── tempest_weather.py      # Main application
├── tempest_settings.json   # Auto-generated user settings (gitignore this)
└── README.md
```

> **Tip:** add `tempest_settings.json` to your `.gitignore` to avoid committing personal window positions and unit preferences.

---

## License

MIT — see the license header at the top of `tempest_weather.py`.
