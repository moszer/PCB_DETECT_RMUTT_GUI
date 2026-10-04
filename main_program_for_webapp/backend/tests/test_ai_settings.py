"""AI key settings from the web UI: persisted to .env, applied live, never sent back."""
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.config import settings
from app.core.security import lease_manager
from app.main import app
from app.services import ai_settings

GEMINI_KEY = "AIzaSyTEST_key_1234567890abcd"


class AISettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = Path(self.tmp.name) / ".env"
        self.env.write_text("# my notes\nPCB_OPERATOR_PASSCODE=keepme\nGEMINI_API_KEY=old\n# GEMINI_MODELS=x\n")
        self.patches = [
            mock.patch.object(ai_settings, "ENV_PATH", self.env),
            mock.patch.dict(os.environ, {"GEMINI_API_KEY": "old"}, clear=False),
        ]
        for p in self.patches:
            p.start()
        for var in ("OPENROUTER_API_KEY", "AI_PROVIDER", "GEMINI_MODELS", "OPENROUTER_MODEL"):
            os.environ.pop(var, None)
        self.client = TestClient(app)
        settings.operator_passcode = "rmutt-aoi"
        self.lease_token = None

    def tearDown(self):
        lease_manager.release_lease(self.lease_token)  # don't leave the station controlled for other tests
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def _token(self):
        res = self.client.post("/api/auth/acquire", json={"operator_name": "t", "passcode": "rmutt-aoi", "force": True})
        self.lease_token = res.json()["operator_token"]
        return {"X-Operator-Token": self.lease_token}

    def test_saves_key_keeps_other_lines_and_applies_now(self):
        res = self.client.put("/api/chat/config", json={"provider": "gemini", "gemini_api_key": GEMINI_KEY}, headers=self._token())
        self.assertEqual(res.status_code, 200, res.text)
        text = self.env.read_text()
        self.assertIn(f"GEMINI_API_KEY={GEMINI_KEY}", text)
        self.assertNotIn("GEMINI_API_KEY=old", text)
        self.assertIn("# my notes", text)
        self.assertIn("PCB_OPERATOR_PASSCODE=keepme", text)
        self.assertIn("AI_PROVIDER=gemini", text)
        self.assertEqual(stat.S_IMODE(self.env.stat().st_mode), 0o600)
        self.assertEqual(os.environ["GEMINI_API_KEY"], GEMINI_KEY)  # live, no restart

    def test_key_is_never_returned(self):
        self.client.put("/api/chat/config", json={"gemini_api_key": GEMINI_KEY}, headers=self._token())
        for res in (self.client.get("/api/chat/config"), self.client.get("/api/chat/status")):
            self.assertNotIn(GEMINI_KEY, res.text)
        info = self.client.get("/api/chat/config").json()["providers"]["gemini"]
        self.assertTrue(info["key_set"])
        self.assertEqual(info["key_hint"], "AIza…abcd")

    def test_empty_string_removes_key(self):
        self.client.put("/api/chat/config", json={"gemini_api_key": ""}, headers=self._token())
        self.assertNotIn("GEMINI_API_KEY=", self.env.read_text().replace("# GEMINI", ""))
        self.assertNotIn("GEMINI_API_KEY", os.environ)

    def test_requires_operator_lease_even_when_station_is_free(self):
        self.assertFalse(lease_manager.get_lease_info().is_controlled)  # nobody holds it, still refused
        res = self.client.put("/api/chat/config", json={"gemini_api_key": GEMINI_KEY})
        self.assertEqual(res.status_code, 403)
        res = self.client.post("/api/chat/config/test", json={"provider": "gemini"})
        self.assertEqual(res.status_code, 403)
        self.assertNotIn(GEMINI_KEY, self.env.read_text())

    def test_rejects_values_that_could_inject_into_env(self):
        for bad in ("abc def ghi jkl", "key\nAI_PROVIDER=x", 'k"ey12345678', "short"):
            res = self.client.put("/api/chat/config", json={"gemini_api_key": bad}, headers=self._token())
            self.assertEqual(res.status_code, 400, bad)
        self.assertEqual(self.env.read_text().count("AI_PROVIDER"), 0)

    def test_key_test_reports_provider_answer(self):
        class Res:
            def __init__(self, code):
                self.status_code = code

        async def fake_get(self, url, headers=None):
            return Res(200 if headers.get("x-goog-api-key") == GEMINI_KEY else 400)

        with mock.patch("httpx.AsyncClient.get", fake_get):
            ok = self.client.post("/api/chat/config/test", json={"provider": "gemini", "api_key": GEMINI_KEY}, headers=self._token()).json()
            bad = self.client.post("/api/chat/config/test", json={"provider": "gemini", "api_key": "AIzaWRONGKEY1234"}, headers=self._token()).json()
        self.assertTrue(ok["ok"])
        self.assertFalse(bad["ok"])


if __name__ == "__main__":
    unittest.main()
