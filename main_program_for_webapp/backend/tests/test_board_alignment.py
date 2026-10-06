"""Board alignment: a board placed turned/shifted is measured and compensated (simulated stage + camera)."""
import base64
import math
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from app.config import settings
from app.core.registration import corrected_position, register_images, solve_board_pose, warp_to_reference
from app.services import board_alignment as ba
from app.services.machine_service import machine_service
from app.services.stage_calibration_service import stage_calibration_service

rng = np.random.default_rng(3)
TEX = cv2.GaussianBlur(rng.integers(0, 255, (1300, 1700)).astype(np.uint8), (0, 0), 2.0)
for _ in range(300):  # some PCB-like structure: pads and traces
    x, y = int(rng.integers(0, 1650)), int(rng.integers(0, 1250))
    cv2.rectangle(TEX, (x, y), (x + int(rng.integers(6, 40)), y + int(rng.integers(6, 40))), int(rng.integers(0, 255)), -1)
TEX = cv2.cvtColor(TEX, cv2.COLOR_GRAY2BGR)
S_TEX, ORIGIN = 40.0, np.array([1550.0, 1150.0])  # texture px per mm; texture px of board mm (0,0)
K = 30.0
M = np.array([[-K, 0.3], [0.4, K]])  # mirrored and slightly turned camera, like the station
W, H = 960, 540
C = np.array([W / 2, H / 2])


def rot(deg):
    r = math.radians(deg)
    return np.array([[math.cos(r), -math.sin(r)], [math.sin(r), math.cos(r)]])


