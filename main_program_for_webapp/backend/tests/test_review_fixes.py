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


    def test_every_analyzed_frame_is_broadcast_with_preview_and_boxes(self):
        """The UI shows each frame as it is captured (no flash), so point_frame carries it."""
        det = Detection(id=1, label="ic", conf=0.9, box=[64, 48, 128, 96], cx=96, cy=72)
        inference_service.predict = MagicMock(return_value=([det], {"inference": 1.0}))
        # A previous test may have stopped a scan mid-move; let the simulated stage settle.
        deadline = time.monotonic() + 5
        while machine_service.get_state().is_moving and time.monotonic() < deadline:
            time.sleep(0.05)
        events = []
        aoi_scan_service.subscribe_progress(events.append)
        ok, token, _ = lease_manager.acquire_lease("QA", "127.0.0.1", force=True)
        try:
            plan = ScanPlanRequest(columns=2, rows=1, pitch_x_mm=2, pitch_y_mm=2, settle_sec=0.0)
            aoi_scan_service.start_scan(plan=plan)
            self._wait_until_idle()
        finally:
            lease_manager.release_lease(token)
            aoi_scan_service._progress_subscribers.remove(events.append)
            inference_service.predict = MagicMock(return_value=([], {"inference": 1.0}))
        frames = [e for e in events if e["event"] == "point_frame"]
        self.assertEqual(sorted(e["point_index"] for e in frames), [0, 1])
        for e in frames:
            self.assertTrue(e["preview"].startswith("data:image/jpeg;base64,"))
            self.assertEqual(e["boxes"][0]["label"], "ic")
            self.assertTrue(all(0 <= v <= 1 for v in e["boxes"][0]["box"]))
            self.assertLess(len(e["preview"]), 200_000)


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


class CameraRestartKeepsSelectionTests(unittest.TestCase):
    def test_argumentless_start_keeps_selected_camera_and_output(self):
        """/stream and /snapshot call start() bare; that reset the camera to index 0."""
        camera_service.stop()
        with patch("app.services.camera_service.cv2.VideoCapture", return_value=MagicMock(isOpened=MagicMock(return_value=False))) as cap:
            camera_service.start(device_index=1, width=1280, height=720, output_size=(640, 640))
            camera_service.stop()
            camera_service.start()
            self.assertEqual(camera_service.device_index, 1)
            self.assertEqual(camera_service.resolution, (640, 640))
            self.assertEqual(cap.call_args_list[-1].args[0], 1)
        camera_service.stop()


class FrameAlignmentTests(unittest.TestCase):
    def test_uniform_stage_shift_does_not_fail_small_parts(self):
        """Real scan: every part shifted ~7.5 px (of 640); 13 px resistors fell under IoU 0.3."""
        from app.core.inspection import evaluate_multiframe_round
        expected, detections = [], []
        for i in range(8):
            x = 0.05 + i * 0.1
            box = [x, 0.40, x + 0.06, 0.40 + 13 / 640]  # thin resistor
            expected.append({"id": f"R{i}", "name": "resistor", "bbox": box})
            dy = 7.5 / 640
            detections.append({"label": "resistor", "conf": 0.9, "box": [box[0], box[1] + dy, box[2], box[3] + dy]})
        unaligned_iou = box_iou_for_test(expected[0]["bbox"], detections[0]["box"])
        self.assertLess(unaligned_iou, 0.3)  # would have failed before
        res = evaluate_multiframe_round(expected, [detections] * 5, target_frames=5)
        self.assertEqual(res["verdict"], "PASS", res["reason"])
        self.assertGreater(res["max_offset"], 0.01)

    def test_single_missing_part_is_still_missing_after_alignment(self):
        from app.core.inspection import evaluate_multiframe_round
        expected = [{"id": f"C{i}", "name": "capacitor", "bbox": [0.1 * i, 0.5, 0.1 * i + 0.05, 0.55]} for i in range(1, 6)]
        dets = [{"label": "capacitor", "conf": 0.9, "box": e["bbox"]} for e in expected[:-1]]
        res = evaluate_multiframe_round(expected, [dets] * 5, target_frames=5)
        self.assertEqual(res["verdict"], "FAIL")
        self.assertEqual(res["missing_count"], 1)


