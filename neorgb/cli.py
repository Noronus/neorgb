"""neorgbctl - command line access to the daemon.

  neorgbctl status                 devices, temps, fans
  neorgbctl effect rainbow [--speed 60] [--colors '#ff0000,#0000ff']
  neorgbctl brightness 70
  neorgbctl fan <id|all> curve <curve-id> | fixed <percent>
  neorgbctl leds <device-key> <channel> <count>[,<count>...]   LEDs per device on a Lighting Node channel
  neorgbctl identify <zone-id>
  neorgbctl raw <method> '<json params>'
"""

from __future__ import annotations

import argparse
import json
import sys

from .client import Client, DaemonError


def _status(c: Client) -> None:
    s = c.call("state")
    print("Geräte:")
    for d in s["devices"]:
        line = f"  {d['name']}  [{d['status']}]  fw {d.get('firmware') or '?'}"
        if d.get("error"):
            line += f"  ! {d['error']}"
        print(line)
        print(f"    key {d['key']}")
    print("Temperaturen:")
    for t in s["sensors"]:
        if t["id"] in ("liquid", "cpu", "gpu") or t["id"].startswith("1b1c"):
            v = "–" if t["value"] is None else f"{t['value']:.1f} °C"
            print(f"  {t['label']:<18} {v}")
    print("Lüfter / Pumpe:")
    for f in s["fans"]:
        cfg = f["cfg"]
        how = f"Kurve {cfg.get('curve')}" if cfg.get("mode") == "curve" else f"fest {cfg.get('fixed')} %"
        duty = "–" if f.get("duty") is None else f"{f['duty']} %"
        fs = "  FAILSAFE" if f.get("failsafe") else ""
        print(f"  {f['name']:<9} {f['rpm']:>5} rpm  {duty:>6}  ({how}){fs}   id {f['id']}")
    print("Zonen:")
    for z in s["zones"]:
        print(f"  {z['name']:<12} {z['leds']:>3} LEDs   id {z['id']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="neorgbctl", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    e = sub.add_parser("effect")
    e.add_argument("effect")
    e.add_argument("--speed", type=float)
    e.add_argument("--colors")
    e.add_argument("--zone")
    b = sub.add_parser("brightness")
    b.add_argument("value", type=float)
    f = sub.add_parser("fan")
    f.add_argument("fan")
    f.add_argument("mode", choices=["curve", "fixed"])
    f.add_argument("value")
    l = sub.add_parser("leds")
    l.add_argument("device")
    l.add_argument("channel", type=int)
    l.add_argument("counts")
    i = sub.add_parser("identify")
    i.add_argument("zone")
    r = sub.add_parser("raw")
    r.add_argument("method")
    r.add_argument("params", nargs="?", default="{}")
    a = ap.parse_args(argv)

    try:
        c = Client()
        if a.cmd == "status":
            _status(c)
        elif a.cmd == "effect":
            spec = {"effect": a.effect}
            if a.speed is not None:
                spec["speed"] = a.speed
            if a.colors:
                spec["colors"] = [x.strip() for x in a.colors.split(",")]
            if a.zone:
                c.call("set_zone", zone=a.zone, follow=False, spec=spec)
            else:
                c.call("set_global", spec=spec)
        elif a.cmd == "brightness":
            c.call("set_brightness", value=a.value)
        elif a.cmd == "fan":
            ids = [x["id"] for x in c.call("state")["fans"]] if a.fan == "all" else [a.fan]
            for fid in ids:
                if a.mode == "curve":
                    c.call("set_fan", fan=fid, mode="curve", curve=a.value)
                else:
                    c.call("set_fan", fan=fid, mode="fixed", fixed=float(a.value))
        elif a.cmd == "leds":
            segs = [int(x) for x in a.counts.split(",") if x.strip()]
            c.call("set_device", key=a.device, channels={str(a.channel): {"segments": segs}})
        elif a.cmd == "identify":
            c.call("identify", zone=a.zone)
        elif a.cmd == "raw":
            print(json.dumps(c.call(a.method, **json.loads(a.params)), indent=1, ensure_ascii=False))
    except DaemonError as e:
        print(f"neorgbctl: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
