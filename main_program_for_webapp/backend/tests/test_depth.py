"""Motion-stereo heights: the core math on synthetic scenes and the /api/aoi/depth flow."""
import math
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.config import settings
from app.core.depth import estimate_shift, height_map, height_map_views
from app.core.security import lease_manager
from app.main import app
from app.services.depth_service import depth_service
from app.services.machine_service import machine_service

Z0 = 200.0
BOX = (420, 430, 560, 540)


def _texture(n, seed):
    rng = np.random.default_rng(seed)
    return cv2.GaussianBlur(rng.integers(0, 255, (n, n)).astype(np.uint8), (0, 0), 1.6)


def _shifted(img, dx, dy):
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def _stripes(n):
    """Lines running along X: matching along an X move is ambiguous, along Y it is not."""
    return np.tile((127 + 100 * np.sin(np.arange(n) / 3.0)).astype(np.uint8)[:, None], (1, n))


def scene_views(shifts, h_obj, n=1400, top=None):
    """Frame A, and one frame B per board shift (px) with a block `h_obj` mm tall."""
    board = _texture(n, 1)
    obj = _texture(n, 2) if top is None else top(n)
    x1, y1, x2, y2 = BOX
    mask = np.zeros((n, n), np.uint8)
    mask[y1:y2, x1:x2] = 255
    a = board.copy()
    a[mask > 0] = obj[mask > 0]
    k = Z0 / (Z0 - h_obj)  # the block is closer to the camera, so it moves further
    bs = []
    for sx, sy in shifts:
        b = _shifted(board, sx, sy)
        obj_b, mask_b = _shifted(obj, sx * k, sy * k), _shifted(mask, sx * k, sy * k)
        b[mask_b > 127] = obj_b[mask_b > 127]
        bs.append(cv2.cvtColor(b, cv2.COLOR_GRAY2BGR))
    return cv2.cvtColor(a, cv2.COLOR_GRAY2BGR), bs


def _noisy(img, seed, sigma=4.0):
    """Camera sensor noise."""
    rng = np.random.default_rng(seed)
    return np.clip(img.astype(np.int16) + rng.normal(0, sigma, img.shape), 0, 255).astype(np.uint8)


def scene(shift_xy, h_obj, n=1400):
    """Frame A, and frame B after the board moved by `shift_xy` px with a block `h_obj` mm tall."""
    a, (b,) = scene_views([shift_xy], h_obj, n)
    return a, b


