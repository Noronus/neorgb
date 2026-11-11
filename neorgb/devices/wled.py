"""WLED controllers on the network, driven over DDP (UDP 4048).

Devices are entered by hand (IP or host name).  Their LED count and
segments come from ``/json/info`` and ``/json/state``.  WLED shows our
frames in its realtime mode and falls back to its own effect a few seconds
after the last frame, so a stopped daemon leaves the strip in a sane state.
"""

from __future__ import annotations

import json
import logging
import socket
import struct
import threading
import time
import urllib.request

from ..effects import Zone

log = logging.getLogger("neorgb.wled")

DDP_PORT = 4048
DDP_MAX = 1440            # bytes of pixel data per packet (480 RGB LEDs)
DDP_RGB8 = 0x0B           # data type: RGB, 8 bit per channel
RETRY = 10.0              # seconds between attempts for an unreachable device


def http_json(host: str, path: str, body: dict | None = None, timeout: float = 3.0) -> dict:
    url = f"http://{host}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def probe(host: str) -> dict:
    """Ask a WLED device who it is.  Raises ValueError with a readable reason."""
    host = normalize_host(host)
    try:
        info = http_json(host, "/json/info")
    except (OSError, ValueError) as e:
        raise ValueError(f"WLED unter {host} nicht erreichbar ({e})") from e
    if "leds" not in info:
        raise ValueError(f"{host} ist kein WLED-Gerät")
    return info


def normalize_host(host: str) -> str:
    host = host.strip()
    for pre in ("http://", "https://"):
        if host.startswith(pre):
            host = host[len(pre):]
    return host.strip("/").split("/")[0]


def device_key(info: dict, host: str) -> str:
    return "wled:" + (info.get("mac") or host)


def ddp_packets(rgb: bytes, seq: int) -> list[bytes]:
    out = []
    off = 0
    while off < len(rgb) or not out:
        chunk = rgb[off:off + DDP_MAX]
        last = off + len(chunk) >= len(rgb)
        flags = 0x41 if last else 0x40          # version 1, push on the last packet
        out.append(struct.pack(">BBBBIH", flags, seq, DDP_RGB8, 1, off, len(chunk)) + chunk)
        off += len(chunk)
        if not chunk:
            break
    return out


class _Dev:
    def __init__(self, entry: dict):
        self.host = normalize_host(entry["host"])
        self.key = entry.get("key") or f"wled:{self.host}"
        self.name = entry.get("name") or self.host
        self.leds = 0
        self.segs: list[int] = []
        self.firmware = ""
        self.status = "starting"
        self.error = ""
        self.next_try = 0.0
        self.addr: tuple | None = None


