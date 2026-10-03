"""Saved sets of test points: create, load, rename, replace and delete."""
import unittest

from fastapi.testclient import TestClient

from app.core.security import lease_manager
from app.main import app
from app.services import point_set_store

POINTS = [
    {"name": "จุด 1", "x_mm": 10.0, "y_mm": 10.0, "zoom": 1.0, "reference_image": "data:image/jpeg;base64,AAAA",
     "expected_components": [{"id": "P1", "name": "ic", "bbox": [0.1, 0.1, 0.2, 0.2]}, {"id": "P2", "name": "resistor", "bbox": [0.5, 0.5, 0.6, 0.6]}]},
    {"name": "จุด 2", "x_mm": 15.0, "y_mm": 21.5, "zoom": 2.0},
]


class PointSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        _, cls.token = lease_manager.acquire_lease("QA", "127.0.0.1", force=True)[:2]
        cls.headers = {"X-Operator-Token": cls.token}

    @classmethod
    def tearDownClass(cls):
        lease_manager.release_lease(cls.token)

    def setUp(self):
        self.created = []

    def tearDown(self):
        for set_id in self.created:
            point_set_store.delete_set(set_id)

    def _create(self, name, points=POINTS):
        res = self.client.post("/api/aoi/point-sets", json={"name": name, "points": points}, headers=self.headers)
        if res.status_code == 200:
            self.created.append(res.json()["id"])
        return res

    def test_save_load_keeps_everything_including_taught_components_and_images(self):
        res = self._create("บอร์ด Astron ทดสอบ")
        self.assertEqual(res.status_code, 200, res.text)
        meta = res.json()
        self.assertEqual((meta["point_count"], meta["component_count"]), (2, 2))
        listed = self.client.get("/api/aoi/point-sets").json()["sets"]
        self.assertIn(meta["id"], [s["id"] for s in listed])
        self.assertNotIn("points", listed[0])  # the list stays small
        loaded = self.client.get(f"/api/aoi/point-sets/{meta['id']}").json()
        self.assertEqual(loaded["points"][0]["reference_image"], "data:image/jpeg;base64,AAAA")
        self.assertEqual(loaded["points"][0]["expected_components"][1]["name"], "resistor")
        self.assertEqual(loaded["points"][1]["zoom"], 2.0)

    def test_names_are_required_and_unique_ignoring_case(self):
        self.assertEqual(self.client.post("/api/aoi/point-sets", json={"name": "  ", "points": POINTS}, headers=self.headers).status_code, 400)
        self.assertEqual(self._create("Board A").status_code, 200)
        self.assertEqual(self._create("board a").status_code, 400)

    def test_rename_then_replace_points_then_delete(self):
        set_id = self._create("เดิม").json()["id"]
        renamed = self.client.put(f"/api/aoi/point-sets/{set_id}", json={"name": "ชื่อใหม่"}, headers=self.headers).json()
        self.assertEqual((renamed["name"], renamed["point_count"]), ("ชื่อใหม่", 2))
        replaced = self.client.put(f"/api/aoi/point-sets/{set_id}", json={"points": POINTS[:1]}, headers=self.headers).json()
        self.assertEqual((replaced["name"], replaced["point_count"]), ("ชื่อใหม่", 1))
        self.assertEqual(self.client.delete(f"/api/aoi/point-sets/{set_id}", headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get(f"/api/aoi/point-sets/{set_id}").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/aoi/point-sets/{set_id}", headers=self.headers).status_code, 404)

    def test_board_can_start_empty_and_be_emptied(self):
        res = self._create("บอร์ดเปล่า", points=[])
        self.assertEqual((res.status_code, res.json()["point_count"]), (200, 0))
        set_id = res.json()["id"]
        filled = self.client.put(f"/api/aoi/point-sets/{set_id}", json={"points": POINTS}, headers=self.headers).json()
        self.assertEqual(filled["point_count"], 2)
        emptied = self.client.put(f"/api/aoi/point-sets/{set_id}", json={"points": []}, headers=self.headers).json()
        self.assertEqual(emptied["point_count"], 0)

    def test_invalid_points_and_missing_token_are_rejected(self):
        bad = [{"name": "x", "x_mm": 1, "y_mm": 1, "expected_components": [{"id": "P1", "name": "ic"}, {"id": "P1", "name": "ic"}]}]
        self.assertEqual(self.client.post("/api/aoi/point-sets", json={"name": "bad", "points": bad}, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.post("/api/aoi/point-sets", json={"name": "nope", "points": POINTS}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
