"""Boards page: summary, readiness, pictures with boxes, history by point ids, duplicate, export/import."""
import base64
import json
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from app.core.security import lease_manager
from app.main import app
from app.services import point_set_store
from app.services.storage_service import storage_service


def picture(w=1280, h=720):
    img = np.full((h, w, 3), 60, np.uint8)
    cv2.rectangle(img, (100, 100), (300, 200), (20, 20, 20), -1)
    ok, jpg = cv2.imencode(".jpg", img)
    return "data:image/jpeg;base64," + base64.b64encode(jpg.tobytes()).decode()


def comp(i, name, box):
    return {"id": f"P{i}", "name": name, "bbox": box}


class BoardsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The pictures are 16:9 like the station camera's 3840x2160 mode.
        cls._aspect = patch("app.routers.boards._camera_aspect", return_value=16 / 9)
        cls._aspect.start()
        cls.client = TestClient(app)
        _, cls.token = lease_manager.acquire_lease("QA", "127.0.0.1", force=True)[:2]
        cls.h = {"X-Operator-Token": cls.token}
        stamp = int(time.time() * 1000)
        cls.ids = [f"pt_t{stamp}_{i}" for i in range(3)]
        points = [
            {"id": cls.ids[0], "name": "จุด 1", "x_mm": 5, "y_mm": 5, "zoom": 1, "reference_image": picture(),
             "expected_components": [comp(1, "ic", [0.1, 0.1, 0.3, 0.3]), comp(2, "resistor", [0.5, 0.5, 0.6, 0.55])]},
            {"id": cls.ids[1], "name": "จุด 2", "x_mm": 20, "y_mm": 20, "zoom": 1, "reference_image": None,
             "expected_components": [comp(1, "capacitor", [0.2, 0.2, 0.3, 0.3])]},
            {"id": cls.ids[2], "name": "จุด 3", "x_mm": 500, "y_mm": 5, "zoom": 1, "reference_image": picture(800, 800),
             "expected_components": []},
        ]
        cls.board = point_set_store.create_set(f"QA board {stamp}", points)
        # A finished scan of this board, with point 1 failing on a missing resistor.
        cls.run_id = f"aoi_test_{stamp}"
        plan = {"plan_mode": "custom", "custom_points": [{"id": i} for i in cls.ids]}
        details = {"component_eval": [{"expected": {"id": "P2", "name": "resistor"}, "status": "missing"}]}
        with storage_service._get_connection() as conn:
            conn.execute("INSERT INTO runs (id, status, is_simulation, is_golden_scan, created_at, overall_verdict, total_points, "
                         "pass_count, fail_count, review_count, error_count, plan_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (cls.run_id, "complete", 1, 0, time.time(), "FAIL", 3, 2, 1, 0, 0, json.dumps(plan)))
            conn.execute("INSERT INTO point_results (run_id, point_index, col, row, x_mm, y_mm, verdict, reason, image_path, annotated_path, "
                         "image_url, annotated_url, detections_json, summary_json, speed_json, details_json, created_at) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (cls.run_id, 0, 0, 0, 5, 5, "FAIL", "missing", "", "", "", "", "[]", "{}", "{}", json.dumps(details), time.time()))

    @classmethod
    def tearDownClass(cls):
        with storage_service._get_connection() as conn:
            conn.execute("DELETE FROM point_results WHERE run_id = ?", (cls.run_id,))
            conn.execute("DELETE FROM runs WHERE id = ?", (cls.run_id,))
        for s in point_set_store.list_sets():
            if s["name"].startswith("QA board"):
                point_set_store.delete_set(s["id"])
        lease_manager.release_lease(cls.token)
        cls._aspect.stop()

    def test_list_and_detail(self):
        boards = self.client.get("/api/boards").json()["boards"]
        b = next(x for x in boards if x["id"] == self.board["id"])
        self.assertEqual(b["classes"], {"ic": 1, "resistor": 1, "capacitor": 1})
        self.assertEqual((b["taught_points"], b["ready_points"], b["issue_points"]), (2, 1, 2))
        self.assertEqual(b["cover_point"], 0)
        self.assertEqual(b["history"]["completed"], 1)
        self.assertEqual(b["history"]["yield_pct"], 0.0)
        d = self.client.get(f"/api/boards/{self.board['id']}").json()
        issues = {p["name"]: p["issues"] for p in d["points"]}
        self.assertEqual(issues["จุด 1"], [])
        self.assertTrue(any("ภาพต้นแบบ" in i for i in issues["จุด 2"]))
        self.assertTrue(any("นอกระยะ" in i for i in issues["จุด 3"]))
        self.assertTrue(any("สัดส่วน" in i for i in issues["จุด 3"]))  # 800x800 taught, camera is 16:9
        self.assertTrue(any("สอนชิ้นส่วน" in i for i in issues["จุด 3"]))
        self.assertEqual(d["history"]["top_failing_points"][0]["name"], "จุด 1")
        self.assertEqual(d["history"]["top_failing_parts"][0]["class"], "resistor")
        self.assertNotIn("reference_image", json.dumps(d))  # no pictures in the JSON

    def test_point_picture_with_boxes(self):
        res = self.client.get(f"/api/boards/{self.board['id']}/points/0/thumb.jpg", params={"w": 480})
        self.assertEqual(res.status_code, 200)
        img = cv2.imdecode(np.frombuffer(res.content, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(img.shape[1], 480)
        self.assertEqual(self.client.get(f"/api/boards/{self.board['id']}/points/1/thumb.jpg").status_code, 404)  # no picture

    def test_duplicate_export_import(self):
        dup = self.client.post(f"/api/boards/{self.board['id']}/duplicate", json={}, headers=self.h)
        self.assertEqual(dup.status_code, 200, dup.text)
        copy = point_set_store.get_set(dup.json()["id"])
        self.assertEqual(len(copy["points"]), 3)
        self.assertFalse({p["id"] for p in copy["points"]} & set(self.ids))  # own history
        exported = self.client.get(f"/api/boards/{self.board['id']}/export")
        self.assertIn("attachment", exported.headers["content-disposition"])
        body = exported.json()
        self.assertEqual(body["format"], "rmutt-aoi-board")
        imp = self.client.post("/api/boards/import", json=body, headers=self.h)
        self.assertEqual(imp.status_code, 200, imp.text)
        self.assertNotEqual(imp.json()["name"], self.board["name"])  # unique name
        bad = self.client.post("/api/boards/import", json={**body, "format": "other"}, headers=self.h)
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.client.post("/api/boards/import", json=body).status_code, 403)


if __name__ == "__main__":
    unittest.main()
