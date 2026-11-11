"""Fans on the mainboard (Super-I/O chips such as NCT67xx) and on AMD GPUs.

Mainboard headers are driven through hwmon ``pwmN`` / ``pwmN_enable``.  A
header only leaves BIOS control once the user gives it a curve or a fixed
value; until then NeoRGB just shows its speed.  On stop, every header goes
back to the mode it had before (kept in a backup file, so this also works
after a crash).

AMD GPUs from RDNA3 on are not driven by ``pwm1`` but by a fan curve the
GPU runs itself (``gpu_od/fan_ctrl/fan_curve``).  That interface exists
only with ``amdgpu.ppfeaturemask`` bit 0x4000 (overdrive) set.  Without it
the GPU fan is shown read-only.

Writing to sysfs needs the udev rule from packaging/60-neorgb.rules.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path

from ..config import CONFIG_DIR
from ..fancontrol import interpolate

log = logging.getLogger("neorgb.hwmon")

HWMON = Path("/sys/class/hwmon")
GPU_POINTS = 5          # the GPU firmware takes exactly five curve points
PERM_HINT = "Keine Schreibrechte. Einmal ausführen, dann neu starten:"
PERM_CMD = "sudo usermod -aG neorgb $USER"
OD_PARAM = "amdgpu.ppfeaturemask=0xfff7ffff"


def overdrive_hint() -> tuple[str, str]:
    """Why the GPU fan is read-only, and what to do about it."""
    cmdline = _read(Path("/proc/cmdline")) or ""
    if "amdgpu.ppfeaturemask" in cmdline:
        return ("Lüfter nur ablesbar: Der Kernel-Parameter ist gesetzt, aber der Treiber bietet "
                "keine Lüftersteuerung an.", "")
    for f in ("/etc/default/grub", "/etc/kernel/cmdline", "/etc/default/limine"):
        if "amdgpu.ppfeaturemask" in (_read(Path(f)) or ""):
            return "Lüfter nur ablesbar: Overdrive ist eingetragen und greift nach dem nächsten Neustart.", ""
    return ("Lüfter nur ablesbar. Das ist kein Befehl, sondern ein Kernel-Parameter: im Bootloader "
            "anhängen (GRUB: GRUB_CMDLINE_LINUX_DEFAULT in /etc/default/grub), dann neu starten.", OD_PARAM)


def _read(p: Path) -> str | None:
    try:
        return p.read_text().strip()
    except OSError:
        return None


def _write(p: Path, v) -> None:
    p.write_text(f"{v}\n")


def _int(p: Path) -> int | None:
    s = _read(p)
    try:
        return int(s) if s is not None else None
    except ValueError:
        return None


# ------------------------------------------------------------ mainboard
class BoardChip:
    """One Super-I/O chip with its PWM headers."""

    kind = "hwmon_fans"

    def __init__(self, daemon, path: Path, name: str):
        self.d = daemon
        self.path = path
        self.chip = name
        self.key = f"hwmon:{name}"
        self.ports = sorted(int(m.group(1)) for f in path.iterdir()
                            if (m := re.fullmatch(r"pwm(\d+)_enable", f.name)))
        self.backup_file = CONFIG_DIR / "backup" / f"hwmon-{name}.json"
        self.orig: dict[str, int] = self._load_backup()
        self.owned: set[int] = set()       # headers NeoRGB currently drives
        self.last: dict[int, tuple[int, float]] = {}
        self.writable = all(os.access(path / f"pwm{p}", os.W_OK) and os.access(path / f"pwm{p}_enable", os.W_OK)
                            for p in self.ports)
        self.fans: list[dict] = []

    def _load_backup(self) -> dict[str, int]:
        try:
            return {k: int(v) for k, v in json.loads(self.backup_file.read_text()).items()}
        except (OSError, ValueError):
            return {}

    def _remember(self, port: int) -> None:
        if str(port) in self.orig:
            return
        en = _int(self.path / f"pwm{port}_enable")
        if en is None or en == 1:   # 1 = manual: not a mode worth restoring to
            en = 5 if self.chip.startswith("nct") else 2
        self.orig[str(port)] = en
        self.backup_file.parent.mkdir(parents=True, exist_ok=True)
        self.backup_file.write_text(json.dumps(self.orig))

    def poll(self) -> None:
        seen = set(self.d.device_cfg(self.key).get("seen_ports", []))
        new_seen = False
        fans = []
        for p in self.ports:
            rpm = _int(self.path / f"fan{p}_input")
            fid = f"{self.key}/fan{p}"
            if rpm and p not in seen:
                seen.add(p)
                new_seen = True
            ch = self.d.cfg.data["cooling"]["channels"].get(fid)
            if p not in seen and not (ch and ch.get("mode") != "hardware"):
                continue          # nothing ever spun on this header
            label = _read(self.path / f"fan{p}_label")
            fans.append({"id": fid, "port": p, "pump": False, "name": label or f"Mainboard {p}",
                         "rpm": rpm or 0, "duty": self.last.get(p, (None,))[0],
                         "source": "board", "hw_name": "BIOS", "writable": self.writable,
                         "default_cfg": {"mode": "hardware", "curve": "balanced", "fixed": 50}})
        self.fans = fans
        if new_seen:
            with self.d.cfg.lock:
                self.d.cfg.data["devices"].setdefault(self.key, {})["seen_ports"] = sorted(seen)
            self.d.cfg.mark()

    def apply(self, duties: dict[int, float | None]) -> None:
        """duties: port -> percent, None = back to BIOS control."""
        if not self.writable:
            return
        now = time.monotonic()
        for p, duty in duties.items():
            base = self.path / f"pwm{p}"
            try:
                if duty is None:
                    if p in self.owned:
                        _write(self.path / f"pwm{p}_enable", self.orig.get(str(p), 5))
                        self.owned.discard(p)
                        self.last.pop(p, None)
                    continue
                if p not in self.owned:
                    self._remember(p)
                    _write(self.path / f"pwm{p}_enable", 1)
                    self.owned.add(p)
                val = max(0, min(255, round(duty * 255 / 100)))
                prev = self.last.get(p)
                if prev is None or prev[0] != round(duty) or now - prev[1] > 5:
                    _write(base, val)
                    self.last[p] = (round(duty), now)
            except OSError as e:
                log.warning("%s pwm%d: %s", self.chip, p, e)

    def release(self) -> None:
        self.apply({p: None for p in list(self.owned)})

    def restore_after_crash(self) -> None:
        """Headers left in manual mode by a crashed run go back to BIOS control."""
        if not self.writable:
            return
        for p, en in self.orig.items():
            if _int(self.path / f"pwm{p}_enable") == 1:
                try:
                    _write(self.path / f"pwm{p}_enable", en)
                except OSError:
                    pass

    def describe(self) -> dict:
        return {"key": self.key, "kind": self.kind, "name": f"Mainboard-Lüfter · {self.chip.upper()}",
                "label": "", "firmware": "", "status": "ok" if self.writable else "error",
                "error": "" if self.writable else PERM_HINT, "fix_cmd": "" if self.writable else PERM_CMD,
                "path": str(self.path),
                "zones": [], "fans": [f["id"] for f in self.fans]}


# ------------------------------------------------------------------ GPU
class AmdGpu:
    kind = "amdgpu_fan"

    def __init__(self, daemon, path: Path):
        self.d = daemon
        self.path = path
        dev = (path / "device").resolve()
        self.pci = dev.name
        self.key = f"amdgpu:{self.pci}"
        self.curve_file = dev / "gpu_od" / "fan_ctrl" / "fan_curve"
        self.zero_rpm_file = dev / "gpu_od" / "fan_ctrl" / "fan_zero_rpm_enable"
        self.has_od = self.curve_file.exists()
        self.writable = self.has_od and os.access(self.curve_file, os.W_OK)
        self.temp_range = (25, 100)
        self.duty_range = (20, 100)
        self._parse_ranges()
        self.owned = False
        self.sent: list[tuple[int, int]] | None = None
        self.zero_rpm_orig: str | None = None   # set while NeoRGB switched zero-RPM off
        self.fans: list[dict] = []

    def _parse_ranges(self) -> None:
        txt = _read(self.curve_file) if self.has_od else None
        if not txt:
            return
        m = re.search(r"temp\)?:\s*(\d+)C\s+(\d+)C", txt)
        if m:
            self.temp_range = (int(m.group(1)), int(m.group(2)))
        m = re.search(r"speed\)?:\s*(\d+)%\s+(\d+)%", txt)
        if m:
            self.duty_range = (int(m.group(1)), int(m.group(2)))

    def poll(self) -> None:
        rpm = _int(self.path / "fan1_input")
        if rpm is None:
            self.fans = []
            return
        self.fans = [{"id": f"{self.key}/fan", "port": 0, "pump": False, "name": "Grafikkarte",
                      "rpm": rpm, "duty": None, "source": "gpu", "hw_name": "GPU", "writable": self.writable,
                      "hint": "" if self.has_od else "Nur Anzeige: Overdrive ist aus (siehe Geräte)",
                      "default_cfg": {"mode": "hardware", "curve": "gpu", "fixed": 50}}]

    def points_for(self, cfg: dict, curves: dict) -> list[tuple[int, int]] | None:
        """The GPU runs the curve itself, against its hotspot temperature."""
        lo_t, hi_t = self.temp_range
        lo_d, hi_d = self.duty_range
        if cfg.get("mode") == "fixed":
            d = max(lo_d, min(hi_d, int(cfg.get("fixed", 50))))
            pts = [(lo_t + (hi_t - lo_t) * i // (GPU_POINTS - 1), d) for i in range(GPU_POINTS)]
        elif cfg.get("mode") == "curve":
            cur = curves.get(cfg.get("curve", "")) or {}
            if not self.is_gpu_sensor(cur.get("sensor", "")):
                return None   # the GPU only knows its own temperature
            src = sorted(cur.get("points") or [])
            if len(src) < 2:
                return None
            a, b = max(lo_t, src[0][0]), min(hi_t, src[-1][0])
            if b <= a:
                a, b = lo_t, hi_t
            pts = []
            for i in range(GPU_POINTS):
                t = a + (b - a) * i / (GPU_POINTS - 1)
                pts.append((int(round(t)), max(lo_d, min(hi_d, int(round(interpolate(src, t)))))))
        else:
            return None
        return pts

    @staticmethod
    def is_gpu_sensor(sid: str) -> bool:
        return sid == "gpu" or sid.startswith("hwmon:amdgpu")

    def set_zero_rpm(self, allow: bool) -> None:
        """Zero-RPM stops the fans below a temperature.  A fixed speed should really spin."""
        if not self.zero_rpm_file.exists() or not os.access(self.zero_rpm_file, os.W_OK):
            return
        try:
            if not allow and self.zero_rpm_orig is None:
                txt = _read(self.zero_rpm_file) or ""
                self.zero_rpm_orig = "1" if re.search(r"^\s*1\s*$", txt, re.M) else "0"
                _write(self.zero_rpm_file, "0")
                _write(self.zero_rpm_file, "c")
            elif allow and self.zero_rpm_orig is not None:
                _write(self.zero_rpm_file, self.zero_rpm_orig)
                _write(self.zero_rpm_file, "c")
                self.zero_rpm_orig = None
        except OSError as e:
            log.warning("GPU %s zero-RPM: %s", self.pci, e)

    def apply(self, pts: list[tuple[int, int]] | None, fixed: bool = False) -> None:
        if not self.writable:
            return
        self.set_zero_rpm(not (fixed and pts is not None))
        try:
            if pts is None:
                if self.owned:
                    _write(self.curve_file, "r")
                    self.owned, self.sent = False, None
                return
            if pts == self.sent:
                return
            for i, (t, d) in enumerate(pts):
                _write(self.curve_file, f"{i} {t} {d}")
            _write(self.curve_file, "c")
            self.owned, self.sent = True, pts
            log.info("GPU %s: Lüfterkurve %s", self.pci, pts)
        except OSError as e:
            log.warning("GPU %s fan_curve: %s", self.pci, e)

    def release(self) -> None:
        self.apply(None)

    def describe(self) -> dict:
        err = cmd = ""
        if not self.has_od:
            err, cmd = overdrive_hint()
        elif not self.writable:
            err, cmd = PERM_HINT, PERM_CMD
        return {"key": self.key, "kind": self.kind, "name": "Grafikkarte (AMD)", "label": "", "firmware": "",
                "status": "ok" if self.writable else ("readonly" if not self.has_od else "error"), "error": err, "fix_cmd": cmd,
                "path": self.pci, "zones": [], "fans": [f["id"] for f in self.fans]}


# --------------------------------------------------------------- source
class HwmonFans(threading.Thread):
    """Daemon extra source: finds the chips and runs them once a second."""

    def __init__(self, daemon):
        super().__init__(daemon=True, name="hwmon-fans")
        self.d = daemon
        self.boards: list[BoardChip] = []
        self.gpus: list[AmdGpu] = []
        self.stop_evt = threading.Event()
        self._lock = threading.Lock()
        self._discover()

    def _discover(self) -> None:
        for h in sorted(HWMON.glob("hwmon*")):
            name = _read(h / "name") or ""
            if name == "amdgpu":
                if (h / "fan1_input").exists():
                    self.gpus.append(AmdGpu(self.d, h))
            elif any(h.glob("pwm*_enable")):
                self.boards.append(BoardChip(self.d, h, name))
        for b in self.boards:
            b.restore_after_crash()

    def chips(self) -> list:
        return [c for c in self.boards + self.gpus if not self.d.device_cfg(c.key).get("disabled")]

    # ---- interface used by the daemon
    def zones(self) -> list:
        return []

    def submit(self, frames: dict) -> None:
        pass

    def reload(self) -> None:
        pass              # exclusions are read on every tick

    def fans(self) -> list[dict]:
        return [f for c in self.chips() for f in c.fans]

    def describe(self) -> list[dict]:
        out = []
        for c in self.boards + self.gpus:
            d = c.describe()
            if self.d.device_cfg(c.key).get("disabled"):
                d.update(status="disabled", error="", fix_cmd="", fans=[])
            out.append(d)
        return out

    def run(self) -> None:
        last = time.monotonic()
        while not self.stop_evt.wait(1.0):
            now = time.monotonic()
            dt, last = now - last, now
            try:
                with self._lock:
                    self.tick(dt)
            except Exception as e:  # noqa: BLE001
                log.warning("hwmon fans: %s", e)

    def tick(self, dt: float) -> None:
        cooling = self.d.cfg.data["cooling"]
        liquid = self.d.sensors.get("liquid")
        active = self.chips()
        for c in self.boards + self.gpus:
            if c not in active:
                c.release()
        for c in active:
            c.poll()
            if isinstance(c, BoardChip):
                duties = {}
                for f in c.fans:
                    ch = self.d.fan_cfg(f)
                    duties[f["port"]] = self.d.fanctl.step(f["id"], ch, cooling["curves"], self.d.sensors, dt,
                                                           cooling.get("settings", {}), 0, liquid)
                c.apply(duties)
                for f in c.fans:
                    if f["port"] in c.owned:
                        f["duty"] = c.last.get(f["port"], (None,))[0]
            else:
                for f in c.fans:
                    ch = self.d.fan_cfg(f)
                    c.apply(c.points_for(ch, cooling["curves"]), fixed=ch.get("mode") == "fixed")
                    cur = cooling["curves"].get(ch.get("curve", "")) or {}
                    if ch.get("mode") == "curve" and not c.is_gpu_sensor(cur.get("sensor", "")):
                        f["mode_note"] = "Diese Kurve nutzt keinen GPU-Sensor. Die Karte regelt weiter selbst."
                    elif c.owned:
                        f["mode_note"] = "Kurve läuft in der Grafikkarte (Hotspot)"
                    else:
                        f["mode_note"] = ""

    def close(self) -> None:
        self.stop_evt.set()
        with self._lock:
            for c in self.boards + self.gpus:
                c.release()
