"""OCR of part markings: rotation handling, noise cleanup and the /api/inspection/ocr endpoint."""
import unittest

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.config import UPLOADS_DIR
from unittest.mock import patch

import app.core.ocr as ocr
from app.core.ocr import binarize_for_tesseract, clean_lines, engine_name, prepare_crop, read_part_text
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


    def test_drops_what_pins_and_textures_read_as(self):
        """Readings seen on the Jetson for a QFP's pin rows and body texture."""
        box = (0, 0, 1, 1)
        junk = ["| eneteertatetenetenente", "SS! oe", "— =z", "== zm =", "a WD ——", "— eels: =",
                "dedaaseancabsavatieadcaeduaisaicicee."]
        keep = ["EPM570T144C5", "N AACSM0537A", "100uF 35V", "LM317-T", "+5V"]
        out = [t for t, _, _ in clean_lines([(t, 0.9, box) for t in junk + keep])]
        self.assertEqual(out, keep)

    def test_score_prefers_clean_codes_over_long_noise(self):
        box = (0, 0, 1, 1)
        noise = [("== zm == om == ALD @ <a", 0.6, box)] * 4
        self.assertGreater(ocr._score([("EPM570T144C5", 0.88, box)]), ocr._score(noise))


class TesseractPathTests(unittest.TestCase):
    def test_light_print_on_dark_body_becomes_dark_on_white(self):
        img, box = marked_part()
        bw = binarize_for_tesseract(prepare_crop(img, box))
        self.assertGreater(bw.mean(), 127)
        self.assertEqual(set(np.unique(bw)) <= {0, 255}, True)

    def test_big_parts_are_inset_to_leave_out_the_pins(self):
        img = np.zeros((1000, 1000, 3), np.uint8)
        big = prepare_crop(img, [0.2, 0.2, 0.6, 0.6])  # 400 px: inset
        small = prepare_crop(img, [0.2, 0.2, 0.25, 0.25])  # 50 px: margin (then upscaled)
        self.assertLess(big.shape[0], 400)
        self.assertGreater(small.shape[0], 50)

    @unittest.skipUnless(ocr._TESSERACT, "tesseract not installed")
    def test_tesseract_reads_the_marking(self):
        img, box = marked_part()
        with patch.object(ocr, "_HAS_VISION", False):
            self.assertEqual(read_part_text(img, box)["text"].replace(" ", ""), "LM317T")


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
