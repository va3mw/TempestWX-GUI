# =============================================================================
# Tempest Weather Station UDP Monitor
# Version 1.2.0
#
# MIT License
# Copyright (c) 2026  Michael Walker VA3MW  &  Claude (Anthropic)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
# =============================================================================
#
# Listens on UDP port 50222 for WeatherFlow Tempest hub broadcasts and displays
# live weather data in a dark-themed tkinter dashboard.
#
# Cross-platform: Windows, macOS, Debian/Ubuntu Linux
#
# Features:
#   - Handles obs_st, obs_air, obs_sky, rapid_wind, evt_strike, evt_precip
#   - Click temperature / wind / pressure values to cycle through all units
#   - Mini bar (300x50, no title bar) — click anywhere on bar to expand
#   - Drag the mini bar by its ≡ handle to reposition it anywhere on screen
#   - Desktop shortcut / launcher created for Windows (.lnk), macOS (.command),
#     or Linux (.desktop) automatically based on the running platform
#   - Settings (unit choices, window position) persisted to tempest_settings.json
#
# Requirements: Python 3.8+, standard library only (tkinter, socket, json …)
# =============================================================================

import json
import math
import os
import platform
import socket
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import font as tkfont, messagebox
from datetime import datetime

VERSION       = "1.2.0"
UDP_PORT      = 50222
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "tempest_settings.json")
# Pick a system font that looks good on each OS
_PLAT = platform.system()
FONT_FAMILY = ("Segoe UI"        if _PLAT == "Windows"
               else "Helvetica Neue" if _PLAT == "Darwin"
               else "DejaVu Sans")   # Linux / Debian

PRECIP_TYPES = {0: "None", 1: "Rain", 2: "Hail", 3: "Rain+Hail"}
WIND_DIRS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]

TEMP_UNITS = ["°F", "°C", "K"]
WIND_UNITS = ["km/h", "mph", "m/s", "kts"]
PRES_UNITS = ["inHg", "hPa", "kPa", "mmHg"]


# ─────────────────────────────────────────────── Unit conversions ──────────

def deg_to_compass(deg):
    if deg is None:
        return "---"
    return WIND_DIRS[round(deg / 22.5) % 16]


def convert_temp(c, unit):
    if c is None:
        return None
    if unit == "°F":
        return round(c * 9 / 5 + 32, 1)
    if unit == "°C":
        return round(c, 1)
    if unit == "K":
        return round(c + 273.15, 1)


def convert_wind(ms, unit):
    if ms is None:
        return None
    if unit == "km/h":
        return round(ms * 3.6, 1)
    if unit == "mph":
        return round(ms * 2.23694, 1)
    if unit == "m/s":
        return round(ms, 1)
    if unit == "kts":
        return round(ms * 1.94384, 1)


def convert_pres(mb, unit):
    if mb is None:
        return None
    if unit == "inHg":
        return round(mb * 0.02953, 2)
    if unit == "hPa":
        return round(mb, 1)
    if unit == "kPa":
        return round(mb * 0.1, 2)
    if unit == "mmHg":
        return round(mb * 0.750062, 1)


def dew_point_c(temp_c, rh):
    if temp_c is None or rh is None or rh <= 0:
        return None
    a, b = 17.27, 237.7
    gamma = (a * temp_c / (b + temp_c)) + math.log(rh / 100.0)
    return b * gamma / (a - gamma)


def heat_index_f(tf, rh):
    """Rothfusz heat index. Returns None when conditions don't apply."""
    if tf is None or rh is None or tf < 80 or rh < 40:
        return None
    hi = (-42.379 + 2.04901523 * tf + 10.14333127 * rh
          - 0.22475541 * tf * rh - 6.83783e-3 * tf ** 2
          - 5.481717e-2 * rh ** 2 + 1.22874e-3 * tf ** 2 * rh
          + 8.5282e-4 * tf * rh ** 2 - 1.99e-6 * tf ** 2 * rh ** 2)
    return round(hi, 1)


def uv_category(uv):
    if uv is None:
        return ""
    if uv < 3:
        return "Low"
    if uv < 6:
        return "Moderate"
    if uv < 8:
        return "High"
    if uv < 11:
        return "Very High"
    return "Extreme"


# ─────────────────────────────────────────── Desktop shortcut helper ───────

