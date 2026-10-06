"""Fast previews of stored images: LQIP + original size (/api/media/meta) and resized JPEGs."""
import time
import unittest

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.config import UPLOADS_DIR
from app.core.thumbs import THUMB_DIR, resized, warm
from app.main import app

URL = "/api/storage/uploads/test_media_preview.png"


class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        cls.path = UPLOADS_DIR / "test_media_preview.png"
        img = np.zeros((1500, 3000, 3), np.uint8)
        cv2.rectangle(img, (100, 100), (2900, 1400), (40, 160, 220), -1)
        cv2.imwrite(str(cls.path), img)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.path.unlink(missing_ok=True)

    def test_meta_gives_the_original_size_and_an_inline_placeholder(self):
        res = self.client.get("/api/media/meta", params={"url": URL})
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual((body["width"], body["height"]), (3000, 1500))
        self.assertTrue(body["lqip"].startswith("data:image/jpeg;base64,"))
        self.assertLess(len(body["lqip"]), 3000)  # ~1 KB: fine inline

    def test_thumb_is_a_small_jpeg_and_cached(self):
        res = self.client.get("/api/media/thumb", params={"url": URL, "w": 480})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.headers["content-type"], "image/jpeg")
        img = cv2.imdecode(np.frombuffer(res.content, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(img.shape[:2], (240, 480))
        self.assertIn("max-age", res.headers["cache-control"])
        first = resized(self.path, 480)
        self.assertTrue(first.is_file() and first.is_relative_to(THUMB_DIR))
        self.assertEqual(resized(self.path, 480).stat().st_mtime_ns, first.stat().st_mtime_ns)  # not redone

    def test_a_changed_source_gets_a_new_preview(self):
        a = resized(self.path, 32)
        time.sleep(0.01)
        img = cv2.imread(str(self.path))
        img[:50] = 255
        cv2.imwrite(str(self.path), img)
        self.assertNotEqual(resized(self.path, 32), a)

    def test_rejects_bad_widths_and_paths(self):
        self.assertEqual(self.client.get("/api/media/thumb", params={"url": URL, "w": 777}).status_code, 400)
        self.assertEqual(self.client.get("/api/media/thumb", params={"url": "/etc/passwd"}).status_code, 400)
        self.assertEqual(self.client.get("/api/media/meta", params={"url": "/api/storage/uploads/../../settings.json"}).status_code, 404)

    def test_warm_prepares_the_preview_in_the_background(self):
        warm(self.path)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                p = resized(self.path, 1600)
                if p.is_file():
                    break
            except Exception:
                pass
            time.sleep(0.05)
        self.assertTrue(resized(self.path, 1600).is_file())


if __name__ == "__main__":
    unittest.main()
