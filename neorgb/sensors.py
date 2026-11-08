"""Temperature sources: every hwmon temp input plus a few friendly aliases."""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

HWMON = Path("/sys/class/hwmon")


@dataclass
class Sensor:
    id: str
    label: str
    path: str | None = None      # sysfs temp*_input, None for device sensors
    value: float | None = None
    ts: float = 0.0


def _read(p: Path) -> str:
    try:
        return p.read_text().strip()
    except OSError:
        return ""


def _pci_of(hw: Path) -> str:
    real = os.path.realpath(hw / "device")
    return os.path.basename(real)


class Sensors:
    """Reads hwmon temps.  Device sensors (AIO liquid) are pushed in by drivers."""

    def __init__(self) -> None:
        self.sensors: dict[str, Sensor] = {}
        self.history: dict[str, deque] = {}
        self._scan()

    def _scan(self) -> None:
        found: dict[str, Sensor] = {}
        if HWMON.exists():
            dgpu = None
            for hw in sorted(HWMON.iterdir()):
                name = _read(hw / "name")
                if name == "amdgpu":
                    # the discrete card is the one with a fan / power cap
                    if (hw / "fan1_input").exists() or (hw / "power1_cap").exists():
                        dgpu = hw
            for hw in sorted(HWMON.iterdir()):
                name = _read(hw / "name")
                pci = _pci_of(hw)
                for inp in sorted(hw.glob("temp*_input")):
                    idx = inp.name[4:-6]
                    label = _read(hw / f"temp{idx}_label") or f"temp{idx}"
                    sid = f"hwmon:{name}:{pci}:{label}"
                    nice = f"{name} {label}"
                    if name == "amdgpu":
                        nice = f"{'GPU' if hw == dgpu else 'iGPU'} {label}"
                    elif name == "k10temp" or name == "coretemp":
                        nice = f"CPU {label}"
                    elif name == "nvme":
                        nice = f"NVMe {label}"
                    found[sid] = Sensor(sid, nice, str(inp))
                    # aliases
                    if name in ("k10temp", "coretemp") and label in ("Tctl", "Package id 0"):
                        found["cpu"] = Sensor("cpu", "CPU", str(inp))
                    if hw == dgpu and label == "junction":
                        found["gpu"] = Sensor("gpu", "GPU (Hotspot)", str(inp))
                    if hw == dgpu and label == "edge" and "gpu" not in found:
                        found["gpu"] = Sensor("gpu", "GPU", str(inp))
        for sid, s in self.sensors.items():
            if s.path is None:
                found[sid] = s
        self.sensors = found

    def push(self, sid: str, label: str, value: float | None) -> None:
        s = self.sensors.get(sid)
        if s is None:
            s = self.sensors[sid] = Sensor(sid, label)
        s.value = value
        s.ts = time.monotonic()
        self._remember(sid, value)

    def _remember(self, sid: str, value: float | None) -> None:
        if value is None:
            return
        h = self.history.setdefault(sid, deque(maxlen=600))
        h.append((time.time(), value))

    def update(self) -> None:
        now = time.monotonic()
        for s in self.sensors.values():
            if s.path is None:
                continue
            raw = _read(Path(s.path))
            try:
                s.value = int(raw) / 1000.0
                s.ts = now
            except ValueError:
                s.value = None
            self._remember(s.id, s.value)

    def get(self, sid: str, max_age: float = 10.0) -> float | None:
        s = self.sensors.get(sid)
        if s is None or s.value is None:
            return None
        if time.monotonic() - s.ts > max_age:
            return None
        return s.value

    def average(self, sid: str, seconds: float) -> float | None:
        """Mean over the last `seconds`; smooths AMD Tctl spikes."""
        h = self.history.get(sid)
        if not h:
            return self.get(sid)
        cutoff = time.time() - seconds
        vals = [v for t, v in h if t >= cutoff]
        if not vals:
            return self.get(sid)
        return sum(vals) / len(vals)

    def listing(self) -> list[dict]:
        order = {"liquid": 0, "cpu": 1, "gpu": 2}
        items = sorted(self.sensors.values(), key=lambda s: (order.get(s.id, 9), s.label))
        return [{"id": s.id, "label": s.label, "value": s.value} for s in items]
