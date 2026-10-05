"""Live stage error: each move is checked against the camera on a simulated stage with backlash."""
import math
import time
import unittest
from unittest.mock import MagicMock, patch

from app.config import settings
from app.services import stage_monitor_service as smod
from app.services.machine_service import machine_service
from app.services.stage_calibration_service import stage_calibration_service
from app.services.stage_monitor_service import stage_monitor_service

from test_stage_calibration import FRAME_H, FRAME_W, PX_PER_MM, ROT, Carriage, render, image_shift  # noqa: F401


def calibration():
    c, s = math.cos(ROT), math.sin(ROT)
    m = [[-PX_PER_MM * c, PX_PER_MM * s], [-PX_PER_MM * s, -PX_PER_MM * c]]
    return {"stage_to_image": m, "image_size": [FRAME_W, FRAME_H]}


class StageMonitorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        machine_service.connect(mode="simulation")
        machine_service.home()

    @classmethod
    def tearDownClass(cls):
        machine_service.disconnect()

    def _wait(self, n, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snap = stage_monitor_service.snapshot()
            if len(snap["samples"]) >= n:
                return snap
            time.sleep(0.05)
        self.fail(f"only {len(stage_monitor_service.snapshot()['samples'])} samples")

    def test_reports_each_moves_error_live(self):
        carriage = Carriage(backlash=(0.05, 0.0), scale_err=(0.0, 0.0))
        events = []
        stage_monitor_service.subscribe(events.append)
        camera = MagicMock(is_active=True, is_mock=False)
        camera.get_fresh_frame.side_effect = lambda *a, **k: (time.monotonic(), carriage.frame())
        spm = machine_service.steps_per_mm
        with patch.object(machine_service, "_move_raw", side_effect=carriage.wrap(machine_service._move_raw)), \
             patch.object(smod, "camera_service", camera), \
             patch.object(smod, "SETTLE_SEC", 0.05), \
             patch.object(stage_calibration_service, "last_result", return_value=calibration()), \
             patch.object(settings, "stage_approach_mm", 0.0):
            machine_service.move_to_steps(int(10 * spm), int(10 * spm))
            carriage.cmd = [10.0, 10.0]
            stage_monitor_service.reset()
            time.sleep(0.6)
            machine_service.move_to_steps(int(11 * spm), int(10 * spm))  # reference stop is 10,10
            snap = self._wait(1)
            first = snap["samples"][-1]
            self.assertEqual(first["move_mm"], [1.0, 0.0])
            self.assertLess(abs(first["error_mm"][0]), 0.004)  # +X move: no slack
            machine_service.move_to_steps(int(10 * spm), int(10 * spm))  # reverse: backlash shows
            snap = self._wait(2)
            second = snap["samples"][-1]
            self.assertEqual(second["move_mm"], [-1.0, 0.0])
            self.assertAlmostEqual(second["error_mm"][0], 0.05, delta=0.006)  # stayed 50 µm short
            self.assertAlmostEqual(second["error_um"], 50, delta=6)
            self.assertEqual(snap["summary"]["n"], 2)
        self.assertTrue(any(e.get("event") == "sample" for e in events))

    def test_without_calibration_it_says_so(self):
        carriage = Carriage()
        camera = MagicMock(is_active=True, is_mock=False)
        camera.get_fresh_frame.side_effect = lambda *a, **k: (time.monotonic(), carriage.frame())
        spm = machine_service.steps_per_mm
        with patch.object(smod, "camera_service", camera), patch.object(smod, "SETTLE_SEC", 0.05), \
             patch.object(stage_calibration_service, "last_result", return_value=None):
            stage_monitor_service.reset()
            machine_service.move_to_steps(int(12 * spm), int(12 * spm))
            deadline = time.monotonic() + 5
            while stage_monitor_service.snapshot()["status"] != "needs_calibration" and time.monotonic() < deadline:
                time.sleep(0.05)
        self.assertEqual(stage_monitor_service.snapshot()["status"], "needs_calibration")


if __name__ == "__main__":
    unittest.main()
