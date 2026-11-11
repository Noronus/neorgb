"""Offline checks: packet layout and control logic without hardware."""
import pathlib, re, sys, unittest
sys.path.insert(0, __file__.rsplit('/tests/', 1)[0])

from neorgb.devices import lighting_node as ln
from neorgb.devices import commander_core as cc
from neorgb.fancontrol import FanController, interpolate
from neorgb.effects import EffectEngine, Zone


class FakeDev:
    def __init__(self, size):
        self.size, self.sent = size, []
    def drain(self): pass
    def write(self, data): self.sent.append(bytes(data))
    def read(self, timeout=0.5):
        last = self.sent[-1]
        return bytes([0x00, last[0], 0x00] + [0] * (self.size - 3)) if self.size == 16 else \
            bytes([0x00, last[1], 0x00] + [0] * (self.size - 3))
    def close(self): pass


class LightingNodeTest(unittest.TestCase):
    def make(self):
        node = ln.LightingNode.__new__(ln.LightingNode)
        node.name, node.channels = "LNP", 2
        node.dev, node.lock = FakeDev(16), __import__("threading").RLock()
        node.counts, node.software, node.last_commit, node.errors = [0, 0], False, 0, 0
        return node

    def test_configure_takes_only_configured_channels(self):
        node = self.make()
        node.configure([40, 0])
        sent = node.dev.sent
        self.assertIn(b"\x38\x00\x02", [x[:3] for x in sent])   # ch 1 to software
        self.assertIn(b"\x38\x01\x01", [x[:3] for x in sent])   # empty ch stays hardware
        self.assertFalse([x for x in sent if x[0] in (0x37, 0x35)])  # no reset, no effect
        self.assertEqual(sent[-1], b"\x33\xff")
        self.assertTrue(node.software)

    def test_led_count_pattern(self):
        pat = ln.test_pattern(10)
        self.assertEqual(len(pat), ln.MAX_LEDS * 3)
        self.assertEqual(pat[0:3], bytes(ln.TEST_COLORS[0]))
        self.assertEqual(pat[27:30], bytes(ln.TEST_COLORS[0]))    # LED 10
        self.assertEqual(pat[30:33], bytes(ln.TEST_COLORS[1]))    # LED 11
        self.assertEqual(pat[80 * 3:80 * 3 + 3], b"\x00\x00\x00")  # after 8 colours: dark

    def test_colors_are_split_in_planes_and_chunks(self):
        node = self.make()
        node.configure([60, 0])
        node.dev.sent.clear()
        rgb = bytes(i % 256 for i in range(60 * 3))
        node.write_colors([rgb, b""])
        direct = [p for p in node.dev.sent if p[0] == 0x32]
        self.assertEqual(len(direct), 6)          # 2 chunks x 3 planes
        first_red = direct[0]
        self.assertEqual(first_red[1:5], bytes([0, 0, 50, 0]))
        self.assertEqual(first_red[5:8], bytes([rgb[0], rgb[3], rgb[6]]))
        self.assertEqual(direct[3][1:5], bytes([0, 50, 10, 0]))
        self.assertLessEqual(max(len(p) for p in node.dev.sent), 64)

    def test_hardware_effect_on_exit(self):
        node = self.make()
        node.configure([10, 20])
        node.dev.sent.clear()
        node.set_hardware_effect("rainbow_wave")
        cfgs = [p for p in node.dev.sent if p[0] == 0x35]
        self.assertEqual([p[3] for p in cfgs], [10, 20])
        self.assertEqual(cfgs[0][8], 0xFF)

    def test_count_test_blanks_its_leds_when_done(self):
        import threading
        from neorgb.daemon import LightingNodeWorker
        w = LightingNodeWorker.__new__(LightingNodeWorker)
        threading.Thread.__init__(w, daemon=True)
        w.dev, w.counts, w.zones, w.blank = self.make(), [10, 0], [], {}
        w.name, w.key, w.test, w._ending, w._reconfig = "LNP", "k", None, None, False
        w._lock, w._wake, w._frame = threading.Lock(), threading.Event(), None
        w.dev.configure(w.counts)
        w.start_test(0, 10)
        w.tick()
        self.assertEqual(w.dev.counts[0], ln.MAX_LEDS)
        w.stop_test()
        w.dev.dev.sent.clear()
        w.tick()
        zeros = [x for x in w.dev.dev.sent if x[0] == 0x32 and x[1] == 0]
        self.assertEqual(sum(x[3] for x in zeros) // 3, ln.MAX_LEDS)   # all 204 LEDs, 3 planes
        self.assertTrue(all(not any(x[5:5 + x[3]]) for x in zeros))
        self.assertEqual(w.dev.counts, [10, 0])

    def test_hardware_effect_leaves_empty_channels_alone(self):
        node = self.make()
        node.configure([10, 0])
        node.dev.sent.clear()
        node.set_hardware_effect("rainbow_wave")
        self.assertFalse([x for x in node.dev.sent if x[:2] in (b"\x37\x01", b"\x35\x01", b"\x38\x01")])
        self.assertTrue(any(p[:3] == b"\x38\x00\x01" for p in node.dev.sent))


class CommanderCoreTest(unittest.TestCase):
    def test_chunks_fit_report(self):
        c = cc.CommanderCore.__new__(cc.CommanderCore)
        c.size = 96
        body = bytes(700)
        parts = list(c._chunks(body, b"\x06\x00", b"\x07\x00"))
        self.assertEqual(b"".join(p for _, p in parts), body)
        for cmd, p in parts:
            self.assertLessEqual(1 + len(cmd) + len(p), 96)

    def test_pump_never_below_minimum(self):
        c = cc.CommanderCore.__new__(cc.CommanderCore)
        c.has_pump = True
        self.assertEqual(c._clamp(0, 10), cc.PUMP_MIN_DUTY)
        self.assertEqual(c._clamp(1, 10), 10)


class Sensors:
    def __init__(self, v): self.v = v
    def get(self, sid, max_age=0): return self.v
    def average(self, sid, s): return self.v


class FanTest(unittest.TestCase):
    curves = {"c": {"sensor": "liquid", "points": [[30, 30], [40, 100]]}}
    settings = {"hysteresis": 2, "ramp_up": 10, "ramp_down": 5}

    def test_interpolate(self):
        self.assertEqual(interpolate([[30, 30], [40, 100]], 35), 65)
        self.assertEqual(interpolate([[30, 30], [40, 100]], 10), 30)
        self.assertEqual(interpolate([[30, 30], [40, 100]], 90), 100)

    def test_ramp_and_hysteresis(self):
        f = FanController()
        cfg = {"mode": "curve", "curve": "c"}
        self.assertEqual(f.step("x", cfg, self.curves, Sensors(30), 1, self.settings, 0, 30), 30)
        self.assertEqual(f.step("x", cfg, self.curves, Sensors(40), 1, self.settings, 0, 40), 40)  # +10/s
        for _ in range(10):
            d = f.step("x", cfg, self.curves, Sensors(40), 1, self.settings, 0, 40)
        self.assertEqual(d, 100)
        # 1 degree down is inside the hysteresis: no change
        self.assertEqual(f.step("x", cfg, self.curves, Sensors(39), 1, self.settings, 0, 39), 100)

    def test_failsafe(self):
        f = FanController()
        cfg = {"mode": "curve", "curve": "c"}
        self.assertEqual(f.step("x", cfg, self.curves, Sensors(None), 1, self.settings, 0, None), 100)
        self.assertEqual(f.step("y", {"mode": "fixed", "fixed": 20}, self.curves, Sensors(30), 1, self.settings, 0, 55), 100)

    def test_failsafe_duty_is_adjustable(self):
        f = FanController()
        cfg = {"mode": "curve", "curve": "c"}
        st = {**self.settings, "failsafe_duty": 70}
        self.assertEqual(f.step("p", cfg, self.curves, Sensors(None), 1, st, 50, 30), 70)
        self.assertEqual(f.states["p"].reason, "sensor:liquid")
        # the pump minimum still wins
        self.assertEqual(f.step("q", cfg, self.curves, Sensors(None), 1, {**st, "failsafe_duty": 20}, 50, 30), 50)
        # hot water overrides the setting
        self.assertEqual(f.step("r", cfg, self.curves, Sensors(None), 1, st, 0, 55), 100)
        self.assertEqual(f.states["r"].reason, "liquid")

    def test_fixed_is_immediate(self):
        f = FanController()
        f.step("x", {"mode": "fixed", "fixed": 80}, self.curves, Sensors(30), 1, self.settings, 0, 30)
        self.assertEqual(f.step("x", {"mode": "fixed", "fixed": 20}, self.curves, Sensors(30), 1, self.settings, 0, 30), 20)


class SensorThreadTest(unittest.TestCase):
    def test_hung_chip_does_not_age_other_sensors(self):
        import threading, time
        from neorgb import sensors as sm
        real = sm._read
        def slow_read(p):
            if "gpu" in str(p):
                time.sleep(3)          # like amdgpu with a stuck SMU
            return "42000"
        sm._read = slow_read
        try:
            s = sm.Sensors.__new__(sm.Sensors)
            s.history, s._stop, s._threads = {}, threading.Event(), []
            s.INTERVAL = 0.1
            s.sensors = {"cpu": sm.Sensor("cpu", "CPU", "/x/cpu/temp1_input", chip="/x/cpu"),
                         "gpu": sm.Sensor("gpu", "GPU", "/x/gpu/temp1_input", chip="/x/gpu")}
            s.start()
            time.sleep(1.5)
            self.assertEqual(s.get("cpu", 1.0), 42.0)
            self.assertIsNone(s.get("gpu", 1.0))
            self.assertIsNone([x for x in s.listing(1.0) if x["id"] == "gpu"][0]["value"])
            s.stop()
        finally:
            sm._read = real


class EffectsTest(unittest.TestCase):
    def test_all_effects_render_right_length(self):
        e = EffectEngine()
        for kind in ("ring", "linear"):
            z = Zone("z", "d", "Z", 24, [8, 8, 8], kind)
            for eff in ("static", "breathing", "spectrum", "rainbow", "gradient", "spin", "comet", "twinkle", "temperature", "off"):
                out = e.render(z, {"effect": eff, "colors": ["#ff0000", "#0000ff"]}, 1.23, Sensors(50))
                self.assertEqual(len(out), 72, eff)

    def test_each_effect_keeps_its_own_settings(self):
        from neorgb.effects import load_snapshot, patch_spec, snapshot_spec
        s = {"effect": "static", "colors": ["#ff0000"], "speed": 50, "min_brightness": 10}
        patch_spec(s, {"effect": "rainbow"})
        patch_spec(s, {"speed": 90, "min_brightness": 20})
        patch_spec(s, {"effect": "static"})
        self.assertEqual(s["speed"], 50)                 # static got its own speed back
        self.assertEqual(s["min_brightness"], 20)        # shared across effects
        patch_spec(s, {"effect": "rainbow"})
        self.assertEqual(s["speed"], 90)
        snap = snapshot_spec(s)
        self.assertNotIn("by_effect", snap)
        patch_spec(s, {"effect": "breathing", "colors": ["#00ff00"], "speed": 5})
        load_snapshot(s, snap)
        self.assertEqual((s["effect"], s["speed"]), ("rainbow", 90))
        patch_spec(s, {"effect": "breathing"})
        self.assertEqual((s["speed"], s["colors"]), (5, ["#00ff00"]))   # parked when the snapshot was loaded

    def test_profile_matches_until_something_changes(self):
        from neorgb.daemon import active_profile, lighting_profile
        from neorgb.effects import patch_spec
        L = {"global": {"effect": "rainbow", "speed": 40},
             "zones": {"a": {"follow": False, "spec": {"effect": "static", "colors": ["#ff0000"]}},
                       "b": {"follow": True, "spec": {"effect": "comet"}}}}
        L["profiles"] = [lighting_profile(L, "Abend")]
        self.assertEqual(active_profile(L), "Abend")
        L["zones"]["c"] = {"follow": True}                       # new zone that follows: still the same
        self.assertEqual(active_profile(L), "Abend")
        patch_spec(L["zones"]["a"]["spec"], {"colors": ["#00ff00"]})
        self.assertEqual(active_profile(L), "")

    def test_screen_follows_the_screen_edges(self):
        from neorgb.screen import W, H

        class Shot:   # left half red, right half blue
            def __init__(self):
                self.f = bytes(c for y in range(H) for x in range(W) for c in ((255, 0, 0) if x < W // 2 else (0, 0, 255)))

            def frame(self):
                return self.f

        e = EffectEngine()
        e.screen = Shot()
        z = Zone("z", "d", "Z", 8, [8], "ring")
        spec = {"effect": "screen", "speed": 100, "saturation": 0}
        for i in range(40):
            out = e.render(z, spec, i * 0.1)
        self.assertGreater(out[2 * 3 + 2], 200)      # LED 2 points right: blue
        self.assertLess(out[2 * 3], 30)
        self.assertGreater(out[6 * 3], 200)          # LED 6 points left: red
        full = e.render(Zone("f", "d", "F", 4), {**spec, "screen_area": "full"}, 0.0)
        self.assertEqual(len(full), 12)
        e.screen = None
        self.assertEqual(len(e.render(z, spec, 0.0)), 24)   # no capture: stays dark, no crash


class HwmonFanTest(unittest.TestCase):
    """Mainboard headers and GPU curve against a fake sysfs directory."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from neorgb.devices import hwmon_fans as hf
        self.hf = hf
        self.tmp = Path(tempfile.mkdtemp())
        hf.CONFIG_DIR = self.tmp / "cfg"
        self.chip = self.tmp / "hwmon10"
        self.chip.mkdir()
        for p in (1, 3):
            (self.chip / f"pwm{p}").write_text("239\n")
            (self.chip / f"pwm{p}_enable").write_text("5\n")
            (self.chip / f"fan{p}_input").write_text("0\n" if p == 1 else "900\n")

        class Cfg:
            data = {"cooling": {"channels": {}, "curves": {}, "settings": {}}, "devices": {}}
            import threading
            lock = threading.RLock()

            def mark(self):
                pass

        class D:
            cfg = Cfg()

            def device_cfg(self, key):
                return self.cfg.data["devices"].get(key, {})
        self.D = D

    def rd(self, name):
        return (self.chip / name).read_text().strip()

    def test_takeover_and_release(self):
        b = self.hf.BoardChip(self.D(), self.chip, "nct6799")
        b.poll()
        self.assertEqual([f["port"] for f in b.fans], [3])      # header 1 never spun
        b.apply({3: 50})
        self.assertEqual(self.rd("pwm3_enable"), "1")
        self.assertEqual(self.rd("pwm3"), "128")
        b.apply({3: None})
        self.assertEqual(self.rd("pwm3_enable"), "5")
        self.assertEqual(self.rd("pwm1_enable"), "5")            # never touched

    def test_crash_leftover_goes_back_to_bios(self):
        b = self.hf.BoardChip(self.D(), self.chip, "nct6799")
        b.apply({3: 80})
        b2 = self.hf.BoardChip(self.D(), self.chip, "nct6799")  # next start after a crash
        b2.restore_after_crash()
        self.assertEqual(self.rd("pwm3_enable"), "5")

    def test_gpu_curve_points(self):
        g = self.hf.AmdGpu.__new__(self.hf.AmdGpu)
        g.temp_range, g.duty_range = (25, 100), (20, 100)
        curves = {"c": {"sensor": "gpu", "points": [[30, 10], [60, 50], [90, 100]]},
                  "water": {"sensor": "liquid", "points": [[25, 20], [40, 100]]}}
        self.assertIsNone(g.points_for({"mode": "curve", "curve": "water"}, curves))
        pts = g.points_for({"mode": "curve", "curve": "c"}, curves)
        self.assertEqual(len(pts), 5)
        self.assertEqual(pts[0], (30, 20))                        # clamped to the GPU minimum
        self.assertEqual(pts[-1], (90, 100))
        self.assertEqual(g.points_for({"mode": "fixed", "fixed": 60}, curves)[2][1], 60)
        self.assertIsNone(g.points_for({"mode": "hardware"}, curves))

    def test_gpu_fixed_switches_zero_rpm_off_and_back(self):
        from pathlib import Path
        g = self.hf.AmdGpu.__new__(self.hf.AmdGpu)
        g.pci, g.writable, g.owned, g.sent, g.zero_rpm_orig = "x", True, False, None, None
        g.curve_file, g.zero_rpm_file = self.tmp / "fan_curve", self.tmp / "fan_zero_rpm_enable"
        g.curve_file.write_text("")
        g.zero_rpm_file.write_text("FAN_ZERO_RPM_ENABLE:\n1\n")
        g.apply([(25, 60)] * 5, fixed=True)
        self.assertEqual(g.zero_rpm_orig, "1")
        g.apply(None)
        self.assertIsNone(g.zero_rpm_orig)



class I18nTest(unittest.TestCase):
    QML = pathlib.Path(__file__).resolve().parent.parent / "neorgb" / "gui" / "qml"
    LIT = re.compile(r'"((?:[^"\\]|\\.)*)"')

    def test_every_qml_text_has_english(self):
        from neorgb.i18n import EN
        missing = []
        for f in sorted(self.QML.glob("*.qml")):
            for m in re.finditer(r'qsTr\("((?:[^"\\]|\\.)*)"\)', f.read_text()):
                if m.group(1) not in EN:
                    missing.append(f"{f.name}: {m.group(1)}")
        self.assertEqual(missing, [])

    def test_no_german_text_outside_qstr(self):
        bilingual = ("Sprache wählen · Choose language",
                     "Lässt sich jederzeit unter Einstellungen ändern. · You can change this any time under Settings.")
        found = []
        for f in sorted(self.QML.glob("*.qml")):
            for line in f.read_text().splitlines():
                if line.strip().startswith("//"):
                    continue
                for m in self.LIT.finditer(line):
                    if re.search("[äöüÄÖÜß]", m.group(1)) and not line[:m.start()].endswith("qsTr(") \
                            and m.group(1) not in bilingual:
                        found.append(f"{f.name}: {m.group(1)}")
        self.assertEqual(found, [])

    def test_daemon_names_have_english(self):
        from neorgb.effects import EFFECTS
        from neorgb.fancontrol import DEFAULT_CURVES
        from neorgb.devices.hwmon_fans import PERM_HINT, overdrive_hint
        from neorgb.i18n import EN
        names = [e["name"] for e in EFFECTS.values()] + [c["name"] for c in DEFAULT_CURVES.values()] \
            + [p["name"] for p in ln.PRESETS] + [PERM_HINT, overdrive_hint()[0]]
        self.assertEqual([n for n in names if n not in EN], [])

    def test_patterns(self):
        from neorgb.i18n import translate
        self.assertEqual(translate("Lüfter 3", "en"), "Fan 3")
        self.assertEqual(translate("Wasser (AIO) fehlt", "en"), "Liquid (AIO) missing")
        self.assertEqual(translate("WLED unter 10.0.0.9 nicht erreichbar (timed out)", "en"),
                         "WLED at 10.0.0.9 not reachable (timed out)")
        self.assertEqual(translate("Kanal 2 gibt es nicht", "en"), "There is no channel 2")
        self.assertEqual(translate("Mein Lüfter", "en"), "Mein Lüfter")      # names the user typed stay
        self.assertEqual(translate("Lüfter 3", "de"), "Lüfter 3")


if __name__ == "__main__":
    unittest.main()
