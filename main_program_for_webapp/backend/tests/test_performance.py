"""Performance log and the computer-vs-Jetson report (table 4.13)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.main import app
from app.services import benchmark, perf_log


def run(verdict, truth, start=0.0, secs=30.0, status="complete"):
    return {"id": f"r{start}", "status": status, "is_simulation": 0, "created_at": start, "completed_at": start + secs,
            "overall_verdict": verdict, "total_points": 3, "host": "jetson", "device": "cuda:0", "model": "best.pt", "ground_truth": truth}


class ReportMathTests(unittest.TestCase):
    def setUp(self):
        self.patch = mock.patch.object(benchmark, "system_info", return_value={"hostname": "jetson", "versions": {}, "model": {}})
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_board_accuracy_and_f1(self):
        # defective = positive. 2 TP, 1 FN, 1 FP, 3 TN, 1 REVIEW (excluded), 1 unlabeled.
        runs = [run("FAIL", "defective", 1), run("FAIL", "defective", 2), run("PASS", "defective", 3), run("FAIL", "good", 4),
                run("PASS", "good", 5), run("PASS", "good", 6), run("PASS", "good", 7), run("REVIEW", "good", 8), run("PASS", None, 9)]
        rep = benchmark.performance_report({"runs": runs, "points": [], "singles": []})
        b = rep["board"]
        self.assertEqual((b["tp"], b["fn"], b["fp"], b["tn"], b["decided"], b["review"]), (2, 1, 1, 3, 7, 1))
        self.assertAlmostEqual(b["accuracy"], 71.43)
        self.assertAlmostEqual(b["f1"], 66.67)  # 2*2 / (2*2 + 1 + 1)

    def test_timing_and_scan_time(self):
        points = [{"speed_json": json.dumps({"inference": 20, "total": 40})}, {"speed_json": json.dumps({"inference": 30, "total": 60})},
                  {"speed_json": json.dumps({"inference": 25})}]  # old row without total
        rep = benchmark.performance_report({"runs": [run("PASS", None, 0, 20), run("PASS", None, 1, 40), run("PASS", None, 2, 1, "aborted")],
                                            "points": points, "singles": []})
        self.assertEqual(rep["images"]["total_ms"]["mean"], 50.0)
        self.assertEqual(rep["images"]["inference_ms"]["mean"], 25.0)
        self.assertEqual(rep["images"]["throughput_fps"], 20.0)
        self.assertEqual(rep["scans"]["finished"], 2)  # aborted runs don't count
        self.assertEqual(rep["scans"]["scan_time_s"]["mean"], 30.0)
        self.assertEqual(len(benchmark.table_rows(rep)), 13)

    def test_dataset_images_resolve_roboflow_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test" / "images").mkdir(parents=True)
            (root / "test" / "images" / "a.jpg").write_bytes(b"x")
            (root / "data.yaml").write_text("test: ../test/images\nnames: [a]\n")
            self.assertEqual([p.name for p in benchmark.dataset_images(str(root / "data.yaml"), "test")], ["a.jpg"])
            with self.assertRaises(benchmark.BenchmarkError):
                benchmark.dataset_images(str(root / "missing.yaml"), "test")


class LogAndApiTests(unittest.TestCase):
    def test_record_writes_one_line_and_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(perf_log, "PERF_DIR", Path(tmp)):
            perf_log.record("scan", {"inference": 12.5, "total": 20.0}, (2160, 2160, 3), 1280, 4)
            lines = next(Path(tmp).glob("perf-*.jsonl")).read_text().splitlines()
            entry = json.loads(lines[0])
            self.assertEqual((entry["tag"], entry["inference_ms"], entry["total_ms"], entry["image"]), ("scan", 12.5, 20.0, [2160, 2160]))
        with mock.patch.object(perf_log, "PERF_DIR", Path("/nonexistent/forbidden")):
            perf_log.record("scan", {"inference": 1.0})  # must not raise

    def test_ground_truth_endpoint_and_report(self):
        client = TestClient(app)
        self.assertEqual(client.put("/api/history/runs/nope/ground-truth", json={"truth": "good"}).status_code, 404)
        self.assertEqual(client.put("/api/history/runs/x/ground-truth", json={"truth": "maybe"}).status_code, 422)
        rep = client.get("/api/history/performance").json()
        self.assertEqual(len(rep["table"]), 13)
        csv_res = client.get("/api/history/performance/export.csv")
        self.assertTrue(csv_res.text.startswith("﻿"))
        self.assertIn("mAP50", csv_res.text)


if __name__ == "__main__":
    unittest.main()
