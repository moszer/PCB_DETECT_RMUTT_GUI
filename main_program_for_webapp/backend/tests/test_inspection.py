"""Tests for inspection evaluation, status mapping, and tolerance calculations."""
import unittest
from app.core.inspection import evaluate_inspection
from app.core.schemas import Detection, ReferencePoint


class InspectionEvaluationTests(unittest.TestCase):
    def test_no_reference_yields_review(self):
        """Verifies that an inspection without references returns REVIEW, not FAIL."""
        dets = [
            Detection(id=1, label="resistor", conf=0.9, box=[10, 10, 20, 20], cx=15, cy=15),
            Detection(id=2, label="capacitor", conf=0.85, box=[30, 30, 40, 40], cx=35, cy=35)
        ]
        verdict, reason, summary, ref_eval, evaluated_dets = evaluate_inspection(
            reference_points=None,
            detections=dets,
            match_dist=50.0,
            fail_on_extra=True
        )
        self.assertEqual(verdict, "REVIEW")
        self.assertIn("No reference profile loaded", reason)
        self.assertEqual(summary.total_refs, 0)
        self.assertEqual(summary.extra, 2)
        self.assertEqual(len(ref_eval), 0)

    def test_all_components_match_yields_pass(self):
        refs = [
            ReferencePoint(x=15, y=15, label="resistor"),
            ReferencePoint(x=35, y=35, label="capacitor")
        ]
        dets = [
            Detection(id=1, label="resistor", conf=0.92, box=[10, 10, 20, 20], cx=15.2, cy=14.8),
            Detection(id=2, label="capacitor", conf=0.88, box=[30, 30, 40, 40], cx=34.9, cy=35.1)
        ]
        verdict, reason, summary, ref_eval, evaluated_dets = evaluate_inspection(
            reference_points=refs,
            detections=dets,
            match_dist=10.0,
            fail_on_extra=True
        )
        self.assertEqual(verdict, "PASS")
        self.assertEqual(summary.ok, 2)
        self.assertEqual(summary.missing, 0)
        self.assertEqual(summary.wrong, 0)
        self.assertEqual(summary.extra, 0)

    def test_missing_component_yields_fail(self):
        refs = [
            ReferencePoint(x=15, y=15, label="resistor"),
            ReferencePoint(x=100, y=100, label="chip")
        ]
        dets = [
            Detection(id=1, label="resistor", conf=0.9, box=[10, 10, 20, 20], cx=15, cy=15)
        ]
        verdict, reason, summary, ref_eval, evaluated_dets = evaluate_inspection(
            reference_points=refs,
            detections=dets,
            match_dist=20.0
        )
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(summary.ok, 1)
        self.assertEqual(summary.missing, 1)
        self.assertEqual(summary.wrong, 0)

    def test_wrong_component_yields_fail(self):
        refs = [
            ReferencePoint(x=15, y=15, label="resistor")
        ]
        dets = [
            Detection(id=1, label="capacitor", conf=0.9, box=[10, 10, 20, 20], cx=15, cy=15)
        ]
        verdict, reason, summary, ref_eval, evaluated_dets = evaluate_inspection(
            reference_points=refs,
            detections=dets,
            match_dist=20.0
        )
        self.assertEqual(verdict, "FAIL")
        self.assertEqual(summary.wrong, 1)
        self.assertEqual(ref_eval[0].status, "WRONG")

    def test_extra_component_yields_fail_when_configured(self):
        refs = [
            ReferencePoint(x=15, y=15, label="resistor")
        ]
        dets = [
            Detection(id=1, label="resistor", conf=0.9, box=[10, 10, 20, 20], cx=15, cy=15),
            Detection(id=2, label="diode", conf=0.7, box=[60, 60, 70, 70], cx=65, cy=65)
        ]
        # With fail_on_extra = True -> FAIL
        verdict1, _, summary1, _, _ = evaluate_inspection(refs, dets, match_dist=20.0, fail_on_extra=True)
        self.assertEqual(verdict1, "FAIL")
        self.assertEqual(summary1.extra, 1)

        # With fail_on_extra = False -> PASS
        verdict2, _, summary2, _, _ = evaluate_inspection(refs, dets, match_dist=20.0, fail_on_extra=False)
        self.assertEqual(verdict2, "PASS")
        self.assertEqual(summary2.extra, 1)


