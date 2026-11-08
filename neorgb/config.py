"""Persistent settings in ~/.config/neorgb/config.json."""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

from .fancontrol import DEFAULT_CURVES, DEFAULT_SETTINGS

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "neorgb"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "version": 1,
    "lighting": {
        "fps": 30,
        "brightness": 100,
        "global": {"effect": "rainbow", "colors": ["#00e5ff", "#7c4dff"], "speed": 40,
                   "scale": 1.0, "brightness": 100},
        "zones": {},
    },
    "cooling": {
        "settings": dict(DEFAULT_SETTINGS),
        "curves": copy.deepcopy(DEFAULT_CURVES),
        "channels": {},
        "hw_fallback": True,
    },
    "devices": {},
    "openrgb": {"enabled": True, "host": "127.0.0.1", "port": 6744, "spawn": True},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, path: Path = CONFIG_FILE):
        self.path = path
        self.lock = threading.RLock()
        self.data = copy.deepcopy(DEFAULTS)
        self.dirty = False
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError) as e:
            bad = self.path.with_suffix(".broken.json")
            try:
                self.path.rename(bad)
            except OSError:
                pass
            print(f"neorgb: config unreadable ({e}), moved to {bad}, using defaults")
            return
        with self.lock:
            self.data = _merge(DEFAULTS, raw)
            # a user who deleted all curves still needs the built-ins as fallback
            if not self.data["cooling"]["curves"]:
                self.data["cooling"]["curves"] = copy.deepcopy(DEFAULT_CURVES)

    def save(self) -> None:
        with self.lock:
            text = json.dumps(self.data, indent=2, ensure_ascii=False)
            self.dirty = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(text)
        os.replace(tmp, self.path)

    def mark(self) -> None:
        self.dirty = True

    def snapshot(self) -> dict:
        with self.lock:
            return copy.deepcopy(self.data)
