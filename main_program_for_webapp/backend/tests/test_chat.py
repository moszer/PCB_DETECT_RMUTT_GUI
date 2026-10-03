"""AI chat: board context building and endpoint guards (no network calls)."""
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services import chat_service


class ChatContextTests(unittest.TestCase):
    def test_context_carries_markings_counts_and_verdict(self):
        ctx = {"point_name": "จุด 7", "verdict": "PASS", "counts": {"ic": 1, "switch": 4},
               "parts": [{"name": "P2 ic", "text": "ALTERA\nEPM570T144C5"}, {"name": "P3 switch"}]}
        text = chat_service.context_text(ctx)
        self.assertIn("ALTERA EPM570T144C5", text)
        self.assertIn("ic ×1", text)
        self.assertIn("PASS", text)

    def test_image_goes_with_the_board_context_and_history_is_capped(self):
        history = [{"role": "user", "content": f"q{i}"} for i in range(30)]
        msgs = chat_service.build_messages(history, {}, "data:image/jpeg;base64,AAAA")
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["content"][1]["type"], "image_url")
        self.assertEqual(len(msgs), 3 + 20)


class ChatEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_unconfigured_key_is_a_clear_503_and_key_never_leaks(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}):
            self.assertFalse(self.client.get("/api/chat/status").json()["configured"])
            res = self.client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
            self.assertEqual(res.status_code, 503)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-v1-secret"}):
            self.assertNotIn("sk-or", self.client.get("/api/chat/status").text)

    def test_refuses_images_outside_storage(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "x"}):
            res = self.client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}], "image_url": "/etc/passwd"})
            self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
