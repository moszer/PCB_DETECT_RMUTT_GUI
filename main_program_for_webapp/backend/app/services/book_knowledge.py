"""Page-cited retrieval from bundled thesis text or a station-local PDF.

Every page of the book is searchable: cover, approval, abstract, acknowledgements, table of
contents, all chapters, bibliography, appendix and the authors' biographies. A local PDF in
ignored station storage overrides the bundled text. Only selected excerpts are sent to the
configured AI provider.

Personal details are removed on the way in (from the PDF and from the bundled text alike):
student IDs, birth dates, birthplaces, home addresses, phone numbers and e-mail. The bundled
text lives in a public repository and the excerpts go to a third-party AI.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from ..config import STORAGE_DIR

BOOK_TITLE = "ระบบตรวจสอบความสมบูรณ์ของแผ่น PCB ด้วยปัญญาประดิษฐ์"
DEFAULT_BOOK_PATH = STORAGE_DIR / "knowledge" / "project_book.pdf"
BUNDLED_INDEX_PATH = Path(__file__).resolve().parents[1] / "resources" / "project_book_pages.json"
# PDF page 13 is page 1 of chapter 1; the pages before it are numbered with Thai letters
# (ก = PDF page 2: the inner title page).
BODY_OFFSET = 12
FRONT_LETTERS = "กขคงจฉชซฌญฎฏฐ"
MAX_RESULTS = 5
MAX_PAGES_PER_READ = 10
_lock = threading.Lock()
_cache: tuple[tuple[str, int, int], list[dict[str, Any]]] | None = None
_WORD = re.compile(r"[a-z0-9]+|[\u0e00-\u0e7f]+", re.I)
_NOISE = ("ในเล่ม", "จากเล่ม", "โครงงานนี้", "ปริญญานิพนธ์", "ช่วยบอก", "เกี่ยวกับ", "อธิบาย", "เท่าไร", "เท่าไหร่")
_HIDDEN = "[ไม่เปิดเผย]"
_REDACT = [
    (re.compile(r"(รหัสนักศึกษา)\s*[\d\s-]{6,}"), rf"\1 {_HIDDEN} "),
    (re.compile(r"\b\d{12}-\d\b"), _HIDDEN),
    # Biography: birth date, birthplace and address run up to the education history.
    (re.compile(r"วัน-?เดือน-?ปี\s*เกิด.*?(?=ประวัติการศึกษา|$)", re.S), f"วันเกิด สถานที่เกิด และที่อยู่ {_HIDDEN} "),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), _HIDDEN),
    (re.compile(r"(?<!\d)0\d{1,2}[- ]?\d{3}[- ]?\d{3,4}(?!\d)"), _HIDDEN),
]
# "1 บทที่ 1 บทนำ 1.1 ..." -> 1, "บทนำ" (the title is one Thai run: no spaces inside)
_CHAPTER = re.compile(r"^\s*\d*\s*บทที่\s*(\d+)\s+(\S+)")


def _book_path() -> Path:
    return Path(os.environ.get("PCB_BOOK_PDF_PATH") or DEFAULT_BOOK_PATH).expanduser()


def _clean(text: str) -> str:
    text = " ".join(text.split())
    for rx, sub in _REDACT:
        text = rx.sub(sub, text)
    return " ".join(text.split())


def page_label(pdf_page: int) -> Optional[str]:
    """The number printed on the page: Thai letters before chapter 1, digits after."""
    if pdf_page > BODY_OFFSET:
        return str(pdf_page - BODY_OFFSET)
    if pdf_page >= 2 and pdf_page - 2 < len(FRONT_LETTERS):
        return FRONT_LETTERS[pdf_page - 2]
    return None  # the cover


def _entry(number: int, text: str) -> Optional[dict[str, Any]]:
    content = _clean(text)
    if len(content) < 8:  # blank pages (e.g. appendix pages with only a number)
        return None
    return {"pdf_page": number, "book_page": number - BODY_OFFSET if number > BODY_OFFSET else None,
            "label": page_label(number), "text": content, "features": _features(content)}


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
    pages = [e for idx, page in enumerate(reader.pages) if (e := _entry(idx + 1, page.extract_text() or ""))]
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
            pages = [e for item in data["pages"] if (e := _entry(int(item["pdf_page"]), item["text"]))]
            if not pages:
                raise ValueError("ดัชนีข้อมูลเล่มไม่มีเนื้อหาที่ค้นหาได้")
        _cache = (key, pages)
        return pages


def _citation(pdf_page: int) -> str:
    label = page_label(pdf_page)
    return f"PDF หน้า {pdf_page}" + (f" (หน้า {label} ในเล่ม)" if label else " (ปก)")


def _public_page(page: dict[str, Any], limit: int = 2200) -> dict[str, Any]:
    return {"pdf_page": page["pdf_page"], "book_page": page["book_page"], "page_label": page["label"],
            "citation": _citation(page["pdf_page"]), "text": page["text"][:limit]}


def chapters(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chapter map from the pages that open with "บทที่ N": title and PDF page range."""
    found = []
    for p in pages:
        m = _CHAPTER.match(p["text"]) if p["pdf_page"] > BODY_OFFSET else None
        if m and all(int(m.group(1)) != c["chapter"] for c in found):
            found.append({"chapter": int(m.group(1)), "title": m.group(2), "pdf_from": p["pdf_page"]})
    last = max(p["pdf_page"] for p in pages) if pages else 0
    for p in pages:  # what follows the last chapter
        if p["pdf_page"] > (found[-1]["pdf_from"] if found else last) and p["text"].lstrip("0123456789 ").startswith("บรรณานุกรม"):
            last = p["pdf_page"] - 1
            break
    for i, c in enumerate(found):
        c["pdf_to"] = found[i + 1]["pdf_from"] - 1 if i + 1 < len(found) else last
    return found


