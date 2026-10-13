"""One scan run as an A4 PDF report, drawn on the station (no browser), to send to Telegram.

The same report as the print view of a run (frontend RunReport.tsx): header with the verdict,
the run's details, the points that did not pass and which components, and every point's
picture; then a page per point that did not pass, with its picture large enough to read.

Drawn with Pillow (Thai text laid out by libraqm when Pillow has it) on 150 dpi pages.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

from ..config import REPO_ROOT, settings

DPI = 150
W, H = 1240, 1754  # A4 portrait at 150 dpi
M = 72  # page margin
INK, MUTED, LINE, SOFT = (17, 24, 39), (100, 116, 139), (203, 213, 225), (241, 245, 249)
VERDICT_COLOR = {"PASS": (21, 128, 61), "FAIL": (185, 28, 28), "REVIEW": (180, 83, 9), "ERROR": (109, 40, 217)}
VERDICT_LABEL = {"PASS": "ผ่าน", "FAIL": "ไม่ผ่าน", "REVIEW": "ตรวจซ้ำ", "ERROR": "ผิดพลาด"}
STATUS_TEXT = {"aborted": "หยุดกลางคัน", "error": "ผิดพลาด", "running": "กำลังสแกน"}
MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
LOGO = REPO_ROOT / "frontend" / "public" / "rmutt-logo.png"

# Fonts: (file, face index); the first that exists is used. Noto Sans Thai has only Thai letters,
# so text is drawn in runs: Thai in a Thai font, everything else (Latin, digits) in a Latin one.
FONTS = {
    "thai": [("/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf", 0), ("/usr/share/fonts/opentype/noto/NotoSansThai-Regular.ttf", 0),
             ("/System/Library/Fonts/Supplemental/Thonburi.ttc", 0), ("/Library/Fonts/Thonburi.ttc", 0)],
    "thai-bold": [("/usr/share/fonts/truetype/noto/NotoSansThai-Bold.ttf", 0), ("/usr/share/fonts/opentype/noto/NotoSansThai-Bold.ttf", 0),
                  ("/System/Library/Fonts/Supplemental/Thonburi.ttc", 1), ("/Library/Fonts/Thonburi.ttc", 1)],
    "latin": [("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", 0), ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
              ("/System/Library/Fonts/Helvetica.ttc", 0)],
    "latin-bold": [("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf", 0), ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
                   ("/System/Library/Fonts/Helvetica.ttc", 1)],
    "mono": [("/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf", 0), ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 0),
             ("/System/Library/Fonts/Menlo.ttc", 0)],
}
FC_QUERY = {"thai": ":lang=th", "thai-bold": ":lang=th:bold", "latin": "sans", "latin-bold": "sans:bold", "mono": "monospace"}
_files: Dict[str, Optional[Tuple[str, int]]] = {}
_faces: Dict[Tuple[str, int], "Face"] = {}


def _font_file(kind: str) -> Optional[Tuple[str, int]]:
    if kind in _files:
        return _files[kind]
    found = next(((p, i) for p, i in FONTS[kind] if os.path.isfile(p)), None)
    if not found and shutil.which("fc-match"):  # another Linux: ask fontconfig
        try:
            out = subprocess.run(["fc-match", "-f", "%{file}", FC_QUERY[kind]], capture_output=True, text=True, timeout=5).stdout.strip()
            found = (out, 0) if out and os.path.isfile(out) else None
        except (OSError, subprocess.SubprocessError):
            found = None
    _files[kind] = found
    return found


def _load(kind: str, size: int):
    found = _font_file(kind)
    try:
        return ImageFont.truetype(found[0], size, index=found[1]) if found else ImageFont.load_default(size)
    except OSError:
        return ImageFont.load_default(size)


def _is_thai(ch: str) -> bool:
    return "\u0e00" <= ch <= "\u0e7f"


class Face:
    """Text in one size and weight: Thai runs in the Thai font, the rest in the Latin (or mono) font,
    on one baseline."""

    def __init__(self, size: int, kind: str):
        self.thai = _load("thai-bold" if kind == "bold" else "thai", size)
        self.latin = _load({"bold": "latin-bold", "mono": "mono"}.get(kind, "latin"), size)
        metrics = [f.getmetrics() for f in (self.thai, self.latin) if hasattr(f, "getmetrics")]
        self.ascent = max((a for a, _ in metrics), default=size)
        self.descent = max((d for _, d in metrics), default=0)

    def runs(self, text: str) -> List[Tuple[str, Any]]:
        out: List[Tuple[str, Any]] = []
        for c in _clusters(text):
            thai = _is_thai(c[0])
            f = self.thai if thai else self.latin
            if out and (out[-1][1] is f or c == " "):  # spaces stay with the run they are in
                out[-1] = (out[-1][0] + c, out[-1][1])
            else:
                out.append((c, f))
        return out

    def getlength(self, text: str) -> float:
        return sum(f.getlength(t) for t, f in self.runs(text))

    def draw(self, d: ImageDraw.ImageDraw, xy, text: str, fill=INK, anchor: str = "la"):
        """anchor as Pillow's: horizontal l / m / r, vertical a (top) / m / s (baseline) / d (bottom)."""
        x, y = xy
        width = self.getlength(text)
        x -= {"l": 0, "m": width / 2, "r": width}[anchor[0]]
        base = {"a": y + self.ascent, "m": y + (self.ascent - self.descent) / 2, "s": y, "d": y - self.descent}[anchor[1]]
        for t, f in self.runs(text):
            d.text((x, base), t, font=f, fill=fill, anchor="ls")
            x += f.getlength(t)


