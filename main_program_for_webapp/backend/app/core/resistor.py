"""Read a through-hole resistor's value from its colour bands (display only, never a verdict).

1. Crop the part and turn it so the body runs left-right.
2. Take the colour along the middle of the body, column by column.
3. The most common colour there is the body (beige, or blue on metal-film parts); it also
   serves as the white balance reference, since its true colour is roughly known.
4. Runs of columns that differ from the body are the bands; each is matched to the nearest
   standard band colour.
5. Both reading directions are decoded (3–6 bands); the one that ends in a tolerance band,
   has the larger gap before it and lands on an E-series value wins.

The camera sees brown, red, orange and gold close together under warm light, so the result
is an estimate with a confidence figure, not a measurement.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

# name: (digit, multiplier exponent, tolerance %, reference sRGB as seen by a camera)
BAND_COLORS: Dict[str, Tuple[Optional[int], Optional[int], Optional[float], Tuple[int, int, int]]] = {
    "black": (0, 0, None, (35, 32, 30)),
    "brown": (1, 1, 1.0, (120, 70, 45)),
    "red": (2, 2, 2.0, (195, 45, 40)),
    "orange": (3, 3, None, (225, 120, 40)),
    "yellow": (4, 4, None, (225, 200, 50)),
    "green": (5, 5, 0.5, (50, 140, 70)),
    "blue": (6, 6, 0.25, (45, 75, 170)),
    "violet": (7, 7, 0.1, (125, 65, 150)),
    "grey": (8, 8, 0.05, (125, 125, 125)),
    "white": (9, 9, None, (230, 230, 225)),
    "gold": (None, -1, 5.0, (175, 145, 75)),
    "silver": (None, -2, 10.0, (180, 180, 180)),
}
THAI_NAMES = {
    "black": "ดำ", "brown": "น้ำตาล", "red": "แดง", "orange": "ส้ม", "yellow": "เหลือง", "green": "เขียว",
    "blue": "น้ำเงิน", "violet": "ม่วง", "grey": "เทา", "white": "ขาว", "gold": "ทอง", "silver": "เงิน",
}
# What a resistor body looks like under neutral light: carbon film (beige) and metal film (blue).
BODY_REFERENCE = {"beige": (215, 190, 150), "blue": (120, 165, 210)}

E12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]
E24 = sorted(set(E12 + [1.1, 1.3, 1.6, 2.0, 2.4, 3.0, 3.6, 4.3, 5.1, 6.2, 7.5, 9.1]))


def _lab(rgb: Sequence[float]) -> np.ndarray:
    px = np.uint8([[[int(rgb[2]), int(rgb[1]), int(rgb[0])]]])  # BGR
    return cv2.cvtColor(px, cv2.COLOR_BGR2LAB)[0, 0].astype(np.float32)


# How bands actually look to the station camera after white balance (OpenCV Lab: L 0-255,
# a/b signed), from clustering the bands of 154 resistors on the station's boards. A glint
# along a black band makes it a bluish grey; brown comes out darker than its nominal colour.
CAMERA_LAB: Dict[str, List[Tuple[float, float, float]]] = {
    "black": [(20, 3, 3), (103, 13, -6)],
    "brown": [(72, 10, 13), (110, 13, 29)],
    "red": [(119, 46, 31)],
    "orange": [(171, 27, 59)],
    "gold": [(160, 5, 27)],
}


def _refs() -> Dict[str, List[np.ndarray]]:
    refs = {name: [_lab(v[3])] for name, v in BAND_COLORS.items()}
    for name, labs in CAMERA_LAB.items():
        refs[name] = [np.array([L, a + 128, b + 128], np.float32) for L, a, b in labs]
    return refs


_REF_LAB = _refs()


def _delta(a: np.ndarray, b: np.ndarray) -> float:
    """Colour distance in OpenCV Lab, with lightness counting half (shading on a round body)."""
    d = a.astype(np.float32) - b.astype(np.float32)
    return float(math.sqrt((0.5 * d[0]) ** 2 + d[1] ** 2 + d[2] ** 2))


def crop_resistor(image: np.ndarray, bbox_norm: Sequence[float]) -> np.ndarray:
    """The part's box, turned so its long side is horizontal."""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = bbox_norm
    crop = image[int(max(0, y1 * h)):int(min(h, y2 * h)), int(max(0, x1 * w)):int(min(w, x2 * w))]
    if crop.size and crop.shape[0] > crop.shape[1]:
        crop = cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)
    return crop


