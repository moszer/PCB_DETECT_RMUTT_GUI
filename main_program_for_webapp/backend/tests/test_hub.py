"""Hugging Face weight downloads, against a local fake Hub (no network)."""
import hashlib
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.core import hub
from app.main import app

REPO = "acme/pcb-models"
BLOB = bytes(range(256)) * 4096  # 1 MiB
LFS_OID = hashlib.sha256(BLOB).hexdigest()
FILES = {"best.pt": BLOB, "run_a/weights/best.pt": BLOB, "run_a/weights/last.pt": BLOB, "run_a/results.csv": b"epoch\n"}


class FakeHub(BaseHTTPRequestHandler):
    corrupt = False  # serve wrong bytes (same length) to test checksum verification

    def log_message(self, *args):  # silence
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _entry(self, path):
        data = FILES[path]
        entry = {"type": "file", "path": path, "size": len(data)}
        if path.endswith(".pt"):
            entry["lfs"] = {"oid": LFS_OID, "size": len(data)}
        return entry

    def do_GET(self):
        if self.path.startswith(f"/api/models/{REPO}/tree/main"):
            return self._json([self._entry(p) for p in FILES])
        prefix = f"/{REPO}/resolve/main/"
        if self.path.startswith(prefix):
            name = self.path[len(prefix):]
            if name not in FILES:
                return self._json({"error": "nf"}, 404)
            data = FILES[name] if not FakeHub.corrupt else bytes(len(FILES[name]))
            start, status = 0, 200
            rng = self.headers.get("Range")
            if rng:
                start, status = int(rng.split("=")[1].split("-")[0]), 206
            body = data[start:]
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json({"error": "nf"}, 404)

    def do_POST(self):
        if self.path == f"/api/models/{REPO}/paths-info/main":
            paths = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["paths"]
            return self._json([self._entry(p) for p in paths if p in FILES])
        self._json({"error": "nf"}, 404)


class HubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHub)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.patches = [
            mock.patch.object(hub, "HUB", f"http://127.0.0.1:{cls.server.server_port}"),
            mock.patch.object(hub, "DEFAULT_REPO", REPO),
        ]
        for p in cls.patches:
            p.start()

    @classmethod
    def tearDownClass(cls):
        for p in cls.patches:
            p.stop()
        cls.server.shutdown()

    def setUp(self):
        FakeHub.corrupt = False
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_only_weights_runs_first(self):
        paths = [m["path"] for m in hub.list_models(REPO)]
        self.assertEqual(paths, ["run_a/weights/best.pt", "run_a/weights/last.pt", "best.pt"])  # runs first, best before last
        self.assertNotIn("run_a/results.csv", paths)

    def test_download_verifies_and_is_idempotent(self):
        out = hub.download("best.pt", self.dir / "m.pt", REPO)
        self.assertEqual(out.read_bytes(), BLOB)
        self.assertFalse((self.dir / "m.pt.part").exists())
        mtime = out.stat().st_mtime_ns
        hub.download("best.pt", out, REPO)
        self.assertEqual(out.stat().st_mtime_ns, mtime)  # intact file is kept, not fetched again

    def test_download_resumes_a_partial_file(self):
        (self.dir / "m.pt.part").write_bytes(BLOB[:300_000])
        out = hub.download("best.pt", self.dir / "m.pt", REPO)
        self.assertEqual(out.read_bytes(), BLOB)

    def test_corrupt_download_is_rejected_and_not_left_behind(self):
        FakeHub.corrupt = True
        with self.assertRaises(hub.HubError):
            hub.download("best.pt", self.dir / "m.pt", REPO)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_missing_file_and_bad_inputs(self):
        with self.assertRaises(hub.HubError):
            hub.download("nope.pt", self.dir / "x.pt", REPO)
        for bad in ("../evil.pt", "/abs.pt", "a//b.pt", "model.txt"):
            with self.assertRaises(hub.HubError, msg=bad):
                hub.check_file(bad)
        with self.assertRaises(hub.HubError):
            hub.check_repo("not-a-repo")

    def test_local_name_is_flat(self):
        self.assertEqual(hub.local_name("m_new_final_l/weights/best.pt"), "m_new_final_l__best.pt")
        self.assertEqual(hub.local_name("best.pt"), "best.pt")


class HubApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch("app.routers.system.STORAGE_DIR", Path(self.tmp.name)),
            mock.patch.object(hub, "DEFAULT_REPO", REPO),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_list_marks_downloaded_files(self):
        listing = [{"path": "run_a/weights/best.pt", "size": 10, "run": "run_a", "kind": "best"}]
        local = Path(self.tmp.name) / "models" / "hub" / REPO.replace("/", "__") / "run_a__best.pt"
        local.parent.mkdir(parents=True)
        local.write_bytes(b"x" * 10)
        with mock.patch.object(hub, "list_models", return_value=listing):
            data = self.client.get("/api/system/models/hub").json()
        self.assertEqual(data["repo"], REPO)
        self.assertTrue(data["models"][0]["downloaded"])

    def test_hub_failure_is_a_readable_502(self):
        with mock.patch.object(hub, "list_models", side_effect=hub.HubError("cannot reach Hugging Face")):
            res = self.client.get("/api/system/models/hub")
        self.assertEqual(res.status_code, 502)
        self.assertIn("cannot reach", res.json()["detail"])

    def test_download_rejects_path_tricks_and_returns_saved_path(self):
        from conftest import operator_headers
        with operator_headers() as headers:
            res = self.client.post("/api/system/models/hub/download", json={"file": "../x.pt"}, headers=headers)
            self.assertEqual(res.status_code, 502)
            saved = Path(self.tmp.name) / "m.pt"
            saved.write_bytes(b"x" * 2048)
            with mock.patch.object(hub, "download", return_value=saved) as dl:
                res = self.client.post("/api/system/models/hub/download", json={"file": "run_a/weights/best.pt"}, headers=headers)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["path"], str(saved))
            self.assertTrue(str(dl.call_args.args[1]).endswith("run_a__best.pt"))


if __name__ == "__main__":
    unittest.main()