def font(size: int, kind: str = "regular") -> Face:
    key = (kind, size)
    if key not in _faces:
        _faces[key] = Face(size, kind)
    return _faces[key]


def thai_datetime(ts: float) -> str:
    t = time.localtime(ts)
    return f"{t.tm_mday} {MONTHS[t.tm_mon - 1]} {t.tm_year + 543} {t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}"


def _clusters(text: str) -> List[str]:
    """Characters with their combining marks (Thai vowels and tone marks) kept together."""
    out: List[str] = []
    for ch in text:
        if out and unicodedata.category(ch) in ("Mn", "Mc", "Me"):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def wrap(text: str, f, width: int) -> List[str]:
    """Lines that fit in width; breaks after a space when it can, else between characters (Thai
    has no spaces between words), never between a letter and its vowel or tone mark."""
    lines: List[str] = []
    for para in str(text).split("\n"):
        line: List[str] = []
        brk = -1  # break point: just after the last space on the line
        for c in _clusters(para):
            if not line or f.getlength("".join(line) + c) <= width:
                line.append(c)
                if c == " ":
                    brk = len(line)
                continue
            if brk > 0:
                lines.append("".join(line[:brk]).rstrip())
                line = line[brk:] + [c]
            else:
                lines.append("".join(line))
                line = [c]
            brk = max((i + 1 for i, x in enumerate(line) if x == " "), default=-1)
        lines.append("".join(line))
    return lines


def problems_of(point: Dict[str, Any], limit: int = 12) -> str:
    """The components that failed at a point, as the print view writes them."""
    bad = [c for c in point.get("component_eval") or [] if c.get("status") in ("missing", "wrong")]
    if not bad:
        s = point.get("summary") or {}
        return point.get("reason") or f"ขาด {s.get('missing', 0)} · ผิด {s.get('wrong', 0)} · เกิน {s.get('extra', 0)}"
    parts = []
    for c in bad[:limit]:
        e = c.get("expected") or {}
        what = "ขาด" if c["status"] == "missing" else "ผิดชนิด" + (f" (พบ {c['wrong_label']})" if c.get("wrong_label") else "")
        parts.append(f"{e.get('name', '?')} ({e.get('id', '?')}) {what}")
    if len(bad) > limit:
        parts.append(f"…อีก {len(bad) - limit} ชิ้น")
    return " · ".join(parts)


