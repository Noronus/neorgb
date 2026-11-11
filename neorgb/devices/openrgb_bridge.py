"""Drive everything OpenRGB knows (Aura, RAM, keyboards, mice) through its SDK.

NeoRGB starts a private OpenRGB server with its own config directory in
which the Corsair hub detectors are switched off, so OpenRGB never opens the
devices NeoRGB drives itself.  Two programs on one HID device is a classic
source of flicker and lockups.

We speak SDK protocol 4 (server and client agree on the lower version).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

from ..config import CONFIG_DIR
from ..effects import Zone

log = logging.getLogger("neorgb.openrgb")

PROTO = 4
PKT_COUNT, PKT_DATA, PKT_VERSION, PKT_NAME = 0, 1, 40, 50
PKT_LIST_UPDATED = 100
PKT_UPDATELEDS, PKT_CUSTOMMODE, PKT_RESIZE = 1050, 1100, 1000

OWN_DETECTORS_OFF = [
    "Corsair Commander Core", "Corsair Commander Core XT", "Corsair Commander Pro",
    "Corsair LS100 Lighting Kit", "Corsair LT100", "Corsair Lighting Node Core",
    "Corsair Lighting Node Pro",
]


class _Reader:
    def __init__(self, data: bytes):
        self.d, self.p = data, 0

    def u16(self) -> int:
        v = struct.unpack_from("<H", self.d, self.p)[0]
        self.p += 2
        return v

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def s(self) -> str:
        n = self.u16()
        raw = self.d[self.p:self.p + n]
        self.p += n
        return raw.rstrip(b"\x00").decode("utf-8", "replace")

    def skip(self, n: int) -> None:
        self.p += n


def parse_controller(data: bytes) -> dict:
    r = _Reader(data)
    r.u32()  # data size
    c = {"type": r.i32(), "name": r.s(), "vendor": r.s(), "description": r.s(),
         "version": r.s(), "serial": r.s(), "location": r.s()}
    nmodes = r.u16()
    c["active_mode"] = r.i32()
    modes = []
    for _ in range(nmodes):
        m = {"name": r.s(), "value": r.i32(), "flags": r.u32()}
        r.u32(); r.u32()             # speed min/max
        r.u32(); r.u32()             # brightness min/max (v3)
        r.u32(); r.u32()             # colors min/max
        r.u32(); r.u32()             # speed, brightness
        r.u32(); r.u32()             # direction, color mode
        r.skip(4 * r.u16())          # colours
        modes.append(m)
    c["modes"] = modes
    zones = []
    for _ in range(r.u16()):
        z = {"name": r.s(), "type": r.i32(), "min": r.u32(), "max": r.u32(), "count": r.u32()}
        r.skip(r.u16())              # matrix map
        segs = []
        for _ in range(r.u16()):     # v4 segments
            segs.append({"name": r.s(), "type": r.i32(), "start": r.u32(), "count": r.u32()})
        z["segments"] = segs
        zones.append(z)
    c["zones"] = zones
    c["leds"] = r.u16()
    return c


class SDK:
    def __init__(self, host: str, port: int):
        self.sock = socket.create_connection((host, port), timeout=3)
        self.sock.settimeout(5)
        self.lock = threading.Lock()
        self.list_changed = False

    def _send(self, dev: int, pid: int, data: bytes = b"") -> None:
        self.sock.sendall(b"ORGB" + struct.pack("<III", dev, pid, len(data)) + data)

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("OpenRGB closed the connection")
            buf += chunk
        return buf

    def _recv(self, want: int) -> bytes:
        while True:
            magic, dev, pid, size = struct.unpack("<4sIII", self._recv_exact(16))
            if magic != b"ORGB":
                raise ConnectionError("bad packet from OpenRGB")
            data = self._recv_exact(size) if size else b""
            if pid == PKT_LIST_UPDATED:
                self.list_changed = True
            if pid == want:
                return data

    def handshake(self) -> int:
        with self.lock:
            self._send(0, PKT_NAME, b"NeoRGB\x00")
            self._send(0, PKT_VERSION, struct.pack("<I", PROTO))
            server = struct.unpack("<I", self._recv(PKT_VERSION)[:4])[0]
        return min(server, PROTO)

    def controllers(self) -> list[dict]:
        with self.lock:
            self._send(0, PKT_COUNT)
            n = struct.unpack("<I", self._recv(PKT_COUNT)[:4])[0]
            out = []
            for i in range(n):
                self._send(i, PKT_DATA, struct.pack("<I", PROTO))
                out.append(parse_controller(self._recv(PKT_DATA)))
        return out

    def poll_events(self) -> None:
        """Consume packets the server pushed on its own (device list updates)."""
        import select
        with self.lock:
            while select.select([self.sock], [], [], 0)[0]:
                magic, dev, pid, size = struct.unpack("<4sIII", self._recv_exact(16))
                if size:
                    self._recv_exact(size)
                if pid == PKT_LIST_UPDATED:
                    self.list_changed = True

    def custom_mode(self, idx: int) -> None:
        with self.lock:
            self._send(idx, PKT_CUSTOMMODE)

    def update_leds(self, idx: int, rgb: bytes) -> None:
        n = len(rgb) // 3
        body = bytearray(struct.pack("<IH", 4 + 2 + 4 * n, n))
        for i in range(n):
            body += bytes((rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2], 0))
        with self.lock:
            self._send(idx, PKT_UPDATELEDS, bytes(body))

    def resize_zone(self, idx: int, zone: int, size: int) -> None:
        with self.lock:
            self._send(idx, PKT_RESIZE, struct.pack("<ii", zone, size))

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def stable_ident(c: dict) -> str:
    """hidraw numbers change between boots, the USB port does not."""
    loc = c.get("location", "")
    if c.get("serial"):
        return c["serial"]
    if "/dev/hidraw" in loc:
        from ..hidraw import enumerate_hidraw
        path = "/dev/" + loc.split("/dev/")[1].split()[0]
        for info in enumerate_hidraw():
            if info.path == path:
                return f"usb-{info.usb_path}:{info.interface}"
    return loc or c.get("name", "")


def write_private_config(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    f = path / "OpenRGB.json"
    try:
        cfg = json.loads(f.read_text())
    except (OSError, json.JSONDecodeError):
        cfg = {}
    det = cfg.setdefault("Detectors", {}).setdefault("detectors", {})
    for name in OWN_DETECTORS_OFF:
        det[name] = False
    cfg.setdefault("AutoStart", {})["enabled"] = False
    f.write_text(json.dumps(cfg, indent=2))


class OpenRGBBridge(threading.Thread):
    kind = "openrgb"

    def __init__(self, daemon, cfg: dict):
        super().__init__(daemon=True, name="openrgb")
        self.d = daemon
        self.cfg = cfg
        self.host = cfg.get("host", "127.0.0.1")
        self.port = int(cfg.get("port", 6744))
        self.proc: subprocess.Popen | None = None
        self.sdk: SDK | None = None
        self.ctrls: list[dict] = []
        self._zones: list[Zone] = []
        self._frame: dict | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self.stop_evt = threading.Event()
        self.status = "starting"
        self.error = ""
        self._reload = False

    # ---- interface used by the daemon
    def zones(self) -> list[Zone]:
        return list(self._zones) if self.status == "ok" else []

    def submit(self, frames: dict) -> None:
        with self._lock:
            self._frame = frames
        self._wake.set()

    def describe(self) -> list[dict]:
        if not self.ctrls:
            return [{"key": "openrgb", "kind": "openrgb", "name": "OpenRGB", "label": "", "firmware": "",
                     "status": self.status, "error": self.error, "path": f"{self.host}:{self.port}",
                     "zones": [], "fans": []}]
        out = []
        for c in self.ctrls:
            out.append({"key": c["key"], "kind": "openrgb", "name": c.get("label", c["name"]), "label": "",
                        "firmware": c.get("version", ""),
                        "status": "disabled" if c.get("disabled") else self.status, "error": self.error,
                        "path": c.get("location", ""), "zones": [z.id for z in self._zones if z.device == c["key"]],
                        "fans": [], "orgb_zones": [{"name": z["name"], "count": z["count"], "min": z["min"],
                                                    "max": z["max"], "index": i} for i, z in enumerate(c["zones"])]})
        return out

    def resize(self, key: str, zone: int, size: int) -> None:
        for c in self.ctrls:
            if c["key"] == key and self.sdk:
                self.sdk.resize_zone(c["idx"], zone, size)
                self._reload = True

    # ---- thread
    def _spawn(self) -> None:
        exe = shutil.which("openrgb")
        if not exe:
            raise RuntimeError("openrgb ist nicht installiert")
        cdir = CONFIG_DIR / "openrgb"
        write_private_config(cdir)
        # Started under its own name: CachyOS' ananicy-cpp puts every process
        # called "openrgb" into the background class (nice 16).  Under load the
        # device threads then starve and keyboard effects stutter and lag.
        link = cdir / "neorgb-openrgb"
        try:
            if not link.is_symlink() or os.readlink(link) != exe:
                link.unlink(missing_ok=True)
                link.symlink_to(exe)
            exe = str(link)
        except OSError:
            pass
        logf = open(cdir / "server.log", "w")
        self.proc = subprocess.Popen(
            [exe, "--server", "--server-port", str(self.port), "--noautoconnect", "--config", str(cdir)],
            stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=str(cdir))

    def _connect(self) -> None:
        deadline = time.monotonic() + 30
        while not self.stop_evt.is_set():
            try:
                self.sdk = SDK(self.host, self.port)
                self.sdk.handshake()
                return
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(1)

    def _load(self) -> None:
        own_paths = set()
        with self.d.wlock:
            for w in self.d.workers.values():
                own_paths.add(w.info.path)
        ctrls = []
        for idx, c in enumerate(self.sdk.controllers()):
            if any(p in c["location"] for p in own_paths):
                continue
            c["key"] = f"orgb:{c['name']}:{stable_ident(c)}"
            c["idx"] = idx
            ctrls.append(c)
        resized = False
        for c in ctrls:
            want = self.d.device_cfg(c["key"]).get("zone_sizes", {})
            for zi, z in enumerate(c["zones"]):
                n = want.get(str(zi))
                if n is not None and z["min"] <= int(n) <= z["max"] and int(n) != z["count"]:
                    self.sdk.resize_zone(c["idx"], zi, int(n))
                    resized = True
        if resized:
            time.sleep(0.5)
            return self._load()
        names: dict[str, int] = {}
        for c in ctrls:
            names[c["name"]] = names.get(c["name"], 0) + 1
            c["label"] = c["name"] if names[c["name"]] == 1 else f"{c['name']} #{names[c['name']]}"
        zones = []
        for c in ctrls:
            c["disabled"] = bool(self.d.device_cfg(c["key"]).get("disabled"))
            c["direct"] = False
            if c["disabled"]:   # excluded by the user: never switch it to direct mode
                continue
            direct = next((i for i, m in enumerate(c["modes"]) if m["name"].lower() in ("direct", "custom")), None)
            c["direct"] = direct is not None
            if direct is not None:
                self.sdk.custom_mode(c["idx"])
            if not c["direct"]:
                continue
            for zi, z in enumerate(c["zones"]):
                if z["count"] <= 0:
                    continue
                segs = [s["count"] for s in z["segments"]] if z["segments"] else [z["count"]]
                kind = "single" if z["count"] == 1 else "linear"
                active = [x for x in c["zones"] if x["count"] > 0]
                zname = c["label"] if len(active) == 1 else f"{c['label']} · {z['name']}"
                zones.append(Zone(f"{c['key']}/z{zi}", c["key"], zname, z["count"], segs, kind))
        self.ctrls = ctrls
        self._zones = zones
        self._reload = False
        log.info("OpenRGB: %d Geräte, %d Zonen", len(ctrls), len(zones))

    def run(self) -> None:
        backoff = 2.0
        while not self.stop_evt.is_set():
            try:
                if self.cfg.get("spawn", True) and (self.proc is None or self.proc.poll() is not None):
                    self._spawn()
                    time.sleep(3)    # detection
                self._connect()
                time.sleep(2)
                self._load()
                self.status, self.error = "ok", ""
                backoff = 2.0
                last_reload = started = time.monotonic()
                while not self.stop_evt.is_set():
                    self._wake.wait(0.2)
                    self._wake.clear()
                    self.sdk.poll_events()
                    since = time.monotonic() - last_reload
                    if self._reload or self.sdk.list_changed or (since > 8 and time.monotonic() - started < 60):
                        self.sdk.list_changed = False
                        self._load()
                        last_reload = time.monotonic()
                    with self._lock:
                        frames, self._frame = self._frame, None
                    if frames is None:
                        continue
                    for c in self.ctrls:
                        if not c["direct"]:
                            continue
                        part = frames.get(c["key"], {})
                        rgb = bytearray()
                        for zi, z in enumerate(c["zones"]):
                            data = part.get(f"{c['key']}/z{zi}")
                            rgb += data if data and len(data) == z["count"] * 3 else bytes(z["count"] * 3)
                        if len(rgb) // 3 == c["leds"]:
                            self.sdk.update_leds(c["idx"], bytes(rgb))
            except Exception as e:  # noqa: BLE001
                self.status, self.error = "error", str(e)
                log.warning("OpenRGB: %s", e)
                if self.sdk:
                    self.sdk.close()
                    self.sdk = None
                self.stop_evt.wait(backoff)
                backoff = min(30.0, backoff * 2)

    def close(self) -> None:
        self.stop_evt.set()
        self._wake.set()
        if self.sdk:
            self.sdk.close()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
