"""Resistor colour bands: decoding, reading synthetic parts, and the /api/inspection/resistor endpoint."""
import unittest

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.config import UPLOADS_DIR
from app.core.resistor import CAMERA_LAB, decode, read_resistor
from app.main import app


def _bgr(name):
    """A band colour as the station camera sees it."""
    L, a, b = CAMERA_LAB[name][0]
    return [int(v) for v in cv2.cvtColor(np.uint8([[[L, a + 128, b + 128]]]), cv2.COLOR_LAB2BGR)[0, 0]]


def resistor(bands, vertical=False, gaps=None, noise=3.0, seed=0):
    """A beige resistor on a red board with the given bands (left to right), and its box."""
    img = np.zeros((300, 600, 3), np.uint8)
    img[:] = (40, 40, 170)  # board
    cv2.line(img, (60, 150), (540, 150), (170, 170, 170), 10)  # leads
    cv2.rectangle(img, (150, 110), (450, 190), (150, 190, 215), -1)  # body (BGR beige)
    x = 185
    for i, name in enumerate(bands):
        cv2.rectangle(img, (x, 110), (x + 22, 190), _bgr(name), -1)
        x += 22 + (gaps[i] if gaps and i < len(gaps) else 18)
    rng = np.random.default_rng(seed)
    img = np.clip(img.astype(np.float32) + rng.normal(0, noise, img.shape), 0, 255).astype(np.uint8)
    img = cv2.GaussianBlur(img, (3, 3), 0)
    box = [140 / 600, 100 / 300, 460 / 600, 200 / 300]
    if vertical:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        box = [1 - box[3], box[0], 1 - box[1], box[2]]
    return img, box


class DecodeTests(unittest.TestCase):
    def test_four_and_five_bands(self):
        self.assertEqual(decode(["brown", "black", "red", "gold"])["text"], "1 kΩ ±5%")
        self.assertEqual(decode(["yellow", "violet", "orange", "gold"])["ohms"], 47000)
        self.assertEqual(decode(["brown", "black", "black", "brown", "brown"])["text"], "1 kΩ ±1%")
        self.assertEqual(decode(["orange", "orange", "brown", "gold"])["e_series"], "E12")
        self.assertEqual(decode(["brown", "black", "red"])["text"], "1 kΩ")  # tolerance band unseen

    def test_invalid_codes(self):
        self.assertIsNone(decode(["black", "brown", "red", "gold"]))  # leading zero
        self.assertIsNone(decode(["gold", "black", "red", "gold"]))
        self.assertIsNone(decode(["brown", "black", "red", "orange"]))  # orange is no tolerance
        self.assertIsNone(decode(["red", "red"]))


class ReadResistorTests(unittest.TestCase):
    def test_reads_values_in_both_directions_and_orientations(self):
        cases = [
            (["brown", "black", "red", "gold"], "1 kΩ ±5%"),
            (["brown", "black", "orange", "gold"], "10 kΩ ±5%"),
            (["orange", "orange", "brown", "gold"], "330 Ω ±5%"),
        ]
        for bands, text in cases:
            for flip in (False, True):
                for vertical in (False, True):
                    with self.subTest(bands=bands, flip=flip, vertical=vertical):
                        seq = bands[::-1] if flip else bands
                        gaps = [18, 18, 40] if not flip else [40, 18, 18]  # tolerance band set apart
                        img, box = resistor(seq, vertical=vertical, gaps=gaps)
                        r = read_resistor(img, box)
                        self.assertEqual(r["text"], text, r)
                        self.assertEqual([b["color"] for b in r["bands"]], bands)
                        self.assertGreater(r["confidence"], 0.5)

    def test_shadow_rings_inside_the_body_are_not_bands(self):
        img, box = resistor(["brown", "black", "red", "gold"], gaps=[18, 18, 40])
        # A faint darker ring of the bulging body between the black and the red band.
        cv2.rectangle(img, (265, 110), (269, 190), (130, 165, 190), -1)
        self.assertEqual(read_resistor(img, box)["text"], "1 kΩ ±5%")

    def test_plain_body_reads_nothing(self):
        img, box = resistor([])
        r = read_resistor(img, box)
        self.assertEqual(r["text"], "")
        self.assertTrue(r["reason"])


class ResistorEndpointTests(unittest.TestCase):
    def test_reads_boxes_of_a_stored_image(self):
        img, box = resistor(["brown", "black", "red", "gold"], gaps=[18, 18, 40])
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        path = UPLOADS_DIR / "test_resistor_endpoint.png"
        cv2.imwrite(str(path), img)
        try:
            client = TestClient(app)
            res = client.post("/api/inspection/resistor", json={"image_url": "/api/storage/uploads/test_resistor_endpoint.png", "boxes": [box]})
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual(res.json()["results"][0]["text"], "1 kΩ ±5%")
            bad = client.post("/api/inspection/resistor", json={"image_url": "/etc/passwd", "boxes": [box]})
            self.assertEqual(bad.status_code, 400)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
