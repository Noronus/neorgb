"""Screen capture for the "screen" lighting effect (like iCUE screen ambience).

Wayland only lets a program see the screen through the desktop portal
(org.freedesktop.portal.ScreenCast).  The first start shows the desktop's
"share screen" dialog; the portal then hands out a restore token so later
starts run without asking.  Frames come from PipeWire through GStreamer and
are scaled down to a small RGB thumbnail; effects sample that.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

log = logging.getLogger("neorgb.screen")

W, H = 64, 36           # thumbnail the effect samples
IDLE_STOP = 5.0         # seconds without a reader before capture stops


class ScreenCapture:
    def __init__(self, token_file: Path) -> None:
        self.token_file = token_file
        self.lock = threading.Lock()
        self._frame: bytes | None = None
        self._stamp = 0.0
        self.error = ""
        self.thread: threading.Thread | None = None
        self.stop_evt = threading.Event()
        self.last_use = 0.0
        self._bus = None

    # ---- used by the render loop
    def frame(self) -> bytes | None:
        """Latest W*H*3 RGB thumbnail, or None.  Starts capture on first use."""
        self.last_use = time.monotonic()
        if self.thread is None or not self.thread.is_alive():
            if not self.error or time.monotonic() - self._stamp > 30:
                self._start()
        with self.lock:
            return self._frame

    def idle_check(self) -> None:
        if self.thread and self.thread.is_alive() and time.monotonic() - self.last_use > IDLE_STOP:
            self.stop()

    def stop(self) -> None:
        self.stop_evt.set()
        t = self.thread
        if t and t is not threading.current_thread():
            t.join(3)
        self.thread = None
        with self.lock:
            self._frame = None

    # ---- capture thread
    def _start(self) -> None:
        self.stop_evt = threading.Event()
        self._stamp = time.monotonic()
        self.thread = threading.Thread(target=self._run, args=(self.stop_evt,), daemon=True, name="screen")
        self.thread.start()

    def _run(self, stop: threading.Event) -> None:
        try:
            import gi
            gi.require_version("Gst", "1.0")
            from gi.repository import Gio, GLib, Gst
        except (ImportError, ValueError) as e:
            self.error = f"GStreamer/PyGObject fehlt: {e}"
            log.warning("screen: %s", self.error)
            return
        ctx = GLib.MainContext.new()
        ctx.push_thread_default()
        pipe = None
        try:
            fd, node = self._portal(Gio, GLib, ctx, stop)
            if fd is None:
                return
            Gst.init(None)
            pipe = Gst.parse_launch(
                f"pipewiresrc fd={fd} path={node} ! video/x-raw,max-framerate=20/1 ! "
                "videoscale method=nearest-neighbour ! video/x-raw,width=480,height=270 ! "
                "videoconvert ! video/x-raw,format=RGB ! "
                f"videoscale method=bilinear2 ! video/x-raw,format=RGB,width={W},height={H} ! "
                "appsink name=sink max-buffers=1 drop=true sync=false")
            sink = pipe.get_by_name("sink")
            pipe.set_state(Gst.State.PLAYING)
            self.error = ""
            log.info("screen: Aufnahme läuft (PipeWire-Node %s)", node)
            bus = pipe.get_bus()
            while not stop.is_set():
                msg = bus.pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.EOS)
                if msg:
                    if msg.type == Gst.MessageType.ERROR:
                        err, _dbg = msg.parse_error()
                        raise RuntimeError(err.message)
                    raise RuntimeError("Bildschirmfreigabe beendet")
                sample = sink.emit("try-pull-sample", 200 * Gst.MSECOND)
                if sample is None:
                    continue
                buf = sample.get_buffer()
                caps = sample.get_caps().get_structure(0)
                stride = (W * 3 + 3) & ~3
                ok, info = buf.map(Gst.MapFlags.READ)
                if not ok:
                    continue
                try:
                    raw = bytes(info.data)
                finally:
                    buf.unmap(info)
                if caps.get_value("width") != W or len(raw) < stride * H:
                    continue
                data = b"".join(raw[y * stride:y * stride + W * 3] for y in range(H)) if stride != W * 3 else raw[:W * H * 3]
                with self.lock:
                    self._frame = data
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            self._stamp = time.monotonic()
            log.warning("screen: %s", e)
        finally:
            if pipe is not None:
                pipe.set_state(Gst.State.NULL)
            self._bus = None
            with self.lock:
                self._frame = None
            ctx.pop_thread_default()

    def _portal(self, Gio, GLib, ctx, stop):
        """Run the ScreenCast portal handshake; returns (pipewire fd, node id)."""
        # Keep the connection: the portal closes the session (and KWin the
        # stream) as soon as this D-Bus client goes away.
        bus = self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        sender = bus.get_unique_name()[1:].replace(".", "_")
        name, path = "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop"
        iface = "org.freedesktop.portal.ScreenCast"
        n = [0]

        def request(method: str, args: list, opts: dict):
            n[0] += 1
            tok = f"neorgb{n[0]}_{int(time.time())}"
            req = f"/org/freedesktop/portal/desktop/request/{sender}/{tok}"
            box: dict = {}

            def on_resp(_c, _s, _p, _i, _sig, params):
                box["r"] = params.unpack()

            sid = bus.signal_subscribe(name, "org.freedesktop.portal.Request", "Response", req,
                                       None, Gio.DBusSignalFlags.NO_MATCH_RULE, on_resp)
            try:
                opts = {**opts, "handle_token": GLib.Variant("s", tok)}
                sig = "(" + "".join(a[0] for a in args) + "a{sv})"
                bus.call_sync(name, path, iface, method,
                              GLib.Variant(sig, tuple(a[1] for a in args) + (opts,)),
                              None, Gio.DBusCallFlags.NONE, -1, None)
                while "r" not in box and not stop.is_set():
                    ctx.iteration(False) or time.sleep(0.05)
            finally:
                bus.signal_unsubscribe(sid)
            if "r" not in box:
                return None
            code, res = box["r"]
            if code != 0:
                raise RuntimeError("Bildschirmfreigabe abgelehnt" if code == 1 else "Portal-Fehler")
            return res

        res = request("CreateSession", [], {"session_handle_token": GLib.Variant("s", "neorgb")})
        if res is None:
            return None, None
        session = res["session_handle"]
        opts = {"types": GLib.Variant("u", 1), "multiple": GLib.Variant("b", False),
                "cursor_mode": GLib.Variant("u", 1), "persist_mode": GLib.Variant("u", 2)}
        try:
            tok = self.token_file.read_text().strip()
            if tok:
                opts["restore_token"] = GLib.Variant("s", tok)
        except OSError:
            pass
        if request("SelectSources", [("o", session)], opts) is None:
            return None, None
        res = request("Start", [("o", session), ("s", "")], {})
        if res is None:
            return None, None
        if res.get("restore_token"):
            try:
                self.token_file.parent.mkdir(parents=True, exist_ok=True)
                self.token_file.write_text(res["restore_token"])
            except OSError as e:
                log.warning("screen: restore token: %s", e)
        streams = res.get("streams") or []
        if not streams:
            raise RuntimeError("Portal lieferte keinen Bildschirm")
        node = streams[0][0]
        ret, fds = bus.call_with_unix_fd_list_sync(name, path, iface, "OpenPipeWireRemote",
                                                    GLib.Variant("(oa{sv})", (session, {})), None,
                                                    Gio.DBusCallFlags.NONE, -1, None, None)
        fd = fds.get(ret.unpack()[0])
        return fd, node


def sample(frame: bytes, x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float]:
    """Mean colour of the thumbnail rectangle (fractions 0..1)."""
    ax, bx = int(x0 * W), max(int(x0 * W) + 1, int(round(x1 * W)))
    ay, by = int(y0 * H), max(int(y0 * H) + 1, int(round(y1 * H)))
    ax, bx = max(0, min(W - 1, ax)), max(1, min(W, bx))
    ay, by = max(0, min(H - 1, ay)), max(1, min(H, by))
    r = g = b = 0
    cnt = 0
    for y in range(ay, by):
        row = y * W * 3
        for x in range(ax, bx):
            i = row + x * 3
            r += frame[i]; g += frame[i + 1]; b += frame[i + 2]
            cnt += 1
    return (r / cnt, g / cnt, b / cnt) if cnt else (0.0, 0.0, 0.0)
