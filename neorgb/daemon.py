"""neorgbd: owns the devices, runs lighting and fan control, serves the UI.

Threads:
  * one worker per USB device (all I/O to that device happens there)
  * render: computes lighting frames at `fps` and hands them to workers
  * main: sensors + fan control once per second, hotplug scan, saving
  * ipc: JSON lines over a Unix socket for the GUI and the CLI
"""

from __future__ import annotations

import copy
import json
import logging
import os
import signal
import socket
import socketserver
import threading
import time
from pathlib import Path

from .config import CONFIG_DIR, Config
from .screen import ScreenCapture
from .devices.hwmon_fans import HwmonFans
from .devices.wled import WLEDBridge
from .effects import EFFECTS, EffectEngine, Zone, load_snapshot, patch_spec, snapshot_spec
from .fancontrol import CRITICAL_LIQUID, DEFAULT_CURVES, FAILSAFE_DUTY, FanController, interpolate
from .hidraw import HidError, HidInfo, enumerate_hidraw
from .sensors import Sensors
from .devices import commander_core as ccmod
from .devices import lighting_node as lnmod

log = logging.getLogger("neorgb")

RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
SOCKET = RUNTIME / "neorgb.sock"


def default_fan_cfg(is_pump: bool) -> dict:
    return {"mode": "curve", "curve": "pump_balanced" if is_pump else "balanced", "fixed": 70 if is_pump else 50}


# ---------------------------------------------------------------- workers
class Worker(threading.Thread):
    kind = "device"

    def __init__(self, daemon: "Daemon", info: HidInfo):
        super().__init__(daemon=True, name=f"dev-{info.path}")
        self.d = daemon
        self.info = info
        self.key = info.key
        self.name = info.name
        self.firmware = ""
        self.zones: list[Zone] = []
        self.fans: list[dict] = []
        self.status = "starting"
        self.error = ""
        self._frame: dict[str, bytes] | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self.stop_evt = threading.Event()
        self.failed_at = 0.0

    # called from other threads
    def submit_frame(self, frame: dict[str, bytes]) -> None:
        with self._lock:
            self._frame = frame
        self._wake.set()

    def take_frame(self) -> dict[str, bytes] | None:
        with self._lock:
            f, self._frame = self._frame, None
        return f

    def stop(self) -> None:
        self.stop_evt.set()
        self._wake.set()

    def run(self) -> None:
        try:
            self.setup()
            self.status = "ok"
            log.info("%s ready (%s)", self.name, self.info.path)
            while not self.stop_evt.is_set():
                self._wake.wait(0.05)
                self._wake.clear()
                self.tick()
        except Exception as e:  # noqa: BLE001 - a device must never kill the daemon
            self.status = "error"
            self.error = str(e)
            self.failed_at = time.monotonic()
            log.warning("%s: %s", self.name, e)
        finally:
            try:
                self.shutdown()
            except Exception as e:  # noqa: BLE001
                log.warning("%s: shutdown: %s", self.name, e)
            if self.status == "ok":
                self.status = "stopped"

    def setup(self) -> None: ...
    def tick(self) -> None: ...
    def shutdown(self) -> None: ...

    def describe(self) -> dict:
        return {"key": self.key, "kind": self.kind, "name": self.name, "label": self.d.device_cfg(self.key).get("label", ""),
                "firmware": self.firmware, "status": self.status, "error": self.error, "path": self.info.path,
                "zones": [z.id for z in self.zones], "fans": [f["id"] for f in self.fans]}