def view(stage_mm, theta=0.0, t=(0.0, 0.0)):
    """Camera picture with the stage at `stage_mm` and the board placed with (theta, t)."""
    ri, mi = np.linalg.inv(rot(theta)), np.linalg.inv(M)
    a = S_TEX * ri @ mi
    off = -a @ C + S_TEX * ri @ (-np.asarray(t) - np.asarray(stage_mm)) + ORIGIN
    return cv2.warpAffine(TEX, np.hstack([a, off[:, None]]), (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_REFLECT)


def data_url(img):
    ok, jpg = cv2.imencode(".jpg", cv2.resize(img, (W, H)), [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return "data:image/jpeg;base64," + base64.b64encode(jpg.tobytes()).decode()


def ncc(a, b):
    a = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)[40:-40, 40:-40].astype(np.float32)
    b = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)[40:-40, 40:-40].astype(np.float32)
    return float(((a - a.mean()) * (b - b.mean())).mean() / (a.std() * b.std()))


class RegistrationMathTests(unittest.TestCase):
    def test_pose_from_two_points_and_corrected_positions(self):
        p1, p2 = (10.0, 8.0), (28.0, 20.0)
        for theta, t in [(2.0, (1.5, -0.8)), (-4.0, (-3.0, 2.0))]:
            with self.subTest(theta=theta):
                samples = []
                for p in (p1, p2):
                    r = register_images(view(p), view(p, theta, t))
                    self.assertIsNotNone(r)
                    samples.append({"stage_mm": p, "shift_px": r["shift_px"], "angle_deg": r["angle_deg"], "matrix_px_per_mm": M.tolist()})
                pose = solve_board_pose(samples)
                self.assertAlmostEqual(pose["angle_deg"], theta, delta=0.02)
                np.testing.assert_allclose(pose["offset_mm"], t, atol=0.005)
                self.assertEqual(pose["angle_source"], "two_points")
                for p in (p1, p2):  # after correction the point sees its taught picture again
                    f = view(corrected_position(p, pose), theta, t)
                    r = register_images(view(p), f)
                    self.assertLess(math.hypot(*r["shift_px"]), 0.5)
                    self.assertGreater(ncc(view(p), warp_to_reference(f, r["matrix"])), 0.97)

    def test_unrelated_pictures_do_not_register(self):
        other = cv2.GaussianBlur(rng.integers(0, 255, (H, W, 3)).astype(np.uint8), (0, 0), 2.0)
        self.assertIsNone(register_images(view((10, 8)), other))


class BoardAlignmentServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        machine_service.connect(mode="simulation")
        machine_service.home()

    @classmethod
    def tearDownClass(cls):
        machine_service.disconnect()

    def _points(self, coords):
        spm = machine_service.steps_per_mm
        return [SimpleNamespace(index=i, name=f"P{i + 1}", x_steps=int(round(x * spm)), y_steps=int(round(y * spm)),
                                x_mm=x, y_mm=y, zoom=1.0) for i, (x, y) in enumerate(coords)]

    def _run(self, theta, t, coords, refs_at):
        points = self._points(coords)
        refs = {i: data_url(view(coords[i])) for i in refs_at}
        camera = MagicMock(is_active=True, is_mock=False)
        camera.wait_until_still.return_value = {"timestamp": 0.0}
        camera.get_fresh_frame.side_effect = lambda *a, **k: (1.0, view(machine_service.get_state().position_mm, theta, t))
        with patch.object(ba, "camera_service", camera), patch("app.services.board_alignment.time.sleep"), \
             patch.object(stage_calibration_service, "last_result", return_value={"stage_to_image": M.tolist(), "image_size": [W, H]}):
            pose = ba.estimate_board_pose(points, refs, 0.0, 800, lambda: False)
            if pose["status"] == "ok":
                ba.check_limits(pose)
                ba.apply_pose(points, pose)
        return pose, points

    def test_measures_the_board_with_the_two_farthest_taught_points_and_moves_all_points(self):
        coords = [(10.0, 8.0), (18.0, 12.0), (28.0, 20.0), (22.0, 9.0)]
        theta, t = 1.5, (1.2, -0.7)
        pose, points = self._run(theta, t, coords, refs_at=[0, 1, 2])
        self.assertEqual(pose["status"], "ok")
        self.assertEqual([m["point"] for m in pose["measured"]], [0, 2])  # farthest pair
        self.assertAlmostEqual(pose["angle_deg"], theta, delta=0.03)
        np.testing.assert_allclose(pose["offset_mm"], t, atol=0.01)
        spm = machine_service.steps_per_mm
        for pt, (x, y) in zip(points, coords):  # every point moved, the untaught one too
            want = corrected_position((x, y), {"angle_deg": theta, "offset_mm": t})
            self.assertAlmostEqual(pt.x_steps / spm, want[0], delta=0.02)
            self.assertAlmostEqual(pt.y_steps / spm, want[1], delta=0.02)

    def test_too_far_off_stops_the_scan_with_a_reason(self):
        with patch.object(settings, "board_align_max_deg", 1.0):
            with self.assertRaisesRegex(ba.BoardMisplaced, "เอียง"):
                self._run(3.0, (0.5, 0.5), [(10.0, 8.0), (28.0, 20.0)], refs_at=[0, 1])

    def test_without_calibration_only_the_pictures_are_aligned(self):
        points = self._points([(10.0, 8.0)])
        camera = MagicMock(is_active=True, is_mock=False)
        camera.wait_until_still.return_value = {"timestamp": 0.0}
        camera.get_fresh_frame.side_effect = lambda *a, **k: (1.0, view((10.0, 8.0), 1.0, (0.3, 0.2)))
        with patch.object(ba, "camera_service", camera), patch("app.services.board_alignment.time.sleep"), \
             patch.object(stage_calibration_service, "last_result", return_value=None):
            pose = ba.estimate_board_pose(points, {0: data_url(view((10.0, 8.0)))}, 0.0, 800, lambda: False)
        self.assertEqual(pose["status"], "no_calibration")

    def test_point_aligner_puts_the_frame_back_on_the_reference(self):
        ref = view((15.0, 10.0))
        frame = view((15.0, 10.0), 2.5, (0.4, -0.3))
        aligner = ba.PointAligner(data_url(ref))
        out = aligner(frame)
        self.assertTrue(aligner.info["applied"])
        self.assertAlmostEqual(aligner.info["angle_deg"], -2.5, delta=0.1)  # mirrored camera
        self.assertGreater(ncc(cv2.resize(ref, (W, H)), out), 0.9)
        self.assertLess(ncc(cv2.resize(ref, (W, H)), frame), 0.5)
        # Later frames reuse the first registration.
        self.assertTrue(np.array_equal(aligner(frame), out))


if __name__ == "__main__":
    unittest.main()