def _picture(path: Optional[str], width: int) -> Optional[Image.Image]:
    """The point's annotated picture scaled to width (OpenCV reads the 4K PNG much faster)."""
    from .notify_service import _local
    import cv2

    src = _local(path)
    if not src:
        return None
    img = cv2.imread(str(src))
    if img is None:
        return None
    h, w = img.shape[:2]
    if w > width:
        img = cv2.resize(img, (width, round(h * width / w)), interpolation=cv2.INTER_AREA)
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


class _Doc:
    """Pages drawn top to bottom; a new page starts when the next block does not fit."""

    def __init__(self):
        self.pages: List[Image.Image] = []
        self.new_page()

    def new_page(self):
        self.page = Image.new("RGB", (W, H), "white")
        self.draw = ImageDraw.Draw(self.page)
        self.pages.append(self.page)
        self.y = M

    def need(self, height: int):
        if self.y + height > H - M - 56:  # keep the footer clear
            self.new_page()

    def text(self, xy, s, f: Face, fill=INK, anchor="la"):
        f.draw(self.draw, xy, s, fill, anchor)

    def heading(self, s: str):
        self.need(70)
        self.y += 18
        self.text((M, self.y), s, font(30, "bold"))
        self.y += 46
        self.draw.line((M, self.y, W - M, self.y), fill=LINE, width=2)
        self.y += 16


def _header(doc: _Doc, run: Dict[str, Any]):
    d, x = doc.draw, M
    if LOGO.is_file():
        try:
            logo = Image.open(LOGO).convert("RGBA")
            logo.thumbnail((96, 96))
            doc.page.paste(logo, (M, doc.y), logo)
            x = M + logo.width + 22
        except OSError:
            pass
    doc.text((x, doc.y + 8), "รายงานผลการตรวจแผงวงจร (AOI)", font(38, "bold"))
    doc.text((x, doc.y + 62), f"RMUTT AOI · PCB Inspection Station · {settings.station_name}", font(20), MUTED)

    status = run.get("status")
    verdict = run.get("overall_verdict") or "ERROR"
    word = STATUS_TEXT.get(status) or verdict
    color = (71, 85, 105) if status in STATUS_TEXT else VERDICT_COLOR.get(verdict, INK)
    label = "" if status in STATUS_TEXT else VERDICT_LABEL.get(verdict, "")
    bw = max(font(40, "bold").getlength(word), font(20).getlength(label)) + 56
    box = (W - M - bw, doc.y, W - M, doc.y + 100)
    d.rounded_rectangle(box, radius=14, outline=color, width=4)
    doc.text(((box[0] + box[2]) / 2, doc.y + 40), word, font(40, "bold"), color, anchor="mm")
    if label:
        doc.text(((box[0] + box[2]) / 2, doc.y + 78), label, font(20), color, anchor="mm")
    doc.y += 128


