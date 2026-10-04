"""Performance page readings and Jetson power/fan control (no real hardware touched)."""
import subprocess
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from app.config import settings
from app.core.security import lease_manager
from app.main import app
from app.services import hardware_service as hw


class Done:
    def __init__(self, code=0, out=""):
        self.returncode, self.stdout, self.stderr = code, out, ""


class HardwareApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        settings.operator_passcode = "rmutt-aoi"
        self.token = None
        hw.hardware_service._control_cache = (0.0, False)
        hw.hardware_service._mode_cache = (0.0, None)

    def tearDown(self):
        lease_manager.release_lease(self.token)

    def _auth(self):
        res = self.client.post("/api/auth/acquire", json={"operator_name": "t", "passcode": "rmutt-aoi", "force": True})
        self.token = res.json()["operator_token"]
        return {"X-Operator-Token": self.token}

    def test_snapshot_works_on_any_machine(self):
        data = self.client.get("/api/system/hardware").json()
        self.assertIn("cores", data["cpu"])
        self.assertGreater(len(data["cpu"]["cores"]), 0)
        self.assertIn("used_mb", data["memory"])

    def test_changes_need_the_operator_lease(self):
        for path, body in (("power-mode", {"mode_id": 1}), ("clocks", {"max": True}), ("fan", {"mode": "cool"})):
            self.assertEqual(self.client.post(f"/api/system/hardware/{path}", json=body).status_code, 403, path)

    def test_fan_percent_is_bounded(self):
        res = self.client.post("/api/system/hardware/fan", json={"mode": "manual", "percent": 5}, headers=self._auth())
        self.assertEqual(res.status_code, 422)

    def test_without_helper_explains_how_to_enable(self):
        with mock.patch.object(hw, "is_jetson", return_value=True):
            res = self.client.post("/api/system/hardware/clocks", json={"max": True}, headers=self._auth())
        self.assertEqual(res.status_code, 400)
        self.assertIn("install-power-control.sh", res.json()["detail"])

    def test_commands_go_through_sudo_helper_only(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return Done(0, "NV Power Mode: 25W\n1\n" if cmd[:2] == ["nvpmodel", "-q"] else "")

        modes = {"current": 2, "modes": [{"id": 0, "name": "15W"}, {"id": 1, "name": "25W"}, {"id": 2, "name": "MAXN_SUPER"}]}
        with mock.patch.object(hw, "is_jetson", return_value=True), mock.patch("pathlib.Path.is_file", return_value=True), \
             mock.patch.object(hw.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(hw.HardwareService, "_power_mode", return_value=modes), \
             mock.patch.object(hw.HardwareService, "snapshot", return_value={}), \
             mock.patch.object(hw.HardwareService, "_start_watchdog"):
            h = self._auth()
            self.assertEqual(self.client.post("/api/system/hardware/power-mode", json={"mode_id": 1}, headers=h).status_code, 200)
            self.assertEqual(self.client.post("/api/system/hardware/power-mode", json={"mode_id": 9}, headers=h).status_code, 400)
            self.assertEqual(self.client.post("/api/system/hardware/clocks", json={"max": True}, headers=h).status_code, 200)
            self.assertEqual(self.client.post("/api/system/hardware/fan", json={"mode": "manual", "percent": 60}, headers=h).status_code, 200)
            self.assertEqual(self.client.post("/api/system/hardware/fan", json={"mode": "quiet"}, headers=h).status_code, 200)
        changes = [c for c in calls if c[:3] == ["sudo", "-n", hw.HELPER] and c[3] != "check"]
        self.assertEqual([c[3:] for c in changes], [["mode", "1"], ["clocks", "on"], ["fan", "manual", "60"], ["fan", "profile", "quiet"]])
        self.assertTrue(all(c[0] == "sudo" for c in calls if c[0] != "nvpmodel"))  # nothing else is executed

    def test_mode_needing_reboot_is_reported(self):
        modes = {"current": 2, "modes": [{"id": 0, "name": "15W"}]}
        with mock.patch.object(hw, "is_jetson", return_value=True), \
             mock.patch.object(hw.HardwareService, "control_available", return_value=True), \
             mock.patch.object(hw.HardwareService, "_power_mode", return_value=modes), \
             mock.patch.object(hw.subprocess, "run", return_value=Done(0, "NVPM WARN: Reboot required for changing to this power mode: 0")):
            with self.assertRaises(hw.HardwareError) as err:
                hw.hardware_service.set_power_mode(0)
        self.assertIn("รีบูต", str(err.exception))

    def test_helper_failure_message_is_shown(self):
        with mock.patch.object(hw, "is_jetson", return_value=True), \
             mock.patch.object(hw.HardwareService, "control_available", return_value=True), \
             mock.patch.object(hw.subprocess, "run", return_value=Done(2, "aoi-jetson-power: no PWM fan found")):
            with self.assertRaises(hw.HardwareError) as err:
                hw.hardware_service.set_fan("manual", 50)
        self.assertIn("no PWM fan", str(err.exception))

    def test_crit_sentinel_is_hidden(self):
        self.assertIsNone(hw._crit(32760))
        self.assertEqual(hw._crit(5048), 5.05)


if __name__ == "__main__":
    unittest.main()