def _get_desktop():
    """Return the real Desktop folder path for the current user.

    Never assumes C:\\Users\\...\\Desktop — asks the OS directly:
      Windows : HKCU registry Shell Folders key (honours relocated Desktops)
      macOS   : ~/Desktop  (always correct on macOS)
      Linux   : xdg-user-dir DESKTOP, falls back to ~/Desktop
    """
    if _PLAT == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
            )
            path, _ = winreg.QueryValueEx(key, "Desktop")
            winreg.CloseKey(key)
            return path                          # e.g. "F:\\Desktop" or "D:\\..."
        except Exception:
            pass                                 # fall through to default below

    elif _PLAT == "Linux":
        try:
            result = subprocess.run(
                ["xdg-user-dir", "DESKTOP"],
                capture_output=True, text=True,
            )
            path = result.stdout.strip()
            if result.returncode == 0 and path:
                return path
        except FileNotFoundError:
            pass                                 # xdg-user-dir not installed

    # macOS and fallback for any platform
    return os.path.join(os.path.expanduser("~"), "Desktop")


def create_shortcut():
    """Create a desktop launcher appropriate for the current OS.

    - Windows : Tempest Weather.lnk  (via PowerShell WScript.Shell)
    - macOS   : Tempest Weather.command  (executable shell script)
    - Linux   : tempest-weather.desktop  (XDG desktop entry)
    """
    script  = os.path.abspath(__file__)
    python  = sys.executable
    desktop = _get_desktop()
    os.makedirs(desktop, exist_ok=True)          # Linux may not have ~/Desktop

    try:
        if _PLAT == "Windows":
            _shortcut_windows(script, python, desktop)
        elif _PLAT == "Darwin":
            _shortcut_macos(script, python, desktop)
        else:
            _shortcut_linux(script, python, desktop)
    except Exception as e:
        messagebox.showerror("Error", f"Could not create shortcut:\n{e}")


def _shortcut_windows(script, python, desktop):
    """Windows .lnk via PowerShell WScript.Shell.

    Uses pythonw.exe (the windowless Python launcher) so no black console
    window appears when the shortcut is double-clicked.  Falls back to
    python.exe if pythonw.exe is not found alongside it.
    """
    # Derive pythonw.exe from the current python.exe path
    pythonw = os.path.join(os.path.dirname(python), "pythonw.exe")
    if not os.path.isfile(pythonw):
        pythonw = python          # safe fallback — console will be visible

    lnk     = os.path.join(desktop, "Tempest Weather.lnk")
    workdir = os.path.dirname(script)
    ps_content = (
        '$ws = New-Object -ComObject WScript.Shell\n'
        f'$s = $ws.CreateShortcut("{lnk}")\n'
        f'$s.TargetPath = "{pythonw}"\n'
        f'$s.Arguments = \'"{script}"\'\n'
        f'$s.WorkingDirectory = "{workdir}"\n'
        '$s.Save()\n'
    )
    ps_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ps1", delete=False, encoding="utf-8"
        ) as f:
            f.write(ps_content)
            ps_file = f.name
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", ps_file],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            messagebox.showinfo("Shortcut Created",
                                "Desktop shortcut 'Tempest Weather' created!")
        else:
            messagebox.showerror("Error", result.stderr or "Unknown error")
    finally:
        if ps_file:
            try:
                os.unlink(ps_file)
            except OSError:
                pass


def _shortcut_macos(script, python, desktop):
    """macOS double-clickable .command shell script on the Desktop."""
    path = os.path.join(desktop, "Tempest Weather.command")
    with open(path, "w", encoding="utf-8") as f:
        f.write("#!/bin/bash\n")
        f.write(f'"{python}" "{script}"\n')
    os.chmod(path, 0o755)
    messagebox.showinfo("Launcher Created",
                        f"Double-click to launch:\n{path}")


def _shortcut_linux(script, python, desktop):
    """Linux XDG .desktop entry — works on GNOME, KDE, XFCE, etc."""
    path = os.path.join(desktop, "tempest-weather.desktop")
    with open(path, "w", encoding="utf-8") as f:
        f.write("[Desktop Entry]\n")
        f.write("Version=1.0\n")
        f.write("Type=Application\n")
        f.write("Name=Tempest Weather Station\n")
        f.write("Comment=WeatherFlow Tempest UDP Monitor\n")
        f.write(f"Exec={python} {script}\n")
        f.write("Terminal=false\n")
        f.write("Categories=Utility;\n")
    os.chmod(path, 0o755)
    messagebox.showinfo("Shortcut Created",
                        f"Desktop entry created:\n{path}")


# ──────────────────────────────────────────────────────── Main window ──────

