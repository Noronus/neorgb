"""Minimal hidraw access without extra dependencies.

Devices are found through sysfs, so we know vendor, product, USB interface
number and serial before opening anything.
"""

from __future__ import annotations

import errno
import os
import re
import select
from dataclasses import dataclass
from pathlib import Path

SYS_HIDRAW = Path("/sys/class/hidraw")


@dataclass(frozen=True)
class HidInfo:
    path: str          # /dev/hidrawN
    vid: int
    pid: int
    name: str
    interface: int     # USB interface number, -1 if unknown
    usb_path: str      # e.g. "1-8.2.4" (stable while the cable stays in the same port)
    serial: str

    @property
    def key(self) -> str:
        """Stable id for config files: serial if the device has one, else USB port."""
        ident = self.serial or self.usb_path
        return f"{self.vid:04x}:{self.pid:04x}:{ident}"


def _read(p: Path) -> str:
    try:
        return p.read_text().strip()
    except OSError:
        return ""


def enumerate_hidraw(vid: int | None = None, pid: int | None = None) -> list[HidInfo]:
    out: list[HidInfo] = []
    if not SYS_HIDRAW.exists():
        return out
    for node in sorted(SYS_HIDRAW.iterdir(), key=lambda p: int(p.name[6:] or 0)):
        dev = node / "device"
        uevent = _read(dev / "uevent")
        m = re.search(r"HID_ID=\w+:([0-9A-Fa-f]+):([0-9A-Fa-f]+)", uevent)
        if not m:
            continue
        v, p = int(m.group(1), 16), int(m.group(2), 16)
        if vid is not None and v != vid:
            continue
        if pid is not None and p != pid:
            continue
        name = ""
        nm = re.search(r"HID_NAME=(.*)", uevent)
        if nm:
            name = nm.group(1).strip()
        serial = ""
        sm = re.search(r"HID_UNIQ=(.*)", uevent)
        if sm:
            serial = sm.group(1).strip()
        real = os.path.realpath(dev)
        # .../1-8.2.4/1-8.2.4:1.0/0003:1B1C:0C1C.0007
        im = re.findall(r"/(\d+-[\d.]+):\d+\.(\d+)", real)
        interface, usb_path = -1, ""
        if im:
            usb_path, iface = im[-1]
            interface = int(iface)
            if not serial:
                serial = _read(Path(real.split(f"/{usb_path}:")[0]) / usb_path / "serial")
        out.append(HidInfo(f"/dev/{node.name}", v, p, name, interface, usb_path, serial))
    return out


class HidError(IOError):
    pass


class HidDevice:
    """A hidraw node opened read/write.

    write() takes the report *without* report id; we add the leading 0x00
    that hidraw wants for devices that do not use numbered reports.
    """

    def __init__(self, info: HidInfo, out_size: int, in_size: int):
        self.info = info
        self.out_size = out_size
        self.in_size = in_size
        try:
            self.fd = os.open(info.path, os.O_RDWR | os.O_NONBLOCK)
        except OSError as e:
            raise HidError(f"cannot open {info.path}: {e.strerror}") from e

    def close(self) -> None:
        if self.fd >= 0:
            try:
                os.close(self.fd)
            finally:
                self.fd = -1

    def drain(self) -> None:
        """Drop reports that are already queued (stale answers)."""
        while True:
            try:
                if not os.read(self.fd, 1024):
                    return
            except BlockingIOError:
                return
            except OSError as e:
                raise HidError(f"{self.info.path}: read failed: {e.strerror}") from e

    def write(self, data: bytes) -> None:
        buf = bytearray(self.out_size + 1)
        n = min(len(data), self.out_size)
        buf[1:1 + n] = data[:n]
        try:
            os.write(self.fd, bytes(buf))
        except OSError as e:
            if e.errno in (errno.ENODEV, errno.EIO, errno.ENOENT):
                raise HidError(f"{self.info.path}: device gone") from e
            raise HidError(f"{self.info.path}: write failed: {e.strerror}") from e

    def read(self, timeout: float = 0.5) -> bytes:
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            raise HidError(f"{self.info.path}: read timeout")
        try:
            data = os.read(self.fd, max(self.in_size, 64) + 64)
        except OSError as e:
            raise HidError(f"{self.info.path}: read failed: {e.strerror}") from e
        if not data:
            raise HidError(f"{self.info.path}: device gone")
        return data
