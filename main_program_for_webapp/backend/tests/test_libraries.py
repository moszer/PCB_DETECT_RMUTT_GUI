"""Libraries page: what is installed, newer releases from PyPI/npm (mocked), cache and the API."""
import json
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services import library_service as ls

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>9.0.0rc1</title><pubDate>Mon, 05 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title>8.5.1</title><pubDate>Sun, 04 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title>8.5.0</title><pubDate>Thu, 01 Oct 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


def fake_get(url, accept="*/*"):
    if "pypi.org/rss/project/" in url:
        return RSS
    if "registry.npmjs.org" in url:
        return json.dumps({"version": "99.0.0"}).encode()
    raise OSError("offline")


class VersionTests(unittest.TestCase):
    def test_update_kind(self):
        self.assertEqual(ls.update_kind("8.4.172", "8.4.173"), "patch")
        self.assertEqual(ls.update_kind("19.2.8", "19.3.0"), "minor")
        self.assertEqual(ls.update_kind("2.1.0", "3.0.0"), "major")
        self.assertEqual(ls.update_kind("0.180.0", "0.186.1"), "major")  # 0.x: minor breaks
        self.assertIsNone(ls.update_kind("1.0.0", "1.0.0"))
        self.assertIsNone(ls.update_kind("2.0", "1.9"))
        self.assertIsNone(ls.update_kind(None, "1.0"))

    def test_latest_stable_from_the_release_feed(self):
        with patch.object(ls, "_get", side_effect=fake_get):
            info = ls.latest_pypi("Some_Package")
        self.assertEqual(info["latest"], "8.5.1")  # the release candidate is skipped
        self.assertIsNotNone(info["released"])


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.cache = ls.CACHE.with_name("library-catalog.test.json")
        self.cache.unlink(missing_ok=True)
        self.p = patch.object(ls, "CACHE", self.cache)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.cache.unlink(missing_ok=True)

    def test_installed_lists(self):
        c = ls.library_service.catalog()
        py = {p["name"].lower(): p for p in c["python"]}
        self.assertTrue(py["fastapi"]["direct"])
        self.assertTrue(py["fastapi"]["satisfies"])
        self.assertFalse(py["starlette"]["direct"])  # comes in with fastapi
        self.assertIn("fastapi", [n.lower() for n in py["starlette"]["needed_by"]])
        self.assertIn("ไม่อัปเดตอัตโนมัติ", py["torch"]["pinned"])
        names = {s["name"] for s in c["system"]}
        self.assertTrue({"Python", "โค้ดโปรเจกต์ (git)"} <= names)
        self.assertIsNone(c["checked_at"])

    def test_check_then_merge_into_the_catalog(self):
        client = TestClient(app)
        with patch.object(ls, "_get", side_effect=fake_get):
            job = client.post("/api/system/libraries/check").json()
            self.assertEqual(job["state"], "running")
            deadline = time.monotonic() + 60
            while ls.library_service.job()["state"] == "running" and time.monotonic() < deadline:
                time.sleep(0.05)
        self.assertEqual(client.get("/api/system/libraries/check").json()["state"], "done")
        c = client.get("/api/system/libraries").json()
        self.assertIsNotNone(c["checked_at"])
        self.assertFalse(c["stale"])
        py = {p["name"].lower(): p for p in c["python"]}
        self.assertEqual(py["fastapi"]["latest"], "8.5.1")
        self.assertIn(py["fastapi"]["update"], ("major", None))
        js = {p["name"]: p for p in c["node"] if p["direct"]}
        if js:
            row = next(iter(js.values()))
            self.assertEqual(row["latest"], "99.0.0")
            self.assertEqual(row["update"], "major")

    def test_offline_check_reports_an_error(self):
        with patch.object(ls, "_get", side_effect=OSError("offline")):
            ls.library_service.check()
            deadline = time.monotonic() + 60
            while ls.library_service.job()["state"] == "running" and time.monotonic() < deadline:
                time.sleep(0.05)
        job = ls.library_service.job()
        self.assertEqual(job["state"], "error")
        self.assertIn("อินเทอร์เน็ต", job["message"])
        self.assertFalse(self.cache.exists())


if __name__ == "__main__":
    unittest.main()
