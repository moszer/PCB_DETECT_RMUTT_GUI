"""Gemini TTS for the AI answers: model fallback, WAV output, cache, and the browser fallback (503)."""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.services import chat_service, tts_service

QUOTA = {"error": {"code": 429, "message": "You exceeded your current quota, please check your plan and billing details."}}


def _audio(mime, data):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}}]}}]})


class TTSServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for store in (chat_service._resting,):
            store.clear()
            self.addCleanup(store.clear)
        p = patch.object(tts_service, "CACHE_DIR", Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)
        self.calls = []

    def _client(self, handler):
        real = httpx.Client
        return patch("app.services.tts_service.httpx.Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

    def test_pcm_answer_becomes_wav_and_is_cached(self):
        def handler(request):
            self.calls.append(request.url.path.split("/")[-1].split(":")[0])
            body = json.loads(request.content)
            self.assertEqual(body["generationConfig"]["responseModalities"], ["AUDIO"])
            return _audio("audio/L16;codec=pcm;rate=24000", b"\x01\x00" * 100)

        env = {"GEMINI_API_KEY": "k", "GEMINI_TTS_MODELS": "tts-a", "PCB_TTS_ENGINES": "gemini"}
        with patch.dict(os.environ, env), self._client(handler):
            audio, model, mime = tts_service.synthesize("สวัสดีครับ")
            again, cached, _ = tts_service.synthesize("สวัสดีครับ")
        self.assertEqual((model, mime), ("tts-a", "audio/wav"))
        self.assertEqual(audio[:4], b"RIFF")
        self.assertEqual(audio[8:12], b"WAVE")
        self.assertEqual(len(audio), 44 + 200)
        self.assertEqual((again, cached), (audio, "cache"))
        self.assertEqual(self.calls, ["tts-a"])  # the second read came from the cache

    def test_always_asks_for_thai_and_copes_with_a_model_without_it(self):
        bodies = []

        def handler(request):
            body = json.loads(request.content)
            bodies.append(body["generationConfig"]["speechConfig"].get("languageCode"))
            if body["generationConfig"]["speechConfig"].get("languageCode"):
                return httpx.Response(400, json={"error": {"message": "languageCode is not supported for this model"}})
            return _audio("audio/wav", b"RIFF....WAVEdata")

        with patch.dict(os.environ, {"GEMINI_API_KEY": "k", "GEMINI_TTS_MODELS": "tts-a", "PCB_TTS_ENGINES": "gemini"}), self._client(handler):
            _, model, _ = tts_service.synthesize("ผล PASS ครับ")
        self.assertEqual(model, "tts-a")
        self.assertEqual(bodies, ["th-TH", None])

    def test_out_of_quota_model_is_skipped(self):
        def handler(request):
            model = request.url.path.split("/")[-1].split(":")[0]
            self.calls.append(model)
            return httpx.Response(429, json=QUOTA) if model == "tts-a" else _audio("audio/wav", b"RIFF....WAVEdata")

        with patch.dict(os.environ, {"GEMINI_API_KEY": "k", "GEMINI_TTS_MODELS": "tts-a,tts-b", "PCB_TTS_ENGINES": "gemini"}), self._client(handler):
            _, model, _ = tts_service.synthesize("หนึ่ง")
            tts_service.synthesize("สอง")
        self.assertEqual(model, "tts-b")
        self.assertEqual(self.calls, ["tts-a", "tts-b", "tts-b"])  # tts-a rests after its quota error

    def test_no_key_or_no_model_means_browser_voice(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "", "PCB_TTS_ENGINES": "gemini"}):
            with self.assertRaises(tts_service.TTSUnavailable):
                tts_service.synthesize("ทดสอบ")
        with patch.dict(os.environ, {"GEMINI_API_KEY": "k", "GEMINI_TTS_MODELS": "tts-a", "PCB_TTS_ENGINES": "gemini"}), \
                self._client(lambda r: httpx.Response(503, json={"error": {"message": "overloaded"}})):
            with self.assertRaises(tts_service.TTSUnavailable):
                tts_service.synthesize("ทดสอบ")

    def _edge(self, chunks=None, error=None):
        """A stand-in for edge_tts.Communicate: yields `chunks` or raises `error`."""
        calls = self.calls

        class Communicate:
            def __init__(self, text, voice):
                calls.append(("edge", voice))

            async def stream(self):
                if error:
                    raise error
                for c in chunks or []:
                    yield c

        import types
        return patch.dict("sys.modules", {"edge_tts": types.SimpleNamespace(Communicate=Communicate)})

    def test_edge_voice_first_as_mp3_and_cached(self):
        audio_chunks = [{"type": "WordBoundary"}, {"type": "audio", "data": b"ID3mp3"}, {"type": "audio", "data": b"-more"}]
        with patch.dict(os.environ, {"PCB_TTS_ENGINES": "edge,gemini", "EDGE_TTS_VOICE": "th-TH-NiwatNeural"}), self._edge(audio_chunks):
            audio, who, mime = tts_service.synthesize("สวัสดีครับ")
            again, cached, mime2 = tts_service.synthesize("สวัสดีครับ")
        self.assertEqual((audio, who, mime), (b"ID3mp3-more", "edge · th-TH-NiwatNeural", "audio/mpeg"))
        self.assertEqual((again, cached, mime2), (audio, "cache", "audio/mpeg"))
        self.assertEqual(self.calls, [("edge", "th-TH-NiwatNeural")])

    def test_edge_failure_falls_back_to_gemini_and_rests_edge(self):
        def handler(request):
            self.calls.append("gemini")
            return _audio("audio/wav", b"RIFF....WAVEdata")

        env = {"PCB_TTS_ENGINES": "edge,gemini", "GEMINI_API_KEY": "k", "GEMINI_TTS_MODELS": "tts-a"}
        with patch.dict(os.environ, env), self._edge(error=ConnectionError("blocked")), self._client(handler):
            _, who, mime = tts_service.synthesize("หนึ่ง")
            tts_service.synthesize("สอง")
        self.assertEqual((who, mime), ("tts-a", "audio/wav"))
        self.assertEqual(self.calls, [("edge", tts_service.edge_voice()), "gemini", "gemini"])  # edge rests after failing

    def test_route_returns_wav_or_503(self):
        client = TestClient(app)
        with patch.object(tts_service, "synthesize", return_value=(b"RIFFxxxxWAVE", "tts-a", "audio/wav")):
            res = client.post("/api/chat/tts", json={"text": "สวัสดี"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["content-type"], "audio/wav")
        self.assertEqual(res.headers["x-tts-model"], "tts-a")
        with patch.object(tts_service, "synthesize", side_effect=tts_service.TTSUnavailable("quota")):
            self.assertEqual(client.post("/api/chat/tts", json={"text": "สวัสดี"}).status_code, 503)

    def test_internet_requests_need_the_lease(self):
        from app.core import access

        self.assertTrue(access.needs_lease("POST", "/api/chat/tts"))


if __name__ == "__main__":
    unittest.main()
