"""Live MJPEG previews are capped per client so leaked browser streams can't exhaust connections."""
import asyncio
import unittest

from app.services.camera_service import CameraService


class StreamLimitTests(unittest.TestCase):
    def test_new_stream_ends_the_oldest_of_the_same_client(self):
        cam = CameraService()
        first = cam._register_stream("10.0.0.5")
        second = cam._register_stream("10.0.0.5")
        other = cam._register_stream("10.0.0.9")
        self.assertFalse(first["stop"])
        third = cam._register_stream("10.0.0.5")
        self.assertTrue(first["stop"])
        self.assertFalse(second["stop"] or third["stop"] or other["stop"])
        self.assertEqual(cam.stream_count, 3)

    def test_generator_stops_and_unregisters(self):
        cam = CameraService()
        cam._running = True
        cam._latest_jpeg = b"jpeg"

        async def run():
            gens = [cam.generate_mjpeg_stream(max_fps=200, client="c") for _ in range(3)]
            for g in gens:
                self.assertIn(b"jpeg", await anext(g))
            # The first stream was superseded by the third: it ends on its next step.
            with self.assertRaises(StopAsyncIteration):
                await anext(gens[0])
            self.assertEqual(cam.stream_count, 2)
            for g in gens[1:]:
                await g.aclose()
            self.assertEqual(cam.stream_count, 0)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