class CommanderCoreWorker(Worker):
    kind = "commander_core"

    def setup(self) -> None:
        cc = self.dev = ccmod.CommanderCore(self.info)
        cc.open()
        self.firmware = cc.firmware
        self.name = f"{cc.aio} · Commander CORE" if cc.aio else cc.name
        self.speed_labels = ["Pumpe"] + [f"Lüfter {i}" for i in range(1, 7)] if cc.has_pump else \
            [f"Lüfter {i}" for i in range(1, 8)]
        self.pending_duties: dict[int, int] | None = None
        self.last_sent: dict[int, int] = {}
        self.last_poll = 0.0
        self.last_conn = 0.0
        self.last_duty_write = 0.0
        self.hw_dirty = True

        cc.enter_software()
        try:   # what the AIO runs on its own; replayed for channels left to the device
            self.hw_cfg = cc.read_hw_config()
        except (HidError, ccmod.ProtocolError):
            self.hw_cfg = None
        self._poll(full=True)
        # set speeds before anything else so nothing spins up or stops
        self.d.fan_tick_worker(self, 1.0)
        self._flush_duties()

        cc.init_led_ports()
        detected = cc.read_led_counts()
        dcfg = self.d.device_cfg(self.key)
        over = dcfg.get("ports", {})
        counts = []
        for i, n in enumerate(detected):
            o = over.get(str(i))
            counts.append(int(o) if o is not None else n)
        self.detected = detected
        cc.setup_rgb(counts)
        names = ["Pumpe"] + [f"Lüfter {i}" for i in range(1, 7)] if cc.has_pump else \
            [f"RGB-Port {i}" for i in range(1, 8)]
        self.zones = []
        for i, n in enumerate(cc.port_counts):
            if n:
                self.zones.append(Zone(f"{self.key}/rgb{i}", self.key, names[i], n, [n], "ring"))
        self.blank = {z.id: bytes(z.leds * 3) for z in self.zones}

    def _poll(self, full: bool = False) -> None:
        cc = self.dev
        now = time.monotonic()
        if full or now - self.last_conn > 5:
            self.connected = cc.read_connected()
            self.last_conn = now
        rpm = cc.read_speeds()
        temps = cc.read_temps()
        self.last_poll = now
        fans = []
        for port, conn in enumerate(self.connected):
            if not conn:
                continue
            is_pump = cc.has_pump and port == 0
            fid = f"{self.key}/{'pump' if is_pump else f'fan{port}'}"
            fans.append({"id": fid, "port": port, "pump": is_pump, "name": self.speed_labels[port],
                         "rpm": rpm[port] if port < len(rpm) else 0,
                         "duty": self.last_sent.get(port)})
        self.fans = fans
        if cc.has_pump and temps and temps[0] is not None:
            self.d.sensors.push("liquid", "Wasser (AIO)", temps[0])
        elif cc.has_pump:
            self.d.sensors.push("liquid", "Wasser (AIO)", None)
        for i, t in enumerate(temps[1:] if cc.has_pump else temps, start=1):
            if t is not None:
                self.d.sensors.push(f"{self.key}/probe{i}", f"Temperaturfühler {i}", t)

    def set_duties(self, duties: dict[int, int]) -> None:
        with self._lock:
            self.pending_duties = duties
        self._wake.set()

    def _flush_duties(self) -> None:
        with self._lock:
            duties, self.pending_duties = self.pending_duties, None
        if duties is None:
            return
        now = time.monotonic()
        # rewrite at least every 5 s even when nothing changed
        if duties == self.last_sent and now - self.last_duty_write < 5:
            return
        self.dev.set_software_duty(duties)
        self.last_sent = dict(duties)
        self.last_duty_write = now
        for f in self.fans:
            f["duty"] = duties.get(f["port"], f.get("duty"))

    def mark_hw_dirty(self) -> None:
        self.hw_dirty = True
        self._wake.set()

    def _write_hw_fallback(self) -> None:
        self.hw_dirty = False
        curves = self.d.hw_fallback_curves(self)
        if not curves:
            return
        cur = self.dev.read_hw_config()
        backup = CONFIG_DIR / "backup" / f"hw-{self.key.replace(':', '_')}.json"
        if not backup.exists():   # keep what the device had before we ever touched it
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_text(json.dumps(cur, indent=1))
        same = True
        for port, pts in curves.items():
            if port >= len(cur["modes"]) or cur["modes"][port] != ccmod.HW_MODE_CURVE:
                same = False
                break
            have = [(round(t, 1), d) for t, d in cur["curves"][port]["points"]]
            want = [(round(t, 1), d) for t, d in pts]
            if have != want or cur["curves"][port]["sensor"] != 0:
                same = False
                break
        if not same:
            log.info("%s: storing hardware fallback curves", self.name)
            self.dev.write_hw_fallback(curves)
            self.hw_cfg = self.dev.read_hw_config()

    def tick(self) -> None:
        frame = self.take_frame()
        if frame is not None and self.zones:
            self.dev.write_colors(b"".join(frame.get(z.id, self.blank[z.id]) for z in self.zones))
        self._flush_duties()
        if time.monotonic() - self.last_poll >= 1.0:
            self._poll()
        if self.hw_dirty and self.d.cfg.data["cooling"].get("hw_fallback", True):
            self._write_hw_fallback()
        self.dev.keepalive()

    def shutdown(self) -> None:
        dev = getattr(self, "dev", None)
        if dev is not None:
            dev.close()   # back to hardware mode -> fallback curves take over


