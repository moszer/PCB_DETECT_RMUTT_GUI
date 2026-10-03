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


class GeminiTests(unittest.TestCase):
    def test_messages_convert_to_gemini_with_inline_image(self):
        msgs = chat_service.build_messages([{"role": "user", "content": "hi"}], {}, "data:image/jpeg;base64,AAAA")
        body = chat_service.to_gemini(msgs)
        self.assertIn("ผู้ช่วย", body["systemInstruction"]["parts"][0]["text"])
        self.assertEqual(body["contents"][0]["parts"][1]["inlineData"], {"mimeType": "image/jpeg", "data": "AAAA"})
        self.assertEqual([c["role"] for c in body["contents"]], ["user", "model", "user"])

    def test_busy_model_falls_through_to_the_next(self):
        import asyncio

        import httpx

        seen = []

        def handler(request):
            seen.append(request.url.path.split("/")[-1].split(":")[0])
            if len(seen) == 1:
                return httpx.Response(503, json={"error": {"message": "high demand"}})
            return httpx.Response(200, text='data: {"candidates":[{"content":{"parts":[{"text":"x","thought":true},{"text":"ok"}]}}]}\n\n')

        real = httpx.AsyncClient
        env = {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "k", "GEMINI_MODELS": "a-model,b-model"}
        with patch.dict(os.environ, env), \
                patch("app.services.chat_service.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)):
            async def run():
                return "".join([x async for x in chat_service.stream_reply([{"role": "user", "content": "hi"}])])

            self.assertEqual(asyncio.run(run()), "ok")
        self.assertEqual(seen, ["a-model", "b-model"])


class RetryTests(unittest.TestCase):
    def test_busy_free_model_is_retried_with_fallbacks(self):
        import asyncio
        import json

        import httpx

        calls = []

        def handler(request):
            calls.append(json.loads(request.content))
            if len(calls) < 3:
                return httpx.Response(429, json={"error": {"message": "Provider returned error"}})
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n')

        real = httpx.AsyncClient
        with patch("app.services.chat_service.httpx.AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)), \
                patch.object(chat_service, "RETRY_DELAYS_SEC", (0, 0)), patch.dict(os.environ, {"AI_PROVIDER": "openrouter"}):
            async def run():
                return "".join([x async for x in chat_service.stream_reply([{"role": "user", "content": "hi"}])])

            self.assertEqual(asyncio.run(run()), "ok")
        self.assertEqual(len(calls), 3)
        self.assertGreater(len(calls[0]["models"]), 1)


class ChatEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_unconfigured_key_is_a_clear_503_and_key_never_leaks(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "openrouter", "OPENROUTER_API_KEY": ""}):
            self.assertFalse(self.client.get("/api/chat/status").json()["configured"])
            res = self.client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
            self.assertEqual(res.status_code, 503)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-v1-secret", "GEMINI_API_KEY": "AQ.secret"}):
            text = self.client.get("/api/chat/status").text
            self.assertNotIn("sk-or", text)
            self.assertNotIn("AQ.", text)

    def test_refuses_images_outside_storage(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "x"}):
            res = self.client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}], "image_url": "/etc/passwd"})
            self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
