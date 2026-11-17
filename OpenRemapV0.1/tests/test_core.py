"""Hardware-free tests. Run: python -m unittest discover -s tests"""
import os
import shutil
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="openremap-test-")
os.environ["OPENREMAP_HOME"] = TMP

from openremap.core import config as cfgmod, devices as devmod  # noqa: E402
from openremap.core.learn import LearnRecorder, LearnSession  # noqa: E402
from openremap.service import ApiError, RemapService  # noqa: E402

IFACE = (0xFF42, 0x0002, 2)


def k95_report(b18=0, b19=0):
    r = bytearray(64)
    r[1] = 0x02
    r[18], r[19] = b18, b19
    return bytes(r)


# The six G-key presses captured from the real keyboard, each followed by its release.
K95_PRESSES = [(0x08, 0), (0x10, 0), (0x20, 0), (0x40, 0), (0x80, 0), (0, 0x01)]


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class DeviceProfileTests(unittest.TestCase):
    def setUp(self):
        devs, errors = devmod.load_all()
        self.assertEqual(errors, [])
        self.k95 = devs["corsair-k95-rgb-platinum-xt"]

    def test_decodes_captured_reports(self):
        for name, (b18, b19) in zip(["G1", "G2", "G3", "G4", "G5", "G6"], K95_PRESSES):
            self.assertEqual(self.k95.pressed(k95_report(b18, b19)), {name})
        self.assertEqual(self.k95.pressed(k95_report()), set())

    def test_ignores_non_key_reports(self):
        other = bytearray(k95_report(0x08))
        other[1] = 0x03
        self.assertIsNone(self.k95.pressed(bytes(other)))

    def test_matches_hid_info(self):
        info = {"vendor_id": 0x1B1C, "product_id": 0x1B89, "usage_page": 0xFF42, "usage": 2, "interface_number": 2}
        self.assertTrue(self.k95.matches(info))
        self.assertFalse(self.k95.matches(dict(info, usage=1)))

    def test_json_round_trip(self):
        clone = devmod.DeviceProfile.from_json(self.k95.to_json(), "x")
        self.assertEqual(clone.pressed(k95_report(0, 1)), {"G6"})


class ConfigTests(unittest.TestCase):
    def test_resolution_with_app_profile(self):
        cfg = cfgmod.normalize({"profiles": [
            {"name": "Default", "bindings": {"d": {"G1": {"type": "log"}, "G2": {"type": "log"}}}},
            {"name": "RDP", "apps": ["MSRDC.exe"], "bindings": {"d": {"G1": {"type": "none"}}}},
        ]})
        self.assertEqual(cfgmod.resolve_action(cfg, "d", "G1", "msrdc.exe"), {"type": "none"})
        self.assertEqual(cfgmod.resolve_action(cfg, "d", "G2", "msrdc.exe"), {"type": "log"})  # falls back
        self.assertEqual(cfgmod.resolve_action(cfg, "d", "G1", "notepad.exe"), {"type": "log"})
        self.assertIsNone(cfgmod.resolve_action(cfg, "d", "G3", None))

    def test_default_always_first(self):
        cfg = cfgmod.normalize({"profiles": [{"name": "Other"}]})
        self.assertEqual([p["name"] for p in cfg["profiles"]], ["Default", "Other"])


class LearnTests(unittest.TestCase):
    def test_session_finds_each_g_key(self):
        clock = FakeClock()
        s = LearnSession(quiet_seconds=2, clock=clock)
        s.start()
        clock.t = 3
        found = []
        for b18, b19 in K95_PRESSES:
            s.arm()
            self.assertIsNone(s.feed(IFACE, k95_report(b18, b19)))  # press: candidate only
            cap = s.feed(IFACE, k95_report())                        # release: confirmed
            found.append((cap.byte, cap.mask))
        self.assertEqual(found, [(18, 0x08), (18, 0x10), (18, 0x20), (18, 0x40), (18, 0x80), (19, 0x01)])

    def test_noisy_bytes_ignored(self):
        clock = FakeClock()
        s = LearnSession(quiet_seconds=2, clock=clock)
        s.start()
        noisy = bytearray(64)
        for v in (1, 2, 3):
            noisy[5] = v
            s.feed(IFACE, bytes(noisy))
        clock.t = 3
        s.arm()
        press = bytearray(noisy)
        press[5] = 0xFF
        press[10] = 0x04
        s.feed(IFACE, bytes(press))
        cap = s.feed(IFACE, bytes(noisy))
        self.assertEqual((cap.byte, cap.mask), (10, 0x04))

    def test_recorder_builds_working_profile(self):
        rec = LearnRecorder(0x1B1C, 0x1B89, quiet_seconds=0)
        rec.session.start()
        rec.session.arm()
        for b18, b19 in K95_PRESSES:
            rec.feed(IFACE, k95_report(b18, b19))
            rec.feed(IFACE, k95_report())
        rec.feed(IFACE, k95_report(0x08))  # G1 again -> duplicate
        rec.feed(IFACE, k95_report())
        snap = rec.snapshot()
        self.assertEqual([c["name"] for c in snap["captures"]], ["G1", "G2", "G3", "G4", "G5", "G6"])
        self.assertEqual(snap["events"][-1]["type"], "duplicate")
        prof = rec.build_profile("My K95")
        self.assertEqual(prof.id, "my-k95")
        self.assertEqual(prof.pressed(k95_report(0x40)), {"G4"})

    def test_rejects_second_interface(self):
        rec = LearnRecorder(1, 2, quiet_seconds=0)
        rec.session.start()
        rec.session.arm()
        rec.feed(IFACE, k95_report(0x08))
        rec.feed(IFACE, k95_report())
        rec.feed((0x0C, 1, 0), bytes([1, 0x20, 0]))
        rec.feed((0x0C, 1, 0), bytes([1, 0, 0]))
        snap = rec.snapshot()
        self.assertEqual(len(snap["captures"]), 1)
        self.assertEqual(snap["events"][-1]["type"], "wrong_interface")


