"""Natural-sounding speech for the AI answers with Gemini TTS.

The browser sends one short piece of an answer at a time (it plays a piece while fetching
the next). Models are tried in order; a model out of quota, busy or silent rests for a while
(chat_service.rest), like the chat models. Audio is cached per (model list, voice, text) in
.cache/tts, so reading the same answer again costs no quota. The cache sits outside the
station data, so backups don't grow with it.

Newer models answer WAV; older ones raw 16-bit PCM ("audio/L16;rate=24000"), which gets a
WAV header so every browser can play it.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import struct
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

import httpx

from ..config import BACKEND_ROOT
from . import chat_service

logger = logging.getLogger(__name__)

DEFAULT_MODELS = "gemini-3.8-flash-tts,gemini-3.8-flash-lite-tts,gemini-2.5-flash-preview-tts"
DEFAULT_VOICE = "Kore"
# Always Thai: left to itself the model guesses the language per sentence, and an answer with
# English words in it (PASS, Yield, YOLO) could switch accent.
DEFAULT_LANGUAGE = "th-TH"
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
CACHE_DIR = BACKEND_ROOT.parent / ".cache" / "tts"
CACHE_MAX_FILES = 400
MAX_CHARS = 600
TIMEOUT_SEC = 30.0
_lock = threading.Lock()


class TTSUnavailable(Exception):
    """No key, or no model could speak right now: the browser uses its own voice instead."""


def models() -> List[str]:
    raw = os.environ.get("GEMINI_TTS_MODELS") or DEFAULT_MODELS
    listed = [m.strip() for m in raw.split(",") if m.strip()]
    now = time.monotonic()
    awake = [m for m in listed if chat_service._resting.get(m, 0.0) <= now]
    return awake or listed


def voice() -> str:
    return (os.environ.get("GEMINI_TTS_VOICE") or DEFAULT_VOICE).strip()


def language() -> str:
    return (os.environ.get("GEMINI_TTS_LANGUAGE") or DEFAULT_LANGUAGE).strip()


def available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def wav_from_pcm(pcm: bytes, rate: int = 24000, channels: int = 1, bits: int = 16) -> bytes:
    block = channels * bits // 8
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack(
        "<IHHIIHH", 16, 1, channels, rate, rate * block, block, bits
    ) + b"data" + struct.pack("<I", len(pcm))
    return header + pcm


def _to_wav(data: bytes, mime: str) -> bytes:
    mime = mime.lower()
    if "wav" in mime or data[:4] == b"RIFF":
        return data
    rate = int(m.group(1)) if (m := re.search(r"rate=(\d+)", mime)) else 24000
    channels = int(m.group(1)) if (m := re.search(r"channels=(\d+)", mime)) else 1
    return wav_from_pcm(data, rate, channels)


def _cache_path(text: str) -> Path:
    key = hashlib.sha256(f"{voice()}|{language()}|{text}".encode("utf-8")).hexdigest()[:32]
    return CACHE_DIR / f"{key}.wav"


def _prune() -> None:
    files = sorted(CACHE_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime)
    for old in files[: max(0, len(files) - CACHE_MAX_FILES)]:
        old.unlink(missing_ok=True)


def synthesize(text: str) -> Tuple[bytes, str]:
    """WAV audio of `text` and the model that made it ("cache" when it was stored)."""
    text = " ".join(str(text or "").split())[:MAX_CHARS]
    if not text:
        raise ValueError("empty text")
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise TTSUnavailable("ไม่มี Gemini API key")
    path = _cache_path(text)
    if path.is_file():
        path.touch()
        return path.read_bytes(), "cache"

    def body(with_language: bool):
        speech = {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice()}}}
        if with_language and language():
            speech["languageCode"] = language()
        return {"contents": [{"parts": [{"text": text}]}], "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": speech}}

    last = ""
    with httpx.Client(timeout=httpx.Timeout(TIMEOUT_SEC, connect=10)) as client:
        for model in models():
            try:
                res = client.post(URL.format(model=model), headers={"x-goog-api-key": key}, json=body(True))
                if res.status_code == 400 and "language" in res.text.lower():
                    # A model that doesn't take a language code: ask again without it.
                    logger.info("TTS model %s rejects languageCode; retrying without it", model)
                    res = client.post(URL.format(model=model), headers={"x-goog-api-key": key}, json=body(False))
            except httpx.TimeoutException:
                chat_service.rest(model, chat_service.TIMEOUT_REST_SEC, "did not answer (TTS)")
                last = f"{model} ไม่ตอบ"
                continue
            except httpx.HTTPError as exc:
                raise TTSUnavailable(f"เชื่อมต่อ Gemini ไม่ได้: {exc.__class__.__name__}") from None
            if res.status_code != 200:
                last = f"HTTP {res.status_code} ({model})"
                wait = chat_service.quota_rest(res.status_code, res.text)
                if wait:
                    chat_service.rest(model, wait, "is out of quota (TTS)")
                elif res.status_code in chat_service.RETRYABLE or res.status_code in chat_service.UNAVAILABLE:
                    chat_service.rest(model, chat_service.BUSY_REST_SEC, f"is busy ({res.status_code}, TTS)")
                else:
                    raise TTSUnavailable(f"Gemini TTS ตอบไม่ได้: {last}: {res.text[:200]}")
                continue
            try:
                part = res.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
                audio = _to_wav(base64.b64decode(part["data"]), part.get("mimeType", ""))
            except (KeyError, IndexError, ValueError, TypeError):
                last = f"{model} ไม่ได้ส่งเสียงกลับมา"
                continue
            with _lock:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                path.write_bytes(audio)
                _prune()
            return audio, model
    raise TTSUnavailable(f"Gemini TTS ไม่ว่างตอนนี้ — {last}")


def model_name() -> Optional[str]:
    listed = models()
    return listed[0] if listed else None