class WLEDBridge(threading.Thread):
    kind = "wled"

    def __init__(self, daemon):
        super().__init__(daemon=True, name="wled")
        self.d = daemon
        self.devs: dict[str, _Dev] = {}
        self._frame: dict | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self.stop_evt = threading.Event()
        self._reload = True
        self.seq = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # ---- interface used by the daemon
    def zones(self) -> list[Zone]:
        out = []
        for dv in list(self.devs.values()):
            if dv.status == "ok" and dv.leds:
                out.append(Zone(f"{dv.key}/z0", dv.key, dv.name, dv.leds, dv.segs or [dv.leds], "linear"))
        return out

    def submit(self, frames: dict) -> None:
        with self._lock:
            self._frame = frames
        self._wake.set()

    def describe(self) -> list[dict]:
        out = []
        for dv in list(self.devs.values()):
            out.append({"key": dv.key, "kind": "wled", "name": dv.name, "label": "", "firmware": dv.firmware,
                        "status": dv.status, "error": dv.error, "path": f"http://{dv.host}", "host": dv.host,
                        "leds": dv.leds, "zones": [f"{dv.key}/z0"] if dv.status == "ok" else [], "fans": []})
        return out

    def reload(self) -> None:
        self._reload = True
        self._wake.set()

    # ---- thread
    def _sync_config(self) -> None:
        self._reload = False
        entries = list(self.d.cfg.data.get("wled", {}).get("devices", []))
        keep = {}
        for e in entries:
            key = e.get("key") or f"wled:{normalize_host(e['host'])}"
            dv = self.devs.get(key) or _Dev(e)
            dv.name = e.get("name") or dv.name
            if self.d.device_cfg(key).get("disabled"):
                dv.status, dv.error = "disabled", ""
            elif dv.status == "disabled":
                dv.status, dv.next_try = "starting", 0.0
            keep[key] = dv
        self.devs = keep

    def _connect(self, dv: _Dev) -> None:
        try:
            info = http_json(dv.host, "/json/info")
            state = http_json(dv.host, "/json/state")
            dv.leds = int(info["leds"]["count"])
            segs = [int(s["stop"]) - int(s["start"]) for s in state.get("seg", []) if s.get("stop", 0) > s.get("start", 0)]
            dv.segs = segs if segs and sum(segs) == dv.leds else [dv.leds]
            dv.firmware = info.get("ver", "")
            dv.addr = (socket.gethostbyname(dv.host), DDP_PORT)
            if not state.get("on"):
                # realtime frames stay dark while WLED itself is switched off
                http_json(dv.host, "/json/state", {"on": True})
            dv.status, dv.error = "ok", ""
            log.info("WLED %s (%s): %d LEDs", dv.name, dv.host, dv.leds)
        except (OSError, ValueError, KeyError) as e:
            if dv.status != "offline":
                log.warning("WLED %s: %s", dv.host, e)
            dv.status, dv.error = "offline", str(e)
            dv.next_try = time.monotonic() + RETRY

    def run(self) -> None:
        last_check = 0.0
        while not self.stop_evt.is_set():
            self._wake.wait(0.5)
            self._wake.clear()
            if self._reload:
                self._sync_config()
            now = time.monotonic()
            for dv in list(self.devs.values()):
                if dv.status in ("starting", "offline") and now >= dv.next_try:
                    self._connect(dv)
            if now - last_check > 30:   # notice LED count or segment changes made in WLED itself
                last_check = now
                for dv in list(self.devs.values()):
                    if dv.status == "ok":
                        threading.Thread(target=self._recheck, args=(dv,), daemon=True).start()
            with self._lock:
                frames, self._frame = self._frame, None
            if frames is None:
                continue
            self.seq = self.seq % 15 + 1
            for dv in list(self.devs.values()):
                if dv.status != "ok" or not dv.addr:
                    continue
                rgb = frames.get(dv.key, {}).get(f"{dv.key}/z0")
                if not rgb or len(rgb) != dv.leds * 3:
                    continue
                try:
                    for pkt in ddp_packets(bytes(rgb), self.seq):
                        self.sock.sendto(pkt, dv.addr)
                except OSError as e:
                    dv.status, dv.error = "offline", str(e)
                    dv.next_try = time.monotonic() + RETRY

    def _recheck(self, dv: _Dev) -> None:
        try:
            info = http_json(dv.host, "/json/info")
            state = http_json(dv.host, "/json/state")
        except (OSError, ValueError):
            dv.status, dv.error, dv.next_try = "offline", "keine Antwort", time.monotonic() + RETRY
            return
        segs = [int(s["stop"]) - int(s["start"]) for s in state.get("seg", []) if s.get("stop", 0) > s.get("start", 0)]
        leds = int(info["leds"]["count"])
        if leds != dv.leds or (segs and sum(segs) == leds and segs != dv.segs):
            dv.leds, dv.segs = leds, segs if segs and sum(segs) == leds else [leds]
            log.info("WLED %s: jetzt %d LEDs", dv.host, leds)

    def close(self) -> None:
        self.stop_evt.set()
        self._wake.set()
        try:
            self.sock.close()
        except OSError:
            pass
