"""Regression tests for the 2026-09 code review fixes."""
import json
import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.core.inspection import digital_zoom, draw_annotated_image, evaluate_inspection
from app.core.schemas import CustomPointRequest, Detection, ReferencePoint, ScanPlanRequest
from app.core.security import lease_manager
from app.services.aoi_scan_service import aoi_scan_service
from app.services.camera_service import camera_service
from app.services.inference_service import inference_service
from app.services.machine_service import machine_service


class AnnotationColorTests(unittest.TestCase):
    def test_missing_reference_marker_is_red_in_bgr(self):
        """Markers were drawn with RGB tuples, so 'red' rendered blue in OpenCV (BGR)."""
        image = np.zeros((60, 60, 3), dtype=np.uint8)
        _, _, _, ref_eval, dets = evaluate_inspection(
            [ReferencePoint(x=30, y=30, label="resistor")], [], match_dist=10
        )
        annotated = draw_annotated_image(image, dets, ref_eval)
        b, g, r = (int(v) for v in annotated[30, 30])
        self.assertGreater(r, b)

    def test_digital_zoom_keeps_size(self):
        frame = np.arange(100 * 80 * 3, dtype=np.uint8).reshape(80, 100, 3)
        self.assertIs(digital_zoom(frame, 1.0), frame)
        self.assertEqual(digital_zoom(frame, 2.0).shape, frame.shape)


class ScanLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cv_patcher = patch("cv2.VideoCapture", return_value=MagicMock(isOpened=MagicMock(return_value=False)))
        cls.cv_patcher.start()
        camera_service.start()
        machine_service.connect(mode="simulation")
        machine_service.home()
        cls._predict = inference_service.predict
        cls._model = inference_service._model
        inference_service._model = MagicMock()
        inference_service.predict = MagicMock(return_value=([], {"inference": 1.0}))

    @classmethod
    def tearDownClass(cls):
        aoi_scan_service.stop_scan()
        camera_service.stop()
        machine_service.disconnect()
        inference_service.predict = cls._predict
        inference_service._model = cls._model
        cls.cv_patcher.stop()

    def tearDown(self):
        aoi_scan_service.stop_scan()

    def _wait_until_idle(self, timeout=10.0):
        deadline = time.monotonic() + timeout
        while aoi_scan_service.is_running and time.monotonic() < deadline:
            time.sleep(0.05)

    def test_lease_expiry_aborts_run_instead_of_leaving_it_running(self):
        ok, token, _ = lease_manager.acquire_lease("QA", "127.0.0.1", force=True)
        self.assertTrue(ok)
        plan = ScanPlanRequest(columns=3, rows=3, pitch_x_mm=2, pitch_y_mm=2, settle_sec=0.3)
        report = aoi_scan_service.start_scan(plan=plan)
        lease_manager.release_lease(token)
        self._wait_until_idle()
        self.assertFalse(aoi_scan_service.is_running)
        self.assertEqual(report.status, "aborted")
        self.assertIn("lease", report.error_message)

    def test_custom_scan_does_not_carry_reference_images(self):
        big_image = "data:image/jpeg;base64," + "A" * 50_000
        plan = ScanPlanRequest(
            plan_mode="custom",
            settle_sec=0.0,
            custom_points=[CustomPointRequest(name="P1", x_mm=1, y_mm=1, reference_image=big_image)],
        )
        report = aoi_scan_service.start_scan(plan=plan)
        self.assertIsNone(report.plan.custom_points[0].reference_image)
        self.assertIsNone(report.points[0].reference_image)
        self.assertLess(len(report.model_dump_json()), 20_000)


class DesktopImportTests(unittest.TestCase):
    def test_imported_points_follow_match_distance_setting(self):
        client = TestClient(app)
        _, token, _ = lease_manager.acquire_lease("QA", "127.0.0.1", force=True)
        with patch("app.routers.references.Path") as path_cls:
            path = path_cls.return_value
            path.is_file.return_value = True
            path.read_text.return_value = json.dumps([{"x": 10, "y": 20, "label": "led"}])
            res = client.post("/api/references/import-desktop", headers={"X-Operator-Token": token})
        lease_manager.release_lease(token)
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIsNone(res.json()["points"][0]["tolerance_px"])


if __name__ == "__main__":
    unittest.main()


class CameraSwitchTests(unittest.TestCase):
    def test_stop_never_releases_capture_while_worker_reads(self):
        """cap.release() during cap.read() segfaulted the backend on camera switches."""
        import threading
        state = {"reading": False, "released_during_read": False}

        class SlowCapture:
            def isOpened(self):
                return True
            def set(self, *_):
                pass
            def get(self, *_):
                return 640.0
            def read(self):
                state["reading"] = True
                time.sleep(0.2)
                state["reading"] = False
                return True, np.zeros((48, 64, 3), dtype=np.uint8)
            def release(self):
                if state["reading"]:
                    state["released_during_read"] = True

        camera_service.stop()
        with patch("app.services.camera_service.cv2.VideoCapture", return_value=SlowCapture()):
            camera_service.start(device_index=0, width=640, height=480)
            time.sleep(0.1)  # worker is inside read()
            camera_service.start(device_index=0, width=1280, height=720)  # switch → stop()
            camera_service.stop()
        self.assertFalse(state["released_during_read"])


class CameraOutputSizeTests(unittest.TestCase):
    def test_fit_output_center_crops_to_square(self):
        from app.services.camera_service import CameraService
        frame = np.zeros((90, 160, 3), dtype=np.uint8)
        frame[:, 35:125] = 255  # the centered 90x90 square
        out = CameraService._fit_output(frame, (64, 64))
        self.assertEqual(out.shape, (64, 64, 3))
        self.assertGreater(int(out.min()), 250)  # no background from the cropped-away sides

    def test_fit_output_noop_without_size(self):
        from app.services.camera_service import CameraService
        frame = np.zeros((9, 16, 3), dtype=np.uint8)
        self.assertIs(CameraService._fit_output(frame, None), frame)

    def test_start_reports_output_size_as_resolution(self):
        client = TestClient(app)
        camera_service.stop()
        res = client.post("/api/camera/start", json={"device_index": 0, "width": 1920, "height": 1080, "output_width": 640, "output_height": 640})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["resolution"], [640, 640])
        _, frame = camera_service.get_fresh_frame(0.0)
        self.assertEqual(frame.shape[:2], (640, 640))
        camera_service.stop()
        bad = client.post("/api/camera/start", json={"output_width": 640})
        self.assertEqual(bad.status_code, 422)
