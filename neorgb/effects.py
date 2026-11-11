"""Software lighting effects.

Every effect renders one zone (a chain of LEDs) into R,G,B bytes.  A zone may
be split into segments (one per fan or strip) so ring effects run on each
fan separately.
"""

from __future__ import annotations

import colorsys
import math
import random
from dataclasses import dataclass, field


@dataclass
class Zone:
    id: str
    device: str
    name: str
    leds: int
    segments: list[int] = field(default_factory=list)   # LEDs per sub device
    kind: str = "linear"                                  # linear | ring | single

    def segs(self) -> list[int]:
        if self.segments and sum(self.segments) == self.leds:
            return self.segments
        return [self.leds] if self.leds else []


def hex_to_rgb(s: str) -> tuple[int, int, int]:
    s = (s or "#000000").lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return 0, 0, 0


def mix(a, b, f: float):
    f = max(0.0, min(1.0, f))
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f)


def hsv(h: float, s: float = 1.0, v: float = 1.0):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return r * 255, g * 255, b * 255


def palette(colors: list[tuple], x: float):
    """Smooth cyclic gradient through colors, x in [0,1)."""
    if not colors:
        return (0, 0, 0)
    if len(colors) == 1:
        return colors[0]
    x = (x % 1.0) * len(colors)
    i = int(x)
    return mix(colors[i % len(colors)], colors[(i + 1) % len(colors)], x - i)


def _speed(p: dict, slow: float, fast: float) -> float:
    """Map speed 0..100 to a period in seconds (slow..fast)."""
    s = max(0.0, min(100.0, float(p.get("speed", 50)))) / 100.0
    return slow * (fast / slow) ** s


EFFECTS = {
    "static":      {"name": "Statisch", "params": ["colors1"]},
    "breathing":   {"name": "Atmen", "params": ["colors", "speed"]},
    "spectrum":    {"name": "Farbwechsel", "params": ["speed"]},
    "rainbow":     {"name": "Regenbogen", "params": ["speed", "scale", "reverse"]},
    "gradient":    {"name": "Farbverlauf", "params": ["colors", "speed", "scale", "reverse"]},
    "spin":        {"name": "Kreisen", "params": ["colors2", "speed", "tail", "reverse"]},
    "comet":       {"name": "Komet", "params": ["colors2", "speed", "tail", "reverse"]},
    "twinkle":     {"name": "Funkeln", "params": ["colors", "background", "speed", "density"]},
    "temperature": {"name": "Temperatur", "params": ["sensor", "temp_low", "temp_high", "colors2"]},
    "screen":      {"name": "Bildschirm", "params": ["screen_area", "speed", "saturation", "reverse"]},
    "off":         {"name": "Aus", "params": []},
}


# Settings every effect shares.  Everything else (colours, speed, ...) belongs
# to the effect that is active and is parked in "by_effect" on a switch.
SHARED_KEYS = ("effect", "by_effect", "min_brightness")


def patch_spec(spec: dict, patch: dict) -> dict:
    """Apply a GUI change to a lighting spec in place.

    Switching the effect stores the old effect's settings and brings back the
    ones the new effect had last time (or keeps the current ones the first time).
    """
    old = spec.get("effect", "static")
    new = patch.get("effect", old)
    if new != old:
        per = spec.setdefault("by_effect", {})
        per[old] = {k: v for k, v in spec.items() if k not in SHARED_KEYS}
        spec.update(per.get(new, {}))
        spec["effect"] = new
    spec.update({k: v for k, v in patch.items() if k not in ("effect", "by_effect")})
    return spec


def snapshot_spec(spec: dict) -> dict:
    """The active effect with its settings, without the parked ones."""
    return {k: v for k, v in spec.items() if k != "by_effect"}


def load_snapshot(spec: dict, snap: dict) -> dict:
    """Bring back a saved effect; the effect that was active is parked as on a switch."""
    patch_spec(spec, {"effect": snap.get("effect", "static")})
    for k in [k for k in spec if k not in SHARED_KEYS]:
        del spec[k]
    spec.update({k: v for k, v in snap.items() if k != "by_effect"})
    return spec


