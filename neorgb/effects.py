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
    "off":         {"name": "Aus", "params": []},
}


class EffectEngine:
    def __init__(self) -> None:
        self.state: dict[str, dict] = {}

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
        else:
            px = [colors[0]] * n

        bri = max(0.0, min(100.0, float(spec.get("brightness", 100)))) / 100.0
        bri = bri ** 2  # perceptual
        for i, c in enumerate(px[:n]):
            out[i * 3] = max(0, min(255, int(c[0] * bri + 0.5)))
            out[i * 3 + 1] = max(0, min(255, int(c[1] * bri + 0.5)))
            out[i * 3 + 2] = max(0, min(255, int(c[2] * bri + 0.5)))
        return out

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