def _meta(doc: _Doc, run: Dict[str, Any]):
    rows = [
        ("บอร์ด", run.get("board_name") or "–", "เลขบอร์ด (serial)", run.get("serial") or "–"),
        ("วันเวลา", thai_datetime(run.get("created_at") or time.time()), "รหัสรอบ", run.get("id") or "–"),
        ("ผลรายจุด", f"ผ่าน {run.get('pass_count', 0)} · ไม่ผ่าน {run.get('fail_count', 0)} · ตรวจซ้ำ {run.get('review_count', 0)} จาก {run.get('total_points', 0)} จุด",
         "เครื่อง / โมเดล", " · ".join(x for x in (run.get("host"), run.get("device")) if x) or "–"),
    ]
    if run.get("model"):
        rows.append(("", "", "ไฟล์โมเดล", Path(str(run["model"])).name))
    if run.get("is_simulation"):
        rows.append(("หมายเหตุ", "สแกนด้วยสเตจจำลอง (ไม่ใช่ผลจากเครื่องจริง)", "", ""))
    th_w, col = 200, (W - 2 * M) // 2
    f, fb, fm = font(22), font(22, "bold"), font(22, "mono")
    mono = ("รหัสรอบ", "เลขบอร์ด (serial)", "ไฟล์โมเดล")
    for a, b, c, e in rows:
        lines_b = wrap(b, fm if a in mono else f, col - th_w - 28)
        lines_e = wrap(e, fm if c in mono else f, col - th_w - 28)
        h = 18 + 34 * max(len(lines_b), len(lines_e), 1)
        doc.need(h)
        doc.draw.rectangle((M, doc.y, M + th_w, doc.y + h), fill=SOFT)
        doc.draw.rectangle((M + col, doc.y, M + col + th_w, doc.y + h), fill=SOFT)
        doc.draw.rectangle((M, doc.y, W - M, doc.y + h), outline=LINE, width=1)
        for cx, head, body in ((M, a, lines_b), (M + col, c, lines_e)):
            doc.text((cx + 14, doc.y + 10), head, fb, MUTED)
            for i, ln in enumerate(body):
                doc.text((cx + th_w + 14, doc.y + 10 + 34 * i), ln, fm if head in mono else f)
        doc.y += h


def _failing_table(doc: _Doc, failing: Sequence[Dict[str, Any]]):
    doc.heading("จุดที่ไม่ผ่าน / ต้องตรวจซ้ำ")
    c1, c2 = 260, 130
    f, fb = font(21), font(21, "bold")
    doc.need(44)
    doc.draw.rectangle((M, doc.y, W - M, doc.y + 40), fill=SOFT)
    for x, s in ((M + 12, "จุด"), (M + c1 + 12, "ผล"), (M + c1 + c2 + 12, "ชิ้นส่วนที่มีปัญหา")):
        doc.text((x, doc.y + 8), s, fb, MUTED)
    doc.y += 40
    for pt in failing:
        name = f"{pt['point_index'] + 1}. {pt.get('name') or 'จุด ' + str(pt['point_index'] + 1)}"
        names = wrap(name, f, c1 - 24)
        text = wrap(problems_of(pt), f, W - 2 * M - c1 - c2 - 24)
        h = 16 + 32 * max(len(names), len(text))
        doc.need(h)
        for i, ln in enumerate(names):
            doc.text((M + 12, doc.y + 8 + 32 * i), ln, f)
        doc.text((M + c1 + 12, doc.y + 8), pt.get("verdict", ""), fb, VERDICT_COLOR.get(pt.get("verdict"), INK))
        for i, ln in enumerate(text):
            doc.text((M + c1 + c2 + 12, doc.y + 8 + 32 * i), ln, f)
        doc.y += h
        doc.draw.line((M, doc.y, W - M, doc.y), fill=LINE, width=1)


def _grid(doc: _Doc, results: Sequence[Dict[str, Any]]):
    doc.heading("ภาพทุกจุด")
    gap, cols = 28, 2
    cw = (W - 2 * M - gap * (cols - 1)) // cols
    f, fb = font(21), font(21, "bold")
    for start in range(0, len(results), cols):
        row = results[start:start + cols]
        pics = [_picture(pt.get("annotated_path"), cw) for pt in row]
        ph = max((p.height for p in pics if p), default=round(cw * 9 / 16))
        doc.need(ph + 56)
        for i, (pt, pic) in enumerate(zip(row, pics)):
            x = M + i * (cw + gap)
            if pic:
                doc.page.paste(pic, (x, doc.y))
            else:
                doc.draw.rectangle((x, doc.y, x + cw, doc.y + ph), fill=SOFT)
                doc.text((x + cw / 2, doc.y + ph / 2), "ไม่มีภาพ", f, MUTED, anchor="mm")
            doc.draw.rectangle((x, doc.y, x + cw, doc.y + ph), outline=LINE, width=1)
            doc.text((x, doc.y + ph + 10), f"{pt['point_index'] + 1}. {pt.get('name') or 'จุด ' + str(pt['point_index'] + 1)}", f)
            v = pt.get("verdict", "")
            doc.text((x + cw, doc.y + ph + 10), v, fb, VERDICT_COLOR.get(v, INK), anchor="ra")
        doc.y += ph + 56


