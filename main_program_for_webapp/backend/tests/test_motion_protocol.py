"""Tests for protocol v2 client and raster scanning."""
import unittest
from app.core.motion_protocol import MotionClient, SimulatedTransport, raster_points


class Clock:
    def __init__(self):
        self.time = 0.0

    def __call__(self) -> float:
        return self.time


class MotionProtocolTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.transport = SimulatedTransport(self.clock)
        self.client = MotionClient(self.transport, self.clock)
        self.client.tick()

    def advance(self, dt=0.25):
        self.clock.time += dt
        self.client.tick()

    def home(self):
        self.client.command("HOME")
        self.advance()

    def test_startup_handshake_and_homing(self):
        self.assertTrue(self.client.ready)
        self.assertFalse(self.client.homed)
        self.home()
        self.assertTrue(self.client.homed)
        self.assertEqual(self.client.position, (0, 0))

    def test_move_enforces_limits(self):
        self.home()
        # Out of bounds movement
        with self.assertRaises(ValueError):
            self.client.command("MOVE", 30000, 0)
        with self.assertRaises(ValueError):
            self.client.command("MOVE", -5, 0)

        # Valid movement
        self.client.command("MOVE", 1000, 2000)
        self.advance()
        self.assertEqual(self.client.position, (1000, 2000))

    def test_stop_preempts_motion(self):
        self.home()
        self.client.command("MOVE", 1000, 2000)
        self.client.command("STOP")
        self.advance()
        self.assertIsNone(self.client.pending)

    def test_raster_planning(self):
        # 2x2 grid, 1mm pitch, 512 steps/mm
        pts = raster_points(
            x=0, y=0, columns=2, rows=2, pitch_x=1.0, pitch_y=1.0,
            steps_per_mm=512, limits=(10000, 10000)
        )
        # Serpentine pattern: (0,0) -> (512,0) -> (512,512) -> (0,512)
        expected = [(0, 0), (512, 0), (512, 512), (0, 512)]
        self.assertEqual(pts, expected)


if __name__ == "__main__":
    unittest.main()