class ServiceTests(unittest.TestCase):
    def setUp(self):
        for p in (os.path.join(TMP, "config.json"),):
            if os.path.exists(p):
                os.remove(p)
        self.s = RemapService()
        self.dev = "corsair-k95-rgb-platinum-xt"

    def test_bindings_and_inheritance(self):
        self.s.set_binding("Default", self.dev, "G3", {"type": "hotkey", "keys": "Win + Shift + S"})
        self.s.create_profile("RDP", ["C:\\Windows\\System32\\msrdc.exe"])
        self.assertEqual(self.s.list_profiles()[1]["apps"], ["msrdc.exe"])
        rows = {r["key"]: r for r in self.s.get_bindings("RDP", self.dev)}
        self.assertFalse(rows["G3"]["own"])
        self.assertEqual(rows["G3"]["inherited_from"], "Default")
        self.assertEqual(rows["G3"]["effective"]["keys"], ["win", "shift", "s"])
        self.s.set_binding("RDP", self.dev, "G3", {"type": "none"})
        rows = {r["key"]: r for r in self.s.get_bindings("RDP", self.dev)}
        self.assertTrue(rows["G3"]["own"])

    def test_dispatch_and_errors(self):
        self.assertEqual(self.s.dispatch("list_profiles")[0]["name"], "Default")
        with self.assertRaises(ApiError) as e:
            self.s.dispatch("set_binding", {"profile": "Default", "device_id": self.dev, "key": "G9",
                                            "action": {"type": "log"}})
        self.assertEqual(e.exception.code, "not_found")
        with self.assertRaises(ApiError):
            self.s.dispatch("_cfg")
        with self.assertRaises(ApiError):
            self.s.validate_action({"type": "text", "text": ""})
        self.assertEqual(self.s.validate_action({"type": "run", "command": " notepad.exe "})["command"], "notepad.exe")

    def test_profile_rules(self):
        with self.assertRaises(ApiError):
            self.s.delete_profile("Default")
        self.s.create_profile("A")
        with self.assertRaises(ApiError) as e:
            self.s.create_profile("A")
        self.assertEqual(e.exception.code, "exists")
        self.s.rename_profile("A", "B")
        self.s.delete_profile("B")
        self.assertEqual(len(self.s.list_profiles()), 1)

    def test_save_learned_device_overwrite_flow(self):
        rec = LearnRecorder(0x1B1C, 0x1B89, quiet_seconds=0)
        rec.session.start()
        rec.session.arm()
        rec.feed(IFACE, k95_report(0x08))
        rec.feed(IFACE, k95_report())
        self.s._sessions["t"] = rec
        with self.assertRaises(ApiError) as e:
            self.s.save_learned_device("t", "Corsair K95 RGB Platinum XT")
        self.assertEqual(e.exception.code, "exists")
        saved = self.s.save_learned_device("t", "Corsair K95 RGB Platinum XT", overwrite=True)
        self.assertEqual(saved["source"], "user")
        dev = {d["id"]: d for d in self.s.list_devices()}[self.dev]
        self.assertEqual(dev["keys"], ["G1"])  # user file overrides built-in
        self.s.delete_device(self.dev)
        dev = {d["id"]: d for d in self.s.list_devices()}[self.dev]
        self.assertEqual(dev["source"], "built-in")

    def test_everything_is_json(self):
        import json
        json.dumps([self.s.list_profiles(), self.s.list_devices(), self.s.action_types(),
                    self.s.get_bindings("Default", self.dev), self.s.engine_status()])


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
