"""OCR of part markings: rotation handling, noise cleanup and the /api/inspection/ocr endpoint."""
import unittest

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.config import UPLOADS_DIR
from app.core.ocr import clean_lines, engine_name, read_part_text
from app.main import app


def marked_part():
    img = np.full((400, 600, 3), 40, np.uint8)
    cv2.rectangle(img, (150, 140), (450, 260), (25, 25, 25), -1)
    cv2.putText(img, "LM317T", (175, 215), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (225, 225, 225), 3)
    return img, [140 / 600, 130 / 400, 460 / 600, 270 / 400]


class CleanLinesTests(unittest.TestCase):
    def test_drops_pads_and_fixes_lookalike_letters(self):
        box = (0, 0, 1, 1)
        lines = [("000", 1.0, box), ("o 0", 1.0, box), ("•", 0.9, box), ("ЕPM570", 1.0, box), ("A", 0.4, box), ("J2", 0.9, box)]
        self.assertEqual([t for t, _, _ in clean_lines(lines)], ["EPM570", "J2"])


@unittest.skipUnless(engine_name(), "no OCR engine on this machine")
class ReadPartTextTests(unittest.TestCase):
    def test_reads_marking_in_any_orientation(self):
        img, box = marked_part()
        cases = {
            0: (img, box),
            180: (cv2.rotate(img, cv2.ROTATE_180), [1 - box[2], 1 - box[3], 1 - box[0], 1 - box[1]]),
            90: (cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE), [1 - box[3], box[0], 1 - box[1], box[2]]),
        }
        for angle, (im, b) in cases.items():
            with self.subTest(angle=angle):
                self.assertEqual(read_part_text(im, b)["text"].replace(" ", ""), "LM317T")

    def test_blank_part_reads_nothing(self):
        img = np.full((300, 300, 3), 30, np.uint8)
        self.assertEqual(read_part_text(img, [0.2, 0.2, 0.8, 0.8])["text"], "")


class OcrEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        img, cls.box = marked_part()
        cls.path = UPLOADS_DIR / "test_ocr_part.png"
        cv2.imwrite(str(cls.path), img)

    @classmethod
    def tearDownClass(cls):
        cls.path.unlink(missing_ok=True)

    @unittest.skipUnless(engine_name(), "no OCR engine on this machine")
    def test_reads_boxes_of_a_stored_image(self):
        res = self.client.post("/api/inspection/ocr", json={"image_url": "/api/storage/uploads/test_ocr_part.png", "boxes": [self.box]})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["results"][0]["text"].replace(" ", ""), "LM317T")

    def test_refuses_paths_outside_storage(self):
        for url in ("/api/storage/../config.py", "/api/storage/uploads/../../app/config.py", "/etc/passwd", "/api/storage/settings.json"):
            with self.subTest(url=url):
                res = self.client.post("/api/inspection/ocr", json={"image_url": url, "boxes": [[0.1, 0.1, 0.2, 0.2]]})
                self.assertIn(res.status_code, (400, 404))


if __name__ == "__main__":
    unittest.main()
