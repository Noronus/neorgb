"""Fan / pump curves with hysteresis and ramping.

Rising temperature is followed at once; falling temperature only lowers the
reference after it dropped by `hysteresis` degrees.  The duty then moves
towards the target with limited speed so fans do not pump up and down.
"""

from __future__ import annotations

from dataclasses import dataclass

CRITICAL_LIQUID = 50.0     # everything to 100 % above this
SENSOR_TIMEOUT = 6.0       # seconds without data -> failsafe


def interpolate(points: list[list[float]], temp: float) -> float:
    pts = sorted((float(t), float(d)) for t, d in points)
    if not pts:
        return 100.0
    if temp <= pts[0][0]:
        return pts[0][1]
    if temp >= pts[-1][0]:
        return pts[-1][1]
    for (t0, d0), (t1, d1) in zip(pts, pts[1:]):
        if t0 <= temp <= t1:
            if t1 == t0:
                return d1
            return d0 + (d1 - d0) * (temp - t0) / (t1 - t0)
    return pts[-1][1]


DEFAULT_CURVES = {
    "quiet": {
        "name": "Leise", "sensor": "liquid", "average": 0,
        "points": [[25, 20], [31, 25], [34, 35], [37, 50], [40, 75], [43, 100]],
    },
    "balanced": {
        "name": "Ausgewogen", "sensor": "liquid", "average": 0,
        "points": [[25, 25], [30, 30], [33, 40], [36, 55], [39, 75], [42, 100]],
    },
    "performance": {
        "name": "Leistung", "sensor": "liquid", "average": 0,
        "points": [[25, 40], [30, 50], [33, 65], [36, 80], [38, 100]],
    },
    "pump_balanced": {
        "name": "Pumpe ausgewogen", "sensor": "liquid", "average": 0,
        "points": [[25, 60], [33, 65], [37, 80], [40, 100]],
    },
    "cpu": {
        "name": "CPU-Temperatur", "sensor": "cpu", "average": 8,
        "points": [[40, 25], [55, 30], [65, 45], [75, 70], [85, 100]],
    },
}

DEFAULT_SETTINGS = {"hysteresis": 1.5, "ramp_up": 8.0, "ramp_down": 3.0}


@dataclass
class ChannelState:
    duty: float | None = None      # what we currently send
    target: float | None = None
    ref_temp: float | None = None
    temp: float | None = None
    failsafe: bool = False


class FanController:
    def __init__(self) -> None:
        self.states: dict[str, ChannelState] = {}

    def step(self, cid: str, cfg: dict, curves: dict, sensors, dt: float,
             settings: dict, min_duty: float, liquid: float | None) -> float | None:
        """Return the duty to send for this channel, None = leave to hardware."""
        st = self.states.setdefault(cid, ChannelState())
        mode = cfg.get("mode", "curve")
        if mode == "hardware":
            st.duty = st.target = None
            return None

        if mode == "fixed":
            target = float(cfg.get("fixed", 50))
            st.failsafe = False
            st.temp = None
        else:
            curve = curves.get(cfg.get("curve", "balanced")) or DEFAULT_CURVES["balanced"]
            sid = curve.get("sensor", "liquid")
            avg = float(curve.get("average", 0) or 0)
            temp = sensors.average(sid, avg) if avg > 0 else sensors.get(sid, SENSOR_TIMEOUT)
            st.temp = temp
            if temp is None:
                st.failsafe = True
                target = 100.0
            else:
                st.failsafe = False
                hyst = float(settings.get("hysteresis", 1.5))
                if st.ref_temp is None or temp > st.ref_temp or temp < st.ref_temp - hyst:
                    st.ref_temp = temp
                target = interpolate(curve.get("points", []), st.ref_temp)

        if liquid is not None and liquid >= CRITICAL_LIQUID:
            target = 100.0
            st.failsafe = True

        target = max(min_duty, min(100.0, target))
        st.target = target
        if st.duty is None or (mode == "fixed" and not st.failsafe):
            st.duty = target
        else:
            up = float(settings.get("ramp_up", 8.0)) * dt
            down = float(settings.get("ramp_down", 3.0)) * dt
            if st.failsafe:
                up = 100.0
            delta = target - st.duty
            st.duty += max(-down, min(up, delta))
        return st.duty
