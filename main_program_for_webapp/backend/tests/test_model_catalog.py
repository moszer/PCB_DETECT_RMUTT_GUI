"""Model discovery finds Ultralytics training runs and user-added folders."""
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.core.model_catalog import discover_models
from app.core.security import lease_manager
from app.main import app


def _make_run(root: Path, name: str, maps: list[float]) -> Path:
    weights = root / "runs" / name / "weights"
    weights.mkdir(parents=True)
    for f in ("best.pt", "last.pt"):
        (weights / f).write_bytes(b"\0" * 1024)
    rows = ["epoch,metrics/mAP50(B),metrics/mAP50-95(B)"] + [f"{i + 1},{m + 0.2:.3f},{m:.3f}" for i, m in enumerate(maps)]
    (root / "runs" / name / "results.csv").write_text("\n".join(rows))
    (root / "runs" / name / "args.yaml").write_text("model: yolo26l.pt\nepochs: 60\nimgsz: 1280\n")
    return weights


class ModelCatalogTests(unittest.TestCase):
    def test_runs_are_found_with_best_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_run(root, "exp_l_1280", [0.41, 0.52, 0.49])
            (root / "venv").mkdir()
            (root / "venv" / "ignored.pt").write_bytes(b"x")
            (root / "plain.pt").write_bytes(b"x")
            models = discover_models([root])
            names = [m["filename"] for m in models]
            self.assertEqual(names[:2], ["exp_l_1280/best.pt", "exp_l_1280/last.pt"])  # runs listed first
            self.assertIn("plain.pt", names)
            self.assertNotIn("venv/ignored.pt", names)
            run = models[0]["run"]
            self.assertEqual((run["map50_95"], run["best_epoch"], run["epochs_done"]), (0.52, 2, 3))
            self.assertEqual((run["train_imgsz"], run["train_epochs"]), ("1280", "60"))

    def test_custom_search_folder_via_settings(self):
        client = TestClient(app)
        _, token, _ = lease_manager.acquire_lease("QA", "127.0.0.1", force=True)
        original = list(settings.model_search_dirs)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                _make_run(Path(tmp), "custom_run", [0.3])
                bad = client.post("/api/system/settings", json={"model_search_dirs": [tmp + "/nope"]}, headers={"X-Operator-Token": token})
                self.assertEqual(bad.status_code, 400)
                ok = client.post("/api/system/settings", json={"model_search_dirs": [tmp]}, headers={"X-Operator-Token": token})
                self.assertEqual(ok.status_code, 200, ok.text)
                listed = client.get("/api/system/models").json()
                self.assertIn(str(Path(tmp).resolve()), listed["custom_dirs"])
                self.assertTrue(any(m["filename"] == "custom_run/best.pt" for m in listed["models"]))
        finally:
            client.post("/api/system/settings", json={"model_search_dirs": original}, headers={"X-Operator-Token": token})
            lease_manager.release_lease(token)


if __name__ == "__main__":
    unittest.main()