class EffectEngine:
    def __init__(self) -> None:
        self.state: dict[str, dict] = {}
        self.screen = None        # ScreenCapture, set by the daemon
        self._scache: tuple = (None, {})

    def _screen(self, zone: Zone, spec: dict, t: float) -> list[tuple]:
        """Colours from the screen: the whole picture, or the screen edge around each fan."""
        from .screen import sample
        n = zone.leds
        frame = self.screen.frame() if self.screen else None
        st = self.state.setdefault(zone.id + ":scr", {"px": [(0.0, 0.0, 0.0)] * n, "last": t})
        if len(st["px"]) != n:
            st["px"] = [(0.0, 0.0, 0.0)] * n
        if frame is None:
            return st["px"]
        if self._scache[0] is not frame:           # one sample per rectangle and frame, shared by all zones
            self._scache = (frame, {})
        memo = self._scache[1]

        def smp(*r):
            r = tuple(round(v, 4) for v in r)
            if r not in memo:
                memo[r] = sample(frame, *r)
            return memo[r]
        if spec.get("screen_area", "edges") == "full":
            target = [smp(0, 0, 1, 1)] * n
        else:
            target = []
            rev = bool(spec.get("reverse"))
            if zone.kind == "ring":
                for size in zone.segs():
                    for i in range(size):
                        a = (i / size) * 2 * math.pi * (-1 if rev else 1)
                        # point on the screen border in this direction, LED 0 at the top
                        dx, dy = math.sin(a), -math.cos(a)
                        k = 0.5 / max(abs(dx), abs(dy))
                        cx, cy = 0.5 + dx * k, 0.5 + dy * k
                        d = 0.12
                        target.append(smp(max(0, cx - d), max(0, cy - d), min(1, cx + d), min(1, cy + d)))
            else:
                for i in range(n):
                    x = (n - 1 - i if rev else i) / n
                    target.append(smp(x, 0, x + 1 / n, 1))
        sat = float(spec.get("saturation", 40)) / 100.0
        if sat:
            out = []
            for r, g, b in target:
                m = (r + g + b) / 3
                f = 1 + 1.5 * sat
                out.append((max(0, min(255, m + (r - m) * f)), max(0, min(255, m + (g - m) * f)), max(0, min(255, m + (b - m) * f))))
            target = out
        dt = max(0.0, min(0.5, t - st["last"]))
        st["last"] = t
        tau = _speed(spec, 1.0, 0.03)          # seconds to follow a change
        f = 1 - math.exp(-dt / tau) if tau > 0 else 1.0
        st["px"] = [mix(a, b, f) for a, b in zip(st["px"], target)]
        return st["px"]

    def render(self, zone: Zone, spec: dict, t: float, sensors=None) -> bytearray:
        n = zone.leds
        out = bytearray(n * 3)
        if n == 0:
            return out
        eff = spec.get("effect", "static")
        colors = [hex_to_rgb(c) for c in spec.get("colors", ["#ffffff"])] or [(255, 255, 255)]
        px: list[tuple] = []

        if eff == "off":
            return out
        elif eff == "static":
            px = [colors[0]] * n
        elif eff == "breathing":
            period = _speed(spec, 8.0, 1.5)
            cycle = t / period
            c = colors[int(cycle) % len(colors)]
            v = (1 - math.cos((cycle % 1.0) * 2 * math.pi)) / 2
            v = 0.03 + 0.97 * v * v
            px = [(c[0] * v, c[1] * v, c[2] * v)] * n
        elif eff == "spectrum":
            period = _speed(spec, 40.0, 3.0)
            px = [hsv(t / period)] * n
        elif eff in ("rainbow", "gradient"):
            period = _speed(spec, 20.0, 1.5)
            scale = float(spec.get("scale", 1.0)) or 1.0
            sign = -1 if spec.get("reverse") else 1
            phase = sign * t / period if float(spec.get("speed", 50)) > 0 else 0.0
            pos = self._positions(zone)
            if eff == "rainbow":
                px = [hsv(p * scale - phase) for p in pos]
            else:
                px = [palette(colors, p * scale - phase) for p in pos]
        elif eff in ("spin", "comet"):
            fg = colors[0]
            bg = colors[1] if len(colors) > 1 else (0, 0, 0)
            period = _speed(spec, 6.0, 0.6)
            tail = max(1.0, float(spec.get("tail", 3)))
            sign = -1 if spec.get("reverse") else 1
            segs = zone.segs() if eff == "spin" else [n]
            for size in segs:
                head = ((sign * t / period) % 1.0) * size
                for i in range(size):
                    d = (head - i) % size
                    f = max(0.0, 1.0 - d / tail) if d < tail else 0.0
                    px.append(mix(bg, fg, f * f))
        elif eff == "twinkle":
            st = self.state.setdefault(zone.id + ":tw", {"leds": [0.0] * n, "hue": [0] * n, "last": t})
            if len(st["leds"]) != n:
                st["leds"], st["hue"] = [0.0] * n, [0] * n
            dt = max(0.0, min(0.2, t - st["last"]))
            st["last"] = t
            fade = dt / (_speed(spec, 3.0, 0.4))
            density = float(spec.get("density", 30)) / 100.0
            bg = hex_to_rgb(spec.get("background", "#000000"))
            for i in range(n):
                st["leds"][i] = max(0.0, st["leds"][i] - fade)
                if st["leds"][i] <= 0 and random.random() < density * dt * 2:
                    st["leds"][i] = 1.0
                    st["hue"][i] = random.randrange(len(colors))
                v = st["leds"][i]
                v = math.sin(v * math.pi) if v > 0 else 0.0
                px.append(mix(bg, colors[st["hue"][i]], v))
        elif eff == "temperature":
            lo = float(spec.get("temp_low", 30))
            hi = float(spec.get("temp_high", 80))
            cold = colors[0]
            hot = colors[1] if len(colors) > 1 else (255, 0, 0)
            temp = sensors.get(spec.get("sensor", "cpu")) if sensors else None
            if temp is None:
                f = (math.sin(t * 6) + 1) / 2  # blink: sensor missing
                px = [mix((0, 0, 0), (255, 120, 0), f)] * n
            else:
                f = (temp - lo) / (hi - lo) if hi > lo else 1.0
                mid = colors[2] if len(colors) > 2 else None
                if mid is not None:
                    c = mix(cold, mid, f * 2) if f < 0.5 else mix(mid, hot, (f - 0.5) * 2)
                else:
                    c = mix(cold, hot, f)
                px = [c] * n
        elif eff == "screen":
            px = self._screen(zone, spec, t)
        else:
            px = [colors[0]] * n

        bri = max(0.0, min(100.0, float(spec.get("brightness", 100)))) / 100.0
        bri = bri ** 2  # perceptual
        for i, c in enumerate(px[:n]):
            out[i * 3] = max(0, min(255, int(c[0] * bri + 0.5)))
            out[i * 3 + 1] = max(0, min(255, int(c[1] * bri + 0.5)))
            out[i * 3 + 2] = max(0, min(255, int(c[2] * bri + 0.5)))
        floor = max(0.0, min(100.0, float(spec.get("min_brightness", 0) or 0))) / 100.0
        if floor > 0:
            self._apply_floor(out, floor, spec, colors)
        return out

    @staticmethod
    def _apply_floor(out: bytearray, floor: float, spec: dict, colors: list[tuple]) -> None:
        """No LED gets darker than ``floor`` (0..1, same perceptual scale as brightness).

        Dim LEDs are lifted keeping their colour.  Black ones take the
        background (if the effect has one) or the effect's first colour.
        """
        target = 255.0 * floor * floor
        bg = hex_to_rgb(spec.get("background", "#000000"))
        fill = bg if max(bg) > 0 else colors[0]
        if max(fill) == 0:
            fill = (255, 255, 255)
        for i in range(0, len(out), 3):
            r, g, b = out[i], out[i + 1], out[i + 2]
            v = max(r, g, b)
            if v >= target:
                continue
            if v == 0:
                r, g, b = fill
                v = max(fill)
            k = target / v
            out[i] = min(255, int(r * k + 0.5))
            out[i + 1] = min(255, int(g * k + 0.5))
            out[i + 2] = min(255, int(b * k + 0.5))

    @staticmethod
    def _positions(zone: Zone) -> list[float]:
        """0..1 position of each LED.  Rings map around the fan, strips along."""
        pos: list[float] = []
        if zone.kind == "ring":
            for size in zone.segs():
                pos += [i / size for i in range(size)]
        else:
            n = zone.leds
            pos = [i / n for i in range(n)]
        return pos
