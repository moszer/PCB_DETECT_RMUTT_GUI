"""Straightening a turned camera: skew estimate, rotated frames, and the calibration following it."""
import math
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.config import settings
from app.core.straighten import estimate_skew_deg, rotate
from app.main import app
from app.services.camera_service import camera_service
from app.services.stage_calibration_service import stage_calibration_service, stage_matrix


def board(seed=0):
    img = np.full((1500, 1500, 3), 40, np.uint8)
    rng = np.random.default_rng(seed)
    for _ in range(120):
        x, y = (int(v) for v in rng.integers(100, 1300, 2))
        cv2.rectangle(img, (x, y), (x + int(rng.integers(20, 150)), y + int(rng.integers(20, 150))), (200, 200, 200), 3)
    return img


class SkewTests(unittest.TestCase):
    def test_finds_the_rotation_that_levels_the_board(self):
        img = board()
        for turned in (0.0, 3.0, -2.0, 0.7, 8.0):
            with self.subTest(turned=turned):
                self.assertAlmostEqual(estimate_skew_deg(rotate(img, turned)), -turned, delta=0.05)

    def test_no_lines_no_answer(self):
        self.assertIsNone(estimate_skew_deg(np.full((600, 800, 3), 128, np.uint8)))


class RotatedFramesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        camera_service.start()  # mock camera in tests

    @classmethod
    def tearDownClass(cls):
        camera_service.stop()

    def test_frames_are_straightened_raw_ones_are_not(self):
        ts, raw = camera_service.get_fresh_frame(time.monotonic(), raw=True)
        with patch.object(settings, "camera_rotate_deg", 4.0):
            t2, raw2 = camera_service.get_latest_frame(raw=True)
            t3, turned = camera_service.get_latest_frame()
        self.assertEqual(t2, t3)
        self.assertTrue(np.array_equal(turned, rotate(raw2, 4.0)))
        self.assertFalse(np.array_equal(turned, raw2))

    def test_calibration_matrix_turns_with_the_picture(self):
        m = np.array([[-130.0, 1.0], [-1.5, 125.0]])
        cal = {"stage_to_image": m.tolist(), "image_size": [2000, 2000], "image_rotation_deg": 0.0}
        with patch.object(stage_calibration_service, "last_result", return_value=cal):
            with patch.object(settings, "camera_rotate_deg", 0.0):
                np.testing.assert_allclose(stage_matrix((2000, 2000)), m)
            with patch.object(settings, "camera_rotate_deg", 3.0):
                turned = stage_matrix((2000, 2000))
        # A stage move now shows up turned by the same 3° in the picture.
        r = cv2.getRotationMatrix2D((0, 0), 3.0, 1.0)[:, :2]
        np.testing.assert_allclose(turned, r @ m, atol=1e-9)
        self.assertAlmostEqual(np.linalg.norm(turned[:, 0]), np.linalg.norm(m[:, 0]), places=6)

    def test_detect_and_preview_endpoints(self):
        client = TestClient(app)
        res = client.get("/api/camera/straighten/preview", params={"angle": 2.5})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["content-type"], "image/jpeg")
        self.assertEqual(client.get("/api/camera/straighten/preview", params={"angle": 40}).status_code, 400)
        det = client.get("/api/camera/straighten/detect")
        self.assertIn(det.status_code, (200, 422))  # the mock picture may have no clear lines


if __name__ == "__main__":
    unittest.main()
