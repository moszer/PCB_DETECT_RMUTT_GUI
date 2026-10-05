"""Read part markings (e.g. "LM317T", "100uF 35V", "DB104G") inside detection boxes.

Engine: Apple Vision (on-device, accurate) when available, otherwise the Tesseract CLI.
Markings are often rotated 90/180/270 degrees on the board, so every crop is read in the
four orientations and the most confident reading wins.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

ROTATIONS: Dict[int, Optional[int]] = {
    0: None,
    90: cv2.ROTATE_90_CLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_COUNTERCLOCKWISE,
}

try:  # macOS only
    import Vision  # type: ignore
    from Foundation import NSData  # type: ignore

    _HAS_VISION = True
except Exception:  # pragma: no cover - other platforms
    _HAS_VISION = False

_TESSERACT = shutil.which("tesseract")
_ENGINE_LOCK = threading.Lock()  # one OCR request at a time (Vision models are shared)


def engine_name() -> Optional[str]:
    if _HAS_VISION:
        return "apple-vision"
    if _TESSERACT:
        return "tesseract"
    return None


Line = Tuple[str, float, Tuple[float, float, float, float]]  # text, confidence, box (x, y, w, h) top-left origin


def _vision_lines(img: np.ndarray) -> List[Line]:
    ok, png = cv2.imencode(".png", img)
    if not ok:
        return []
    data = NSData.dataWithBytes_length_(png.tobytes(), len(png))
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(False)  # markings are codes, not words
    request.setRecognitionLanguages_(["en-US"])
    request.setMinimumTextHeight_(0.05)
    success, _ = handler.performRequests_error_([request], None)
    if not success:
        return []
    lines: List[Line] = []
    for obs in request.results() or []:
        candidates = obs.topCandidates_(1)
        if not candidates:
            continue
        cand = candidates[0]
        bb = obs.boundingBox()  # normalized, origin bottom-left
        box = (bb.origin.x, 1 - bb.origin.y - bb.size.height, bb.size.width, bb.size.height)
        lines.append((str(cand.string()), float(cand.confidence()), box))
    return lines


# Tesseract word confidence below which a word is noise (unless it looks like a part code).
TESSERACT_MIN_CONF = 0.6
# Stray marks Tesseract glues to words ("|", "—", "_" from edges and pins).
_EDGE_JUNK = re.compile(r"^[^0-9A-Za-z+(#]+|[^0-9A-Za-z%)Ω.]+$")
# An uppercase/digit code with both letters and digits: EPM570T144C5, N-AACQM0537A, LM317T.
_CODE_LIKE = re.compile(r"^(?=.*\d)(?=.*[A-Z])[A-Z0-9][A-Z0-9\-./]{3,}$")


def binarize_for_tesseract(img: np.ndarray) -> np.ndarray:
    """Dark text on a white page, as Tesseract expects: part markings are usually light
    print on a dark body, and its own thresholding on a colour photo leaves the body's
    texture, glare and pins as noise."""
    g = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(g)
    _, bw = cv2.threshold(cv2.GaussianBlur(g, (3, 3), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if bw.mean() < 127:  # mostly dark: the text is the light part
        bw = 255 - bw
    return cv2.copyMakeBorder(bw, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)


def _tesseract_lines(img: np.ndarray) -> List[Line]:
    img = binarize_for_tesseract(img)
    ok, png = cv2.imencode(".png", img)
    if not ok or not _TESSERACT:
        return []
    try:
        out = subprocess.run(
            [_TESSERACT, "stdin", "stdout", "--psm", "6", "tsv"],
            input=png.tobytes(), capture_output=True, timeout=10,
        ).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows: Dict[Tuple[int, int, int], List[Tuple[str, float, Tuple[int, int, int, int]]]] = {}
    h, w = img.shape[:2]
    for row in out.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or not cols[11].strip():
            continue
        try:
            conf = float(cols[10])
        except ValueError:
            continue
        if conf < 0:
            continue
        word = _EDGE_JUNK.sub("", cols[11])
        if not word:
            continue
        conf /= 100
        # Tesseract often scores whole lines 0 next to a stray "|" although the code itself is
        # read right: keep words shaped like part codes, as uncertain readings.
        if conf < TESSERACT_MIN_CONF:
            if not _CODE_LIKE.match(word):
                continue  # fragments of texture, pins and logos come back at low confidence
            conf = 0.5
        key = (int(cols[2]), int(cols[3]), int(cols[4]))  # block, paragraph, line
        rows.setdefault(key, []).append((word, conf, tuple(int(c) for c in cols[6:10])))
    lines: List[Line] = []
    for words in rows.values():
        xs = [b[0] for _, _, b in words]
        ys = [b[1] for _, _, b in words]
        x2 = [b[0] + b[2] for _, _, b in words]
        y2 = [b[1] + b[3] for _, _, b in words]
        text = " ".join(t for t, _, _ in words)
        conf = sum(c for _, c, _ in words) / len(words)
        lines.append((text, conf, (min(xs) / w, min(ys) / h, (max(x2) - min(xs)) / w, (max(y2) - min(ys)) / h)))
    return lines


def _read_lines(img: np.ndarray) -> List[Line]:
    with _ENGINE_LOCK:
        if _HAS_VISION:
            try:
                return _vision_lines(img)
            except Exception:  # pragma: no cover - defensive: fall back to Tesseract
                logger.warning("Apple Vision OCR failed; trying Tesseract", exc_info=True)
        return _tesseract_lines(img)


# Cyrillic/Greek look-alikes OCR engines sometimes return for Latin part codes.
_HOMOGLYPHS = str.maketrans("АВЕКМНОРСТХІУаеорсхуΑΒΕΚΜΝΟΡΤΧ", "ABEKMHOPCTXIYaeopcxyABEKMNOPTX")
# Through-hole pads and vias read as these; a line made only of them is not text.
_PAD_CHARS = set("oO0°•·.,:;'\"-_ ")


# Characters a marking may contain besides letters and digits (100uF/35V, LM317-T, 1.5K, +5V...).
_MARK_PUNCT = set("-./+%()#:_Ωµ ")


def _junk(text: str) -> int:
    return sum(1 for ch in text if not ch.isalnum() and ch not in _MARK_PUNCT)


def clean_lines(lines: Sequence[Line]) -> List[Line]:
    """Normalize look-alike letters and drop readings that are just pads, dots or noise.

    Pins, pads and textured bodies read as runs of '=', '—', '|' and short fragments
    ("== zm =", "a WD ——"): a line must be mostly letters/digits and hold a real token.
    """
    out: List[Line] = []
    for text, conf, box in lines:
        text = text.translate(_HOMOGLYPHS).strip()
        alnum = re.sub(r"[^0-9A-Za-z]", "", text)
        if not alnum or set(text) <= _PAD_CHARS:
            continue
        if conf < 0.35 or (len(alnum) < 2 and conf < 0.6):
            continue
        visible = len(text.replace(" ", ""))
        if len(alnum) / max(1, visible) < 0.6:
            continue
        # A row of pins reads as a long run of lowercase letters ("dedaaseancabsavati...").
        if any(len(t) >= 10 and t.isalpha() and t.islower() for t in re.findall(r"[A-Za-z]+", text)):
            continue
        # Keep the line only if one word has 2+ characters, or it is short and certain.
        tokens = [re.sub(r"[^0-9A-Za-z]", "", t) for t in text.split()]
        if max((len(t) for t in tokens), default=0) < 3 and not (len(alnum) >= 2 and conf >= 0.8 and not _junk(text)):
            continue
        out.append((text, conf, box))
    return out


def _score(lines: Sequence[Line]) -> float:
    """Confident readings with more real characters win; stray symbols count against."""
    return sum(conf * (len(re.sub(r"[^0-9A-Za-z]", "", text)) - 2 * _junk(text)) for text, conf, _ in lines)


def warm_up() -> None:
    """The first Vision request loads its models (~25 s); do it once in the background."""
    try:
        img = np.full((96, 320, 3), 255, np.uint8)
        cv2.putText(img, "WARM 123", (10, 64), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 3)
        _read_lines(img)
    except Exception:  # pragma: no cover
        logger.warning("OCR warm-up failed", exc_info=True)


def prepare_crop(image: np.ndarray, bbox_norm: Sequence[float], pad: Optional[float] = None) -> np.ndarray:
    """Crop a part and upscale small crops so the text is legible.

    Small parts get a little margin (the box may clip the marking); large ones are inset
    instead, leaving out the rows of pins along an IC's edges, which read as text.
    """
    h, w = image.shape[:2]
    x1, y1, x2, y2 = bbox_norm
    if pad is None:
        pad = -0.07 if min((x2 - x1) * w, (y2 - y1) * h) >= 200 else 0.08
    px, py = (x2 - x1) * pad, (y2 - y1) * pad
    l, t = int(max(0, (x1 - px) * w)), int(max(0, (y1 - py) * h))
    r, b = int(min(w, (x2 + px) * w)), int(min(h, (y2 + py) * h))
    crop = image[t:b, l:r]
    if crop.size == 0:
        return crop
    ch, cw = crop.shape[:2]
    scale = min(4.0, max(1.0, 320 / min(ch, cw)), 1600 / max(ch, cw))
    if scale != 1.0:
        crop = cv2.resize(crop, (int(cw * scale), int(ch * scale)), interpolation=cv2.INTER_CUBIC)
    return crop


def read_part_text(image: np.ndarray, bbox_norm: Sequence[float]) -> Dict[str, Any]:
    """Best reading of the text inside one box: {text, lines, rotation, confidence}."""
    crop = prepare_crop(image, bbox_norm)
    empty = {"text": "", "lines": [], "rotation": 0, "confidence": 0.0}
    if crop.size == 0 or min(crop.shape[:2]) < 8:
        return empty
    # Text usually runs along the long side: try those orientations first.
    order = [0, 180, 90, 270] if crop.shape[1] >= crop.shape[0] else [90, 270, 0, 180]
    best: Tuple[float, int, List[Line]] = (0.0, 0, [])
    for angle in order:
        code = ROTATIONS[angle]
        lines = clean_lines(_read_lines(crop if code is None else cv2.rotate(crop, code)))
        score = _score(lines)
        if score > best[0]:
            best = (score, angle, lines)
        # A clear, confident reading needs no other orientation.
        if lines and score >= 4 and min(c for _, c, _ in lines) >= 0.9:
            break
    _, angle, lines = best
    if not lines:
        return empty
    if not _HAS_VISION:
        # Vision already returns lines in reading order (also for upside-down text).
        lines = sorted(lines, key=lambda ln: (round(ln[2][1], 2), ln[2][0]))
    return {
        "text": "\n".join(t for t, _, _ in lines),
        "lines": [{"text": t, "confidence": round(c, 3)} for t, c, _ in lines],
        "rotation": angle,
        "confidence": round(sum(c for _, c, _ in lines) / len(lines), 3),
    }
