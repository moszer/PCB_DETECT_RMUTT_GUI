"""Dataset capture: 4-corner planning, simulated capture, label editing and YOLO export."""
import io
import time
import unittest
import zipfile
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.core.schemas import Detection
from app.core.security import lease_manager
from app.main import app
from app.services.camera_service import camera_service
from app.services.dataset_service import dataset_service, plan_board_points
from app.services.inference_service import inference_service
from app.services.machine_service import machine_service


class PlanTests(unittest.TestCase):
    def test_raster_covers_corners_exactly(self):
        pts, layout = plan_board_points([(2, 3), (12, 3), (12, 9), (2, 9)], 4, 4, 10, (10_000, 10_000))
        self.assertEqual((layout["columns"], layout["rows"]), (4, 3))
        xs = sorted({p[0] for p in pts})
        ys = sorted({p[1] for p in pts})
        self.assertEqual((xs[0], xs[-1], ys[0], ys[-1]), (20, 120, 30, 90))  # edges land on the board

    def test_rejects_too_many_images(self):
        with self.assertRaises(ValueError):
            plan_board_points([(0, 0), (100, 0), (100, 100), (0, 100)], 1, 1, 10, (10_000, 10_000))


class CaptureFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cv = patch("cv2.VideoCapture", return_value=MagicMock(isOpened=MagicMock(return_value=False)))
        cls.cv.start()
        camera_service.stop()
        camera_service.start(width=640, height=480, output_size=None, output_mode="fit")
        machine_service.connect(mode="simulation")
        machine_service.home()
        cls._predict, cls._model, cls._names = inference_service.predict, inference_service._model, inference_service._model_names
        inference_service._model = MagicMock()
        inference_service._model_names = {0: "resistor", 1: "capacitor"}
        det = Detection(id=1, label="capacitor", conf=0.9, box=[64, 48, 128, 96], cx=96, cy=72)
        inference_service.predict = MagicMock(return_value=([det], {"inference": 1.0}))
        cls.client = TestClient(app)
        _, cls.token = lease_manager.acquire_lease("QA", "127.0.0.1", force=True)[:2]
        cls.headers = {"X-Operator-Token": cls.token}

    @classmethod
    def tearDownClass(cls):
        dataset_service.stop_capture()
        lease_manager.release_lease(cls.token)
        inference_service.predict, inference_service._model, inference_service._model_names = cls._predict, cls._model, cls._names
        machine_service.disconnect()
        camera_service.stop()
        cls.cv.stop()

    def _wait(self, timeout=20):
        deadline = time.monotonic() + timeout
        while dataset_service.is_running and time.monotonic() < deadline:
            time.sleep(0.05)

    def test_capture_label_edit_and_export(self):
        corners = [[1, 1], [5, 1], [5, 4], [1, 4]]
        res = self.client.post(
            "/api/datasets/capture",
            json={"name": "QA board", "corners": corners, "pitch_x_mm": 4, "pitch_y_mm": 3, "settle_sec": 0},
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 200, res.text)
        ds_id = res.json()["id"]
        # The stage belongs to the capture: AOI scans and manual moves are refused meanwhile.
        if dataset_service.is_running:
            self.assertEqual(self.client.post("/api/aoi/jog", json={"dx_mm": 1, "dy_mm": 0}, headers=self.headers).status_code, 400)
        self._wait()

        meta = self.client.get(f"/api/datasets/{ds_id}").json()
        self.assertEqual(meta["status"], "complete", meta.get("error"))
        self.assertEqual(len(meta["images"]), 4)  # 2 columns x 2 rows
        self.assertEqual(meta["classes"][:2], ["resistor", "capacitor"])
        first = meta["images"][0]["file"]

        labels = self.client.get(f"/api/datasets/{ds_id}/labels/{first}").json()
        self.assertEqual(labels["boxes"][0]["label"], "capacitor")
        for got, want in zip(labels["boxes"][0]["bbox"], [0.1, 0.1, 0.2, 0.2]):
            self.assertAlmostEqual(got, want, places=4)

        # Relabel with a brand-new class; it is appended to the class list.
        saved = self.client.put(
            f"/api/datasets/{ds_id}/labels/{first}",
            json={"boxes": [{"label": "fuse", "bbox": [0.5, 0.5, 0.6, 0.7]}]},
            headers=self.headers,
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["labeled_by"], "manual")
        self.assertIn("fuse", self.client.get(f"/api/datasets/{ds_id}").json()["classes"])

        zip_res = self.client.get(f"/api/datasets/{ds_id}/download")
        self.assertEqual(zip_res.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(zip_res.content)) as zf:
            names = zf.namelist()
            self.assertIn("data.yaml", names)
            self.assertEqual(sum("/images/" in n for n in names), 4)
            self.assertTrue(any(n.startswith("valid/images/") for n in names))  # train_lab / dashboard layout
            data_yaml = zf.read("data.yaml").decode()
            self.assertIn("nc: 3", data_yaml)
            fuse_line = zf.read(f"train/labels/{first.replace('.jpg', '.txt')}").decode().strip()
            self.assertTrue(fuse_line.startswith("2 "))

        self.assertEqual(self.client.delete(f"/api/datasets/{ds_id}", headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get(f"/api/datasets/{ds_id}").status_code, 404)

    def test_rejects_path_traversal_ids(self):
        self.assertEqual(self.client.get("/api/datasets/..%2F..%2Fsettings").status_code, 404)
        self.assertEqual(self.client.get("/api/datasets/ds_x/labels/..%2Fdataset.json").status_code, 404)


if __name__ == "__main__":
    unittest.main()
