"""Tiny blocking client for the daemon socket (used by CLI and tests)."""

from __future__ import annotations

import itertools
import json
import socket

from .daemon import SOCKET


class DaemonError(RuntimeError):
    pass


class Client:
    def __init__(self, path=SOCKET, timeout: float = 5.0):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(timeout)
        try:
            self.sock.connect(str(path))
        except (FileNotFoundError, ConnectionRefusedError) as e:
            raise DaemonError("neorgbd läuft nicht (systemctl --user start neorgbd)") from e
        self.f = self.sock.makefile("rwb")
        self.ids = itertools.count(1)

    def call(self, method: str, **params):
        rid = next(self.ids)
        self.f.write((json.dumps({"id": rid, "method": method, "params": params}) + "\n").encode())
        self.f.flush()
        line = self.f.readline()
        if not line:
            raise DaemonError("Verbindung zum Daemon verloren")
        res = json.loads(line)
        if "error" in res:
            raise DaemonError(res["error"])
        return res["result"]

    def close(self) -> None:
        try:
            self.f.close()
            self.sock.close()
        except OSError:
            pass