class MultiFrameInspectionTests(unittest.TestCase):
    def test_box_iou(self):
        from app.core.inspection import box_iou
        b1 = [0, 0, 10, 10]
        b2 = [0, 0, 10, 10]
        self.assertAlmostEqual(box_iou(b1, b2), 1.0)

        b3 = [5, 5, 15, 15]
        # Inter: 5x5=25, Union: 100+100-25=175 -> 25/175 = 1/7 ~= 0.1428
        self.assertAlmostEqual(box_iou(b1, b3), 25.0 / 175.0, places=4)

        b4 = [20, 20, 30, 30]
        self.assertEqual(box_iou(b1, b4), 0.0)

    def test_slot_status(self):
        from app.core.inspection import slot_status
        # target=10, pass_th=8, uncertain=4
        self.assertEqual(slot_status(8, 10), "confirmed")
        self.assertEqual(slot_status(10, 10), "confirmed")
        self.assertEqual(slot_status(7, 10), "uncertain")
        self.assertEqual(slot_status(4, 10), "uncertain")
        self.assertEqual(slot_status(3, 10), "suspect")
        self.assertEqual(slot_status(0, 10), "suspect")

    def test_evaluate_multiframe_round_pass(self):
        from app.core.inspection import evaluate_multiframe_round
        expected = [
            {"id": "P1", "label": "chip", "box": [10, 10, 50, 50]},
            {"id": "P2", "label": "resistor", "box": [60, 60, 80, 80]},
        ]
        # 10 frames where both components are always detected
        frames = []
        for _ in range(10):
            frames.append([
                {"label": "chip", "box": [11, 10, 50, 49]},
                {"label": "resistor", "box": [60, 61, 79, 80]},
            ])

        res = evaluate_multiframe_round(expected, frames, target_frames=10, pass_threshold=8)
        self.assertEqual(res["verdict"], "PASS")
        self.assertEqual(res["confirmed_count"], 2)
        self.assertEqual(res["missing_count"], 0)

    def test_slots_are_drawn_where_the_shifted_frame_put_them(self):
        """A stage shift moves every part; the saved frame must show the boxes moved with it."""
        from app.core.inspection import evaluate_multiframe_round
        expected = [
            {"id": "P1", "label": "chip", "box": [0.10, 0.10, 0.20, 0.20]},
            {"id": "P2", "label": "resistor", "box": [0.40, 0.40, 0.45, 0.43]},
            {"id": "P3", "label": "capacitor", "box": [0.60, 0.20, 0.66, 0.26]},
        ]
        dx, dy = 0.0, 0.03  # small parts: IoU without alignment would fail
        frames = [[{"label": e["label"], "box": [e["box"][0] + dx, e["box"][1] + dy, e["box"][2] + dx, e["box"][3] + dy]}
                   for e in expected] for _ in range(5)]
        res = evaluate_multiframe_round(expected, frames, target_frames=5, pass_threshold=4)
        self.assertEqual(res["verdict"], "PASS")
        self.assertEqual(res["frame_offset"], [0.0, 0.03])
        for c, e in zip(res["components"], expected):
            self.assertEqual(c["expected"]["box"], e["box"])  # the reference itself is unchanged
            for got, want in zip(c["box_in_frame"], [e["box"][0], e["box"][1] + dy, e["box"][2], e["box"][3] + dy]):
                self.assertAlmostEqual(got, want, places=5)

    def test_evaluate_multiframe_round_missing(self):
        from app.core.inspection import evaluate_multiframe_round
        expected = [
            {"id": "P1", "label": "chip", "box": [10, 10, 50, 50]},
            {"id": "P2", "label": "resistor", "box": [60, 60, 80, 80]},
        ]
        # Resistor only appears in 2 frames out of 10
        frames = []
        for i in range(10):
            frame = [{"label": "chip", "box": [10, 10, 50, 50]}]
            if i < 2:
                frame.append({"label": "resistor", "box": [60, 60, 80, 80]})
            frames.append(frame)

        res = evaluate_multiframe_round(expected, frames, target_frames=10, pass_threshold=8)
        self.assertEqual(res["verdict"], "FAIL")
        self.assertEqual(res["confirmed_count"], 1)
        self.assertEqual(res["missing_count"], 1)

    def test_draw_multiframe_annotated_image(self):
        import numpy as np
        from app.core.inspection import draw_multiframe_annotated_image
        img = np.zeros((200, 200, 3), dtype=np.uint8)
        component_eval = [
            {"slot_id": "P1", "name": "chip", "bbox": [0.1, 0.1, 0.4, 0.4], "status": "confirmed", "hit_ratio": 1.0, "message": "OK"},
            {"slot_id": "P2", "name": "resistor", "bbox": [0.5, 0.5, 0.8, 0.8], "status": "missing", "hit_ratio": 0.0, "message": "Missing"}
        ]
        out_img = draw_multiframe_annotated_image(img, component_eval)
        self.assertEqual(out_img.shape, img.shape)


if __name__ == "__main__":
    unittest.main()