def _point_pages(doc: _Doc, failing: Sequence[Dict[str, Any]]):
    """A page per point that did not pass: its components and its picture, large."""
    for pt in failing:
        doc.new_page()
        v = pt.get("verdict", "")
        doc.text((M, doc.y), f"จุด {pt['point_index'] + 1}" + (f" · {pt['name']}" if pt.get("name") else ""), font(32, "bold"))
        doc.text((W - M, doc.y + 4), v, font(32, "bold"), VERDICT_COLOR.get(v, INK), anchor="ra")
        doc.y += 52
        pos = f"ตำแหน่ง X {pt.get('x_mm', 0):.1f} · Y {pt.get('y_mm', 0):.1f} mm"
        s = pt.get("summary") or {}
        counts = f"ถูกต้อง {s.get('ok', 0)} · ขาด {s.get('missing', 0)} · ผิดชนิด {s.get('wrong', 0)} · เกิน {s.get('extra', 0)}"
        doc.text((M, doc.y), f"{pos}   {counts}", font(21), MUTED)
        doc.y += 40
        for ln in wrap(problems_of(pt, limit=40), font(22), W - 2 * M):
            doc.text((M, doc.y), ln, font(22))
            doc.y += 34
        doc.y += 10
        pic = _picture(pt.get("annotated_path"), W - 2 * M)
        if pic:
            room = H - M - 56 - doc.y
            if pic.height > room:  # keep it on this page
                pic = pic.resize((round(pic.width * room / pic.height), room), Image.LANCZOS)
            doc.page.paste(pic, (M + (W - 2 * M - pic.width) // 2, doc.y))
            doc.draw.rectangle((M + (W - 2 * M - pic.width) // 2, doc.y, M + (W - 2 * M + pic.width) // 2, doc.y + pic.height), outline=LINE, width=1)


def _footers(doc: _Doc, printed_at: float):
    n = len(doc.pages)
    for i, page in enumerate(doc.pages, 1):
        d = ImageDraw.Draw(page)
        d.line((M, H - M - 40, W - M, H - M - 40), fill=LINE, width=1)
        font(17).draw(d, (M, H - M), f"สร้างเมื่อ {thai_datetime(printed_at)} · ผลจากระบบตรวจอัตโนมัติ ควรยืนยันด้วยการตรวจด้วยตาสำหรับจุดที่ไม่ผ่าน",
                      MUTED, anchor="ld")
        font(17).draw(d, (W - M, H - M), f"หน้า {i}/{n}", MUTED, anchor="rd")


def run_pdf(run: Dict[str, Any], printed_at: Optional[float] = None) -> bytes:
    """The run (storage_service.get_run) as a PDF file."""
    results = run.get("results") or []
    failing = [pt for pt in results if pt.get("verdict") != "PASS"]
    doc = _Doc()
    _header(doc, run)
    _meta(doc, run)
    if run.get("error_message"):
        doc.y += 14
        for ln in wrap(str(run["error_message"]), font(21), W - 2 * M):
            doc.need(32)
            doc.text((M, doc.y), ln, font(21), VERDICT_COLOR["FAIL"])
            doc.y += 32
    if failing:
        _failing_table(doc, failing)
    if results:
        _grid(doc, results)
    _point_pages(doc, failing)
    _footers(doc, printed_at or time.time())
    out = io.BytesIO()
    doc.pages[0].save(out, "PDF", save_all=True, append_images=doc.pages[1:], resolution=DPI, quality=82,
                      title=f"AOI report {run.get('id', '')}", author="RMUTT AOI")
    return out.getvalue()
