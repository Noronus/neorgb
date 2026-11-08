"""NeoRGB desktop app (PySide6 / QML).  Talks to neorgbd over its socket."""

from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
SOCKET = str(RUNTIME / "neorgb.sock")
HERE = Path(__file__).resolve().parent


LIVE_FAN_FIELDS = ("rpm", "duty", "target", "temp", "failsafe")


def _key_prop(key: str, sig: Signal) -> Property:
    return Property("QVariant", lambda self: self._d.get(key), notify=sig)


class Store(QObject):
    """The daemon state, split per top-level key.

    QML binds to ``store.devices``, ``store.fans`` and so on.  Each key only
    notifies when its content really changed, so the once-a-second poll no
    longer rebuilds every card, closes open dropdowns or resets sliders.
    Fan readings that change every second live apart in ``fan_live``.
    """

    devicesChanged = Signal()
    fansChanged = Signal()
    fan_liveChanged = Signal()
    zonesChanged = Signal()
    sensorsChanged = Signal()
    configChanged = Signal()
    effectsChanged = Signal()
    effect_orderChanged = Signal()
    presetsChanged = Signal()
    hw_effectsChanged = Signal()
    uptimeChanged = Signal()

    devices = _key_prop("devices", devicesChanged)
    fans = _key_prop("fans", fansChanged)
    fan_live = _key_prop("fan_live", fan_liveChanged)
    zones = _key_prop("zones", zonesChanged)
    sensors = _key_prop("sensors", sensorsChanged)
    config = _key_prop("config", configChanged)
    effects = _key_prop("effects", effectsChanged)
    effect_order = _key_prop("effect_order", effect_orderChanged)
    presets = _key_prop("presets", presetsChanged)
    hw_effects = _key_prop("hw_effects", hw_effectsChanged)
    uptime = _key_prop("uptime", uptimeChanged)

    KEYS = ("devices", "fans", "fan_live", "zones", "sensors", "config", "effects",
            "effect_order", "presets", "hw_effects", "uptime")

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)   # a parent keeps QML's GC from claiming it
        self._d: dict = {}
        self._json: dict[str, str] = {}

    def update(self, state: dict) -> bool:
        state = dict(state)
        fans = state.get("fans") or []
        state["fan_live"] = {f["id"]: {k: f.get(k) for k in LIVE_FAN_FIELDS} for f in fans}
        state["fans"] = [{k: v for k, v in f.items() if k not in LIVE_FAN_FIELDS} for f in fans]
        changed = False
        for key in self.KEYS:
            val = state.get(key)
            j = json.dumps(val, sort_keys=True)
            if j != self._json.get(key):
                self._json[key] = j
                self._d[key] = val
                getattr(self, key + "Changed").emit()
                changed = True
        return changed


