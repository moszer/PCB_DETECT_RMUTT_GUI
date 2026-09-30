"""Integration tests for FastAPI endpoints."""
import io
import unittest
import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.services.inference_service import inference_service


class ApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health_check(self):
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("station", data)

    def test_system_status_and_devices(self):
        res = self.client.get("/api/system/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("machine", data)
        self.assertIn("control_lease", data)

        res_dev = self.client.get("/api/system/devices")
        self.assertEqual(res_dev.status_code, 200)
        dev_data = res_dev.json()
        self.assertTrue(any(d["id"] == "cpu" for d in dev_data["devices"]))

    def test_camera_devices_and_switch(self):
        res = self.client.get("/api/camera/devices")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("devices", data)
        self.assertGreaterEqual(len(data["devices"]), 1)
        self.assertIn("current_index", data)

        # Switch camera to index 0
        res_switch = self.client.post("/api/camera/start", json={
            "device_index": 0,
            "width": 1280,
            "height": 720,
            "fps": 30
        })
        self.assertEqual(res_switch.status_code, 200)
        self.assertTrue(res_switch.json()["success"])

    def test_lease_acquire_and_release(self):
        # 1. Attempt acquire without passcode should fail with 403
        res_fail = self.client.post("/api/auth/acquire", json={"operator_name": "NoPasscode"})
        self.assertEqual(res_fail.status_code, 403)

        # 2. Acquire with valid passcode succeeds
        res = self.client.post("/api/auth/acquire", json={
            "operator_name": "TestOperator",
            "passcode": "rmutt-aoi"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        token = data.get("operator_token") or data.get("operator_id")
        self.assertIsNotNone(token)

        # 3. Check public lease status - token must not be leaked!
        res_lease = self.client.get("/api/auth/lease")
        self.assertTrue(res_lease.json()["is_controlled"])
        self.assertEqual(res_lease.json()["operator_name"], "TestOperator")
        self.assertIsNone(res_lease.json().get("active_operator_id"))

        # 4. Renew lease with secret token
        res_renew = self.client.post("/api/auth/renew", headers={"X-Operator-Token": token})
        self.assertEqual(res_renew.status_code, 200)

        # 5. Release lease with secret token
        res_rel = self.client.post("/api/auth/release", headers={"X-Operator-Token": token})
        self.assertEqual(res_rel.status_code, 200)


    def test_aoi_plan_and_simulation_scan(self):
        # Plan a 2x1 grid
        plan_req = {
            "origin_x_mm": 0.0,
            "origin_y_mm": 0.0,
            "columns": 2,
            "rows": 1,
            "pitch_x_mm": 5.0,
            "pitch_y_mm": 5.0,
            "speed": 800,
            "settle_sec": 0.05
        }
        res_plan = self.client.post("/api/aoi/plan", json=plan_req)
        self.assertEqual(res_plan.status_code, 200)
        pts = res_plan.json()
        self.assertEqual(len(pts), 2)

    def test_upload_inspection(self):
        # Create a small dummy image in memory
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        _, buf = cv2.imencode(".png", img)
        file_bytes = buf.tobytes()

        # Upload image to /api/inspection/inspect-upload
        res = self.client.post(
            "/api/inspection/inspect-upload",
            files={"file": ("test.png", io.BytesIO(file_bytes), "image/png")},
            data={"conf": 0.25, "match_dist": 50.0}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("verdict", data)
        self.assertIn("summary", data)
        self.assertIn("image_url", data)


if __name__ == "__main__":
    unittest.main()