def _profile(crop: np.ndarray) -> np.ndarray:
    """Per-column colour (Lab) across the middle of the body.

    Each column uses its darker half: a glint runs along every band of the round body and
    would turn black into grey and red into pink.
    """
    h = crop.shape[0]
    strip = crop[int(h * 0.28):max(int(h * 0.28) + 1, int(h * 0.72))]
    lab = cv2.cvtColor(cv2.GaussianBlur(strip, (3, 3), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    cols = []
    for x in range(lab.shape[1]):
        col = lab[:, x]
        cut = np.percentile(col[:, 0], 60)
        dark = col[col[:, 0] <= cut]
        cols.append(np.median(dark if len(dark) >= 2 else col, axis=0))
    prof = np.array(cols)
    k = max(1, crop.shape[1] // 120) * 2 + 1
    return cv2.GaussianBlur(prof.reshape(1, -1, 3), (k, 1), 0).reshape(-1, 3)


def _local_body(prof: np.ndarray, lo: int, hi: int) -> np.ndarray:
    """The body colour around each column: light falls unevenly along the part, so one body
    colour for the whole length marks its darker end as a band."""
    n = len(prof)
    win = max(8, int(0.3 * (hi - lo + 1)))
    out = np.zeros_like(prof)
    for x in range(n):
        a, b = max(lo, x - win // 2), min(hi + 1, x + win // 2 + 1)
        seg = prof[a:b] if b > a else prof[lo:hi + 1]
        light = seg[seg[:, 0] >= np.percentile(seg[:, 0], 65)]
        out[x] = np.median(light, axis=0)
    return out


def _band_distance(c: np.ndarray, body: np.ndarray) -> float:
    """How much a column stands out from the body: darker or a different hue (a lighter
    column is glare or a ridge of the body, not a band)."""
    dl = max(0.0, float(body[0] - c[0]))
    return float(math.sqrt((0.6 * dl) ** 2 + (c[1] - body[1]) ** 2 + (c[2] - body[2]) ** 2))


def _body_color(prof: np.ndarray) -> Tuple[np.ndarray, str]:
    """The most common colour in the middle 80% of the crop (the body between the bands)."""
    n = len(prof)
    mid = prof[int(n * 0.1):max(int(n * 0.1) + 1, int(n * 0.9))]
    best, best_count = mid[0], -1
    for c in mid[:: max(1, len(mid) // 60)]:
        count = sum(_delta(c, o) < 12 for o in mid)
        if count > best_count:
            best, best_count = c, count
    near = np.array([o for o in mid if _delta(best, o) < 12])
    body = np.median(near, axis=0)
    kind = "blue" if body[2] < 124 else "beige"
    return body, kind


def _white_balance(body_lab: np.ndarray, kind: str) -> np.ndarray:
    """Per-channel gains (B, G, R) that bring the body to its usual colour."""
    px = cv2.cvtColor(np.uint8([[body_lab.clip(0, 255)]]), cv2.COLOR_LAB2BGR)[0, 0].astype(np.float32)
    ref = np.array(BODY_REFERENCE[kind][::-1], np.float32)
    return np.clip(ref / np.maximum(px, 1), 0.6, 1.7)


def find_bands(crop: np.ndarray) -> Dict[str, Any]:
    """Bands along the body: [{start, end, lab}] (columns of the crop) plus the body colour."""
    prof = _profile(crop)
    body, kind = _body_color(prof)
    near_body = np.array([_delta(c, body) for c in prof]) < 20
    # The body spans from the first to the last body-coloured column; leads and board lie outside.
    idx = np.where(near_body)[0]
    if idx.size < len(prof) * 0.2:
        return {"bands": [], "body": body, "kind": kind, "span": (0, 0)}
    lo, hi = int(idx[0]), int(idx[-1])
    local = _local_body(prof, lo, hi)
    dist = np.array([_band_distance(prof[x], local[x]) for x in range(len(prof))])
    min_w = max(2, int(round(0.02 * len(prof))))
    bands = []
    x = lo
    while x <= hi:
        if dist[x] >= 16:
            s0 = x
            while x <= hi and dist[x] >= 10:
                x += 1
            if x - s0 >= min_w:
                seg = prof[s0:x]
                w = x - s0
                core = seg[w // 4:max(w // 4 + 1, w - w // 4)]
                bands.append({"start": s0, "end": x, "lab": np.median(core, axis=0),
                              "strength": float(dist[s0:x].max())})
        x += 1
    return {"bands": bands, "body": body, "kind": kind, "span": (lo, hi), "dist": dist}


# Colours rare on real parts get a small handicap (colour distance units), so a grey-looking
# black (glare) or a pale body ridge does not win on a tie.
RARE_PENALTY = {"grey": 6.0, "white": 6.0, "silver": 4.0, "violet": 2.0, "blue": 2.0, "green": 2.0, "yellow": 1.0}
# A gold/silver band weaker than this, inside the row of bands, is a shadow ring of the body.
WEAK_METALLIC = 26.0


def _prune(bands: List[Dict[str, Any]], ranked: List[List[Tuple[str, float]]], span: Tuple[int, int]):
    """Drop what is not a band: the board or a lead at the very ends of the body, and the
    shadow rings of a bulging body, which read as weak gold."""
    lo, hi = span
    length = max(1, hi - lo)
    keep = []
    for i, b in enumerate(bands):
        centre = (b["start"] + b["end"]) / 2
        if centre - lo < 0.04 * length or hi - centre < 0.04 * length:
            continue
        keep.append(i)
    out = []
    for k, i in enumerate(keep):
        name = ranked[i][0][0]
        at_end = k in (0, len(keep) - 1)
        if name in ("gold", "silver") and bands[i]["strength"] < WEAK_METALLIC and not at_end:
            continue
        out.append(i)
    # A run of gold at one end: only the outermost can be the tolerance band.
    while len(out) >= 2 and ranked[out[-1]][0][0] == "gold" and ranked[out[-2]][0][0] == "gold" and bands[out[-2]]["strength"] < WEAK_METALLIC:
        out.pop(-2)
    while len(out) >= 2 and ranked[out[0]][0][0] == "gold" and ranked[out[1]][0][0] == "gold" and bands[out[1]]["strength"] < WEAK_METALLIC:
        out.pop(1)
    return [bands[i] for i in out], [ranked[i] for i in out]


def classify(lab: np.ndarray, gains: np.ndarray) -> List[Tuple[str, float]]:
    """Band colour names, nearest first, with their distances (after white balance)."""
    bgr = cv2.cvtColor(np.uint8([[lab.clip(0, 255)]]), cv2.COLOR_LAB2BGR)[0, 0].astype(np.float32)
    corrected = cv2.cvtColor(np.uint8([[np.clip(bgr * gains, 0, 255)]]), cv2.COLOR_BGR2LAB)[0, 0].astype(np.float32)
    return sorted(
        ((name, min(_delta(corrected, r) for r in refs) + RARE_PENALTY.get(name, 0.0)) for name, refs in _REF_LAB.items()),
        key=lambda t: t[1],
    )


def _format(ohms: float) -> str:
    for unit, scale in (("MΩ", 1e6), ("kΩ", 1e3), ("Ω", 1.0)):
        if ohms >= scale or unit == "Ω":
            v = ohms / scale
            return f"{v:.3g} {unit}" if v < 100 else f"{v:.0f} {unit}"
    return f"{ohms} Ω"


def _in_series(mantissa: float, series: Sequence[float]) -> bool:
    return any(abs(mantissa - s) < 1e-6 for s in series)


def decode(colors: Sequence[str]) -> Optional[Dict[str, Any]]:
    """Value of a band sequence read left to right (3–6 bands), or None if not a valid code."""
    n = len(colors)
    if n < 3 or n > 6:
        return None
    digits_n = 3 if n >= 5 else 2
    digits = [BAND_COLORS[c][0] for c in colors[:digits_n]]
    mult = BAND_COLORS[colors[digits_n]][1]
    tol = BAND_COLORS[colors[digits_n + 1]][2] if n >= digits_n + 2 else None
    if any(d is None for d in digits) or digits[0] == 0 or mult is None:
        return None
    if n >= digits_n + 2 and tol is None:
        return None
    base = int("".join(str(d) for d in digits))
    ohms = base * 10.0 ** mult
    mantissa = float(f"{ohms / 10 ** math.floor(math.log10(ohms)):.3g}") if ohms > 0 else 0
    return {
        "ohms": ohms,
        "tolerance_pct": tol,
        # Three bands read: the tolerance band was not seen (too close to the body colour).
        "text": f"{_format(ohms)} ±{tol:g}%" if tol is not None else _format(ohms),
        "e_series": "E12" if _in_series(mantissa, E12) else "E24" if _in_series(mantissa, E24) else None,
    }


def read_resistor(image: np.ndarray, bbox_norm: Sequence[float]) -> Dict[str, Any]:
    """Estimated value of the resistor in a box: {text, ohms, bands, confidence, ...}."""
    empty: Dict[str, Any] = {"text": "", "ohms": None, "bands": [], "confidence": 0.0, "alternatives": []}
    crop = crop_resistor(image, bbox_norm)
    if crop.size == 0 or crop.shape[1] < 24 or crop.shape[0] < 8:
        return {**empty, "reason": "ภาพตัวต้านทานเล็กเกินไป"}
    found = find_bands(crop)
    bands = found["bands"]
    if len(bands) < 3:
        return {**empty, "reason": "หาแถบสีได้ไม่ครบ (ต้องมีอย่างน้อย 3 แถบ)", "bands": _band_info(bands, None, crop)}
    gains = _white_balance(found["body"], found["kind"])
    bands, ranked = _prune(bands, [classify(b["lab"], gains) for b in bands], found["span"])
    if len(bands) < 3:
        return {**empty, "reason": "หาแถบสีได้ไม่ครบ (ต้องมีอย่างน้อย 3 แถบ)", "bands": _band_info(bands, [r[0][0] for r in ranked], crop)}
    bands, ranked = bands[:6], ranked[:6]
    width = max(1, found["span"][1] - found["span"][0])
    gaps = [bands[i + 1]["start"] - bands[i]["end"] for i in range(len(bands) - 1)]

    candidates = []
    for reverse in (False, True):
        order = list(range(len(ranked)))[::-1] if reverse else list(range(len(ranked)))
        # Try the nearest colour of each band, then the runner-up for the least certain bands.
        choices = [[ranked[i][0]] for i in order]
        for k, i in enumerate(order):
            first, second = ranked[i][0], ranked[i][1]
            # Faint brown and gold look alike: give metallic readings a wider second chance.
            if second[1] - first[1] < (20 if first[0] in ("gold", "silver") else 12):
                choices[k].append(second)
        for combo in _combos(choices, limit=64):
            colors = [c for c, _ in combo]
            value = decode(colors)
            if not value:
                continue
            dist = sum(d for _, d in combo) / len(combo)
            score = -dist
            if colors[-1] in ("gold", "silver"):
                score += 12
            if value["e_series"]:
                score += 10 if value["e_series"] == "E12" else 6
            # Gold/silver multipliers (under 10 Ω) are rare; mostly a faint brown band.
            if value["ohms"] < 10:
                score -= 14
            # The value bands start near one end of the body; the far end holds the tolerance band.
            first, last = bands[order[0]], bands[order[-1]]
            lead = (first["start"] - found["span"][0]) if not reverse else (found["span"][1] - first["end"])
            tail = (found["span"][1] - last["end"]) if not reverse else (last["start"] - found["span"][0])
            if len(colors) == 3 and tail > 1.5 * max(1, lead):
                score += 8
            # The tolerance band usually stands apart from the value bands.
            if len(colors) >= 4 and gaps:
                last_gap = gaps[0] if reverse else gaps[-1]
                others = (gaps[1:] if reverse else gaps[:-1]) or [last_gap]
                if last_gap > 1.3 * float(np.median(others)):
                    score += 6
            candidates.append((score, dist, reverse, colors, value))
    if not candidates:
        return {**empty, "reason": "อ่านสีแถบแล้วไม่เป็นรหัสตัวต้านทานที่ถูกต้อง", "bands": _band_info(bands, [r[0][0] for r in ranked], crop)}
    candidates.sort(key=lambda c: -c[0])
    score, dist, reverse, colors, value = candidates[0]
    confidence = max(0.05, min(0.95, 1.0 - dist / 45.0))
    if value["e_series"] is None:
        confidence *= 0.6
    alternatives = []
    for c in candidates[1:]:
        if c[4]["text"] != value["text"] and c[4]["text"] not in alternatives:
            alternatives.append(c[4]["text"])
        if len(alternatives) >= 2:
            break
    order = list(range(len(colors)))[::-1] if reverse else list(range(len(colors)))
    return {
        "text": value["text"],
        "ohms": value["ohms"],
        "tolerance_pct": value["tolerance_pct"],
        "e_series": value["e_series"],
        "bands": _band_info([bands[i] for i in order], colors, crop),
        "confidence": round(confidence, 2),
        "alternatives": alternatives,
        "body": found["kind"],
        "reversed": reverse,
        "span_px": width,
    }


def _combos(choices: List[List[Tuple[str, float]]], limit: int):
    out: List[List[Tuple[str, float]]] = [[]]
    for opts in choices:
        out = [prev + [o] for prev in out for o in opts][:limit]
    return out


def _band_info(bands: Sequence[Dict[str, Any]], colors: Optional[Sequence[str]], crop: np.ndarray) -> List[Dict[str, Any]]:
    out = []
    for i, b in enumerate(bands):
        bgr = cv2.cvtColor(np.uint8([[b["lab"].clip(0, 255)]]), cv2.COLOR_LAB2BGR)[0, 0]
        name = colors[i] if colors and i < len(colors) else None
        out.append({
            "color": name,
            "name_th": THAI_NAMES.get(name or "", ""),
            "seen_hex": "#%02x%02x%02x" % (int(bgr[2]), int(bgr[1]), int(bgr[0])),
            "position": round((b["start"] + b["end"]) / 2 / crop.shape[1], 3),
        })
    return out