class Backend(QObject):
    stateChanged = Signal()
    frameChanged = Signal()
    historyChanged = Signal()
    connectedChanged = Signal()
    toast = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._state: dict = {}
        self._frame: dict = {}
        self._history: dict = {}
        self._connected = False
        self._buf = b""
        self._ids = itertools.count(1)
        self._pending: dict[int, str] = {}
        self._preview = False
        self._store = Store(self)
        self.sock = QLocalSocket(self)
        self.sock.readyRead.connect(self._read)
        self.sock.connected.connect(self._on_connected)
        self.sock.disconnected.connect(self._on_disconnected)
        self.sock.errorOccurred.connect(lambda *_: self._on_disconnected())

        self.t_state = QTimer(self, interval=1000, timeout=self._poll_state)
        self.t_frame = QTimer(self, interval=66, timeout=self._poll_frame)
        self.t_hist = QTimer(self, interval=5000, timeout=self._poll_history)
        self.t_retry = QTimer(self, interval=2000, timeout=self._connect)
        self.t_retry.start()
        self._connect()

    # ---------------------------------------------------------- connection
    def _connect(self) -> None:
        if self.sock.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            self.sock.connectToServer(SOCKET)

    def _on_connected(self) -> None:
        self._connected = True
        self.connectedChanged.emit()
        self.t_state.start()
        self.t_hist.start()
        if self._preview:
            self.t_frame.start()
        self._poll_state()
        self._poll_history()

    def _on_disconnected(self) -> None:
        if self._connected:
            self._connected = False
            self.connectedChanged.emit()
        self._pending.clear()
        self._buf = b""
        self.t_state.stop()
        self.t_frame.stop()
        self.t_hist.stop()

    def _send(self, method: str, params: dict | None = None, tag: str = "") -> None:
        if not self._connected:
            return
        rid = next(self._ids)
        self._pending[rid] = tag or method
        msg = json.dumps({"id": rid, "method": method, "params": params or {}}) + "\n"
        self.sock.write(msg.encode())

    def _read(self) -> None:
        self._buf += bytes(self.sock.readAll())
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            try:
                res = json.loads(line)
            except json.JSONDecodeError:
                continue
            tag = self._pending.pop(res.get("id"), "")
            if "error" in res:
                self.toast.emit(str(res["error"]))
                continue
            r = res.get("result")
            if tag == "state":
                self._state = r
                self._store.update(r)
                self.stateChanged.emit()
            elif tag == "frame":
                self._frame = r
                self.frameChanged.emit()
            elif tag.startswith("history:"):
                self._history[tag[8:]] = r
                self.historyChanged.emit()
            elif tag == "mutate":
                QTimer.singleShot(60, self._poll_state)

    def _poll_state(self) -> None:
        if "state" not in self._pending.values():
            self._send("state")

    def _poll_frame(self) -> None:
        if "frame" not in self._pending.values():
            self._send("frame")

    def _poll_history(self) -> None:
        for sid in ("liquid", "cpu", "gpu"):
            self._send("history", {"sensor": sid, "seconds": 600}, tag=f"history:{sid}")

    # ------------------------------------------------------------- for QML
    @Property("QVariant", notify=stateChanged)
    def state(self):
        return self._state

    @Property(QObject, constant=True)
    def store(self):
        return self._store

    @Property("QVariant", notify=frameChanged)
    def frame(self):
        return self._frame

    @Property("QVariant", notify=historyChanged)
    def history(self):
        return self._history

    @Property(bool, notify=connectedChanged)
    def connected(self):
        return self._connected

    @Slot(str, "QVariant")
    def call(self, method: str, params) -> None:
        if hasattr(params, "toVariant"):
            params = params.toVariant()
        self._send(method, params or {}, tag="mutate")

    @Slot(bool)
    def setPreview(self, on: bool) -> None:
        self._preview = on
        if on and self._connected:
            self.t_frame.start()
        else:
            self.t_frame.stop()

    @Slot()
    def startDaemon(self) -> None:
        if shutil.which("systemctl"):
            r = subprocess.run(["systemctl", "--user", "start", "neorgbd.service"], capture_output=True, text=True)
            if r.returncode == 0:
                return
        # not installed as service: run it detached from this checkout
        subprocess.Popen([sys.executable, "-m", "neorgb.daemon"], cwd=str(HERE.parent.parent),
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    QQuickStyle.setStyle("Basic")
    app = QGuiApplication(sys.argv)
    app.setApplicationName("NeoRGB")
    app.setOrganizationName("neorgb")
    app.setDesktopFileName("neorgb")
    icon = HERE / "icons" / "neorgb.svg"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    backend = Backend()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "Main.qml")))
    if not engine.rootObjects():
        return 1
    shot = os.environ.get("NEORGB_SCREENSHOT")
    if shot:   # dev helper: NEORGB_SCREENSHOT=out.png NEORGB_PAGE=1
        win = engine.rootObjects()[0]
        page = int(os.environ.get("NEORGB_PAGE", "0"))
        win.setProperty("page", page)

        def grab():
            win.grabWindow().save(shot)
            app.quit()
        QTimer.singleShot(int(os.environ.get("NEORGB_DELAY", "2500")), grab)
    rc = app.exec()
    del engine   # tear QML down while backend still exists, avoids null errors on exit
    return rc


if __name__ == "__main__":
    sys.exit(main())