def box_iou_for_test(a, b):
    from app.core.inspection import box_iou
    return box_iou(a, b)


class CameraCropModeTests(unittest.TestCase):
    def test_crop_mode_cuts_center_without_resizing(self):
        from app.services.camera_service import CameraService
        frame = np.zeros((2160, 3840, 3), dtype=np.uint8)
        frame[1080, 1920] = 255  # single pixel at the exact center
        out = CameraService._fit_output(frame, (640, 640), "crop")
        self.assertEqual(out.shape, (640, 640, 3))
        self.assertEqual(int(out[320, 320, 0]), 255)  # 1:1 — the pixel survives undiluted

    def test_crop_mode_falls_back_to_fit_on_small_frames(self):
        from app.services.camera_service import CameraService
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        self.assertEqual(CameraService._fit_output(frame, (640, 640), "crop").shape, (640, 640, 3))

    def test_api_reports_capture_and_mode(self):
        client = TestClient(app)
        camera_service.stop()
        with patch("app.services.camera_service.cv2.VideoCapture", return_value=MagicMock(isOpened=MagicMock(return_value=False))):
            res = client.post("/api/camera/start", json={"width": 3840, "height": 2160, "output_width": 640, "output_height": 640, "output_mode": "crop"})
            self.assertEqual(res.status_code, 200, res.text)
            body = client.get("/api/camera/devices").json()
            self.assertEqual((body["resolution"], body["capture_resolution"], body["output_mode"]), ([640, 640], [3840, 2160], "crop"))
            camera_service.start()  # bare restart keeps the mode
            self.assertEqual(camera_service.output_mode, "crop")
        camera_service.stop()

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


class CameraRestartKeepsSelectionTests(unittest.TestCase):
    def test_argumentless_start_keeps_selected_camera_and_output(self):
        """/stream and /snapshot call start() bare; that reset the camera to index 0."""
        camera_service.stop()
        with patch("app.services.camera_service.cv2.VideoCapture", return_value=MagicMock(isOpened=MagicMock(return_value=False))) as cap:
            camera_service.start(device_index=1, width=1280, height=720, output_size=(640, 640))
            camera_service.stop()
            camera_service.start()
            self.assertEqual(camera_service.device_index, 1)
            self.assertEqual(camera_service.resolution, (640, 640))
            self.assertEqual(cap.call_args_list[-1].args[0], 1)
        camera_service.stop()


class FrameAlignmentTests(unittest.TestCase):
    def test_uniform_stage_shift_does_not_fail_small_parts(self):
        """Real scan: every part shifted ~7.5 px (of 640); 13 px resistors fell under IoU 0.3."""
        from app.core.inspection import evaluate_multiframe_round
        expected, detections = [], []
        for i in range(8):
            x = 0.05 + i * 0.1
            box = [x, 0.40, x + 0.06, 0.40 + 13 / 640]  # thin resistor
            expected.append({"id": f"R{i}", "name": "resistor", "bbox": box})
            dy = 7.5 / 640
            detections.append({"label": "resistor", "conf": 0.9, "box": [box[0], box[1] + dy, box[2], box[3] + dy]})
        unaligned_iou = box_iou_for_test(expected[0]["bbox"], detections[0]["box"])
        self.assertLess(unaligned_iou, 0.3)  # would have failed before
        res = evaluate_multiframe_round(expected, [detections] * 5, target_frames=5)
        self.assertEqual(res["verdict"], "PASS", res["reason"])
        self.assertGreater(res["max_offset"], 0.01)

    def test_single_missing_part_is_still_missing_after_alignment(self):
        from app.core.inspection import evaluate_multiframe_round
        expected = [{"id": f"C{i}", "name": "capacitor", "bbox": [0.1 * i, 0.5, 0.1 * i + 0.05, 0.55]} for i in range(1, 6)]
        dets = [{"label": "capacitor", "conf": 0.9, "box": e["bbox"]} for e in expected[:-1]]
        res = evaluate_multiframe_round(expected, [dets] * 5, target_frames=5)
        self.assertEqual(res["verdict"], "FAIL")
        self.assertEqual(res["missing_count"], 1)