class TempestMonitor(tk.Tk):

    BG      = "#1a1a2e"
    CARD    = "#16213e"
    ACCENT  = "#0f3460"
    LBL     = "#a8dadc"
    VAL     = "#e2e2e2"
    UNIT    = "#7f8c8d"
    CLICK   = "#57c4d8"   # teal — visual cue for clickable values
    MINI_BG = "#0d1b2a"

    def __init__(self):
        super().__init__()
        self.title("Tempest Weather Station")
        self.resizable(False, False)
        self.configure(bg=self.BG)

        self._temp_idx = 0
        self._wind_idx = 0
        self._pres_idx = 0

        self._data             = {}
        self._last_rapid_wind  = {}
        self._last_strike      = {}
        self._last_precip_time = None

        self._mini_mode       = False
        self._saved_geo       = None   # full "WxH+x+y" saved before entering mini
        self._drag_ox         = 0
        self._drag_oy         = 0

        self._load_settings()
        self._build_ui()
        self._apply_saved_geometry()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._start_listener()

    # ──────────────────────────────────────────────────── Settings ─────────

    def _load_settings(self):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                s = json.load(f)
            self._temp_idx = max(0, min(s.get("temp_idx", 0), len(TEMP_UNITS) - 1))
            self._wind_idx = max(0, min(s.get("wind_idx", 0), len(WIND_UNITS) - 1))
            self._pres_idx = max(0, min(s.get("pres_idx", 0), len(PRES_UNITS) - 1))
            self._saved_geo = s.get("geometry", "")
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            self._saved_geo = ""

    def _save_settings(self):
        try:
            geo = self.geometry() if not self._mini_mode else (self._saved_geo or "")
            s = {
                "temp_idx": self._temp_idx,
                "wind_idx": self._wind_idx,
                "pres_idx": self._pres_idx,
                "geometry": geo,
            }
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(s, f, indent=2)
        except OSError:
            pass

    def _apply_saved_geometry(self):
        """On startup restore only the window *position* (+X+Y), never the
        saved size.  The window is resizable=False so tkinter fits it to
        content automatically; forcing an old WxH would leave a blank gap
        at the bottom whenever the layout has shrunk since last run."""
        if not self._saved_geo:
            return
        try:
            # Geometry strings look like "WxH+X+Y" or "WxH-X+Y" etc.
            # Split on '+'/'-' to extract the X and Y offsets.
            parts = self._saved_geo.replace("-", "+-").split("+")
            if len(parts) >= 3:
                self.geometry(f"+{parts[1]}+{parts[2]}")
        except (ValueError, tk.TclError):
            pass

    def _on_close(self):
        self._save_settings()
        self.destroy()

    # ──────────────────────────────────────────────────── UI construction ──

    def _build_ui(self):
        # Tighter fonts to keep the window compact
        big   = tkfont.Font(family=FONT_FAMILY, size=18, weight="bold")
        med   = tkfont.Font(family=FONT_FAMILY, size=11, weight="bold")
        small = tkfont.Font(family=FONT_FAMILY, size=9)
        tiny  = tkfont.Font(family=FONT_FAMILY, size=8)

        # ── Title bar ─────────────────────────────────────────────────────
        # IMPORTANT: pack side="right" widgets FIRST — otherwise the left
        # label claims all space and clips anything packed after it.
        self._title_frame = tk.Frame(self, bg=self.ACCENT, pady=3)
        self._title_frame.grid(row=0, column=0, columnspan=4, sticky="ew")

        self._mini_btn = tk.Button(
            self._title_frame, text="⊟ Mini",
            command=self._enter_mini,
            bg="#457b9d", fg="white",
            font=tiny, relief="flat", padx=6, pady=3, cursor="hand2",
        )
        self._mini_btn.pack(side="right", padx=3)   # packed BEFORE the label

        tk.Label(
            self._title_frame, text=f"  Tempest  v{VERSION}",
            font=tkfont.Font(family=FONT_FAMILY, size=11, weight="bold"),
            bg=self.ACCENT, fg=self.VAL,
        ).pack(side="left")

        # Status and hint moved to the bottom card — title bar stays narrow

        # ── Content frame (holds all cards) ───────────────────────────────
        self._content_frame = tk.Frame(self, bg=self.BG)
        self._content_frame.grid(row=1, column=0, columnspan=4, sticky="nsew")

        cf = self._content_frame

        def card(row, col, rowspan=1, colspan=1):
            f = tk.Frame(
                cf, bg=self.CARD, padx=6, pady=4,
                highlightbackground=self.ACCENT, highlightthickness=1,
            )
            f.grid(row=row, column=col, rowspan=rowspan, columnspan=colspan,
                   padx=3, pady=3, sticky="nsew")
            return f

        def lbl(parent, text):
            return tk.Label(
                parent, text=text.upper(), font=tiny,
                bg=self.CARD, fg=self.LBL,
            )

        def val_w(parent, clickable=False):
            v = tk.StringVar(value="---")
            w = tk.Label(
                parent, textvariable=v, font=big,
                bg=self.CARD,
                fg=self.CLICK if clickable else self.VAL,
                cursor="hand2" if clickable else "",
            )
            return v, w

        def unit_w(parent, text="", clickable=False):
            v = tk.StringVar(value=text)
            w = tk.Label(
                parent, textvariable=v, font=small,
                bg=self.CARD,
                fg=self.CLICK if clickable else self.UNIT,
                cursor="hand2" if clickable else "",
            )
            return v, w

        def sub_w(parent, font_override=None):
            v = tk.StringVar(value="")
            w = tk.Label(
                parent, textvariable=v,
                font=font_override or tiny,
                bg=self.CARD, fg=self.UNIT,
            )
            return v, w

        # ── Row 0: Temperature | Humidity | Pressure | UV/Solar ───────────
        c = card(0, 0)
        lbl(c, "Temperature").pack(anchor="w")
        # Value + unit on the same row so the card stays narrow
        row0 = tk.Frame(c, bg=self.CARD); row0.pack(anchor="w")
        self._temp_var, w = val_w(row0, clickable=True)
        w.pack(side="left")
        w.bind("<Button-1>", lambda e: self._cycle_temp())
        self._temp_unit_var, wu = unit_w(row0, TEMP_UNITS[0], clickable=True)
        wu.configure(font=med)
        wu.pack(side="left", anchor="s", pady=4)
        wu.bind("<Button-1>", lambda e: self._cycle_temp())
        self._feels_var, w = sub_w(c)
        w.pack(anchor="w")

        c = card(0, 1)
        lbl(c, "Humidity").pack(anchor="w")
        row0 = tk.Frame(c, bg=self.CARD); row0.pack(anchor="w")
        self._humid_var, w = val_w(row0)
        w.pack(side="left")
        tk.Label(row0, text=" %", font=med, bg=self.CARD, fg=self.UNIT).pack(
            side="left", anchor="s", pady=4)
        self._dewpt_var, w = sub_w(c)
        w.pack(anchor="w")

        c = card(0, 2)
        lbl(c, "Pressure").pack(anchor="w")
        row0 = tk.Frame(c, bg=self.CARD); row0.pack(anchor="w")
        self._pres_var, w = val_w(row0, clickable=True)
        w.pack(side="left")
        w.bind("<Button-1>", lambda e: self._cycle_pres())
        self._pres_unit_var, wu = unit_w(row0, PRES_UNITS[0], clickable=True)
        wu.configure(font=med)
        wu.pack(side="left", anchor="s", pady=4)
        wu.bind("<Button-1>", lambda e: self._cycle_pres())

        c = card(0, 3)
        lbl(c, "UV Index").pack(anchor="w")
        row0 = tk.Frame(c, bg=self.CARD); row0.pack(anchor="w")
        self._uv_var, w = val_w(row0)
        w.pack(side="left")
        self._uv_desc, w = sub_w(row0, small)
        w.pack(side="left", anchor="s", pady=4, padx=(4, 0))
        lbl(c, "Solar Rad").pack(anchor="w", pady=(4, 0))
        row0b = tk.Frame(c, bg=self.CARD); row0b.pack(anchor="w")
        self._solar_var, w = val_w(row0b)
        w.configure(font=med)
        w.pack(side="left")
        tk.Label(row0b, text=" W/m²", font=small, bg=self.CARD,
                 fg=self.UNIT).pack(side="left", anchor="s", pady=2)

        # ── Row 1: Wind (2 cols) | Rain | Lightning ────────────────────────
        c = card(1, 0, colspan=2)
        lbl(c, "Wind").pack(anchor="w")

        wind_spd_row = tk.Frame(c, bg=self.CARD)
        wind_spd_row.pack(anchor="w", fill="x")
        self._wind_spd_var, w = val_w(wind_spd_row, clickable=True)
        w.pack(side="left")
        w.bind("<Button-1>", lambda e: self._cycle_wind())
        self._wind_spd_unit_var, wu = unit_w(wind_spd_row, " " + WIND_UNITS[0], clickable=True)
        wu.configure(font=med)
        wu.pack(side="left", anchor="s", pady=4)
        wu.bind("<Button-1>", lambda e: self._cycle_wind())

        wind_sub_row = tk.Frame(c, bg=self.CARD)
        wind_sub_row.pack(anchor="w", fill="x")
        self._wind_dir_var, w = sub_w(wind_sub_row, med)
        w.configure(fg=self.VAL)
        w.pack(side="left")
        self._wind_lull_var, w = sub_w(wind_sub_row)
        w.pack(side="left", padx=(10, 0))
        self._wind_gust_var, w = sub_w(wind_sub_row)
        w.pack(side="left", padx=(6, 0))

        lbl(c, "Rapid Wind").pack(anchor="w", pady=(6, 0))
        self._rapid_var, w = sub_w(c, small)
        w.configure(fg=self.VAL)
        w.pack(anchor="w")

        c = card(1, 2)
        lbl(c, "Rain").pack(anchor="w")
        row1 = tk.Frame(c, bg=self.CARD); row1.pack(anchor="w")
        self._rain_var, w = val_w(row1)
        w.pack(side="left")
        self._rain_unit_var, wu = unit_w(row1, "in")
        wu.configure(font=med)
        wu.pack(side="left", anchor="s", pady=4)
        self._precip_type_var, w = sub_w(c)
        w.pack(anchor="w")
        self._rain_evt_var, w = sub_w(c)
        w.pack(anchor="w")

        c = card(1, 3)
        lbl(c, "Lightning").pack(anchor="w")
        row1 = tk.Frame(c, bg=self.CARD); row1.pack(anchor="w")
        self._strike_count_var, w = val_w(row1)
        w.pack(side="left")
        tk.Label(row1, text=" strikes", font=med, bg=self.CARD,
                 fg=self.UNIT).pack(side="left", anchor="s", pady=4)
        self._strike_dist_var, w = sub_w(c, small)
        w.configure(fg=self.VAL)
        w.pack(anchor="w")
        self._strike_evt_var, w = sub_w(c)
        w.pack(anchor="w")

        # ── Row 2: Battery + Last Update — combined single card ────────────
        c = card(2, 0, colspan=4)
        # Lay out horizontally: battery on left, update info on right
        bottom_row = tk.Frame(c, bg=self.CARD)
        bottom_row.pack(fill="x")

        # Battery (inline value + V)
        bat_frame = tk.Frame(bottom_row, bg=self.CARD)
        bat_frame.pack(side="left", padx=(0, 20))
        lbl(bat_frame, "Battery").pack(anchor="w")
        bat_val_row = tk.Frame(bat_frame, bg=self.CARD)
        bat_val_row.pack(anchor="w")
        self._bat_var, w = val_w(bat_val_row)
        w.configure(font=med, fg=self.VAL)
        w.pack(side="left")
        tk.Label(bat_val_row, text=" V", font=small,
                 bg=self.CARD, fg=self.UNIT).pack(side="left", anchor="s", pady=2)

        # Separator
        tk.Frame(bottom_row, bg=self.ACCENT, width=1).pack(
            side="left", fill="y", padx=10)

        # Last update + device
        upd_frame = tk.Frame(bottom_row, bg=self.CARD)
        upd_frame.pack(side="left", fill="x", expand=True)
        lbl(upd_frame, "Last Update").pack(anchor="w")
        self._update_var, w = sub_w(upd_frame, small)
        w.configure(fg=self.VAL)
        w.pack(anchor="w")
        self._device_var, w = sub_w(upd_frame)
        w.pack(anchor="w")

        # ── Status bar row (packet status + hint + shortcut button) ──────────
        # Pack right-side widgets FIRST so they are never clipped.
        tk.Frame(c, bg=self.ACCENT, height=1).pack(fill="x", pady=(6, 2))
        status_row = tk.Frame(c, bg=self.CARD)
        status_row.pack(fill="x")

        tk.Button(
            status_row, text="📌 Lnk",
            command=create_shortcut,
            bg="#2d6a4f", fg="white",
            font=tiny, relief="flat", padx=5, pady=2, cursor="hand2",
        ).pack(side="right")                         # rightmost — packed first

        tk.Label(status_row, text="↻ cycle units",
                 font=tiny, bg=self.CARD, fg="#6a9fb5").pack(side="right", padx=6)

        self._status_var = tk.StringVar(value="Waiting…")
        tk.Label(status_row, textvariable=self._status_var,
                 font=tiny, bg=self.CARD, fg=self.UNIT).pack(side="left")

        for col in range(4):
            # weight=0 keeps cards at content width (no stretching).
            # Only configure the content frame — NOT the main window,
            # so the main window can grow freely to fit the content frame.
            cf.grid_columnconfigure(col, weight=0, minsize=120)

        # ── Mini frame (hidden until mini mode) ───────────────────────────
        self._mini_frame = tk.Frame(self, bg=self.MINI_BG, height=50)
        self._build_mini_frame()

    def _build_mini_frame(self):
        mf       = self._mini_frame
        mini_f   = tkfont.Font(family=FONT_FAMILY, size=12, weight="bold")
        mini_s   = tkfont.Font(family=FONT_FAMILY, size=9)
        MINI_ACC = "#1d3557"

        # Clicking anywhere on the mini bar (except the drag handle) expands
        # the window back to full size.
        def _expand(event=None):
            self._exit_mini()

        def clickable(widget):
            """Make a widget expand on click and show a pointer cursor."""
            widget.configure(cursor="hand2")
            widget.bind("<Button-1>", _expand)

        # The mini frame background itself is also clickable
        mf.configure(cursor="hand2")
        mf.bind("<Button-1>", _expand)

        # ── Drag handle (left edge) ───────────────────────────────────────
        # Uses its own ButtonPress/Motion bindings — NOT wired to expand.
        drag = tk.Label(
            mf, text="≡", bg=MINI_ACC, fg="white",
            font=tkfont.Font(family=FONT_FAMILY, size=14),
            width=2, cursor="fleur",
        )
        drag.pack(side="left", fill="y")
        drag.bind("<ButtonPress-1>", self._mini_drag_start)
        drag.bind("<B1-Motion>",     self._mini_drag_motion)

        def sep():
            w = tk.Label(mf, text="|", bg=self.MINI_BG, fg="#2a4a6a", font=mini_s)
            w.pack(side="left", padx=4)
            clickable(w)

        # ── Temperature ───────────────────────────────────────────────────
        self._mini_temp_var = tk.StringVar(value="---")
        w = tk.Label(mf, textvariable=self._mini_temp_var,
                     bg=self.MINI_BG, fg=self.VAL, font=mini_f)
        w.pack(side="left", padx=(6, 0))
        clickable(w)

        sep()

        # ── Wind speed + compass direction ────────────────────────────────
        self._mini_wind_var = tk.StringVar(value="---")
        w = tk.Label(mf, textvariable=self._mini_wind_var,
                     bg=self.MINI_BG, fg=self.VAL, font=mini_f)
        w.pack(side="left")
        clickable(w)

        sep()

        # ── Lightning strike count ─────────────────────────────────────────
        self._mini_strike_var = tk.StringVar(value="⚡ ---")
        w = tk.Label(mf, textvariable=self._mini_strike_var,
                     bg=self.MINI_BG, fg="#f4d03f", font=mini_f)
        w.pack(side="left")
        clickable(w)

    # ──────────────────────────────────────────────────── Mini mode drag ───

    def _mini_drag_start(self, event):
        self._drag_ox = event.x_root - self.winfo_x()
        self._drag_oy = event.y_root - self.winfo_y()

    def _mini_drag_motion(self, event):
        self.geometry(f"+{event.x_root - self._drag_ox}+{event.y_root - self._drag_oy}")

    # ──────────────────────────────────────────────── Mini mode toggle ─────

    def _enter_mini(self):
        # Save the complete geometry (size + position) before shrinking
        self._saved_geo = self.geometry()      # e.g. "820x560+200+150"
        self._save_settings()

        self._title_frame.grid_remove()
        self._content_frame.grid_remove()
        self._mini_frame.grid(row=0, column=0, columnspan=4, sticky="nsew")
        self.update_idletasks()
        self.overrideredirect(True)
        self.geometry("300x50")
        self._mini_mode = True
        self._refresh_mini()

    def _exit_mini(self):
        self.overrideredirect(False)
        self.deiconify()
        self._mini_frame.grid_remove()
        self._title_frame.grid(row=0, column=0, columnspan=4, sticky="ew")
        self._content_frame.grid(row=1, column=0, columnspan=4, sticky="nsew")
        self._mini_mode = False
        # Restore the full saved geometry (size + position) after tkinter
        # has had a moment to re-layout the restored frames
        self.after(30, lambda: self.geometry(self._saved_geo or ""))
        self._save_settings()

    # ──────────────────────────────────────────────────── Unit cycling ─────

    def _cycle_temp(self):
        self._temp_idx = (self._temp_idx + 1) % len(TEMP_UNITS)
        self._save_settings()
        self._refresh_display()

    def _cycle_wind(self):
        self._wind_idx = (self._wind_idx + 1) % len(WIND_UNITS)
        self._save_settings()
        self._refresh_display()

    def _cycle_pres(self):
        self._pres_idx = (self._pres_idx + 1) % len(PRES_UNITS)
        self._save_settings()
        self._refresh_display()

    # ──────────────────────────────────────────────────── Data display ─────

    def _refresh_display(self):
        d = self._data
        t_unit = TEMP_UNITS[self._temp_idx]
        w_unit = WIND_UNITS[self._wind_idx]
        p_unit = PRES_UNITS[self._pres_idx]

        temp_c        = d.get("temp_c")
        rh            = d.get("rh")
        pres_mb       = d.get("pres_mb")
        wind_avg_ms   = d.get("wind_avg_ms")
        wind_lull_ms  = d.get("wind_lull_ms")
        wind_gust_ms  = d.get("wind_gust_ms")
        wind_dir      = d.get("wind_dir")
        uv            = d.get("uv")
        solar         = d.get("solar")
        rain_mm       = d.get("rain_mm")
        precip_type   = d.get("precip_type")
        strike_count  = d.get("strike_count")
        strike_dist_km = d.get("strike_dist_km")
        battery       = d.get("battery")

        # ── Temperature ───────────────────────────────────────────────────
        tval = convert_temp(temp_c, t_unit)
        self._temp_var.set(str(tval) if tval is not None else "---")
        self._temp_unit_var.set(t_unit)

        if temp_c is not None and rh is not None:
            tf = temp_c * 9 / 5 + 32
            hi = heat_index_f(tf, rh)
            dp = dew_point_c(temp_c, rh)
            if hi is not None:
                hi_c = (hi - 32) * 5 / 9
                hi_val = convert_temp(hi_c, t_unit)
                self._feels_var.set(f"Feels like {hi_val}{t_unit}")
            elif dp is not None:
                dp_val = convert_temp(dp, t_unit)
                self._feels_var.set(f"Dew pt {dp_val}{t_unit}")
            else:
                self._feels_var.set("")
        else:
            self._feels_var.set("")

        # ── Humidity ──────────────────────────────────────────────────────
        self._humid_var.set(f"{round(rh)}" if rh is not None else "---")
        if temp_c is not None and rh is not None:
            dp = dew_point_c(temp_c, rh)
            if dp is not None:
                self._dewpt_var.set(f"Dew pt {convert_temp(dp, t_unit)}{t_unit}")
            else:
                self._dewpt_var.set("")
        else:
            self._dewpt_var.set("")

        # ── Pressure ──────────────────────────────────────────────────────
        pval = convert_pres(pres_mb, p_unit)
        self._pres_var.set(str(pval) if pval is not None else "---")
        self._pres_unit_var.set(p_unit)

        # ── UV / Solar ────────────────────────────────────────────────────
        self._uv_var.set(f"{round(uv, 1)}" if uv is not None else "---")
        self._uv_desc.set(uv_category(uv))
        self._solar_var.set(f"{round(solar)}" if solar is not None else "---")

        # ── Wind ──────────────────────────────────────────────────────────
        def fw(ms):
            return convert_wind(ms, w_unit)

        spd = fw(wind_avg_ms)
        self._wind_spd_var.set(str(spd) if spd is not None else "---")
        self._wind_spd_unit_var.set(f" {w_unit}")

        self._wind_dir_var.set(
            f"{deg_to_compass(wind_dir)}  {round(wind_dir)}°"
            if wind_dir is not None else "---"
        )

        lull = fw(wind_lull_ms)
        gust = fw(wind_gust_ms)
        self._wind_lull_var.set(f"Lull {lull} {w_unit}" if lull is not None else "")
        self._wind_gust_var.set(f"  Gust {gust} {w_unit}" if gust is not None else "")

        rw = self._last_rapid_wind
        if rw:
            rspd = fw(rw.get("speed_ms"))
            rdir = rw.get("dir_deg")
            ts   = rw.get("ts", "")
            self._rapid_var.set(
                f"{rspd} {w_unit}  {deg_to_compass(rdir)}  "
                f"{round(rdir) if rdir is not None else '---'}°  @ {ts}"
            )

        # ── Rain ──────────────────────────────────────────────────────────
        if rain_mm is not None:
            if t_unit == "°F":
                self._rain_var.set(f"{round(rain_mm / 25.4, 2)}")
                self._rain_unit_var.set("in")
            else:
                self._rain_var.set(f"{round(rain_mm, 1)}")
                self._rain_unit_var.set("mm")
        else:
            self._rain_var.set("---")

        if precip_type is not None:
            self._precip_type_var.set(f"Type: {PRECIP_TYPES.get(precip_type, '?')}")

        if self._last_precip_time:
            self._rain_evt_var.set(f"Last rain start: {self._last_precip_time}")

        # ── Lightning ─────────────────────────────────────────────────────
        self._strike_count_var.set(
            f"{strike_count}" if strike_count is not None else "---"
        )
        self._strike_dist_var.set(
            f"{strike_dist_km} km avg dist" if strike_dist_km is not None else ""
        )

        ls = self._last_strike
        if ls:
            dist = ls.get("dist_km")
            ts   = ls.get("ts", "")
            self._strike_evt_var.set(
                f"Last: {dist} km  @ {ts}" if dist else f"Last:  @ {ts}"
            )

        # ── Battery ───────────────────────────────────────────────────────
        self._bat_var.set(f"{battery:.2f}" if battery is not None else "---")

        # Keep mini display in sync
        self._refresh_mini()

    def _refresh_mini(self):
        d      = self._data
        t_unit = TEMP_UNITS[self._temp_idx]
        w_unit = WIND_UNITS[self._wind_idx]

        tval = convert_temp(d.get("temp_c"), t_unit)
        self._mini_temp_var.set(f"{tval}{t_unit}" if tval is not None else "---")

        wspd = convert_wind(d.get("wind_avg_ms"), w_unit)
        wdir = deg_to_compass(d.get("wind_dir"))
        self._mini_wind_var.set(
            f"{wspd} {w_unit}  {wdir}" if wspd is not None else f"--- {w_unit}"
        )

        sc = d.get("strike_count")
        self._mini_strike_var.set(f"⚡ {sc}" if sc is not None else "⚡ ---")

    # ──────────────────────────────────────────────────── UDP listener ─────

    def _start_listener(self):
        threading.Thread(target=self._listen_loop, daemon=True).start()

    def _listen_loop(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", UDP_PORT))
            self.after(0, lambda: self._status_var.set(
                f"Listening on UDP :{UDP_PORT}"))
        except OSError as e:
            self.after(0, lambda: self._status_var.set(f"Socket error: {e}"))
            return

        while True:
            try:
                data, addr = sock.recvfrom(4096)
                msg = json.loads(data.decode("utf-8"))
                self.after(0, lambda m=msg, a=addr: self._handle_message(m, a))
            except Exception:
                pass

    def _ts(self, epoch):
        try:
            return datetime.fromtimestamp(epoch).strftime("%H:%M:%S")
        except Exception:
            return str(epoch)

    def _handle_message(self, msg, addr):
        mtype = msg.get("type")
        now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if mtype == "obs_st":
            obs = msg.get("obs", [[]])[0]
            if len(obs) >= 17:
                self._data.update({
                    "wind_lull_ms":    obs[1],
                    "wind_avg_ms":     obs[2],
                    "wind_gust_ms":    obs[3],
                    "wind_dir":        obs[4],
                    "pres_mb":         obs[6],
                    "temp_c":          obs[7],
                    "rh":              obs[8],
                    "uv":              obs[10],
                    "solar":           obs[11],
                    "rain_mm":         obs[12],
                    "precip_type":     obs[13],
                    "strike_dist_km":  obs[14],
                    "strike_count":    obs[15],
                    "battery":         obs[16],
                })
                self._update_var.set(now)
                self._device_var.set(
                    f"Device: {msg.get('serial_number', addr[0])}")
                self._refresh_display()

        elif mtype == "obs_air":
            obs = msg.get("obs", [[]])[0]
            if len(obs) >= 7:
                self._data.update({
                    "pres_mb":         obs[1],
                    "temp_c":          obs[2],
                    "rh":              obs[3],
                    "strike_count":    obs[4],
                    "strike_dist_km":  obs[5],
                    "battery":         obs[6],
                })
                self._update_var.set(now)
                self._refresh_display()

        elif mtype == "obs_sky":
            obs = msg.get("obs", [[]])[0]
            if len(obs) >= 13:
                self._data.update({
                    "uv":              obs[2],
                    "rain_mm":         obs[3],
                    "wind_lull_ms":    obs[4],
                    "wind_avg_ms":     obs[5],
                    "wind_gust_ms":    obs[6],
                    "wind_dir":        obs[7],
                    "solar":           obs[10],
                    "precip_type":     obs[12],
                })
                self._update_var.set(now)
                self._refresh_display()

        elif mtype == "rapid_wind":
            ob = msg.get("ob", [])
            if len(ob) >= 3:
                self._last_rapid_wind = {
                    "speed_ms": ob[1],
                    "dir_deg":  ob[2],
                    "ts":       self._ts(ob[0]),
                }
                self._refresh_display()

        elif mtype == "evt_strike":
            evt = msg.get("evt", [])
            if len(evt) >= 3:
                self._last_strike = {
                    "dist_km": evt[1],
                    "energy":  evt[2],
                    "ts":      self._ts(evt[0]),
                }
                self._refresh_display()

        elif mtype == "evt_precip":
            evt = msg.get("evt", [])
            if evt:
                self._last_precip_time = self._ts(evt[0])
                self._refresh_display()

        # Keep status short — it's in the title bar and drives window width
        self._status_var.set(f"{mtype}  @  {datetime.now().strftime('%H:%M:%S')}")


if __name__ == "__main__":
    app = TempestMonitor()
    app.mainloop()
