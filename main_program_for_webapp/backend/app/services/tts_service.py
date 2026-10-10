"""Natural-sounding speech for the AI answers.

Engines are tried in order (PCB_TTS_ENGINES, default "edge,gemini"):
- edge: Microsoft Edge's read-aloud voices (edge-tts), free, no key or quota; an unofficial
  service, so Gemini and then the browser's own voice take over if it stops answering.
- gemini: Gemini TTS with the chat key (daily quota per model). Models are tried in order; a
  model out of quota, busy or silent rests for a while (chat_service.rest).

The browser sends one short piece of an answer at a time (it plays a piece while fetching
the next). Audio is cached per (engine, voice, language, text) in .cache/tts, so reading the
same answer again is instant. The cache sits outside the station data, so backups don't grow.

Gemini's newer models answer WAV, older ones raw 16-bit PCM ("audio/L16;rate=24000"), which
gets a WAV header; Edge answers MP3.
"""
from __future__ import annotations

import asyncio
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

DEFAULT_ENGINES = "edge,gemini"
DEFAULT_EDGE_VOICE = "th-TH-NiwatNeural"  # male, ~1 s a piece; or th-TH-PremwadeeNeural (female, ~4 s)
EDGE_TIMEOUT_SEC = 20.0
EDGE_REST_SEC = 300.0
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
    """No engine could speak right now: the browser uses its own voice instead."""


def engines() -> List[str]:
    raw = os.environ.get("PCB_TTS_ENGINES") or DEFAULT_ENGINES
    return [e.strip().lower() for e in raw.split(",") if e.strip().lower() in ("edge", "gemini")]


def edge_voice() -> str:
    return (os.environ.get("EDGE_TTS_VOICE") or DEFAULT_EDGE_VOICE).strip()


def _edge_ready() -> bool:
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        return False
    return chat_service._resting.get("edge-tts", 0.0) <= time.monotonic()


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
    return any(e == "edge" and _edge_ready() or e == "gemini" and os.environ.get("GEMINI_API_KEY") for e in engines())


def engine_name() -> Optional[str]:
    for e in engines():
        if e == "edge" and _edge_ready():
            return f"edge · {edge_voice()}"
        if e == "gemini" and os.environ.get("GEMINI_API_KEY"):
            return f"gemini · {model_name()} · {voice()}"
    return None


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


def _cache_path(engine: str, text: str) -> Path:
    who = edge_voice() if engine == "edge" else f"{voice()}|{language()}"
    key = hashlib.sha256(f"{engine}|{who}|{text}".encode("utf-8")).hexdigest()[:32]
    return CACHE_DIR / f"{key}.{'mp3' if engine == 'edge' else 'wav'}"


def _store(path: Path, audio: bytes) -> None:
    with _lock:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        _prune()


def _prune() -> None:
    files = sorted([*CACHE_DIR.glob("*.wav"), *CACHE_DIR.glob("*.mp3")], key=lambda p: p.stat().st_mtime)
    for old in files[: max(0, len(files) - CACHE_MAX_FILES)]:
        old.unlink(missing_ok=True)


MIME = {"mp3": "audio/mpeg", "wav": "audio/wav"}


def synthesize(text: str) -> Tuple[bytes, str, str]:
    """(audio, what made it, mime type) for `text`; "cache" when it was stored before."""
    text = " ".join(str(text or "").split())[:MAX_CHARS]
    if not text:
        raise ValueError("empty text")
    problems = []
    for engine in engines():
        path = _cache_path(engine, text)
        if path.is_file():
            path.touch()
            return path.read_bytes(), "cache", MIME[path.suffix[1:]]
        try:
            if engine == "edge":
                audio, who = _edge(text)
            else:
                audio, who = _gemini(text)
        except TTSUnavailable as exc:
            problems.append(str(exc))
            continue
        _store(path, audio)
        return audio, who, MIME[path.suffix[1:]]
    raise TTSUnavailable(" · ".join(problems) or "ไม่ได้เปิดเสียง AI (PCB_TTS_ENGINES)")


def _edge(text: str) -> Tuple[bytes, str]:
    if not _edge_ready():
        raise TTSUnavailable("Edge TTS ไม่พร้อม")
    import edge_tts

    async def run() -> bytes:
        data = bytearray()
        async for chunk in edge_tts.Communicate(text, edge_voice()).stream():
            if chunk.get("type") == "audio":
                data += chunk["data"]
        return bytes(data)

    try:
        audio = asyncio.run(asyncio.wait_for(run(), EDGE_TIMEOUT_SEC))
    except Exception as exc:  # network, service change, timeout: rest it, try the next engine
        chat_service.rest("edge-tts", EDGE_REST_SEC, f"failed ({exc.__class__.__name__})")
        raise TTSUnavailable(f"Edge TTS ใช้ไม่ได้: {exc.__class__.__name__}") from None
    if not audio:
        chat_service.rest("edge-tts", EDGE_REST_SEC, "sent no audio")
        raise TTSUnavailable("Edge TTS ไม่ได้ส่งเสียงกลับมา")
    return audio, f"edge · {edge_voice()}"


def _gemini(text: str) -> Tuple[bytes, str]:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise TTSUnavailable("ไม่มี Gemini API key")

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
            return audio, model
    raise TTSUnavailable(f"Gemini TTS ไม่ว่างตอนนี้ — {last}")


def model_name() -> Optional[str]:
    listed = models()
    return listed[0] if listed else None