def _sections(pages: list[dict[str, Any]]) -> dict[str, list[int]]:
    """Where the parts outside the chapters are, by their heading words."""
    # Checked in this order: a contents page lists the other headings near its top.
    heads = {"สารบัญ": "contents", "บทคัดย่อ": "abstract", "Abstract": "abstract", "ABSTRACT": "abstract",
             "กิตติกรรมประกาศ": "acknowledgements", "คำอธิบายสัญลักษณ์": "abbreviations", "บรรณานุกรม": "bibliography",
             "ภาคผนวก": "appendix", "ภาคพนก": "appendix", "ประวัติผู้จัดทำ": "authors"}
    out: dict[str, list[int]] = {}
    for p in pages:
        start = p["text"][:25]  # the page number and the heading
        for word, key in heads.items():
            if word in start:
                out.setdefault(key, []).append(p["pdf_page"])
                break
    if not out.get("abstract"):  # the abstract page is headed by the thesis-title block
        out["abstract"] = [p["pdf_page"] for p in pages if p["pdf_page"] <= BODY_OFFSET and "บทคัดย่อ" in p["text"]
                           and p["pdf_page"] not in out.get("contents", [])][:2]
    return out


def get_project_book_overview() -> dict[str, Any]:
    pages = _load()
    by_number = {p["pdf_page"]: p for p in pages}
    parts = _sections(pages)
    chapter_map = chapters(pages)
    first = lambda nums, limit: [_public_page(by_number[n], limit) for n in nums if n in by_number]  # noqa: E731
    last_chapter = chapter_map[-1] if chapter_map else None
    return {
        "title": BOOK_TITLE, "pages_indexed": len(pages), "pdf_pages": max(by_number) if by_number else 0,
        "title_pages": first([n for n in (1, 2, 3, 4) if n in by_number], 1200),
        "abstract": first(parts.get("abstract", [])[:2], 2400),
        "chapters": chapter_map,
        "sections": parts,
        "contents": first(parts.get("contents", [])[:2], 1800),
        "conclusion": first([last_chapter["pdf_from"]] if last_chapter else [], 1800),
        "note": ("หน้าที่ระบุคือเลขหน้า PDF และเลขหน้าที่พิมพ์ในเล่ม; อ่านหน้าเต็มด้วย read_project_book_page (ได้ถึง "
                 f"{MAX_PAGES_PER_READ} หน้าต่อครั้ง); ข้อมูลส่วนตัว (รหัสนักศึกษา วันเกิด ที่อยู่) ไม่ได้เก็บไว้; "
                 "ข้อมูลผลทดลองที่ยังระบุว่ารอผลจริงหรือเป็นช่องเติม ห้ามสรุปเป็นผลที่วัดได้แล้ว"),
    }


def read_project_book_page(pdf_page: int, to_page: Optional[int] = None) -> dict[str, Any]:
    """One page, or a run of up to MAX_PAGES_PER_READ pages (pdf_page..to_page)."""
    start = int(pdf_page)
    end = int(to_page) if to_page else start
    if end < start:
        start, end = end, start
    end = min(end, start + MAX_PAGES_PER_READ - 1)
    pages = _load()
    total = max((p["pdf_page"] for p in pages), default=0)
    if not 1 <= start <= total:
        return {"error": f"เล่มมี PDF หน้า 1–{total}"}
    found = [p for p in pages if start <= p["pdf_page"] <= end]
    if not found:
        return {"error": f"PDF หน้า {start}" + (f"–{end}" if end != start else "") + " ไม่มีข้อความ (หน้าว่างหรือเป็นรูปภาพ)"}
    if start == end:
        return _public_page(found[0], 6500)
    return {"pages": [_public_page(p, 6500) for p in found], "next_page": end + 1 if end < total else None}


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
