"""Load the whole QML UI offscreen, without a running daemon.

Exits 1 if a QML module is missing or a page fails to load.  Used to check
that a distro package pulls in every Qt/QML piece it needs:

    python3 tests/smoke_gui.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, QUrl, QtMsgType, qInstallMessageHandler  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402

from neorgb.gui import app as A  # noqa: E402

problems = []


def on_msg(mode, ctx, msg):
    if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        problems.append(msg)


qInstallMessageHandler(on_msg)
QQuickStyle.setStyle("Basic")
app = QGuiApplication(sys.argv)
backend = A.Backend()
engine = QQmlApplicationEngine()
engine.rootContext().setContextProperty("backend", backend)
engine.load(QUrl.fromLocalFile(str(A.HERE / "qml" / "Main.qml")))
roots = engine.rootObjects()
if roots:
    win = roots[0]
    pages = iter(range(5))

    def next_page():
        try:
            win.setProperty("page", next(pages))
            QTimer.singleShot(300, next_page)
        except StopIteration:
            app.quit()

    QTimer.singleShot(500, next_page)
    app.exec()
del engine

qml = [p for p in problems if "qml" in p.lower() or "module" in p.lower()]
print("geladen aus", A.HERE)
for p in qml:
    print("QML:", p)
if not roots or qml:
    print("FEHLER: Oberfläche lädt nicht sauber")
    sys.exit(1)
print("OK: alle 5 Seiten geladen")