class HeightMapTests(unittest.TestCase):
    def test_block_height_is_recovered_in_any_move_direction(self):
        for angle, h in [(0, 10.0), (90, 5.0), (-37, 8.0), (180, 2.0)]:
            with self.subTest(angle=angle, h=h):
                shift = (200 * math.cos(math.radians(angle)), 200 * math.sin(math.radians(angle)))
                a, b = scene(shift, h)
                dx, dy, _ = estimate_shift(a, b)
                self.assertAlmostEqual(math.hypot(dx, dy), 200, delta=2)
                r = height_map(a, b, (dx, dy), BOX, Z0)
                self.assertAlmostEqual(r["stats"]["median_mm"], h, delta=0.6)
                self.assertEqual(len(r["heights"]), r["grid_w"] * r["grid_h"])
                # The board margin around the part stays near zero.
                grid = np.array(r["heights"]).reshape(r["grid_h"], r["grid_w"])
                self.assertLess(abs(float(np.median(grid[:5, :]))), 0.6)

    def test_noise_and_shiny_tops_do_not_spike_the_max(self):
        """Real frames: sensor noise and a texture-less (shiny) patch must not create 20+ mm spikes."""
        a, b = scene((200, 0), 6.0)
        rng = np.random.default_rng(7)
        for img, dx in ((a, 0), (b, int(200 * Z0 / (Z0 - 6.0)))):
            x1, y1, x2, y2 = BOX
            img[y1 + 20:y2 - 20, x1 + 20 + dx:x1 + 80 + dx] = 235  # flat glare on the part's top
            img[:] = np.clip(img.astype(np.int16) + rng.normal(0, 6, img.shape), 0, 255).astype(np.uint8)
        dx, dy, _ = estimate_shift(a, b)
        r = height_map(a, b, (dx, dy), BOX, Z0)
        self.assertAlmostEqual(r["stats"]["median_mm"], 6.0, delta=1.0)
        self.assertLess(r["stats"]["max_mm"], 9.0)
        self.assertLess(max(r["heights"]), 12.0)

    def test_isolated_spikes_are_rejected(self):
        from app.core.depth import reject_outliers

        h = np.full((60, 60), 5.0, np.float32)
        h[10, 10] = 25.0
        h[40, 30] = -4.0
        valid = reject_outliers(h, np.ones_like(h, bool))
        self.assertFalse(valid[10, 10])
        self.assertFalse(valid[40, 30])
        self.assertTrue(valid[30, 30])

    def test_views_in_several_directions_measure_what_one_direction_cannot(self):
        shifts = [(180, 0), (0, 180), (-180, 0), (0, -180)]
        a, bs = scene_views(shifts, 6.0, top=_stripes)
        a, bs = _noisy(a, 0), [_noisy(b, i + 1) for i, b in enumerate(bs)]
        views = [(b, estimate_shift(a, b)[:2]) for b in bs]
        one = height_map_views(a, views[:1], BOX, Z0)
        self.assertGreater(abs(one["stats"]["median_mm"] - 6.0), 2.0)  # +X alone is lost on the lines
        four = height_map_views(a, views, BOX, Z0)
        self.assertAlmostEqual(four["stats"]["median_mm"], 6.0, delta=0.5)
        self.assertGreater(four["stats"]["box_valid_ratio"], 0.9)
        self.assertEqual((four["stats"]["views_used"], four["stats"]["views_total"]), (4, 4))
        self.assertIsNotNone(four["stats"]["spread_mm"])

    def test_fused_views_are_more_precise_than_one(self):
        shifts = [(180, 0), (0, 180), (-180, 0), (0, -180)]
        a, bs = scene_views(shifts, 6.0)
        a, bs = _noisy(a, 0), [_noisy(b, i + 1) for i, b in enumerate(bs)]
        views = [(b, estimate_shift(a, b)[:2]) for b in bs]

        def rms(r):
            g = np.array(r["heights"]).reshape(r["grid_h"], r["grid_w"])
            bx1, by1, bx2, by2 = r["box_in_roi"]
            inner = g[int(by1 * r["grid_h"]) + 2:int(by2 * r["grid_h"]) - 2, int(bx1 * r["grid_w"]) + 2:int(bx2 * r["grid_w"]) - 2]
            return float(np.sqrt(np.mean((inner - 6.0) ** 2)))

        self.assertLess(rms(height_map_views(a, views, BOX, Z0)), rms(height_map_views(a, views[:1], BOX, Z0)))

    def test_a_view_the_part_left_is_skipped(self):
        a, bs = scene_views([(180, 0), (-600, 0)], 4.0)
        views = [(bs[0], estimate_shift(a, bs[0])[:2]), (bs[1], (-600.0, 0.0))]  # the part is off frame B
        r = height_map_views(a, views, BOX, Z0)
        self.assertEqual((r["stats"]["views_used"], r["stats"]["views_total"]), (1, 2))
        self.assertAlmostEqual(r["stats"]["median_mm"], 4.0, delta=0.6)

    def test_rejects_frames_that_did_not_move(self):
        a, _ = scene((0, 0), 5)
        with self.assertRaises(ValueError):
            height_map(a, a, (0.5, 0.0), BOX, Z0)


