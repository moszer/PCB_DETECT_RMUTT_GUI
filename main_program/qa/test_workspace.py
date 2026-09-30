"""Offscreen interaction checks. Run with the project's venv:
QT_QPA_PLATFORM=offscreen venv/bin/python -m unittest discover -s qa -v
"""
import os
import json
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import tempfile
import unittest
from unittest.mock import patch
from threading import Event
from pathlib import Path

import cv2
import numpy as np
from PyQt6.QtCore import QPoint
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.window import DefectDetectionGUI
from app.mixins.settings_mixin import SettingsMixin
from app.update_dialog import UpdateDialog
from app.updater import UpdateInfo, UpdateError


class TestWindow(DefectDetectionGUI):
    def load_default_assets(self): pass
    def load_settings(self): pass
    def save_settings(self): pass


class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = TestWindow()
        self.window.show()
        QTest.qWait(400)
        self.temp = tempfile.TemporaryDirectory()
        self.source = str(Path(self.temp.name) / ("pcb_" + "sample_" * 16 + ".png"))
        cv2.imwrite(self.source, np.full((400, 600, 3), (50, 90, 35), dtype=np.uint8))

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_empty_state_actions_and_panel_toggles(self):
        w = self.window
        for button in (w.btn_reinspect, w.btn_save_annotated, w.btn_export_history,
                       w.btn_zoom_in, w.btn_prev_image, w.btn_camera_capture):
            self.assertFalse(button.isEnabled())
        self.assertTrue(w.btn_select.isEnabled())
        w.btn_toggle_history.click()
        self.assertTrue(w.history_panel.isVisible())
        self.assertTrue(w.history_empty.isVisible())
        self.assertFalse(w.image_scroll.isVisible())
        w.btn_toggle_left.click()
        self.assertFalse(w.left_scroll.isVisible())
        w.btn_toggle_history.click()
        self.assertFalse(w.history_panel.isVisible())

    def test_update_check_stays_responsive_and_blocks_early_close(self):
        w = self.window
        dialog = UpdateDialog(w)
        w._update_dialog = dialog
        gate = Event()
        info = UpdateInfo("a" * 40, "b" * 40, "v1.0.0", "v1.0.1", "Fix camera", ("app.py",))
        def check():
            gate.wait(2)
            return info
        with patch.object(dialog.updater, "check", side_effect=check):
            dialog.show()
            dialog.check()
            QTest.qWait(20)
            self.assertTrue(dialog._busy)
            dialog.reject()
            self.assertTrue(dialog.isVisible())
            w.close()
            self.assertTrue(w.isVisible())
            gate.set()
            for _ in range(100):
                if not dialog._busy:
                    break
                QTest.qWait(10)
            self.assertFalse(dialog._busy)
            self.assertTrue(dialog.install_button.isEnabled())
            self.assertIn("v1.0.1", dialog.versions.text())
            w._camera_worker = object()
            dialog.install()
            self.assertIn("Stop the camera", dialog.status.text())
            w._camera_worker = None
            with patch.object(dialog.updater, "install", return_value="") as install:
                dialog.install()
                for _ in range(100):
                    if not dialog._busy:
                        break
                    QTest.qWait(10)
                install.assert_called_once_with(info)
            self.assertTrue(dialog.installed)
            self.assertFalse(dialog.check_button.isEnabled())
            self.assertIn("restart required", dialog.versions.text())
            dialog.accept()
            self.assertFalse(w.isVisible())
        w._update_dialog = None
        dialog.deleteLater()

    def test_current_version_with_local_edits_does_not_report_update_failure(self):
        dialog = UpdateDialog(self.window)
        info = UpdateInfo("a" * 40, "a" * 40, "v1.0.0", "v1.0.0", "", (),
                          "Local tracked files have changes.")
        dialog.checked(info)
        dialog.finished_work()
        self.assertIn("up to date", dialog.status.text())
        self.assertIn("Before a future update", dialog.details.toPlainText())
        self.assertFalse(dialog.install_button.isEnabled())
        pending = UpdateInfo("a" * 40, "b" * 40, "v1.0.0", "v1.0.1", "Update", (), info.blocker)
        dialog.checked(pending)
        dialog.finished_work()
        self.assertIn("unavailable", dialog.status.text())
        self.assertFalse(dialog.install_button.isEnabled())
        dialog.deleteLater()

    def test_update_failure_allows_retry(self):
        dialog = UpdateDialog(self.window)
        with patch.object(dialog.updater, "check", side_effect=UpdateError("Network unavailable")):
            dialog.check()
            for _ in range(100):
                if not dialog._busy:
                    break
                QTest.qWait(10)
            self.assertTrue(dialog.check_button.isEnabled())
            self.assertFalse(dialog.install_button.isEnabled())
            self.assertIn("Network unavailable", dialog.details.toPlainText())
        dialog.deleteLater()

    def test_view_only_image_and_zoom(self):
        w = self.window
        w.open_image_path(self.source)
        QTest.qWait(100)
        self.assertEqual(w.verdict_label.text(), "VIEW ONLY")
        self.assertTrue(w.btn_zoom_in.isEnabled())
        self.assertFalse(w.btn_reinspect.isEnabled())
        self.assertFalse(w.btn_save_annotated.isEnabled())
        w.btn_zoom_in.click()
        self.assertEqual(w.zoom_factor, 1.25)
        w.btn_zoom_fit.click()
        self.assertEqual(w.zoom_factor, 1.0)
        self.assertIn("600 × 400", w.canvas_hint.text())

    def test_processor_preference_roundtrip_and_busy_state(self):
        w = self.window
        path = Path(self.temp.name) / "settings.json"
        w._settings_path = lambda: str(path)
        self.assertEqual(w.device_combo.currentData(), "auto")
        for preference in ("cuda:0", "mps"):
            with self.subTest(preference=preference):
                self.assertGreaterEqual(w.device_combo.findData(preference), 0)
                w.device_combo.setCurrentIndex(w.device_combo.findData(preference))
                SettingsMixin.save_settings(w)
                w.device_combo.setCurrentIndex(w.device_combo.findData("cpu"))
                SettingsMixin.load_settings(w)
                self.assertEqual(w.device_combo.currentData(), preference)
        w._inference_running = True
        w._update_action_buttons()
        self.assertFalse(w.device_combo.isEnabled())
        self.assertFalse(w.btn_load_model.isEnabled())
        w._inference_running = False
        w._update_action_buttons()
        self.assertTrue(w.device_combo.isEnabled())
        w._on_device_selected("NVIDIA Orin (cuda:0)", "")
        self.assertIn("NVIDIA Orin", w.device_status.text())
        w._on_device_selected("Apple GPU (MPS)", "")
        self.assertIn("Apple GPU", w.device_status.text())

    def test_inspection_result_and_component_selection(self):
        w = self.window
        w.current_image_path = self.source
        w.model = object()
        w.check_auto_log.setChecked(False)
        w.reference_points = [{"x": 50, "y": 50, "label": "resistor"}]
        dets = [{"x": 50, "y": 50, "label": "resistor", "conf": .96, "box": (30, 30, 70, 70)}]
        w._on_inference_done(dets, cv2.imread(self.source), dict(preprocess=1, inference=2, postprocess=1), self.source, True)
        QTest.qWait(100)
        self.assertEqual(w.verdict_label.text(), "PASS")
        self.assertEqual(w.pass_count, 1)
        self.assertTrue(w.btn_save_annotated.isEnabled())
        self.assertTrue(w.btn_export_history.isEnabled())
        w.select_detection_at(50, 50)
        self.assertTrue(w.right_panel.isVisible())
        self.assertEqual(w.detail_class_value.text(), "resistor")
        w.close_right_panel()
        self.assertFalse(w.right_panel.isVisible())
        # A new image must not keep the previous board's result or export.
        w.model = None
        w.open_image_path(self.source)
        self.assertEqual(w.verdict_label.text(), "VIEW ONLY")
        self.assertFalse(w.btn_save_annotated.isEnabled())

    def test_minimum_layout_and_long_names_in_both_themes(self):
        w = self.window
        w.resize(1100, 760)
        w.open_image_path(self.source)
        detection = {"x": 50, "y": 50, "label": "resistor", "conf": .96, "box": (30, 30, 70, 70)}
        w.update_right_panel(detection)
        for theme in ("light", "dark"):
            w._current_theme = theme
            w.apply_styles()
            QTest.qWait(150)
            self.assertEqual(w.width(), 1100)
            # The verdict is outside the canvas, including at minimum width.
            result_top = w.verdict_card.mapTo(w, QPoint(0, 0)).y()
            canvas_bottom = w.image_scroll.mapTo(w, QPoint(0, w.image_scroll.height())).y()
            self.assertGreater(result_top, canvas_bottom)
            for widget in (w.btn_select, w.btn_save_annotated, w.btn_reinspect,
                           w.btn_next_image, w.verdict_card, w.right_panel):
                rect = widget.rect()
                top_left = widget.mapTo(w, rect.topLeft())
                bottom_right = widget.mapTo(w, rect.bottomRight())
                self.assertTrue(w.rect().contains(top_left), widget.objectName())
                self.assertTrue(w.rect().contains(bottom_right), widget.objectName())

    def test_history_has_room_at_minimum_size(self):
        w = self.window
        w.resize(1100, 760)
        w.toggle_history_panel()
        QTest.qWait(100)
        self.assertGreater(w.history_panel.height(), 400)
        self.assertFalse(w.image_scroll.isVisible())
        w.toggle_history_panel()
        QTest.qWait(100)
        self.assertTrue(w.image_scroll.isVisible())
        self.assertTrue(w.verdict_card.isVisible())

    def test_stale_saved_asset_paths_keep_the_loaded_assets(self):
        w = self.window
        w.model_path_input.setText("/loaded/model.pt")
        w.ref_path_input.setText("/loaded/profile.json")
        path = Path(self.temp.name) / "settings.json"
        path.write_text(json.dumps({"model_path": "/missing/old-model.pt",
                                    "ref_path": "/missing/old-profile.json"}))
        w._settings_path = lambda: str(path)
        SettingsMixin.load_settings(w)
        self.assertEqual(w.model_path_input.text(), "/loaded/model.pt")
        self.assertEqual(w.ref_path_input.text(), "/loaded/profile.json")

    def test_collapsible_card_fast_reversal(self):
        card = self.window.reference_card
        card.set_expanded(True)
        QTest.qWait(30)
        card.set_expanded(False)
        QTest.qWait(250)
        self.assertFalse(card.is_expanded())
        self.assertEqual(card.body.maximumHeight(), 0)

    def test_busy_and_camera_states_block_conflicting_actions(self):
        w = self.window
        w.open_image_path(self.source)
        w.model = object()
        w._inference_running = True
        w._update_action_buttons()
        self.assertFalse(w.btn_select.isEnabled())
        self.assertFalse(w.btn_reinspect.isEnabled())
        self.assertFalse(w.btn_camera_toggle.isEnabled())
        w._inference_running = False
        w._camera_worker = object()
        w._update_action_buttons()
        self.assertFalse(w.btn_reinspect.isEnabled())
        self.assertFalse(w.btn_camera_capture.isEnabled())
        w._camera_latest_frame = cv2.imread(self.source)
        w._update_action_buttons()
        self.assertTrue(w.btn_camera_capture.isEnabled())
        w._camera_worker = None


if __name__ == "__main__":
    unittest.main()