class LightingNodeWorker(Worker):
    kind = "lighting_node"

    def setup(self) -> None:
        ln = self.dev = lnmod.LightingNode(self.info)
        ln.open()
        self.firmware = ln.firmware
        self.name = ln.name
        dcfg = self.d.device_cfg(self.key)
        chans = dcfg.get("channels", {})
        counts, self.zones = [], []
        for ch in range(ln.channels):
            c = chans.get(str(ch), {})
            segs = [int(s) for s in c.get("segments", []) if int(s) > 0]
            n = sum(segs)
            counts.append(n)
            if n:
                kind = c.get("kind", "linear")
                self.zones.append(Zone(f"{self.key}/ch{ch}", self.key, c.get("name") or f"Kanal {ch + 1}",
                                       n, segs, kind))
        self.counts = counts
        self.test: dict | None = None        # {"ch", "block", "until"} while counting LEDs
        self._ending: dict | None = None     # test that just ended, its LEDs still need blanking
        self._reconfig = False
        # nothing configured yet: leave the hub alone, it keeps its own effect
        if any(counts):
            ln.configure(counts)
        self.blank = {z.id: bytes(z.leds * 3) for z in self.zones}
        self.last_write = 0.0

    # called from the API thread
    def start_test(self, ch: int, block: int) -> None:
        if not 0 <= ch < self.dev.channels:
            raise ValueError(f"Kanal {ch + 1} gibt es nicht")
        if self.test and self.test["ch"] != ch:
            self._ending = self.test
        log.info("%s: counting LEDs on channel %d (blocks of %d)", self.name, ch + 1, block)
        self.test = {"ch": ch, "block": max(1, block), "until": time.monotonic() + lnmod.TEST_SECONDS}
        self._reconfig = True
        self._wake.set()

    def stop_test(self) -> None:
        if self.test:
            self._ending = self.test
        self.test = None
        self._reconfig = True
        self._wake.set()

    def test_info(self) -> dict | None:
        t = self.test
        return {"ch": t["ch"], "block": t["block"]} if t else None

    def tick(self) -> None:
        test = self.test
        if test and time.monotonic() > test["until"]:
            self._ending, self.test, test = test, None, None
            self._reconfig = True
        if self._reconfig:
            self._reconfig = False
            self._blank_ended_test()
            counts = list(self.counts)
            if test:
                counts[test["ch"]] = lnmod.MAX_LEDS
            self.dev.configure(counts)
        frame = self.take_frame()
        if frame is not None and (self.zones or test):
            per = []
            zi = {z.id: z for z in self.zones}
            for ch in range(self.dev.channels):
                zid = f"{self.key}/ch{ch}"
                if test and ch == test["ch"]:
                    per.append(lnmod.test_pattern(test["block"]))
                else:
                    per.append(frame.get(zid, self.blank.get(zid, b"")) if zid in zi else b"")
            self.dev.write_colors(per)
        self.dev.keepalive()

    def _blank_ended_test(self) -> None:
        """LEDs behind the configured count keep their last colour: switch the test colours off."""
        ending, self._ending = self._ending, None
        if ending is None:
            return
        per = [b""] * self.dev.channels
        per[ending["ch"]] = bytes(lnmod.MAX_LEDS * 3)
        self.dev.write_colors(per)

    def shutdown(self) -> None:
        dev = getattr(self, "dev", None)
        if dev is None:
            return
        try:
            if getattr(self, "test", None):
                self._ending, self.test = self.test, None
                self._blank_ended_test()
            if hasattr(self, "counts"):
                dev.counts = list(self.counts)   # store the real length, not the test length
            if any(self.counts):
                eff, colors = self.d.hw_lighting_for(self.key)
                if eff == "off":
                    dev.set_hardware_off()
                else:
                    dev.set_hardware_effect(eff, colors)
        finally:
            dev.close()


DRIVERS: dict[tuple[int, int], type[Worker]] = {}
for _pid in ccmod.MODELS:
    DRIVERS[(ccmod.VID, _pid)] = CommanderCoreWorker
for _pid in lnmod.MODELS:
    DRIVERS[(lnmod.VID, _pid)] = LightingNodeWorker


# ----------------------------------------------------------------- profiles
def lighting_profile(L: dict, name: str) -> dict:
    """Every zone's effect at once: the global one, and which zones run their own."""
    zones = {}
    for zid, z in L.get("zones", {}).items():
        own = not z.get("follow", True)
        zones[zid] = {"follow": not own, "spec": snapshot_spec(z["spec"]) if own and z.get("spec") else None}
    return {"name": name, "global": snapshot_spec(L["global"]), "zones": zones}


def active_profile(L: dict) -> str:
    """Name of the profile that matches the current lighting, or ""."""
    cur = lighting_profile(L, "")
    norm = lambda z: {"follow": True, "spec": None} if z.get("follow", True) else z  # noqa: E731
    for prof in L.get("profiles", []):
        if prof["global"] != cur["global"]:
            continue
        ids = set(cur["zones"]) | set(prof["zones"])
        if all(norm(cur["zones"].get(i, {})) == norm(prof["zones"].get(i, {})) for i in ids):
            return prof["name"]
    return ""


