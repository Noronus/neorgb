"""Corsair iCUE Commander CORE / CORE XT / Commander ST.

Protocol notes (from liquidctl docs, OpenLinkHub and OpenRGB, all GPL):

* Every report starts with 0x08, then a command.  Answers start with 0x00,
  echo the command in byte 1 and carry a status in byte 2 (0 = ok).
* "Software mode" (01 03 00 02) hands control to us.  The firmware drops back
  to hardware mode by itself when it hears nothing for a few seconds, which is
  our safety net if the daemon dies.
* Data lives behind "endpoints".  We keep channel 0 open on the colour
  endpoint (0x22) and use channel 1 for everything else (open/read/close).
* The hardware speed endpoints (0x60/0x61/0x62 0x6d) are what the device runs
  on its own when no software talks to it.  We write a safe liquid-temperature
  curve there as fallback.
* Port 0 is the AIO pump (Commander CORE / ST).  The XT has no pump, its
  port 0 is fan 1.
"""

from __future__ import annotations

import struct
import threading
import time
from dataclasses import dataclass, field

from ..hidraw import HidDevice, HidError, HidInfo

VID = 0x1B1C
MODELS = {
    0x0C1C: ("Corsair iCUE Commander CORE", 96, True),
    0x0C32: ("Corsair iCUE Commander ST", 64, True),
    0x0C2A: ("Corsair iCUE Commander CORE XT", 64, False),
}

CMD_SOFTWARE = b"\x01\x03\x00\x02"
CMD_HARDWARE = b"\x01\x03\x00\x01"
CMD_FIRMWARE = b"\x02\x13"
CMD_PUMP_VERSION = b"\x02\x57"
CMD_RADIATOR = b"\x02\x58"

EP_LED_COUNT = b"\x20"
EP_SPEEDS = b"\x17"
EP_SET_SPEED = b"\x18"
EP_CONNECTED = b"\x1a"
EP_TEMPS = b"\x21"
EP_COLOR = b"\x22"
EP_LED_PORTS = b"\x1e"
EP_HW_MODE = b"\x60\x6d"
EP_HW_FIXED = b"\x61\x6d"
EP_HW_CURVE = b"\x62\x6d"

DT_LED_COUNT = b"\x0f\x00"
DT_SPEEDS = b"\x06\x00"
DT_SET_SPEED = b"\x07\x00"
DT_CONNECTED = b"\x09\x00"
DT_TEMPS = b"\x10\x00"
DT_COLOR = b"\x12\x00"
DT_HW_MODE = b"\x03\x00"
DT_HW_FIXED = b"\x04\x00"
DT_HW_CURVE = b"\x05\x00"

HW_MODE_FIXED = 0x00
HW_MODE_CURVE = 0x02

COLOR_CH = 0
DATA_CH = 1

# LED count -> (port type code for the 0x1e endpoint, name)
LED_TYPES = {
    4: (0x03, "ML PRO RGB fan"),
    8: (0x05, "8-LED fan (SP/AF Elite)"),
    10: (0x01, "RGB LED strip"),
    12: (0x04, "HD RGB fan"),
    16: (0x02, "LL RGB fan"),
    21: (0x08, "Pump"),
    24: (0x08, "Pump"),
    29: (0x08, "Pump"),
    34: (0x06, "QL RGB fan"),
}

# Known AIOs: (pump version, radiator size) -> name
AIOS = {
    (1, 240): "H100i ELITE CAPELLIX", (2, 240): "H100i ELITE CAPELLIX",
    (1, 280): "H115i ELITE CAPELLIX", (1, 360): "H150i ELITE CAPELLIX",
    (2, 360): "H150i ELITE CAPELLIX", (1, 420): "H170i ELITE CAPELLIX",
    (3, 240): "H100i ELITE (LCD/CAPELLIX)", (3, 360): "H150i ELITE (LCD/CAPELLIX)",
    (3, 420): "H170i ELITE (LCD/CAPELLIX)",
    (5, 240): "H100i ELITE XT", (6, 240): "H100i ELITE XT", (5, 280): "H115i ELITE XT",
    (5, 360): "H150i ELITE XT", (6, 360): "H150i ELITE XT", (5, 420): "H170i ELITE XT",
}

