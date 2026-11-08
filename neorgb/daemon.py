"""neorgbd: owns the devices, runs lighting and fan control, serves the UI.

Threads:
  * one worker per USB device (all I/O to that device happens there)
  * render: computes lighting frames at `fps` and hands them to workers
  * main: sensors + fan control once per second, hotplug scan, saving
  * ipc: JSON lines over a Unix socket for the GUI and the CLI
"""

from __future__ import annotations

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
from .effects import EFFECTS, EffectEngine, Zone
from .fancontrol import DEFAULT_CURVES, FanController, interpolate
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
        # nothing configured yet: leave the hub alone, it keeps its own effect
        if any(counts):
            ln.configure(counts)
        self.blank = {z.id: bytes(z.leds * 3) for z in self.zones}
        self.last_write = 0.0

    def tick(self) -> None:
        frame = self.take_frame()
        if frame is not None and self.zones:
            per = []
            zi = {z.id: z for z in self.zones}
            for ch in range(self.dev.channels):
                zid = f"{self.key}/ch{ch}"
                per.append(frame.get(zid, self.blank.get(zid, b"")) if zid in zi else b"")
            self.dev.write_colors(per)
        self.dev.keepalive()

    def shutdown(self) -> None:
        dev = getattr(self, "dev", None)
        if dev is None:
            return
        try:
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


# ----------------------------------------------------------------- daemon
class Daemon:
    def __init__(self) -> None:
        self.cfg = Config()
        self.sensors = Sensors()
        self.sensors.update()
        self.engine = EffectEngine()
        self.fanctl = FanController()
        self.workers: dict[str, Worker] = {}
        self.wlock = threading.RLock()
        self.identify: dict[str, float] = {}
        self.preview: dict[str, bytes] = {}
        self.stop_evt = threading.Event()
        self.started = time.time()
        self.last_change = 0.0
        self.extra_sources: list = []   # OpenRGB bridge etc.

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
            return [f for w in self.workers.values() if w.status == "ok" for f in w.fans]

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
            ch = c["channels"].get(f["id"]) or default_fan_cfg(f["pump"])
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

    # ---------------------------------------------------------------- fans
    def fan_tick_worker(self, w: CommanderCoreWorker, dt: float) -> None:
        cooling = self.cfg.data["cooling"]
        liquid = self.sensors.get("liquid")
        duties = {}
        for f in w.fans:
            ch = cooling["channels"].get(f["id"]) or default_fan_cfg(f["pump"])
            mind = ccmod.PUMP_MIN_DUTY if f["pump"] else ccmod.FAN_MIN_DUTY
            duty = self.fanctl.step(f["id"], ch, cooling["curves"], self.sensors, dt,
                                    cooling.get("settings", {}), mind, liquid)
            if duty is not None:
                duties[f["port"]] = int(round(duty))
        w.set_duties(duties)

    def fan_tick(self, dt: float) -> None:
        self.sensors.update()
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
            with self.wlock:
                ws = list(self.workers.values())
            for w in ws:
                w.stop()
            for w in ws:
                w.join(5)
            for src in self.extra_sources:
                src.close()
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
                        extra[w.key] = {"channels": w.dev.channels}
            for d in devs:
                d.update(extra.get(d["key"], {}))
            rank = {"commander_core": 0, "lighting_node": 1}
            devs.sort(key=lambda d: (rank.get(d["kind"], 5), d["name"]))
            for src in self.extra_sources:
                devs += src.describe()
            fans = []
            for f in self.all_fans():
                st = self.fanctl.states.get(f["id"])
                fans.append({**f, "target": st.target if st else None, "temp": st.temp if st else None,
                             "failsafe": st.failsafe if st else False,
                             "cfg": snap["cooling"]["channels"].get(f["id"]) or default_fan_cfg(f["pump"])})
            zones = [{"id": z.id, "device": z.device, "name": z.name, "leds": z.leds, "segments": z.segs(),
                      "kind": z.kind, "cfg": snap["lighting"]["zones"].get(z.id, {"follow": True})}
                     for z in self.all_zones()]
            return {"devices": devs, "fans": fans, "zones": zones, "sensors": self.sensors.listing(),
                    "config": snap, "effects": EFFECTS, "effect_order": list(EFFECTS), "presets": lnmod.PRESETS,
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
                c.data["lighting"]["global"].update(p["spec"])
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
                    base = z.get("spec") or dict(c.data["lighting"]["global"])
                    base.update(p["spec"])
                    z["spec"] = base
            self.changed()
            return True
        if method == "identify":
            self.identify[p["zone"]] = time.monotonic() + float(p.get("seconds", 4))
            return True
        if method == "set_fan":
            with c.lock:
                ch = c.data["cooling"]["channels"].setdefault(p["fan"], default_fan_cfg(p["fan"].endswith("/pump")))
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
                for k in ("hysteresis", "ramp_up", "ramp_down"):
                    if k in p:
                        c.data["cooling"]["settings"][k] = float(p[k])
                if "hw_fallback" in p:
                    c.data["cooling"]["hw_fallback"] = bool(p["hw_fallback"])
            self.changed(cooling=True)
            return True
        if method == "set_device":
            key = p["key"]
            with c.lock:
                d = c.data["devices"].setdefault(key, {})
                for k in ("label", "hw_effect", "disabled"):
                    if k in p:
                        d[k] = p[k]
                if "channels" in p:
                    d.setdefault("channels", {}).update(p["channels"])
                if "ports" in p:
                    d.setdefault("ports", {}).update({str(k): v for k, v in p["ports"].items()})
            self.changed()
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
                src._reload = True
                src._wake.set()
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