class DepthEndpointTests(unittest.TestCase):
    """Simulated stage; the camera returns frame A at the point and B after the side move."""

    PX_PER_MM = 30.0

    @classmethod
    def setUpClass(cls):
        machine_service.connect(mode="simulation")
        machine_service.home()
        cls.client = TestClient(app)
        _, cls.token = lease_manager.acquire_lease("QA", "127.0.0.1", force=True)[:2]
        cls.headers = {"X-Operator-Token": cls.token}

    def setUp(self):
        # The lease outlives a few tests only: if it lapses mid-move the stage is stopped.
        self.assertTrue(lease_manager.renew_lease(self.token))

    @classmethod
    def tearDownClass(cls):
        lease_manager.release_lease(cls.token)
        machine_service.disconnect()
        depth_service.clear()

    def _camera(self, point, cache):
        """Frame at the stage's current position: the board shifts PX_PER_MM px per mm moved."""
        def frame(zoom):
            x_mm, y_mm = machine_service.get_state().position_mm
            moved = (round(x_mm - point[0], 3), round(y_mm - point[1], 3))
            if moved not in cache:
                a, (b,) = scene_views([(moved[0] * self.PX_PER_MM, moved[1] * self.PX_PER_MM)], 6.0)
                cache[moved] = a if moved == (0, 0) else b
            return cache[moved]
        return frame

    def _post(self, body):
        return self.client.post("/api/aoi/depth", json=body, headers=self.headers)

    def test_measure_moves_around_returns_and_reports_height(self):
        depth_service.clear()
        point = (10.0, 12.0)
        cache = {}
        n = 1400
        bbox = [BOX[0] / n, BOX[1] / n, BOX[2] / n, BOX[3] / n]
        with patch.object(depth_service, "_fresh_frame", side_effect=self._camera(point, cache)), \
             patch("app.services.depth_service.camera_service", MagicMock(is_active=True, is_mock=False)), \
             patch("app.services.depth_service.time.sleep"), \
             patch.object(settings, "depth_views", 4):
            res = self._post({"x_mm": point[0], "y_mm": point[1], "zoom": 1, "bbox": bbox})
            self.assertEqual(res.status_code, 200, res.text)
            body = res.json()
            self.assertAlmostEqual(body["stats"]["median_mm"], 6.0, delta=0.7)
            self.assertEqual((body["stats"]["views_used"], body["stats"]["views_total"]), (4, 4))
            # Shots at the point and at ±X, ±Y one baseline away.
            b = settings.depth_baseline_mm
            self.assertEqual(set(cache), {(0, 0), (b, 0), (-b, 0), (0, b), (0, -b)})
            self.assertTrue(body["texture"].startswith("data:image/jpeg;base64,"))
            self.assertEqual(body["camera_distance_mm"], settings.depth_camera_distance_mm)
            self.assertAlmostEqual(body["mm_per_px"], 1 / self.PX_PER_MM, delta=0.002)
            # The stage is back at the point afterwards.
            self.assertEqual(tuple(round(v, 2) for v in machine_service.get_state().position_mm), point)
            # A second part at the same point reuses the cached shots.
            calls = len(cache)
            with patch.object(depth_service, "_shot", side_effect=AssertionError("no new shots expected")):
                again = self._post({"x_mm": point[0], "y_mm": point[1], "zoom": 1, "bbox": [0.1, 0.1, 0.2, 0.2]})
            self.assertEqual(again.status_code, 200, again.text)
            self.assertEqual(len(cache), calls)

    def test_single_view_mode_moves_along_x_only(self):
        depth_service.clear()
        point = (10.0, 12.0)
        cache = {}
        n = 1400
        bbox = [BOX[0] / n, BOX[1] / n, BOX[2] / n, BOX[3] / n]
        with patch.object(depth_service, "_fresh_frame", side_effect=self._camera(point, cache)), \
             patch("app.services.depth_service.camera_service", MagicMock(is_active=True, is_mock=False)), \
             patch("app.services.depth_service.time.sleep"), \
             patch.object(settings, "depth_views", 1):
            res = self._post({"x_mm": point[0], "y_mm": point[1], "zoom": 1, "bbox": bbox, "recapture": True})
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual(res.json()["stats"]["views_used"], 1)
            self.assertAlmostEqual(res.json()["stats"]["median_mm"], 6.0, delta=0.7)
            self.assertEqual(len(cache), 2)
            self.assertEqual(next(k for k in cache if k != (0, 0))[1], 0)

    def test_moves_beyond_the_travel_are_left_out(self):
        depth_service.clear()
        point = (2.0, 12.0)  # -X by a baseline would leave the travel
        cache = {}
        n = 1400
        bbox = [BOX[0] / n, BOX[1] / n, BOX[2] / n, BOX[3] / n]
        with patch.object(depth_service, "_fresh_frame", side_effect=self._camera(point, cache)), \
             patch("app.services.depth_service.camera_service", MagicMock(is_active=True, is_mock=False)), \
             patch("app.services.depth_service.time.sleep"), \
             patch.object(settings, "depth_views", 4):
            res = self._post({"x_mm": point[0], "y_mm": point[1], "zoom": 1, "bbox": bbox, "recapture": True})
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual(res.json()["stats"]["views_total"], 3)
            self.assertTrue(all(k[0] >= -point[0] for k in cache))

    def test_needs_a_homed_stage(self):
        machine_service.disconnect()
        try:
            res = self.client.post(
                "/api/aoi/depth", json={"x_mm": 1, "y_mm": 1, "bbox": [0.1, 0.1, 0.2, 0.2], "recapture": True}, headers=self.headers
            )
            self.assertEqual(res.status_code, 400)
        finally:
            machine_service.connect(mode="simulation")
            machine_service.home()


if __name__ == "__main__":
    unittest.main()
