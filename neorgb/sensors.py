"""Temperature sources: every hwmon temp input plus a few friendly aliases.

Each hwmon chip is read by its own thread.  A chip whose sysfs reads hang
(e.g. amdgpu with a stuck SMU takes seconds per read) then only goes stale
itself and cannot make the other sensors look old.
"""

from __future__ import annotations

import os
import threading
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
    chip: str = ""               # hwmon dir; one reader thread per chip


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

    INTERVAL = 1.0

    def __init__(self) -> None:
        self.sensors: dict[str, Sensor] = {}
        self.history: dict[str, deque] = {}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
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
                    chip = str(hw)
                    found[sid] = Sensor(sid, nice, str(inp), chip=chip)
                    # aliases
                    if name in ("k10temp", "coretemp") and label in ("Tctl", "Package id 0"):
                        found["cpu"] = Sensor("cpu", "CPU", str(inp), chip=chip)
                    if hw == dgpu and label == "junction":
                        found["gpu"] = Sensor("gpu", "GPU (Hotspot)", str(inp), chip=chip)
                    if hw == dgpu and label == "edge" and "gpu" not in found:
                        found["gpu"] = Sensor("gpu", "GPU", str(inp), chip=chip)
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

    def _read_one(self, s: Sensor) -> None:
        raw = _read(Path(s.path))
        try:
            s.value = int(raw) / 1000.0
            s.ts = time.monotonic()
        except ValueError:
            s.value = None
        self._remember(s.id, s.value)

    def update(self) -> None:
        """Read everything once, in the caller's thread (tests, before start)."""
        for s in list(self.sensors.values()):
            if s.path is not None:
                self._read_one(s)

    def start(self) -> None:
        """One reader thread per hwmon chip."""
        chips: dict[str, list[Sensor]] = {}
        for s in self.sensors.values():
            if s.path is not None:
                chips.setdefault(s.chip, []).append(s)
        for chip, group in chips.items():
            t = threading.Thread(target=self._chip_loop, args=(group,), daemon=True,
                                 name=f"hwmon:{os.path.basename(chip)}")
            t.start()
            self._threads.append(t)

    def _chip_loop(self, group: list[Sensor]) -> None:
        while not self._stop.is_set():
            for s in group:
                self._read_one(s)
            self._stop.wait(self.INTERVAL)

    def stop(self) -> None:
        self._stop.set()

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

    def listing(self, max_age: float = 10.0) -> list[dict]:
        """Stale sensors show as None, so a hung chip reads "–" in the app."""
        order = {"liquid": 0, "cpu": 1, "gpu": 2}
        items = sorted(self.sensors.values(), key=lambda s: (order.get(s.id, 9), s.label))
        return [{"id": s.id, "label": s.label, "value": self.get(s.id, max_age)} for s in items]

    def label(self, sid: str) -> str:
        s = self.sensors.get(sid)
        return s.label if s else sid
