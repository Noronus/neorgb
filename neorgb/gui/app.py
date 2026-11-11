"""NeoRGB desktop app (PySide6 / QML).  Talks to neorgbd over its socket."""

from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Property, QLocale, QObject, QProcess, QSettings, QTimer, QTranslator, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .. import i18n

RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
SOCKET = str(RUNTIME / "neorgb.sock")
GUI_SOCKET = str(RUNTIME / "neorgb-gui.sock")   # second launch shows the running window
UNIT = "neorgbd.service"
HERE = Path(__file__).resolve().parent


LIVE_FAN_FIELDS = ("rpm", "duty", "target", "temp", "failsafe", "why")


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("neorgb")
    except Exception:   # running from a checkout that was never installed
        import re
        m = re.search(r'^version = "(.+)"', (HERE.parent.parent / "pyproject.toml").read_text(), re.M)
        return m.group(1) if m else "?"


class Translator(QTranslator):
    """Feeds qsTr() (and texts from the daemon) through neorgb.i18n."""

    def __init__(self, lang: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.lang = lang

    def translate(self, context, source, disambiguation=None, n=-1):  # noqa: ARG002
        return i18n.translate(source, self.lang)

    def isEmpty(self) -> bool:
        return False


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
    serviceModeChanged = Signal()
    languageChanged = Signal()
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
        self._mode = ""          # "", "restarting" or "off" (switched off until next login/boot)
        self._quit_then_start = False
        self._store = Store(self)
        # language: NEORGB_LANG (screenshots, tests) > saved choice > ask on first start
        self._settings = QSettings("neorgb", "NeoRGB")
        forced = os.environ.get("NEORGB_LANG", "")
        saved = str(self._settings.value("language", "") or "")
        self._fixed_lang = forced in i18n.LANGUAGES
        lang = forced if self._fixed_lang else saved
        self._lang_chosen = lang in i18n.LANGUAGES
        if not self._lang_chosen:   # what the picker shows behind it until the user picks
            lang = "de" if QLocale.system().language() == QLocale.Language.German else "en"
        self._lang = lang
        self.translator = Translator(lang, self)
        QApplication.instance().installTranslator(self.translator)
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
        self._set_mode("")
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
        if self._quit_then_start:
            self._quit_then_start = False
            QTimer.singleShot(500, self.startDaemon)

    def _set_mode(self, mode: str) -> None:
        if mode != self._mode:
            self._mode = mode
            self.serviceModeChanged.emit()

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
                self.toast.emit(self.t(str(res["error"])))
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

    @Property(str, notify=serviceModeChanged)
    def serviceMode(self):
        return self._mode

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

    @Slot(str)
    def copyText(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self.toast.emit(self.t("Kopiert"))

    # ------------------------------------------------------------- language
    def t(self, text: str) -> str:
        return i18n.translate(text, self._lang)

    @Property(str, notify=languageChanged)
    def language(self):
        return self._lang

    @Property(bool, notify=languageChanged)
    def languageChosen(self):
        return self._lang_chosen

    @Property("QVariant", constant=True)
    def languages(self):
        return [{"id": k, "name": v} for k, v in i18n.LANGUAGES.items()]

    @Property(str, constant=True)
    def version(self):
        return _version()

    @Slot(str)
    def setLanguage(self, lang: str) -> None:
        if lang not in i18n.LANGUAGES:
            return
        if not self._fixed_lang:
            self._settings.setValue("language", lang)
            self._settings.sync()
        changed = lang != self._lang or not self._lang_chosen
        self._lang = self.translator.lang = lang
        self._lang_chosen = True
        if changed:
            self.languageChanged.emit()

    # ------------------------------------------------------ service control
    @staticmethod
    def _unit_active() -> bool:
        if not shutil.which("systemctl"):
            return False
        r = subprocess.run(["systemctl", "--user", "is-active", "--quiet", UNIT], capture_output=True)
        return r.returncode == 0

    def _systemctl(self, verb: str, fail: str) -> None:
        """Run ``systemctl --user <verb> neorgbd`` without blocking the UI."""
        p = QProcess(self)

        def done(code: int, _status) -> None:
            if code != 0:
                err = bytes(p.readAllStandardError()).decode(errors="replace").strip()
                self._set_mode("")
                self.toast.emit(fail + (f": {err.splitlines()[-1]}" if err else ""))
            p.deleteLater()
        p.finished.connect(done)
        p.start("systemctl", ["--user", verb, UNIT])

    @Slot()
    def startDaemon(self) -> None:
        self._set_mode("restarting")
        if shutil.which("systemctl"):
            r = subprocess.run(["systemctl", "--user", "start", UNIT], capture_output=True, text=True)
            if r.returncode == 0:
                return
        # not installed as service: run it detached from this checkout
        subprocess.Popen([sys.executable, "-m", "neorgb.daemon"], cwd=str(HERE.parent.parent),
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @Slot()
    def restartDaemon(self) -> None:
        """Restart neorgbd, and with it the OpenRGB server it spawns."""
        self._set_mode("restarting")
        if self._unit_active():
            self._systemctl("restart", self.t("Neustart fehlgeschlagen"))
        elif self._connected:
            self._quit_then_start = True
            self._send("quit")
        else:
            self.startDaemon()

    @Slot()
    def stopDaemon(self) -> None:
        """Switch neorgbd off.  It stays enabled, so it comes back on the next login."""
        self._set_mode("off")
        self._quit_then_start = False
        if self._unit_active():
            self._systemctl("stop", self.t("Ausschalten fehlgeschlagen"))
        elif self._connected:
            self._send("quit")


class Tray(QObject):
    """Tray icon: left click shows/hides the window, right click opens the menu."""

    def __init__(self, app: QApplication, backend: Backend, win, icon: QIcon) -> None:
        super().__init__(app)
        self.app, self.backend, self.win = app, backend, win
        self.menu = QMenu()
        self.a_status = QAction(self.menu, enabled=False)
        self.a_show = QAction(self.menu, triggered=self.show_window)
        self.a_restart = QAction(self.menu, triggered=backend.restartDaemon)
        self.a_power = QAction(self.menu, triggered=self.toggle_power)
        self.a_quit = QAction(self.menu, triggered=app.quit)
        for a in (self.a_status, None, self.a_show, self.a_restart, self.a_power, None, self.a_quit):
            self.menu.addSeparator() if a is None else self.menu.addAction(a)
        self.icon = QSystemTrayIcon(icon, self)
        self.icon.setToolTip("NeoRGB")
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._activated)
        backend.connectedChanged.connect(self.refresh)
        backend.serviceModeChanged.connect(self.refresh)
        backend.languageChanged.connect(self.refresh)
        self.refresh()
        self.icon.show()

    def refresh(self) -> None:
        b = self.backend
        t = b.t
        self.a_show.setText(t("Fenster öffnen"))
        self.a_restart.setText(t("Dienst neu starten"))
        self.a_quit.setText(t("Beenden (Dienst läuft weiter)"))
        if b.connected:
            status, power = "Dienst läuft", "Ausschalten bis zum Neustart"
        elif b.serviceMode == "restarting":
            status, power = "Dienst startet …", "Ausschalten bis zum Neustart"
        elif b.serviceMode == "off":
            status, power = "Ausgeschaltet bis zum Neustart", "Dienst starten"
        else:
            status, power = "Dienst läuft nicht", "Dienst starten"
        self.a_status.setText(t(status))
        self.a_power.setText(t(power))
        self.icon.setToolTip("NeoRGB · " + t(status))

    def toggle_power(self) -> None:
        if self.backend.connected or self.backend.serviceMode == "restarting":
            self.backend.stopDaemon()
        else:
            self.backend.startDaemon()

    def show_window(self) -> None:
        self.win.show()
        self.win.raise_()
        self.win.requestActivate()

    def _activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.win.isVisible() and self.win.isActive():
                self.win.hide()
            else:
                self.show_window()


def _already_running() -> bool:
    """Ask a running NeoRGB window to come to the front.  True if one answered."""
    s = QLocalSocket()
    s.connectToServer(GUI_SOCKET)
    if not s.waitForConnected(300):
        return False
    s.write(b"show\n")
    s.waitForBytesWritten(300)
    s.disconnectFromServer()
    return True


def main() -> int:
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    QQuickStyle.setStyle("Basic")
    app = QApplication(sys.argv)
    app.setApplicationName("NeoRGB")
    app.setOrganizationName("neorgb")
    app.setDesktopFileName("neorgb")
    shot = os.environ.get("NEORGB_SCREENSHOT")
    if not shot and _already_running():
        return 0
    icon = QIcon(str(HERE / "icons" / "neorgb.svg"))
    app.setWindowIcon(icon)
    backend = Backend()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    backend.languageChanged.connect(engine.retranslate)
    engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "Main.qml")))
    if not engine.rootObjects():
        return 1
    win = engine.rootObjects()[0]
    tray = None
    if not shot:
        tray = Tray(app, backend, win, icon)
        # closing the window keeps NeoRGB in the tray; "Beenden" in the tray menu quits
        app.setQuitOnLastWindowClosed(not QSystemTrayIcon.isSystemTrayAvailable())
        QLocalServer.removeServer(GUI_SOCKET)
        server = QLocalServer(app)
        server.newConnection.connect(lambda: (server.nextPendingConnection().deleteLater(), tray.show_window()))
        server.listen(GUI_SOCKET)
    if shot:   # dev helper: NEORGB_SCREENSHOT=out.png NEORGB_PAGE=1
        page = int(os.environ.get("NEORGB_PAGE", "0"))
        win.setProperty("page", page)

        def grab():
            win.grabWindow().save(shot)
            app.quit()
        QTimer.singleShot(int(os.environ.get("NEORGB_DELAY", "2500")), grab)
    rc = app.exec()
    del tray
    del engine   # tear QML down while backend still exists, avoids null errors on exit
    return rc


if __name__ == "__main__":
    sys.exit(main())
