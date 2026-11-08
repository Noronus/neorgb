"""Corsair Lighting Node PRO / CORE (and LS100 / LT100, same protocol).

These hubs are plain addressable-LED drivers: they cannot detect what is
plugged in, so the LED count per channel has to come from the user.  The
firmware also needs that count in an effect config (0x35) or it keeps
whatever an older program stored, which is a common reason for strips that
only light partly or flicker.

Commands (64 byte out, 16 byte in, no report ids):
  02            firmware            -> 00 maj min patch
  32 ch s n c   direct colours, colour plane c (0 R, 1 G, 2 B), n <= 50
  33 ff         commit / apply  (also the keepalive, needed within 20 s)
  34 ch         begin effect
  35 ch ...     effect config: start, count, mode, speed, dir, style, 0, 3 colours, 3 temps
  37 ch         reset channel
  38 ch st      port state 01 hardware, 02 software
  39 ch b       brightness 0..100
"""

from __future__ import annotations

import threading
import time

from ..hidraw import HidDevice, HidError, HidInfo

VID = 0x1B1C
MODELS = {
    0x0C0B: ("Corsair Lighting Node PRO", 2),
    0x0C1A: ("Corsair Lighting Node CORE", 1),
    0x0C1E: ("Corsair LS100 Lighting Kit", 1),
    0x0C23: ("Corsair LT100 Smart Lighting Towers", 2),
}

MAX_LEDS = 204
CHUNK = 50

# Hardware effects (what the hub shows when no software is running)
HW_EFFECTS = {
    "rainbow_wave": 0x00, "color_shift": 0x01, "color_pulse": 0x02, "color_wave": 0x03,
    "static": 0x04, "visor": 0x06, "marquee": 0x07, "blink": 0x08, "sequential": 0x09,
    "rainbow": 0x0A,
}

# Presets for the setup page: name -> LEDs per device
PRESETS = {
    "Corsair RGB LED strip (Lighting Node PRO kit)": 10,
    "iCUE LS100 strip 250 mm": 15,
    "iCUE LS100 strip 350 mm": 21,
    "iCUE LS100 strip 450 mm": 27,
    "HD RGB fan": 12,
    "LL RGB fan": 16,
    "QL RGB fan": 34,
    "ML PRO RGB fan": 4,
    "SP / AF RGB Elite fan (8 LED)": 8,
    "SP RGB fan (1 LED)": 1,
    "LT100 tower": 27,
}


class LightingNode:
    kind = "lighting_node"

    def __init__(self, info: HidInfo):
        self.info = info
        self.name, self.channels = MODELS[info.pid]
        self.dev = HidDevice(info, 64, 16)
        self.lock = threading.RLock()
        self.firmware = ""
        self.counts = [0] * self.channels
        self.software = False
        self.last_commit = 0.0
        self.errors = 0

    def _xfer(self, data: bytes, read: bool = True) -> bytes:
        self.dev.write(data)
        if not read:
            return b""
        try:
            res = self.dev.read(0.1)
        except HidError as e:
            if "gone" in str(e):
                raise
            self.errors += 1
            return b""
        return res

    def open(self) -> None:
        with self.lock:
            self.dev.drain()
            r = self._xfer(b"\x02")
            if len(r) >= 4:
                self.firmware = f"{r[1]}.{r[2]}.{r[3]}"

    def configure(self, counts: list[int]) -> None:
        """Tell the hub how many LEDs hang on each channel and take over."""
        counts = [max(0, min(MAX_LEDS, int(c))) for c in counts[: self.channels]]
        counts += [0] * (self.channels - len(counts))
        with self.lock:
            self.dev.drain()
            for ch, n in enumerate(counts):
                self._xfer(bytes([0x37, ch]))
                if n:
                    self._xfer(bytes([0x35, ch, 0x00, n, HW_EFFECTS["static"], 0, 0, 0, 0,
                                      0x00, 0x00, 0x00]))
                self._xfer(bytes([0x39, ch, 100]))
            self.counts = counts
            self.software = True
            self._xfer(b"\x33\xff")
            self.last_commit = time.monotonic()

    def write_colors(self, per_channel: list[bytes]) -> None:
        """per_channel[ch] = R,G,B bytes for the LEDs on that channel."""
        with self.lock:
            for ch, rgb in enumerate(per_channel[: self.channels]):
                n = min(len(rgb) // 3, self.counts[ch])
                if not n:
                    continue
                self._xfer(bytes([0x38, ch, 0x02]))
                for start in range(0, n, CHUNK):
                    cnt = min(CHUNK, n - start)
                    seg = rgb[start * 3:(start + cnt) * 3]
                    for plane in range(3):
                        self._xfer(bytes([0x32, ch, start, cnt, plane]) + seg[plane::3])
            self._xfer(b"\x33\xff")
            self.last_commit = time.monotonic()
            self.dev.drain()

    def keepalive(self) -> None:
        if self.software and time.monotonic() - self.last_commit > 5:
            with self.lock:
                self._xfer(b"\x33\xff")
                self.last_commit = time.monotonic()

    def set_hardware_effect(self, effect: str = "rainbow_wave",
                            colors: tuple = ((255, 255, 255), (0, 0, 0), (0, 0, 0)),
                            speed: int = 1) -> None:
        """Store an effect the hub runs on its own (boot, daemon stopped)."""
        mode = HW_EFFECTS.get(effect, 0x00)
        with self.lock:
            for ch, n in enumerate(self.counts):
                self._xfer(bytes([0x37, ch]))
                if not n:
                    continue
                self._xfer(bytes([0x34, ch]))
                self._xfer(bytes([0x38, ch, 0x01]))
                c = [v for rgb in colors for v in rgb]
                self._xfer(bytes([0x35, ch, 0x00, n, mode, speed, 0x00, 0x00, 0x00] + c + [0] * 6))
            self._xfer(b"\x33\xff")
            self.software = False

    def set_hardware_off(self) -> None:
        self.set_hardware_effect("static", ((0, 0, 0), (0, 0, 0), (0, 0, 0)))

    def close(self) -> None:
        self.dev.close()
