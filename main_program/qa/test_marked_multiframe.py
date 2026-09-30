"""Tests for marked points reference snapshot and multi-frame completeness inspection."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.aoi_dialog import AOIDialog
from app.window import DefectDetectionGUI
from app.inspection_logic import (
    box_iou,
    match_frame_detections,
    slot_status,
    evaluate_multiframe_round,
    draw_multiframe_overlay,
)


class Host(DefectDetectionGUI):
    def load_default_assets(self): pass
    def load_settings(self): pass
    def save_settings(self): pass


class FakeCamera:
    def __init__(self):
        self.running = True
        self.timestamp = None
    def snapshot(self):
        return (time.monotonic() if self.timestamp is None else self.timestamp,
                np.zeros((120, 160, 3), dtype=np.uint8))
    def isRunning(self): return self.running
    def requestInterruption(self): self.running = False


class FakeModel:
    def predict(self, source, **kwargs):
        import cv2
        box = SimpleNamespace(cls=[0], conf=[.95], xyxy=[np.array([20., 20., 50., 50.])])
        return [SimpleNamespace(orig_img=cv2.imread(source), boxes=[box], speed={"inference": 1})]


class MarkedPointReferenceAndMultiFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.host = Host()
        self.host.main_program_root = self.tmp.name
        self.host.model = FakeModel()
        self.host.model_names = {0: "IC_CHIP"}
        self.host.current_model_path = "test-model.pt"
        self.dialog = AOIDialog(self.host)
        self.dialog.mode.setCurrentIndex(0)
        self.dialog.camera = FakeCamera()
        self.dialog.settle.setValue(0.1)
        self.dialog.connect_machine()
        self.wait(lambda: self.dialog.machine.ready)
        self.dialog.command("HOME")
        self.wait(lambda: self.dialog.machine.homed)

    def wait(self, predicate, timeout=7000):
        deadline = time.monotonic() + timeout / 1000
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(25)
        self.assertTrue(predicate(), self.dialog.status.text())

    def tearDown(self):
        self.dialog.reject()
        self.wait(lambda: not self.dialog.timer.isActive())
        self.dialog.deleteLater()
        self.host.close()
        self.host.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def test_box_iou_and_bipartite_matching(self):
        # Exact overlap
        b1 = [10, 10, 50, 50]
        b2 = [10, 10, 50, 50]
        self.assertAlmostEqual(box_iou(b1, b2), 1.0)

        # No overlap
        b3 = [100, 100, 150, 150]
        self.assertAlmostEqual(box_iou(b1, b3), 0.0)

        # Matching logic
        expected = [{"id": 1, "label": "IC_CHIP", "box": [10, 10, 50, 50]}]
        detected = [{"label": "IC_CHIP", "box": [12, 11, 52, 49], "conf": 0.92}]
        res = match_frame_detections(expected, detected, min_iou=0.3)
        self.assertEqual(len(res["matches"]), 1)
        self.assertEqual(len(res["wrong_matches"]), 0)
        self.assertEqual(len(res["unmatched_detections"]), 0)

    def test_slot_status_thresholds(self):
        # 10 frames default: >= 8 is confirmed, 4-7 is uncertain, < 4 is suspect (missing in round eval)
        self.assertEqual(slot_status(10, 10), "confirmed")
        self.assertEqual(slot_status(8, 10), "confirmed")
        self.assertEqual(slot_status(7, 10), "uncertain")
        self.assertEqual(slot_status(4, 10), "uncertain")
        self.assertEqual(slot_status(3, 10), "suspect")
        self.assertEqual(slot_status(0, 10), "suspect")

    def test_mark_point_captures_reference_and_detects_components(self):
        # Jog machine to (100, 150)
        self.dialog.machine.position = (100, 150)
        self.dialog.mark_current_point()

        self.assertEqual(len(self.dialog.marked_points), 1)
        self.assertIn(0, self.dialog.marked_references)
        ref_data = self.dialog.marked_references[0]
        self.assertTrue(os.path.exists(ref_data["image_path"]))
        self.assertEqual(len(ref_data["detections"]), 1)
        self.assertEqual(ref_data["detections"][0]["label"], "IC_CHIP")

        # Table state item should indicate reference components
        state_item = self.dialog.table.item(0, 3)
        self.assertIsNotNone(state_item)
        self.assertIn("Ref", state_item.text())

        # Mark a second point
        self.dialog.machine.position = (200, 250)
        self.dialog.mark_current_point()
        self.assertEqual(len(self.dialog.marked_points), 2)
        self.assertIn(1, self.dialog.marked_references)

        # Remove last point
        self.dialog.remove_last_marked_point()
        self.assertEqual(len(self.dialog.marked_points), 1)
        self.assertNotIn(1, self.dialog.marked_references)
        self.assertIn(0, self.dialog.marked_references)

        # Clear then mark multiple points to test individual deletion
        self.dialog.clear_marked_points()
        self.dialog.machine.position = (100, 100)
        self.dialog.mark_current_point()
        self.dialog.machine.position = (200, 200)
        self.dialog.mark_current_point()
        self.dialog.machine.position = (300, 300)
        self.dialog.mark_current_point()
        self.assertEqual(len(self.dialog.marked_points), 3)

        # Delete middle point (index 1) via delete_selected_point
        self.dialog.delete_selected_point(1)
        self.assertEqual(len(self.dialog.marked_points), 2)
        self.assertEqual(self.dialog.marked_points[0][:2], (100, 100))
        self.assertEqual(self.dialog.marked_points[1][:2], (300, 300))
        self.assertEqual(self.dialog.marked_references[0]["pos"], (100, 100))
        self.assertEqual(self.dialog.marked_references[1]["pos"], (300, 300))

        # Delete first point (index 0) via table selection
        self.dialog.table.selectRow(0)
        self.dialog.delete_selected_point()
        self.assertEqual(len(self.dialog.marked_points), 1)
        self.assertEqual(self.dialog.marked_points[0][:2], (300, 300))
        self.assertEqual(self.dialog.marked_references[0]["pos"], (300, 300))

        # Clear points
        self.dialog.clear_marked_points()
        self.assertEqual(len(self.dialog.marked_points), 0)
        self.assertEqual(len(self.dialog.marked_references), 0)

    def test_replay_marked_scan_runs_multiframe_completeness(self):
        # Set up 1 marked point with reference snapshot
        self.dialog.machine.position = (100, 100)
        self.dialog.mark_current_point()
        self.assertEqual(len(self.dialog.marked_points), 1)

        # Configure multi-frame: 3 frames for quick test
        self.dialog.check_multiframe.setChecked(True)
        self.dialog.multiframe_spin.setValue(3)
        self.dialog.pass_ratio_spin.setValue(80)

        with patch("app.mixins.inspection_mixin.select_device", return_value=SimpleNamespace(device="cpu", label="CPU", detail="")):
            self.dialog.start_replay_marked_scan()
            self.wait(lambda: not self.dialog.active)

        self.assertEqual(self.dialog.report["status"], "complete")
        results = self.dialog.report["results"]
        self.assertEqual(len(results), 1)

        row = results[0]
        self.assertIn("multiframe", row)
        mf = row["multiframe"]
        self.assertEqual(mf["target_frames"], 3)
        self.assertEqual(mf["frames_inspected"], 3)
        self.assertEqual(mf["verdict"], "PASS")

        # Check annotated image has been generated
        ann_path = self.dialog.run_folder / row["annotated_image"]
        self.assertTrue(ann_path.is_file())

    def test_model_selection_ui_and_change(self):
        # 1. Check model controls are initialized
        self.assertTrue(hasattr(self.dialog, "model_combo"))
        self.assertTrue(hasattr(self.dialog, "btn_browse_model"))
        self.assertTrue(hasattr(self.dialog, "btn_refresh_models"))
        self.assertTrue(hasattr(self.dialog, "aoi_device_combo"))
        self.assertTrue(hasattr(self.dialog, "aoi_conf_spin"))
        self.assertTrue(hasattr(self.dialog, "lbl_model_badge"))

        # 2. Check model badge displays active model
        badge_text = self.dialog.lbl_model_badge.text()
        self.assertIn("test-model.pt", badge_text)

        # 3. Test changing model
        dummy_model_file = Path(self.tmp.name) / "new_model.pt"
        dummy_model_file.write_text("dummy")

        with patch.object(self.host, "load_model") as mock_load:
            def fake_load(path):
                self.host.current_model_path = path
                self.host.model_names = {0: "resistor", 1: "capacitor"}
            mock_load.side_effect = fake_load

            ok = self.dialog.change_model(str(dummy_model_file))
            self.assertTrue(ok)
            mock_load.assert_called_once_with(str(dummy_model_file))
            self.assertIn("new_model.pt", self.dialog.lbl_model_badge.text())
            self.assertIn("2 classes", self.dialog.lbl_model_badge.text())

        # 4. Test conf and processor sync
        self.dialog.aoi_conf_spin.setValue(45)
        self.assertEqual(self.host.conf_slider.value(), 45)

        self.dialog.aoi_device_combo.setCurrentIndex(self.dialog.aoi_device_combo.findData("cpu"))
        self.assertEqual(self.host.device_combo.currentData(), "cpu")

        # 5. Test detection resolution (imgsz) selection
        self.assertTrue(hasattr(self.dialog, "aoi_imgsz_combo"))
        self.assertEqual(self.dialog.current_imgsz(), 640)

        # Switch to 1280
        idx_1280 = self.dialog.aoi_imgsz_combo.findData(1280)
        self.assertGreaterEqual(idx_1280, 0)
        self.dialog.aoi_imgsz_combo.setCurrentIndex(idx_1280)
        self.assertEqual(self.dialog.current_imgsz(), 1280)
        self.assertIn("1280px", self.dialog.lbl_imgsz_hint.text())

        # Switch to 1920
        idx_1920 = self.dialog.aoi_imgsz_combo.findData(1920)
        self.assertGreaterEqual(idx_1920, 0)
        self.dialog.aoi_imgsz_combo.setCurrentIndex(idx_1920)
        self.assertEqual(self.dialog.current_imgsz(), 1920)
        self.assertIn("1920px", self.dialog.lbl_imgsz_hint.text())

        # 6. Test browsing folder of models
        dummy_folder = Path(self.tmp.name) / "test_run_folder"
        dummy_folder.mkdir(parents=True, exist_ok=True)
        (dummy_folder / "last.pt").write_text("last")
        (dummy_folder / "best.pt").write_text("best")

        with patch("PyQt6.QtWidgets.QFileDialog.getExistingDirectory", return_value=str(dummy_folder)), \
             patch.object(self.dialog, "change_model", return_value=True) as mock_change:
            self.dialog.browse_model_folder()
            mock_change.assert_called()
            self.assertEqual(self.dialog._custom_model_dir, str(dummy_folder.resolve()))
            self.assertIn("เลือกโฟลเดอร์", self.dialog.status.text())

        # Test smart start dir
        start_dir = self.dialog._get_model_start_dir()
        self.assertEqual(start_dir, str(dummy_folder.resolve()))

        # Test browse single model file
        test_file = dummy_folder / "best.pt"
        with patch("PyQt6.QtWidgets.QFileDialog.getOpenFileName", return_value=(str(test_file), "PyTorch Model (*.pt)")), \
             patch.object(self.dialog, "change_model", return_value=True) as mock_change_file:
            self.dialog.browse_model()
            mock_change_file.assert_called_with(str(test_file.resolve()))

    def test_live_and_output_match_selected_resolution(self):
        # 1. Default imgsz is 640 and aspect mode is 1:1
        self.assertEqual(self.dialog.current_imgsz(), 640)
        self.assertEqual(self.dialog.aspect_mode, "1:1")
        self.assertIn("640 × 640 px", self.dialog.camera_info.text())
        self.assertIn("640 × 640 px", self.dialog.captured_info.text())

        # Test simulated 4K sensor frame (2160, 3840, 3)
        raw_sensor_frame = np.zeros((2160, 3840, 3), dtype=np.uint8)
        processed = self.dialog._process_frame_for_active_resolution(raw_sensor_frame)
        self.assertEqual(processed.shape, (640, 640, 3))

        # Test live preview frame processing
        self.dialog.show_frame(raw_sensor_frame)
        self.assertIsNotNone(self.dialog._last_live_frame)
        self.assertEqual(self.dialog._last_live_frame.shape, (640, 640, 3))

        # 2. Switch imgsz to 1280
        idx_1280 = self.dialog.aoi_imgsz_combo.findData(1280)
        self.dialog.aoi_imgsz_combo.setCurrentIndex(idx_1280)
        self.assertEqual(self.dialog.current_imgsz(), 1280)
        processed_1280 = self.dialog._process_frame_for_active_resolution(raw_sensor_frame)
        self.assertEqual(processed_1280.shape, (1280, 1280, 3))
        self.assertIn("1280 × 1280 px", self.dialog.captured_info.text())

        # 3. Test snap_and_inspect output matches selected resolution
        self.dialog.camera = FakeCamera()
        self.dialog.snap_and_inspect()
        self.assertIsNotNone(self.dialog._last_captured_frame)
        self.assertEqual(self.dialog._last_captured_frame.shape, (1280, 1280, 3))
        self.assertIn("Output: 1280 × 1280 px", self.dialog.captured_info.text())

        # 4. Test aspect ratio mode switching
        self.dialog.aspect_combo.setCurrentIndex(self.dialog.aspect_combo.findData("16:9"))
        self.assertEqual(self.dialog.aspect_mode, "16:9")
        proc_16_9 = self.dialog._process_frame_for_active_resolution(raw_sensor_frame)
        # 1280 width with 16:9 aspect ratio -> 1280x720
        self.assertEqual(proc_16_9.shape, (720, 1280, 3))

        # 5. Switch back to 1:1 and 640
        self.dialog.aspect_combo.setCurrentIndex(self.dialog.aspect_combo.findData("1:1"))
        self.dialog.aoi_imgsz_combo.setCurrentIndex(self.dialog.aoi_imgsz_combo.findData(640))
        self.assertEqual(self.dialog.current_imgsz(), 640)
        self.dialog.mark_current_point()
        ref_data = self.dialog.marked_references[0]
        self.assertEqual(ref_data["image"].shape, (640, 640, 3))


if __name__ == "__main__":
    unittest.main()