PUMP_MIN_DUTY = 50   # never let the pump go below this
FAN_MIN_DUTY = 0     # 0 % is allowed for fans (semi passive), curves decide


class ProtocolError(HidError):
    pass


@dataclass
class CCStatus:
    rpm: list[int] = field(default_factory=list)          # per speed port
    connected: list[bool] = field(default_factory=list)   # per speed port
    temps: list[float | None] = field(default_factory=list)
    duty: list[int | None] = field(default_factory=list)  # what we last set


class CommanderCore:
    kind = "commander_core"

    def __init__(self, info: HidInfo):
        name, size, has_pump = MODELS[info.pid]
        self.info = info
        self.name = name
        self.has_pump = has_pump
        self.size = size
        self.dev = HidDevice(info, size, size)
        self.lock = threading.RLock()
        self.firmware = ""
        self.aio = ""
        self.led_counts: list[int] = []    # per RGB port, 0 = nothing
        self.port_counts: list[int] = []   # what we told the device (0x1e)
        self.software = False
        self.color_open = False
        self.last_io = 0.0

    # ------------------------------------------------------------------ io
    def _xfer(self, cmd: bytes, data: bytes = b"", *, retries: int = 3) -> bytes:
        report = b"\x08" + cmd + data
        last_err: Exception | None = None
        for _ in range(retries):
            try:
                self.dev.drain()
                self.dev.write(report)
                deadline = time.monotonic() + 0.5
                while True:
                    res = self.dev.read(max(0.01, deadline - time.monotonic()))
                    if res[0] == 0x00 and res[1] == cmd[0]:
                        self.last_io = time.monotonic()
                        return res
            except HidError as e:
                last_err = e
                if "gone" in str(e):
                    raise
                time.sleep(0.02)
        raise ProtocolError(f"{self.name}: no answer to {cmd.hex()}: {last_err}")

    def _close_ep(self, ch: int) -> None:
        self._xfer(bytes([0x05, 0x01, ch]))

    def _open_ep(self, ch: int, ep: bytes) -> None:
        self._xfer(bytes([0x0D, ch]) + ep)

    def _read_ep(self, ep: bytes, dtype: bytes, parts: int = 1) -> bytes:
        for attempt in range(4):
            self._close_ep(DATA_CH)
            self._open_ep(DATA_CH, ep)
            first = self._xfer(bytes([0x08, DATA_CH, 0x01]))
            data = first[5:]
            for part in range(2, parts + 1):
                more = self._xfer(bytes([0x08, DATA_CH, part]))
                data += more[3:]
            self._close_ep(DATA_CH)
            if first[3:5] == dtype:
                return data
            time.sleep(0.05 * (attempt + 1))
        raise ProtocolError(f"{self.name}: endpoint {ep.hex()} answered type {first[3:5].hex()}, wanted {dtype.hex()}")

    def _chunks(self, payload: bytes, cmd_first: bytes, cmd_more: bytes):
        first_room = self.size - 1 - len(cmd_first)
        more_room = self.size - 1 - len(cmd_more)
        yield cmd_first, payload[:first_room]
        pos = first_room
        while pos < len(payload):
            yield cmd_more, payload[pos:pos + more_room]
            pos += more_room

    def _write_ep(self, ep: bytes, dtype: bytes, data: bytes) -> bytes:
        body = struct.pack("<HH", len(data) + len(dtype), 0) + dtype + data
        self._close_ep(DATA_CH)
        self._open_ep(DATA_CH, ep)
        res = b""
        for i, (cmd, chunk) in enumerate(self._chunks(body, bytes([0x06, DATA_CH]), bytes([0x07, DATA_CH]))):
            r = self._xfer(cmd, chunk)
            if i == 0:
                res = r
        self._close_ep(DATA_CH)
        return res

    # ------------------------------------------------------------ lifecycle
    def open(self) -> None:
        """Read identity.  Does not change anything on the device."""
        with self.lock:
            fw = self._xfer(CMD_FIRMWARE)
            self.firmware = f"{fw[3]}.{fw[4]}.{fw[5]}"
            if self.has_pump:
                try:
                    pv = self._xfer(CMD_PUMP_VERSION)[3]
                    rad = struct.unpack_from("<H", self._xfer(CMD_RADIATOR), 3)[0]
                    self.aio = AIOS.get((pv, rad), f"AIO pump v{pv}, {rad} mm")
                except ProtocolError:
                    self.aio = "AIO"

    def enter_software(self) -> None:
        with self.lock:
            self._xfer(CMD_SOFTWARE)
            self.software = True
            self.color_open = False

    def enter_hardware(self) -> None:
        with self.lock:
            try:
                if self.color_open:
                    self._close_ep(COLOR_CH)
            except HidError:
                pass
            self.color_open = False
            self._xfer(CMD_HARDWARE)
            self.software = False

    def close(self) -> None:
        with self.lock:
            try:
                if self.software:
                    self.enter_hardware()
            finally:
                self.dev.close()

    def keepalive(self) -> None:
        """Software mode times out when the device hears nothing."""
        if self.software and time.monotonic() - self.last_io > 1.0:
            with self.lock:
                self._xfer(CMD_FIRMWARE)

    # -------------------------------------------------------------- reading
    @property
    def speed_labels(self) -> list[str]:
        if self.has_pump:
            return ["Pump"] + [f"Fan {i}" for i in range(1, 7)]
        return [f"Fan {i}" for i in range(1, 7)]

    @property
    def rgb_labels(self) -> list[str]:
        if self.has_pump:
            return ["Pump"] + [f"RGB port {i}" for i in range(1, 7)]
        return [f"RGB port {i}" for i in range(1, 8)]

    def read_led_counts(self) -> list[int]:
        with self.lock:
            d = self._read_ep(EP_LED_COUNT, DT_LED_COUNT)
        n = d[0]
        counts = []
        for i in range(n):
            mode, count = struct.unpack_from("<HH", d, 1 + i * 4)
            counts.append(count if mode == 2 else 0)
        self.led_counts = counts
        return counts

    def read_connected(self) -> list[bool]:
        with self.lock:
            d = self._read_ep(EP_CONNECTED, DT_CONNECTED)
        # 0x07 connected + spinning, 0x02 connected but no tach (zero RPM)
        return [d[1 + i] in (0x07, 0x02) for i in range(d[0])]

    def read_speeds(self) -> list[int]:
        with self.lock:
            d = self._read_ep(EP_SPEEDS, DT_SPEEDS)
        return [struct.unpack_from("<H", d, 1 + i * 2)[0] for i in range(d[0])]

    def read_temps(self) -> list[float | None]:
        with self.lock:
            d = self._read_ep(EP_TEMPS, DT_TEMPS)
        out: list[float | None] = []
        for i in range(d[0]):
            ok = d[1 + i * 3] == 0x00
            val = struct.unpack_from("<H", d, 2 + i * 3)[0] / 10.0
            out.append(val if ok and 0 < val < 100 else None)
        return out

    def read_hw_config(self) -> dict:
        """The speed setup the device runs in hardware mode."""
        with self.lock:
            modes = self._read_ep(EP_HW_MODE, DT_HW_MODE)
            fixed = self._read_ep(EP_HW_FIXED, DT_HW_FIXED)
            curves = self._read_ep(EP_HW_CURVE, DT_HW_CURVE, parts=3)
        n = modes[0]
        out = {"modes": list(modes[1:1 + n]),
               "fixed": [struct.unpack_from("<H", fixed, 1 + 2 * i)[0] for i in range(fixed[0])],
               "curves": []}
        pos = 1
        for _ in range(curves[0]):
            sensor, count = curves[pos], curves[pos + 1]
            pts = [struct.unpack_from("<HH", curves, pos + 2 + 4 * k) for k in range(count)]
            out["curves"].append({"sensor": sensor, "points": [(t / 10, d) for t, d in pts]})
            pos += 2 + 4 * count
        return out

    # -------------------------------------------------------------- writing
    def _clamp(self, port: int, duty: int) -> int:
        duty = max(0, min(100, int(round(duty))))
        if self.has_pump and port == 0:
            duty = max(PUMP_MIN_DUTY, duty)
        return duty

    def set_software_duty(self, duties: dict[int, int]) -> None:
        """Set fixed duty per speed port while in software mode."""
        if not duties:
            return
        payload = bytearray([len(duties)])
        for port in sorted(duties):
            payload += bytes([port, 0x00, self._clamp(port, duties[port]), 0x00])
        with self.lock:
            for _ in range(5):
                res = self._write_ep(EP_SET_SPEED, DT_SET_SPEED, bytes(payload))
                if res[2] == 0x00:
                    return
                time.sleep(0.05)
        raise ProtocolError(f"{self.name}: device refused speed update")

    def write_hw_fallback(self, curves: dict[int, list[tuple[float, int]]]) -> None:
        """Store liquid-temperature curves that the device runs on its own.

        curves: port -> [(temp_c, duty), ...] with 2..7 points.
        Ports that are not given keep their current hardware setting.
        """
        with self.lock:
            modes = bytearray(self._read_ep(EP_HW_MODE, DT_HW_MODE))
            n = modes[0]
            raw = self._read_ep(EP_HW_CURVE, DT_HW_CURVE, parts=3)
            per_port: list[bytes] = []
            pos = 1
            for _ in range(raw[0]):
                count = raw[pos + 1]
                per_port.append(bytes(raw[pos:pos + 2 + 4 * count]))
                pos += 2 + 4 * count
            for port, pts in curves.items():
                if port >= n or port >= len(per_port):
                    continue
                pts = sorted(pts)[:7]
                if len(pts) < 2:
                    continue
                blob = bytearray([0x00, len(pts)])  # sensor 0 = liquid
                for t, d in pts:
                    blob += struct.pack("<HH", int(round(t * 10)), self._clamp(port, d))
                per_port[port] = bytes(blob)
                modes[1 + port] = HW_MODE_CURVE
            self._write_ep(EP_HW_MODE, DT_HW_MODE, bytes(modes[:1 + n]))
            self._write_ep(EP_HW_CURVE, DT_HW_CURVE, bytes([len(per_port)]) + b"".join(per_port))

    # ------------------------------------------------------------------ RGB
    def setup_rgb(self, port_counts: list[int]) -> None:
        """Tell the device which LED device sits on each RGB port and open
        the colour endpoint.  port_counts: LEDs per RGB port (0 = unused)."""
        with self.lock:
            buf = bytearray(b"\x0d\x00\x07")
            for count in port_counts[:7]:
                code = LED_TYPES.get(count, (None,))[0]
                if count and code is not None:
                    buf += bytes([0x01, code])
                else:
                    buf += b"\x00"
            # This endpoint has no separate data type, the 0d 00 above is it.
            self._close_ep(DATA_CH)
            self._open_ep(DATA_CH, EP_LED_PORTS)
            body = struct.pack("<HH", len(buf), 0) + bytes(buf)
            for cmd, chunk in self._chunks(body, bytes([0x06, DATA_CH]), bytes([0x07, DATA_CH])):
                self._xfer(cmd, chunk)
            self._close_ep(DATA_CH)
            self.port_counts = [c if c in LED_TYPES else 0 for c in port_counts[:7]]
            self._close_ep(COLOR_CH)
            self._open_ep(COLOR_CH, EP_COLOR)
            self.color_open = True

    def init_led_ports(self) -> None:
        """Ask the device to re-probe its RGB ports (as iCUE does on start)."""
        with self.lock:
            for port in range(7):
                self._xfer(bytes([0x14, port, 0x01]))
        time.sleep(0.5)

    def write_colors(self, rgb: bytes) -> None:
        """rgb: R,G,B bytes for every LED of every configured port, in order."""
        if not self.color_open:
            return
        body = struct.pack("<HH", len(rgb) + 2, 0) + DT_COLOR + rgb
        with self.lock:
            for cmd, chunk in self._chunks(body, bytes([0x06, COLOR_CH]), bytes([0x07, COLOR_CH])):
                self._xfer(cmd, chunk, retries=1)