def box_iou_for_test(a, b):
    from app.core.inspection import box_iou
    return box_iou(a, b)


class CameraCropModeTests(unittest.TestCase):
    def test_crop_mode_cuts_center_without_resizing(self):
        from app.services.camera_service import CameraService
        frame = np.zeros((2160, 3840, 3), dtype=np.uint8)
        frame[1080, 1920] = 255  # single pixel at the exact center
        out = CameraService._fit_output(frame, (640, 640), "crop")
        self.assertEqual(out.shape, (640, 640, 3))
        self.assertEqual(int(out[320, 320, 0]), 255)  # 1:1 — the pixel survives undiluted

    def test_crop_mode_falls_back_to_fit_on_small_frames(self):
        from app.services.camera_service import CameraService
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        self.assertEqual(CameraService._fit_output(frame, (640, 640), "crop").shape, (640, 640, 3))

    def test_api_reports_capture_and_mode(self):
        client = TestClient(app)
        camera_service.stop()
        with patch("app.services.camera_service.cv2.VideoCapture", return_value=MagicMock(isOpened=MagicMock(return_value=False))):
            res = client.post("/api/camera/start", json={"width": 3840, "height": 2160, "output_width": 640, "output_height": 640, "output_mode": "crop"})
            self.assertEqual(res.status_code, 200, res.text)
            body = client.get("/api/camera/devices").json()
            self.assertEqual((body["resolution"], body["capture_resolution"], body["output_mode"]), ([640, 640], [3840, 2160], "crop"))
            camera_service.start()  # bare restart keeps the mode
            self.assertEqual(camera_service.output_mode, "crop")
        camera_service.stop()


class GpuOutOfMemoryTests(unittest.TestCase):
    """Jetson reports CUDA OOM as an NVML internal assert; predict frees the cache and retries."""

    def _service(self, failures):
        from app.services.inference_service import InferenceService

        svc = InferenceService()
        calls = {"n": 0}

        def predict(**kwargs):
            calls["n"] += 1
            if calls["n"] <= failures:
                raise RuntimeError('NVML_SUCCESS == r INTERNAL ASSERT FAILED at "CUDACachingAllocator.cpp":1407')
            return []

        svc._model = MagicMock(predict=predict)
        return svc, calls

    def test_retries_once_after_freeing_memory(self):
        svc, calls = self._service(failures=1)
        with patch("app.services.inference_service.release_memory") as release, patch("app.services.perf_log.record"):
            dets, _ = svc.predict(np.zeros((32, 32, 3), np.uint8))
        self.assertEqual((dets, calls["n"], release.call_count), ([], 2, 1))

    def test_gives_a_clear_error_when_memory_stays_short(self):
        svc, calls = self._service(failures=5)
        with patch("app.services.inference_service.release_memory"), patch("app.services.perf_log.record"):
            with self.assertRaisesRegex(RuntimeError, "หน่วยความจำ GPU ไม่พอ"):
                svc.predict(np.zeros((32, 32, 3), np.uint8))
        self.assertEqual(calls["n"], 2)

    def test_other_errors_are_not_retried(self):
        from app.services.inference_service import InferenceService, is_gpu_out_of_memory

        self.assertFalse(is_gpu_out_of_memory(RuntimeError("shape mismatch")))
        self.assertTrue(is_gpu_out_of_memory(RuntimeError("CUDA out of memory. Tried to allocate 1.5 GiB")))
        svc = InferenceService()
        svc._model = MagicMock(predict=MagicMock(side_effect=RuntimeError("shape mismatch")))
        with self.assertRaisesRegex(RuntimeError, "shape mismatch"):
            svc.predict(np.zeros((32, 32, 3), np.uint8))
        self.assertEqual(svc._model.predict.call_count, 1)

    def test_release_memory_is_safe_without_cuda(self):
        from app.services.inference_service import release_memory

        release_memory()
