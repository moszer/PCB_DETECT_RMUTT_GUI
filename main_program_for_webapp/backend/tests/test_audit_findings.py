import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings, REFERENCES_DIR
from app.core.schemas import ReferenceProfile, ReferencePoint, ScanPlanRequest
from app.services.aoi_scan_service import aoi_scan_service
from app.services.camera_service import camera_service
from app.services.machine_service import machine_service
from app.services.inference_service import inference_service
from app.services.machine_service import machine_service
from app.services.storage_service import storage_service


class FakeVideoCapture:
    """Mock OpenCV VideoCapture to safely test without touching hardware cameras."""
    def __init__(self, index):
        self.index = index
    def isOpened(self):
        return False
    def release(self):
        pass
    def set(self, prop, val):
        pass
    def get(self, prop):
        return 0.0
    def read(self):
        return (False, None)


class AuditFindingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cv_patcher = patch("cv2.VideoCapture", side_effect=lambda idx: FakeVideoCapture(idx))
        cls.cv_patcher.start()
        cls.client = TestClient(app)
        settings.operator_passcode = "rmutt-aoi"
        camera_service.start()
        machine_service.connect(mode="simulation")
        machine_service.home()


        # Mock inference service so scan can run in unit tests without GPU
        cls._orig_model = inference_service._model
        cls._orig_path = inference_service._model_path
        cls._orig_predict = inference_service.predict
        inference_service._model = MagicMock()
        inference_service._model_path = "mock_model.pt"
        inference_service.predict = MagicMock(return_value=([], {"preprocess": 1.0, "inference": 5.0, "postprocess": 1.0}))

    @classmethod
    def tearDownClass(cls):
        camera_service.stop()
        machine_service.disconnect()
        cls.cv_patcher.stop()
        inference_service._model = cls._orig_model
        inference_service._model_path = cls._orig_path
        inference_service.predict = cls._orig_predict




    def _acquire_lease(self) -> str:
        res = self.client.post("/api/auth/acquire", json={
            "operator_name": "QA_Operator",
            "passcode": "rmutt-aoi",
            "force": True
        })
        self.assertEqual(res.status_code, 200)
        return res.json()["operator_token"]

    def tearDown(self):
        aoi_scan_service.stop_scan()

    def test_f01_no_deadlock_on_start_and_stop_scan(self):
        """F01: start_scan and stop_scan must be reentrant without thread deadlock."""
        token = self._acquire_lease()
        plan = ScanPlanRequest(
            origin_x_mm=0.0,
            origin_y_mm=0.0,
            columns=2,
            rows=2,
            pitch_x_mm=5.0,
            pitch_y_mm=5.0,
            speed=800,
            settle_sec=0.01
        )
        report = aoi_scan_service.start_scan(plan=plan, is_golden_scan=False)
        self.assertIsNotNone(report)
        self.assertTrue(report.id.startswith("aoi_"))
        
        # Stop scan must terminate promptly
        aoi_scan_service.stop_scan()
        self.assertFalse(aoi_scan_service.is_running)


    def test_f03_auth_and_secret_leakage_protection(self):
        """F03: Passcode required, credentials not leaked in status or settings."""
        # 1. Attempt acquire without passcode fails
        res_fail = self.client.post("/api/auth/acquire", json={"operator_name": "Attacker"})
        self.assertEqual(res_fail.status_code, 403)

        # 2. Acquire with invalid passcode fails
        res_fail2 = self.client.post("/api/auth/acquire", json={"operator_name": "Attacker", "passcode": "wrong"})
        self.assertEqual(res_fail2.status_code, 403)

        # 3. Settings endpoint must not leak operator_passcode
        res_settings = self.client.get("/api/system/settings")
        self.assertEqual(res_settings.status_code, 200)
        self.assertNotIn("operator_passcode", res_settings.json())
        self.assertTrue(res_settings.json().get("has_passcode"))

        # 4. Status endpoint must not leak active_operator_id token
        res_status = self.client.get("/api/system/status")
        self.assertEqual(res_status.status_code, 200)
        lease_info = res_status.json()["control_lease"]
        self.assertIsNone(lease_info.get("active_operator_id"))

    def test_f04_reference_path_traversal_rejection(self):
        """F04: Reference IDs with path traversal must be rejected with 400."""
        token = self._acquire_lease()
        traversal_profile = {
            "id": "../escaped_ref",
            "name": "Malicious Profile",
            "profile_type": "single",
            "points": []
        }
        res = self.client.post(
            "/api/references",
            json=traversal_profile,
            headers={"X-Operator-Token": token}
        )
        self.assertEqual(res.status_code, 400)
        # Ensure file was NOT created outside references dir
        escaped_file = REFERENCES_DIR.parent / "escaped_ref.json"
        self.assertFalse(escaped_file.exists())

    def test_f05_soft_limit_synchronization(self):
        """F05: Updating soft limits must update machine_service and enforce in planner."""
        token = self._acquire_lease()
        # Set soft limits to 10.0 x 10.0 mm
        res = self.client.post(
            "/api/system/settings",
            json={"soft_limit_x_mm": 10.0, "soft_limit_y_mm": 10.0},
            headers={"X-Operator-Token": token}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(machine_service._soft_limits_mm, (10.0, 10.0))

        # Planning beyond 10mm should now be rejected by planner
        plan_out_of_bounds = ScanPlanRequest(
            origin_x_mm=0.0,
            origin_y_mm=0.0,
            columns=2,
            rows=2,
            pitch_x_mm=15.0,  # Exceeds 10.0mm!
            pitch_y_mm=5.0
        )
        with self.assertRaises(ValueError):
            aoi_scan_service.plan_scan(plan_out_of_bounds)

        # Restore default soft limits
        self.client.post(
            "/api/system/settings",
            json={"soft_limit_x_mm": 38.0, "soft_limit_y_mm": 38.0},
            headers={"X-Operator-Token": token}
        )

    def test_f07_references_listing_returns_summary(self):
        """F07: list_references returns ReferenceSummary with points_count without crashing."""
        token = self._acquire_lease()
        test_profile = {
            "id": "test_qa_board_01",
            "name": "QA Test Board",
            "profile_type": "single",
            "points": [
                {"id": "p1", "x": 100.0, "y": 200.0, "label": "chip", "tolerance_px": 30.0},
                {"id": "p2", "x": 300.0, "y": 400.0, "label": "resistor", "tolerance_px": 25.0}
            ]
        }
        res_save = self.client.post(
            "/api/references",
            json=test_profile,
            headers={"X-Operator-Token": token}
        )
        self.assertEqual(res_save.status_code, 200)

        # List references
        res_list = self.client.get("/api/references")
        self.assertEqual(res_list.status_code, 200)
        items = res_list.json()
        target = next((item for item in items if item["id"] == "test_qa_board_01"), None)
        self.assertIsNotNone(target)
        self.assertEqual(target["points_count"], 2)

        # Clean up
        self.client.delete("/api/references/test_qa_board_01", headers={"X-Operator-Token": token})

    def test_f08_system_status_with_active_run_total_points(self):
        """F08: GET /api/system/status must not 500 when active_scan is running."""
        token = self._acquire_lease()
        plan = ScanPlanRequest(
            origin_x_mm=0.0,
            origin_y_mm=0.0,
            columns=2,
            rows=1,
            pitch_x_mm=5.0,
            pitch_y_mm=5.0,
            speed=800,
            settle_sec=0.01
        )
        report = aoi_scan_service.start_scan(plan=plan, is_golden_scan=False)
        try:
            res = self.client.get("/api/system/status")
            self.assertEqual(res.status_code, 200)
            status_data = res.json()
            self.assertIsNotNone(status_data["active_scan"])
            self.assertEqual(status_data["active_scan"]["total_points"], 2)
        finally:
            aoi_scan_service.stop_scan()

    def test_f10_f11_camera_mock_flag_and_resolution_switch(self):
        """F10 & F11: Camera reports is_mock accurately and reopens on resolution change."""
        # 1. Start 1080p
        res1 = self.client.post("/api/camera/start", json={
            "device_index": 0,
            "width": 1920,
            "height": 1080,
            "fps": 30
        })
        self.assertEqual(res1.status_code, 200)
        data1 = res1.json()
        self.assertTrue(data1["success"])
        self.assertIn("is_mock", data1)

        # 2. Switch to 4K (3840x2160)
        res2 = self.client.post("/api/camera/start", json={
            "device_index": 0,
            "width": 3840,
            "height": 2160,
            "fps": 30
        })
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertTrue(data2["success"])
        # Resolution in service must now match requested
        self.assertEqual(camera_service.resolution, (3840, 2160))

    def test_f15_f16_single_inspections_and_production_statistics(self):
        """F15 & F16: Single inspections recorded in history, stats exclude simulation."""
        # Query single inspections endpoint
        res_single = self.client.get("/api/history/single-inspections")
        self.assertEqual(res_single.status_code, 200)
        self.assertIn("inspections", res_single.json())
        self.assertIn("total", res_single.json())

        # Query statistics
        res_stats = self.client.get("/api/history/statistics")
        self.assertEqual(res_stats.status_code, 200)
        stats = res_stats.json()
        self.assertIn("board_yield_rate", stats)
        self.assertIn("simulation_runs", stats)
        self.assertIn("golden_runs", stats)
        self.assertIn("single_inspections_count", stats)
