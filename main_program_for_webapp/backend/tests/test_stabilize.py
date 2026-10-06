"""Anti-shake: wait until the picture stops moving after a stage move."""
import math
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app.config import settings
from app.core.stabilize import motion_px, small_gray, wait_until_still
from app.services.camera_service import camera_service

rng = np.random.default_rng(0)
BOARD = cv2.GaussianBlur(rng.integers(0, 255, (1300, 2200)).astype(np.uint8), (0, 0), 2.5)


def view(dx, dy):
    m = np.float32([[1, 0, -150 + dx], [0, 1, -150 + dy]])
    return cv2.warpAffine(BOARD, m, (1920, 1000), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


class RingingCamera:
    """30 fps camera on a frame that swings after a move: amplitude decays with time constant tau."""

    def __init__(self, amplitude=40.0, tau=0.25, hz=7.0, fps=30.0):
        self.amplitude, self.tau, self.hz, self.fps = amplitude, tau, hz, fps
        self.i = 0

    def offset(self, i):
        t = i / self.fps
        a = self.amplitude * math.exp(-t / self.tau)
        return a * math.sin(2 * math.pi * self.hz * t), 0.4 * a * math.cos(2 * math.pi * self.hz * t)

    def next(self, after):
        self.i += 1
        return float(self.i), view(*self.offset(self.i))


class StillDetectionTests(unittest.TestCase):
    def test_motion_between_frames_in_full_resolution_px(self):
        a, s = small_gray(view(0, 0))
        b, _ = small_gray(view(12, -5))
        self.assertAlmostEqual(motion_px(a, b, s), 13.0, delta=1.0)

    def test_waits_for_the_swing_to_die_down(self):
        cam = RingingCamera()
        r = wait_until_still(cam.next, 0.0, max_wait_sec=5, threshold_px=1.5)
        self.assertTrue(r["still"])
        # Still means the swing has really decayed (amplitude below a couple of px)...
        self.assertLess(cam.amplitude * math.exp(-(cam.i / cam.fps) / cam.tau), 3.0)
        # ...and not much later than that (within ~0.3 s of frames).
        t_needed = cam.tau * math.log(cam.amplitude / 1.0)
        self.assertLess(cam.i / cam.fps, t_needed + 0.4)
        self.assertEqual(r["timestamp"], float(cam.i))

    def test_a_still_frame_returns_after_a_few_frames(self):
        cam = RingingCamera(amplitude=0.0)
        r = wait_until_still(cam.next, 0.0, max_wait_sec=5)
        self.assertTrue(r["still"])
        self.assertEqual(r["frames"], 3)

    def test_gives_up_after_the_max_wait(self):
        cam = RingingCamera(amplitude=40.0, tau=1e9)  # never settles
        started = time.monotonic()
        r = wait_until_still(cam.next, 0.0, max_wait_sec=0.3)
        self.assertFalse(r["still"])
        self.assertLess(time.monotonic() - started, 1.5)

    def test_a_blank_view_does_not_hold_the_stage(self):
        blank = lambda after: (after + 1, np.full((720, 1280), 90, np.uint8))
        self.assertTrue(wait_until_still(blank, 0.0, max_wait_sec=2)["still"])

    def test_camera_service_skips_when_disabled_or_mock(self):
        with patch.object(settings, "stabilize_enabled", False):
            r = camera_service.wait_until_still(12.5)
        self.assertEqual((r["still"], r["timestamp"], r.get("skipped")), (True, 12.5, True))


if __name__ == "__main__":
    unittest.main()
