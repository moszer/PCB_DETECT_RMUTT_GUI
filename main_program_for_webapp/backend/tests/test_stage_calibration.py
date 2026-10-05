"""Stage calibration: the math on synthetic shifts, and the full job on a simulated stage whose
carriage has backlash and a scale error, seen by a fake camera."""
import math
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.config import settings
from app.core.security import lease_manager
from app.core.stage_calibration import checkerboard_mm_per_px, fit_axis, measure_shift, summarize
from app.main import app
from app.services import stage_calibration_service as scs_module
from app.services.machine_service import machine_service
from app.services.stage_calibration_service import stage_calibration_service

PX_PER_MM = 130.0
ROT = math.radians(1.2)  # camera turned slightly on its mount


def _texture(h, w, seed=1):
    rng = np.random.default_rng(seed)
    return cv2.GaussianBlur(rng.integers(0, 255, (h, w)).astype(np.uint8), (0, 0), 2.0)


BOARD = _texture(2200, 2600)
FRAME_W, FRAME_H = 1280, 720


def render(shift_px):
    """The camera's view of the board when the board has moved by `shift_px` in the image."""
    dx, dy = shift_px
    cx, cy = BOARD.shape[1] / 2, BOARD.shape[0] / 2
    m = np.float32([[1, 0, -(cx - FRAME_W / 2) + dx], [0, 1, -(cy - FRAME_H / 2) + dy]])
    view = cv2.warpAffine(BOARD, m, (FRAME_W, FRAME_H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return cv2.cvtColor(view, cv2.COLOR_GRAY2BGR)


def image_shift(phys_mm):
    """Board moving +X/+Y moves the image the other way, turned by ROT."""
    x, y = phys_mm
    c, s = math.cos(ROT), math.sin(ROT)
    return (-PX_PER_MM * (c * x - s * y), -PX_PER_MM * (s * x + c * y))


class MathTests(unittest.TestCase):
    def test_measure_shift_small_and_large_with_prediction(self):
        ref = render((0, 0))
        for true in [(12.3, -4.7), (-260.4, 3.2), (5.5, 300.25)]:
            with self.subTest(true=true):
                frame = render(true)
                dx, dy, resp = measure_shift(ref, frame, predicted=(true[0] + 9, true[1] - 7))
                self.assertAlmostEqual(dx, true[0], delta=0.15)
                self.assertAlmostEqual(dy, true[1], delta=0.15)
                self.assertGreater(resp, 0.2)

    def test_fit_recovers_scale_backlash_and_summary(self):
        backlash = 0.04
        pos = list(np.linspace(-2, 2, 9))
        rows, fwd = [], []
        for p in pos:
            rows.append(image_shift((p, 0)))
            fwd.append(True)
        for p in pos[::-1]:
            rows.append(image_shift((p + backlash, 0)))  # moving - leaves the carriage behind
            fwd.append(False)
        fx = fit_axis(pos + pos[::-1], rows, fwd)
        rows_y = [image_shift((0, p)) for p in pos] + [image_shift((0, p + 2 * backlash)) for p in pos[::-1]]
        fy = fit_axis(pos + pos[::-1], rows_y, fwd)
        s = summarize(fx, fy, {"plus": [image_shift((0, 0))] * 3, "minus": [image_shift((backlash, 2 * backlash))] * 3},
                      mm_per_px=1 / PX_PER_MM * 1.01, steps_per_mm=512)
        self.assertAlmostEqual(s["x"]["px_per_mm"], PX_PER_MM, delta=0.01)
        self.assertAlmostEqual(s["x"]["backlash_mm"], backlash, delta=1e-4)
        self.assertAlmostEqual(s["y"]["backlash_mm"], 2 * backlash, delta=1e-4)
        self.assertAlmostEqual(s["camera_rotation_deg"], math.degrees(ROT), delta=0.01)
        self.assertAlmostEqual(s["squareness_deg"], 0, delta=0.01)
        self.assertAlmostEqual(s["xy_scale_ratio"], 1, delta=1e-4)
        self.assertAlmostEqual(s["x"]["scale_error_pct"], 1.0, delta=0.01)
        self.assertAlmostEqual(s["x"]["suggested_steps_per_mm"], 512 / 1.01, delta=0.01)
        self.assertEqual(s["repeatability"]["direction_gap_mm"], [-0.04, -0.08])
        self.assertAlmostEqual(s["suggested_approach_mm"], 0.17, delta=0.001)
        back = [e for e in s["x"]["errors"] if not e[2]]
        self.assertTrue(all(abs(e[1] - backlash) < 1e-3 for e in back))

    def test_checkerboard_scale(self):
        sq = 40  # px
        img = np.full((720, 1280), 255, np.uint8)
        for r in range(8):
            for c in range(11):
                if (r + c) % 2 == 0:
                    img[100 + r * sq:100 + (r + 1) * sq, 200 + c * sq:200 + (c + 1) * sq] = 0
        mm = checkerboard_mm_per_px(img, (10, 7), 5.0)
        self.assertAlmostEqual(mm, 5.0 / sq, delta=0.002)
        self.assertIsNone(checkerboard_mm_per_px(np.full((200, 200), 128, np.uint8), (10, 7), 5.0))


class Carriage:
    """Where the carriage really is: it lags `backlash` mm behind after moving -, and the drive
    moves `1 + scale_err` mm per commanded mm."""

    def __init__(self, backlash=(0.05, 0.08), scale_err=(0.004, -0.003)):
        self.backlash, self.scale_err = backlash, scale_err
        self.cmd = [0.0, 0.0]
        self.lag = [0.0, 0.0]
        self.raw_moves = []

    def wrap(self, original):
        def move(x_steps, y_steps, speed, timeout_sec):
            target = (x_steps / machine_service.steps_per_mm, y_steps / machine_service.steps_per_mm)
            for k in (0, 1):
                if target[k] < self.cmd[k] - 1e-9:
                    self.lag[k] = self.backlash[k]
                elif target[k] > self.cmd[k] + 1e-9:
                    self.lag[k] = 0.0
                self.cmd[k] = target[k]
            self.raw_moves.append(target)
            return original(x_steps, y_steps, speed, timeout_sec)
        return move

    def physical(self):
        return tuple(self.cmd[k] * (1 + self.scale_err[k]) + self.lag[k] for k in (0, 1))

    def frame(self):
        p = self.physical()
        return render(image_shift(p))


class CompensationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        machine_service.connect(mode="simulation")
        machine_service.home()

    @classmethod
    def tearDownClass(cls):
        machine_service.disconnect()

    def test_moves_arriving_minus_overshoot_then_come_up(self):
        carriage = Carriage()
        spm = machine_service.steps_per_mm
        with patch.object(machine_service, "_move_raw", side_effect=carriage.wrap(machine_service._move_raw)), \
             patch.object(settings, "stage_approach_mm", 0.3), patch("time.sleep"):
            machine_service.move_to_steps(int(10 * spm), int(10 * spm))
            carriage.raw_moves.clear()
            machine_service.move_to_steps(int(8 * spm), int(12 * spm))  # X arrives -, Y arrives +
            first = carriage.raw_moves[0]
            self.assertAlmostEqual(first[0], 7.7, delta=1 / spm)
            self.assertEqual((first[1], carriage.raw_moves[1]), (12.0, (8.0, 12.0)))
            self.assertEqual(len(carriage.raw_moves), 2)
            carriage.raw_moves.clear()
            machine_service.move_to_steps(int(9 * spm), int(13 * spm))  # both +: one move
            self.assertEqual(carriage.raw_moves, [(9.0, 13.0)])
            carriage.raw_moves.clear()
            machine_service.move_to_steps(int(9 * spm), int(13 * spm), compensate=False)
            machine_service.move_to_steps(int(5 * spm), int(5 * spm), compensate=False)
            self.assertEqual(carriage.raw_moves, [(9.0, 13.0), (5.0, 5.0)])
            self.assertEqual(machine_service.get_state().position_mm, (5.0, 5.0))

    def test_off_by_default(self):
        self.assertEqual(type(settings).model_fields["stage_approach_mm"].default, 0.0)


class CalibrationJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        machine_service.connect(mode="simulation")
        machine_service.home()
        cls.client = TestClient(app)
        _, cls.token = lease_manager.acquire_lease("QA", "127.0.0.1", force=True)[:2]
        cls.headers = {"X-Operator-Token": cls.token}

    @classmethod
    def tearDownClass(cls):
        lease_manager.release_lease(cls.token)
        machine_service.disconnect()

    def setUp(self):
        self.assertTrue(lease_manager.renew_lease(self.token))
        self.tmp = scs_module.RESULT_FILE.with_name("stage_calibration.test.json")
        self.tmp.unlink(missing_ok=True)

    def tearDown(self):
        self.tmp.unlink(missing_ok=True)

    def _run(self, carriage, approach_mm):
        spm = machine_service.steps_per_mm
        machine_service.move_to_steps(int(15 * spm), int(15 * spm), compensate=False)
        with patch.object(machine_service, "_move_raw", side_effect=carriage.wrap(machine_service._move_raw)), \
             patch.object(stage_calibration_service, "_fresh_frame", side_effect=carriage.frame), \
             patch.object(scs_module, "camera_service", MagicMock(is_active=True, is_mock=False)), \
             patch.object(scs_module, "RESULT_FILE", self.tmp), \
             patch.object(settings, "stage_approach_mm", approach_mm), \
             patch.object(scs_module, "time", SimpleNamespace(time=time.time, monotonic=time.monotonic, sleep=lambda _s: None)):
            carriage.cmd = list(machine_service.get_state().position_mm)
            res = self.client.post("/api/aoi/calibration/start", json={}, headers=self.headers)
            self.assertEqual(res.status_code, 200, res.text)
            # Moving manually is refused while it runs.
            busy = self.client.post("/api/aoi/jog", json={"dx_mm": 1, "dy_mm": 0}, headers=self.headers)
            self.assertEqual(busy.status_code, 400)
            deadline = time.monotonic() + 120
            while stage_calibration_service.is_running and time.monotonic() < deadline:
                lease_manager.renew_lease(self.token)
                time.sleep(0.05)
            status = self.client.get("/api/aoi/calibration").json()
        self.assertEqual(status["state"], "done", status.get("message"))
        self.assertEqual(status["step"], status["total"])
        return status["last"]

    def test_full_job_measures_the_simulated_faults(self):
        carriage = Carriage(backlash=(0.05, 0.08), scale_err=(0.004, -0.003))
        r = self._run(carriage, 0.0)
        self.assertEqual(r["center_mm"], [15.0, 15.0])
        self.assertAlmostEqual(r["x"]["backlash_mm"], 0.05, delta=0.004)
        self.assertAlmostEqual(r["y"]["backlash_mm"], 0.08, delta=0.004)
        self.assertAlmostEqual(r["camera_rotation_deg"], math.degrees(ROT), delta=0.05)
        # Y moves 0.7% less than X per commanded mm.
        self.assertAlmostEqual(r["xy_scale_ratio"], 0.997 / 1.004, delta=0.0005)
        self.assertLess(r["x"]["linearity_mm"], 0.005)
        self.assertLess(r["repeatability"]["plus"]["rms_mm"], 0.003)
        gap = r["repeatability"]["direction_gap_mm"]
        self.assertAlmostEqual(gap[0], -0.05, delta=0.005)
        self.assertAlmostEqual(gap[1], -0.08, delta=0.005)
        self.assertAlmostEqual(r["suggested_approach_mm"], 0.17, delta=0.01)
        self.assertNotIn("compensated", r["repeatability"])
        # Back at the centre afterwards.
        self.assertEqual(machine_service.get_state().position_mm, (15.0, 15.0))

    def test_with_compensation_returns_land_on_the_same_spot(self):
        carriage = Carriage(backlash=(0.05, 0.08), scale_err=(0, 0))
        r = self._run(carriage, 0.2)
        comp = r["repeatability"]["compensated"]
        self.assertLess(comp["worst_pair_mm"], 0.005)
        self.assertEqual(r["approach_mm_during_test"], 0.2)

    def test_refuses_without_a_real_camera(self):
        res = self.client.post("/api/aoi/calibration/start", json={}, headers=self.headers)
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