# ----------------------------------------------------------------- daemon
class Daemon:
    def __init__(self) -> None:
        self.cfg = Config()
        self.sensors = Sensors()
        self.sensors.start()
        self.engine = EffectEngine()
        self.engine.screen = ScreenCapture(CONFIG_DIR / "screencast-token")
        self.fanctl = FanController()
        self.workers: dict[str, Worker] = {}
        self.wlock = threading.RLock()
        self.identify: dict[str, float] = {}
        self.preview: dict[str, bytes] = {}
        self.stop_evt = threading.Event()
        self.started = time.time()
        self.last_change = 0.0
        self.extra_sources: list = []   # OpenRGB bridge etc.
        self.wled = WLEDBridge(self)
        self.hwfans = HwmonFans(self)

    # ------------------------------------------------------------ helpers
    def device_cfg(self, key: str) -> dict:
        return self.cfg.data["devices"].get(key, {})

    def all_zones(self) -> list[Zone]:
        with self.wlock:
            zones = [z for w in self.workers.values() if w.status == "ok" for z in w.zones]
        for src in self.extra_sources:
            zones += src.zones()
        return zones

    def all_fans(self) -> list[dict]:
        with self.wlock:
            fans = [f for w in self.workers.values() if w.status == "ok" for f in w.fans]
        for src in self.extra_sources:
            if hasattr(src, "fans"):
                fans += src.fans()
        return fans

    def fan_default(self, fid: str) -> dict:
        for f in self.all_fans():
            if f["id"] == fid:
                return dict(f.get("default_cfg") or default_fan_cfg(f["pump"]))
        return default_fan_cfg(fid.endswith("/pump"))

    def zone_spec(self, zone_id: str, lighting: dict) -> dict:
        z = lighting.get("zones", {}).get(zone_id)
        spec = z["spec"] if z and not z.get("follow", True) and z.get("spec") else lighting["global"]
        return spec

    def hw_lighting_for(self, key: str) -> tuple[str, tuple]:
        """Effect the Lighting Node stores for when we are not running."""
        dcfg = self.device_cfg(key)
        hw = dcfg.get("hw_effect", "auto")
        g = self.cfg.data["lighting"]["global"]
        from .effects import hex_to_rgb
        cols = [hex_to_rgb(c) for c in g.get("colors", ["#ffffff"])] + [(0, 0, 0)] * 3
        if hw == "auto":
            hw = {"static": "static", "breathing": "color_pulse", "spectrum": "color_shift",
                  "off": "off", "rainbow": "rainbow_wave", "gradient": "color_wave",
                  "spin": "marquee", "comet": "visor"}.get(g.get("effect"), "rainbow_wave")
        return hw, tuple(cols[:3])

    def hw_fallback_curves(self, w: CommanderCoreWorker) -> dict[int, list[tuple[float, int]]]:
        c = self.cfg.data["cooling"]
        curves = c["curves"]
        out = {}
        for f in w.fans:
            ch = self.fan_cfg(f)
            if ch.get("mode") == "hardware":
                continue   # the AIO keeps the curve it has stored
            if ch.get("mode") == "fixed":
                d = int(ch.get("fixed", 50))
                pts = [(20.0, d), (60.0, d)]
            else:
                cur = curves.get(ch.get("curve", "")) or {}
                if cur.get("sensor") != "liquid":
                    cur = DEFAULT_CURVES["pump_balanced" if f["pump"] else "balanced"]
                pts = [(float(t), int(round(d))) for t, d in sorted(cur["points"])]
                if len(pts) > 7:   # device holds 7 points: resample
                    lo, hi = pts[0][0], pts[-1][0]
                    pts = [(round(lo + (hi - lo) * i / 6, 1), int(round(interpolate(cur["points"], lo + (hi - lo) * i / 6))))
                           for i in range(7)]
            if f["pump"]:
                pts = [(t, max(ccmod.PUMP_MIN_DUTY, d)) for t, d in pts]
            if len(pts) >= 2:
                out[f["port"]] = pts
        return out

    # --------------------------------------------------------------- scan
    def scan(self) -> None:
        found = {}
        for info in enumerate_hidraw():
            drv = DRIVERS.get((info.vid, info.pid))
            if drv is None or info.interface not in (0, -1):
                continue
            if self.device_cfg(info.key).get("disabled"):
                continue
            found[info.key] = (info, drv)
        with self.wlock:
            for key, w in list(self.workers.items()):
                gone = key not in found
                dead = not w.is_alive()
                if gone or (dead and time.monotonic() - w.failed_at > 5):
                    w.stop()
                    del self.workers[key]
            for key, (info, drv) in found.items():
                if key not in self.workers:
                    w = drv(self, info)
                    self.workers[key] = w
                    w.start()

    def restart_worker(self, key: str) -> None:
        with self.wlock:
            w = self.workers.pop(key, None)
        if w:
            w.stop()
            w.join(5)
        self.scan()

    # ------------------------------------------------------------- render
    def render_loop(self) -> None:
        t0 = time.monotonic()
        while not self.stop_evt.is_set():
            lighting = self.cfg.snapshot()["lighting"]
            fps = max(5, min(60, int(lighting.get("fps", 30))))
            master = float(lighting.get("brightness", 100)) / 100.0
            t = time.monotonic() - t0
            frames: dict[str, dict[str, bytes]] = {}
            now = time.monotonic()
            for z in self.all_zones():
                spec = dict(self.zone_spec(z.id, lighting))
                spec["brightness"] = float(spec.get("brightness", 100)) * master
                spec["min_brightness"] = max(float(spec.get("min_brightness", 0) or 0),
                                             float(self.device_cfg(z.device).get("min_brightness", 0) or 0))
                until = self.identify.get(z.id)
                if until and until > now:
                    on = int((until - now) * 4) % 2 == 0
                    spec = {"effect": "static", "colors": ["#ffffff" if on else "#000000"], "brightness": 100}
                elif until:
                    self.identify.pop(z.id, None)
                data = bytes(self.engine.render(z, spec, t, self.sensors))
                self.preview[z.id] = data
                frames.setdefault(z.device, {})[z.id] = data
            with self.wlock:
                for key, w in self.workers.items():
                    if w.status == "ok":
                        w.submit_frame(frames.get(key, {}))
            for src in self.extra_sources:
                src.submit(frames)
            time.sleep(max(0.0, 1.0 / fps - (time.monotonic() - now)))

    def screen_state(self) -> dict:
        sc = self.engine.screen
        running = bool(sc.thread and sc.thread.is_alive())
        return {"running": running, "live": sc._frame is not None, "error": sc.error}

    # ---------------------------------------------------------------- fans
    def fan_cfg(self, f: dict) -> dict:
        """Channel settings in effect.  A device with fan control switched off runs on its own."""
        ch = self.cfg.data["cooling"]["channels"].get(f["id"]) or f.get("default_cfg") or default_fan_cfg(f["pump"])
        if self.device_cfg(f["id"].rsplit("/", 1)[0]).get("fan_control") is False:
            return {**ch, "mode": "hardware"}
        return ch

    @staticmethod
    def aio_own_duty(w: CommanderCoreWorker, port: int, liquid: float | None) -> float:
        """The duty the AIO would pick itself in hardware mode (its stored curve or fixed value)."""
        hw = getattr(w, "hw_cfg", None)
        if liquid is None or not hw or port >= len(hw["modes"]):
            return float(FAILSAFE_DUTY)
        if liquid >= CRITICAL_LIQUID:
            return 100.0
        if hw["modes"][port] == ccmod.HW_MODE_CURVE and port < len(hw["curves"]) and len(hw["curves"][port]["points"]) >= 2:
            return interpolate([list(p) for p in hw["curves"][port]["points"]], liquid)
        if hw["modes"][port] == ccmod.HW_MODE_FIXED and port < len(hw["fixed"]):
            return float(min(100, hw["fixed"][port]))
        return float(FAILSAFE_DUTY)

    def fan_tick_worker(self, w: CommanderCoreWorker, dt: float) -> None:
        cooling = self.cfg.data["cooling"]
        liquid = self.sensors.get("liquid")
        duties = {}
        for f in w.fans:
            ch = self.fan_cfg(f)
            mind = ccmod.PUMP_MIN_DUTY if f["pump"] else ccmod.FAN_MIN_DUTY
            if ch.get("mode") == "hardware":   # software mode is needed for RGB: replay the AIO's own curve
                duties[f["port"]] = int(round(max(mind, self.aio_own_duty(w, f["port"], liquid))))
                self.fanctl.states.pop(f["id"], None)
                continue
            duty = self.fanctl.step(f["id"], ch, cooling["curves"], self.sensors, dt,
                                    cooling.get("settings", {}), mind, liquid)
            if duty is not None:
                duties[f["port"]] = int(round(duty))
        w.set_duties(duties)

    def failsafe_text(self, st) -> str:
        if not st or not st.failsafe:
            return ""
        if st.reason == "liquid":
            return f"Wasser über {CRITICAL_LIQUID:.0f} °C"
        if st.reason.startswith("sensor:"):
            return f"{self.sensors.label(st.reason[7:])} fehlt"
        return ""

    def fan_tick(self, dt: float) -> None:
        with self.wlock:
            ws = [w for w in self.workers.values() if isinstance(w, CommanderCoreWorker) and w.status == "ok"]
        for w in ws:
            self.fan_tick_worker(w, dt)

    # ----------------------------------------------------------------- run
    def changed(self, cooling: bool = False) -> None:
        self.cfg.mark()
        self.last_change = time.monotonic()
        if cooling:
            self._hw_pending = time.monotonic()

    def run(self) -> None:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        signal.signal(signal.SIGTERM, lambda *_: self.stop_evt.set())
        signal.signal(signal.SIGINT, lambda *_: self.stop_evt.set())
        self._hw_pending = 0.0
        ipc = start_ipc(self)
        if self.cfg.data["openrgb"].get("enabled"):
            self.start_openrgb()
        self.wled.start()
        self.extra_sources.append(self.wled)
        self.hwfans.start()
        self.extra_sources.append(self.hwfans)
        self.scan()
        threading.Thread(target=self.render_loop, daemon=True, name="render").start()
        last = time.monotonic()
        last_scan = last
        boot_gap = time.clock_gettime(time.CLOCK_BOOTTIME) - time.monotonic()
        try:
            while not self.stop_evt.wait(1.0):
                now = time.monotonic()
                gap = time.clock_gettime(time.CLOCK_BOOTTIME) - now
                if gap - boot_gap > 3:   # we were suspended
                    log.info("resume detected, re-initialising devices")
                    boot_gap = gap
                    for key in list(self.workers):
                        self.restart_worker(key)
                self.fan_tick(now - last)
                self.engine.screen.idle_check()
                last = now
                if now - last_scan > 3:
                    self.scan()
                    last_scan = now
                if self._hw_pending and now - self._hw_pending > 5:
                    self._hw_pending = 0.0
                    with self.wlock:
                        for w in self.workers.values():
                            if isinstance(w, CommanderCoreWorker):
                                w.mark_hw_dirty()
                if self.cfg.dirty and now - self.last_change > 1.5:
                    self.cfg.save()
        finally:
            log.info("stopping, handing devices back to hardware mode")
            ipc.shutdown()
            self.engine.screen.stop()
            with self.wlock:
                ws = list(self.workers.values())
            for w in ws:
                w.stop()
            for w in ws:
                w.join(5)
            for src in self.extra_sources:
                src.close()
            self.sensors.stop()
            if self.cfg.dirty:
                self.cfg.save()
            try:
                SOCKET.unlink()
            except OSError:
                pass

    def start_openrgb(self) -> None:
        try:
            from .devices.openrgb_bridge import OpenRGBBridge
        except ImportError:
            return
        b = OpenRGBBridge(self, self.cfg.data["openrgb"])
        b.start()
        self.extra_sources.append(b)

    # ----------------------------------------------------------------- api
    def api(self, method: str, p: dict):
        c = self.cfg
        if method == "state":
            snap = c.snapshot()
            with self.wlock:
                devs = [w.describe() for w in self.workers.values()]
                extra = {}
                for w in self.workers.values():
                    if isinstance(w, CommanderCoreWorker) and w.status == "ok":
                        extra[w.key] = {"detected": getattr(w, "detected", [])}
                    if isinstance(w, LightingNodeWorker) and w.status == "ok":
                        extra[w.key] = {"channels": w.dev.channels, "test": w.test_info()}
            for d in devs:
                d.update(extra.get(d["key"], {}))
            rank = {"commander_core": 0, "lighting_node": 1}
            devs.sort(key=lambda d: (rank.get(d["kind"], 5), d["name"]))
            for src in self.extra_sources:
                devs += src.describe()
            # excluded devices that are not listed otherwise, so they can be switched back on
            seen = {d["key"] for d in devs}
            for key, dc in snap["devices"].items():
                if dc.get("disabled") and key not in seen:
                    devs.append({"key": key, "kind": dc.get("kind", ""), "name": dc.get("name") or key,
                                 "label": "", "firmware": "", "status": "disabled", "error": "", "path": "",
                                 "zones": [], "fans": []})
            fans = []
            for f in self.all_fans():
                st = self.fanctl.states.get(f["id"])
                fans.append({**f, "target": st.target if st else None, "temp": st.temp if st else None,
                             "failsafe": st.failsafe if st else False, "why": self.failsafe_text(st),
                             "cfg": snap["cooling"]["channels"].get(f["id"]) or f.get("default_cfg") or default_fan_cfg(f["pump"]),
                             "managed": snap["devices"].get(f["id"].rsplit("/", 1)[0], {}).get("fan_control") is not False})
            zones = [{"id": z.id, "device": z.device, "name": z.name, "leds": z.leds, "segments": z.segs(),
                      "kind": z.kind, "cfg": snap["lighting"]["zones"].get(z.id, {"follow": True})}
                     for z in self.all_zones()]
            return {"devices": devs, "fans": fans, "zones": zones, "sensors": self.sensors.listing(),
                    "config": snap, "effects": EFFECTS, "effect_order": list(EFFECTS),
                    "screen": self.screen_state(), "active_profile": active_profile(snap["lighting"]), "presets": lnmod.PRESETS,
                    "hw_effects": list(lnmod.HW_EFFECTS) + ["off", "auto"], "uptime": time.time() - self.started}
        if method == "frame":
            want = p.get("zones")
            return {zid: data.hex() for zid, data in self.preview.items() if not want or zid in want}
        if method == "history":
            sid = p["sensor"]
            secs = float(p.get("seconds", 300))
            cutoff = time.time() - secs
            return [(t, v) for t, v in self.sensors.history.get(sid, []) if t >= cutoff]
        if method == "set_global":
            with c.lock:
                patch_spec(c.data["lighting"]["global"], p["spec"])
            self.changed()
            return True
        if method in ("save_profile", "load_profile", "delete_profile"):
            with c.lock:
                L = c.data["lighting"]
                profiles = L.setdefault("profiles", [])
                if method == "save_profile":
                    name = str(p.get("name") or "").strip() or f"Profil {len(profiles) + 1}"
                    prof = lighting_profile(L, name)
                    for i, e in enumerate(profiles):
                        if e["name"] == name:
                            profiles[i] = prof
                            break
                    else:
                        profiles.append(prof)
                elif method == "load_profile":
                    prof = copy.deepcopy(profiles[int(p["index"])])
                    load_snapshot(L["global"], prof["global"])
                    for zid in set(L["zones"]) | set(prof["zones"]):
                        pz = prof["zones"].get(zid, {"follow": True})
                        z = L["zones"].setdefault(zid, {"follow": True})
                        z["follow"] = pz["follow"]
                        if pz.get("spec"):
                            z["spec"] = load_snapshot(z.get("spec") or copy.deepcopy(L["global"]), pz["spec"])
                else:
                    del profiles[int(p["index"])]
            self.changed()
            return True
        if method in ("save_effect", "load_effect", "delete_effect"):
            target = p.get("target") or ""          # "" = global, else a zone id
            with c.lock:
                L = c.data["lighting"]
                saved = L.setdefault("saved", {}).setdefault(target or "global", [])
                if target:
                    z = L["zones"].setdefault(target, {"follow": True})
                    spec = z.get("spec") or copy.deepcopy(L["global"])
                else:
                    z, spec = None, L["global"]
                if method == "save_effect":
                    name = str(p.get("name") or "").strip() or EFFECTS.get(spec.get("effect"), {}).get("name", "Effekt")
                    snap = snapshot_spec(spec)
                    for e in saved:                    # same name: overwrite
                        if e["name"] == name:
                            e["spec"] = snap
                            break
                    else:
                        saved.append({"name": name, "spec": snap})
                elif method == "load_effect":
                    load_snapshot(spec, copy.deepcopy(saved[int(p["index"])]["spec"]))
                    if z is not None:
                        z["spec"], z["follow"] = spec, False
                else:
                    del saved[int(p["index"])]
            self.changed()
            return True
        if method == "set_brightness":
            with c.lock:
                c.data["lighting"]["brightness"] = max(0, min(100, float(p["value"])))
            self.changed()
            return True
        if method == "set_zone":
            with c.lock:
                z = c.data["lighting"]["zones"].setdefault(p["zone"], {"follow": True})
                if "follow" in p:
                    z["follow"] = bool(p["follow"])
                if "spec" in p:
                    base = z.get("spec") or copy.deepcopy(c.data["lighting"]["global"])
                    z["spec"] = patch_spec(base, p["spec"])
            self.changed()
            return True
        if method == "led_test":
            with self.wlock:
                w = self.workers.get(p["key"])
            if not isinstance(w, LightingNodeWorker) or w.status != "ok":
                raise ValueError("Lighting Node nicht bereit")
            if p.get("on", True):
                w.start_test(int(p["ch"]), int(p.get("block", 10)))
            else:
                w.stop_test()
            return True
        if method == "identify":
            self.identify[p["zone"]] = time.monotonic() + float(p.get("seconds", 4))
            return True
        if method == "set_fan":
            with c.lock:
                ch = c.data["cooling"]["channels"].setdefault(p["fan"], self.fan_default(p["fan"]))
                for k in ("mode", "curve", "fixed", "label"):
                    if k in p:
                        ch[k] = p[k]
            self.changed(cooling=True)
            return True
        if method == "set_curve":
            cur = p["curve"]
            pts = sorted([[float(t), max(0.0, min(100.0, float(d)))] for t, d in cur.get("points", [])])
            if len(pts) < 2:
                raise ValueError("eine Kurve braucht mindestens 2 Punkte")
            with c.lock:
                old = c.data["cooling"]["curves"].get(p["id"], {})
                old.update({k: v for k, v in cur.items() if k != "points"})
                old["points"] = pts
                c.data["cooling"]["curves"][p["id"]] = old
            self.changed(cooling=True)
            return True
        if method == "delete_curve":
            with c.lock:
                used = [k for k, v in c.data["cooling"]["channels"].items() if v.get("curve") == p["id"]]
                if used:
                    raise ValueError("Kurve wird noch verwendet")
                c.data["cooling"]["curves"].pop(p["id"], None)
            self.changed(cooling=True)
            return True
        if method == "set_cooling":
            with c.lock:
                lim = {"hysteresis": (0, 10), "ramp_up": (0.5, 100), "ramp_down": (0.5, 100),
                       "failsafe_duty": (0, 100), "sensor_timeout": (2, 120)}
                for k, (lo, hi) in lim.items():
                    if k in p:
                        c.data["cooling"]["settings"][k] = max(lo, min(hi, float(p[k])))
                if "hw_fallback" in p:
                    c.data["cooling"]["hw_fallback"] = bool(p["hw_fallback"])
            self.changed(cooling=True)
            return True
        if method == "set_device":
            key = p["key"]
            with c.lock:
                d = c.data["devices"].setdefault(key, {})
                for k in ("label", "hw_effect", "disabled", "name", "kind", "fan_control"):
                    if k in p:
                        d[k] = p[k]
                if "channels" in p:
                    d.setdefault("channels", {}).update(p["channels"])
                if "ports" in p:
                    d.setdefault("ports", {}).update({str(k): v for k, v in p["ports"].items()})
                if "min_brightness" in p:
                    d["min_brightness"] = max(0, min(100, float(p["min_brightness"])))
            self.changed()
            if "disabled" in p:
                for src in self.extra_sources:
                    src.reload()
            if p.get("restart", True):
                threading.Thread(target=self.restart_worker, args=(key,), daemon=True).start()
            return True
        if method == "set_lighting":
            with c.lock:
                if "fps" in p:
                    c.data["lighting"]["fps"] = max(5, min(60, int(p["fps"])))
            self.changed()
            return True
        if method == "set_orgb_zone":
            with c.lock:
                d = c.data["devices"].setdefault(p["key"], {})
                d.setdefault("zone_sizes", {})[str(int(p["zone"]))] = int(p["size"])
            self.changed()
            for src in self.extra_sources:
                src.reload()
            return True
        if method == "set_openrgb":
            with c.lock:
                c.data["openrgb"].update({k: v for k, v in p.items() if k in ("enabled", "host", "port", "spawn")})
            self.changed()
            return True
        if method == "hw_config":
            with self.wlock:
                ws = [w for w in self.workers.values() if isinstance(w, CommanderCoreWorker) and w.status == "ok"]
            return {w.key: w.dev.read_hw_config() for w in ws}
        if method == "rescan":
            self.scan()
            return True
        if method == "save":
            c.save()
            return True
        if method == "add_wled":
            from .devices import wled
            host = wled.normalize_host(str(p.get("host", "")))
            if not host:
                raise ValueError("Bitte eine IP-Adresse oder einen Hostnamen eintragen")
            info = wled.probe(host)
            key = wled.device_key(info, host)
            with c.lock:
                devs = c.data["wled"]["devices"]
                if any(d.get("key") == key or d.get("host") == host for d in devs):
                    raise ValueError(f"{host} ist schon eingetragen")
                name = str(p.get("name") or "").strip() or info.get("name") or host
                devs.append({"host": host, "key": key, "name": name})
            self.changed()
            self.wled.reload()
            return {"key": key, "name": name, "leds": info["leds"]["count"]}
        if method == "remove_wled":
            with c.lock:
                c.data["wled"]["devices"] = [d for d in c.data["wled"]["devices"] if d.get("key") != p["key"]]
                c.data["devices"].pop(p["key"], None)
                c.data["lighting"]["zones"].pop(p["key"] + "/z0", None)
            self.changed()
            self.wled.reload()
            return True
        if method == "rename_wled":
            with c.lock:
                for d in c.data["wled"]["devices"]:
                    if d.get("key") == p["key"]:
                        d["name"] = str(p["name"]).strip() or d["host"]
            self.changed()
            self.wled.reload()
            return True
        if method == "quit":   # used by the app when neorgbd does not run under systemd
            self.stop_evt.set()
            return True
        raise ValueError(f"unknown method {method}")


# -------------------------------------------------------------------- ipc
class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        d: Daemon = self.server.neorgb  # type: ignore[attr-defined]
        for line in self.rfile:
            try:
                req = json.loads(line)
                res = {"id": req.get("id"), "result": d.api(req["method"], req.get("params") or {})}
            except Exception as e:  # noqa: BLE001
                res = {"id": None if not isinstance(locals().get("req"), dict) else req.get("id"), "error": str(e)}
            self.wfile.write((json.dumps(res, default=str) + "\n").encode())
            self.wfile.flush()


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def start_ipc(d: Daemon) -> _Server:
    if SOCKET.exists():
        # another daemon alive?
        s = socket.socket(socket.AF_UNIX)
        try:
            s.connect(str(SOCKET))
            s.close()
            raise SystemExit("neorgbd läuft bereits")
        except ConnectionRefusedError:
            SOCKET.unlink()
        except FileNotFoundError:
            pass
    srv = _Server(str(SOCKET), _Handler)
    os.chmod(SOCKET, 0o600)
    srv.neorgb = d  # type: ignore[attr-defined]
    threading.Thread(target=srv.serve_forever, daemon=True, name="ipc").start()
    return srv


def main() -> None:
    Daemon().run()


if __name__ == "__main__":
    main()
