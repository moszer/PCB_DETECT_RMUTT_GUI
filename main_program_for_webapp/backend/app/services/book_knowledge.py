"""Page-cited retrieval from bundled thesis text or a station-local PDF.

The bundled text contains content pages only. A local PDF in ignored station storage
overrides it. Only selected excerpts are sent to the configured AI provider.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Any

from ..config import STORAGE_DIR

BOOK_TITLE = "ระบบตรวจสอบความสมบูรณ์ของแผ่น PCB ด้วยปัญญาประดิษฐ์"
DEFAULT_BOOK_PATH = STORAGE_DIR / "knowledge" / "project_book.pdf"
BUNDLED_INDEX_PATH = Path(__file__).resolve().parents[1] / "resources" / "project_book_pages.json"
# PDF pages 1–6 contain signatures, student IDs and acknowledgements; 94–97
# contain author biographies. The searchable material is the TOC and chapters.
FIRST_CONTENT_PAGE = 7
LAST_CONTENT_PAGE = 88
MAX_RESULTS = 5
_lock = threading.Lock()
_cache: tuple[tuple[str, int, int], list[dict[str, Any]]] | None = None
_WORD = re.compile(r"[a-z0-9]+|[\u0e00-\u0e7f]+", re.I)
_NOISE = ("ในเล่ม", "จากเล่ม", "โครงงานนี้", "ปริญญานิพนธ์", "ช่วยบอก", "เกี่ยวกับ", "อธิบาย", "เท่าไร", "เท่าไหร่")


def _book_path() -> Path:
    return Path(os.environ.get("PCB_BOOK_PDF_PATH") or DEFAULT_BOOK_PATH).expanduser()


def _clean(text: str) -> str:
    return " ".join(text.split())


def _features(text: str) -> Counter[str]:
    """Thai character grams plus whole English/number words; no tokenizer needed."""
    terms: Counter[str] = Counter()
    for word in _WORD.findall(text.lower()):
        if word.isascii():
            if len(word) > 1:
                terms[word] += 1
        else:
            for n in (2, 3, 4):
                terms.update(word[i:i+n] for i in range(max(0, len(word) - n + 1)))
    return terms


def _read_pages(path: Path) -> list[dict[str, Any]]:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("ยังไม่มี pypdf; ติดตั้ง dependency จาก backend/requirements.txt") from None
    reader = PdfReader(path)
    pages = []
    for idx in range(FIRST_CONTENT_PAGE - 1, min(LAST_CONTENT_PAGE, len(reader.pages))):
        content = _clean(reader.pages[idx].extract_text() or "")
        if len(content) >= 30:
            pages.append({"pdf_page": idx + 1, "book_page": idx + 1 - 12 if idx + 1 >= 13 else None,
                          "text": content, "features": _features(content)})
    if not pages:
        raise ValueError("PDF ไม่มีข้อความที่ค้นหาได้ในช่วงเนื้อหา; อาจต้องใช้ OCR ก่อน")
    return pages


def book_status() -> dict[str, Any]:
    try:
        pages = _load()
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        return {"available": False, "message": str(exc)}
    return {"available": True, "title": BOOK_TITLE, "pages_indexed": len(pages),
            "source": "station_pdf" if _book_path().is_file() else "bundled_text"}


def _load() -> list[dict[str, Any]]:
    global _cache
    pdf_path = _book_path()
    path = pdf_path if pdf_path.is_file() else BUNDLED_INDEX_PATH
    try:
        stat = path.stat()
    except FileNotFoundError:
        raise FileNotFoundError("ไม่พบข้อมูลเล่ม; อัปเดตโค้ดสถานี หรือวาง PDF ไว้ใน backend/data/knowledge/project_book.pdf") from None
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    with _lock:
        if _cache and _cache[0] == key:
            return _cache[1]
        if path == pdf_path:
            pages = _read_pages(path)
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
            pages = []
            for item in data["pages"]:
                number = int(item["pdf_page"])
                if not FIRST_CONTENT_PAGE <= number <= LAST_CONTENT_PAGE:
                    continue
                content = _clean(item["text"])
                if len(content) >= 30:
                    pages.append({"pdf_page": number, "book_page": number - 12 if number >= 13 else None,
                                  "text": content, "features": _features(content)})
            if not pages:
                raise ValueError("ดัชนีข้อมูลเล่มไม่มีเนื้อหาที่ค้นหาได้")
        _cache = (key, pages)
        return pages


def _public_page(page: dict[str, Any], limit: int = 2200) -> dict[str, Any]:
    return {"pdf_page": page["pdf_page"], "book_page": page["book_page"],
            "citation": f"PDF หน้า {page['pdf_page']}", "text": page["text"][:limit]}


def get_project_book_overview() -> dict[str, Any]:
    pages = _load()
    by_number = {p["pdf_page"]: p for p in pages}
    return {"title": BOOK_TITLE, "pages_indexed": len(pages),
            "contents": [_public_page(by_number[n], 1800) for n in (7, 8) if n in by_number],
            "conclusion": [_public_page(by_number[84], 1800)] if 84 in by_number else [],
            "note": "หน้าที่ระบุคือเลขหน้า PDF; ข้อมูลผลทดลองที่ยังระบุว่ารอผลจริงหรือเป็นช่องเติม ห้ามสรุปเป็นผลที่วัดได้แล้ว"}


def read_project_book_page(pdf_page: int) -> dict[str, Any]:
    page_number = int(pdf_page)
    if not FIRST_CONTENT_PAGE <= page_number <= LAST_CONTENT_PAGE:
        return {"error": f"อ่านได้เฉพาะเนื้อหา PDF หน้า {FIRST_CONTENT_PAGE}–{LAST_CONTENT_PAGE}"}
    page = next((p for p in _load() if p["pdf_page"] == page_number), None)
    return _public_page(page, 6500) if page else {"error": f"PDF หน้า {page_number} ไม่มีข้อความให้ค้นหา"}


def search_project_book(query: str) -> dict[str, Any]:
    query = str(query or "").strip()[:250]
    if len(query) < 2:
        return {"error": "กรุณาระบุคำค้นอย่างน้อย 2 ตัวอักษร"}
    pages = _load()
    query_text = query.lower()
    for noise in _NOISE:
        query_text = query_text.replace(noise, " ")
    q = _features(query_text)
    if not q:
        return {"results": [], "note": "ไม่พบคำค้นที่ใช้ค้นหาได้"}
    df = Counter(term for page in pages for term in page["features"])
    ranked = []
    for page in pages:
        score = sum(min(page["features"].get(term, 0), 3) *
                    math.log1p((len(pages) + 1) / (df[term] + 1)) * (1.3 if len(term) >= 4 else 1)
                    for term in q)
        if query_text.strip() and query_text.strip() in page["text"].lower():
            score += 25
        if score:
            ranked.append((score, page))
    ranked.sort(key=lambda entry: entry[0], reverse=True)
    results = [_public_page(page, 2400) for _, page in ranked[:MAX_RESULTS]]
    return {"title": BOOK_TITLE, "query": query, "results": results,
            "note": "เป็นข้อความจาก PDF ที่ดึงอัตโนมัติ อาจผิดเพราะรูป/ตารางหรือการแยกข้อความ; ตรวจหน้าที่อ้างเมื่อค่าดูขัดกัน"}
