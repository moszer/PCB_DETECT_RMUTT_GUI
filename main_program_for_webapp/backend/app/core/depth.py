"""Rough component heights from top-down frames taken a few mm apart (motion stereo).

The camera looks straight down and the XY stage moves the board sideways between the two
frames. Everything shifts in the image, but parts closer to the camera (taller) shift more:

    disparity d = f * B / Z      (f: focal length px, B: stage move mm, Z: distance to camera)

With the board surface at distance Z0 and a local board disparity d_b, a point with
disparity d sits at height

    h = Z0 * (1 - d_b / d)

so only pixel disparities and Z0 are needed — f and the exact stage distance cancel out,
which also makes the measurement immune to stage backlash. d_b is measured on the board
around each part, absorbing lens distortion and board tilt.

Several moves (e.g. ±X and ±Y) can be fused: each direction misses different spots
(the side of a part facing away from the move, edges running along it), and averaging
the views that agree lowers the noise.

Accuracy is coarse (about 1 mm at 200 mm working distance and a 5 mm move); flat, shiny
or texture-less tops give holes that are filled from their surroundings.
"""
from __future__ import annotations

import math
import warnings
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

MAX_PART_HEIGHT_MM = 20.0
# Matches on flat/shiny areas (local contrast below this) are dropped: they are mostly wrong.
MIN_TEXTURE_STD = 4.0
# A cell this far (mm) from its neighbourhood median is treated as a mismatch.
OUTLIER_MM = 2.0


def reject_outliers(heights: np.ndarray, valid: np.ndarray, window: int = 9, tol_mm: float = OUTLIER_MM) -> np.ndarray:
    """Valid mask without isolated spikes (cells far from their neighbourhood median)."""
    filled = np.where(valid, heights, np.nan).astype(np.float32)
    fallback = float(np.nanmedian(filled)) if np.isfinite(filled).any() else 0.0
    base = np.where(np.isfinite(filled), filled, fallback).astype(np.float32)
    k = window if window % 2 else window + 1
    # medianBlur needs uint8 for large kernels: quantize to 0.1 mm over the clipped range.
    lo, hi = -5.0, MAX_PART_HEIGHT_MM + 5
    q = np.clip((base - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
    med = cv2.medianBlur(q, k).astype(np.float32) / 255 * (hi - lo) + lo
    return valid & (np.abs(base - med) <= tol_mm)


def to_gray(frame: np.ndarray) -> np.ndarray:
    return frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def estimate_shift(frame_a: np.ndarray, frame_b: np.ndarray, work_side: int = 1024) -> Tuple[float, float, float]:
    """Dominant (board) image shift from A to B in pixels, plus the correlation peak strength."""
    a, b = to_gray(frame_a), to_gray(frame_b)
    h, w = a.shape[:2]
    scale = min(1.0, work_side / max(h, w))
    if scale < 1:
        size = (max(1, int(w * scale)), max(1, int(h * scale)))
        a = cv2.resize(a, size, interpolation=cv2.INTER_AREA)
        b = cv2.resize(b, size, interpolation=cv2.INTER_AREA)
    window = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(a.astype(np.float32), b.astype(np.float32), window)
    return dx / scale, dy / scale, float(response)


def _patch_matrix(center: Tuple[float, float], theta: float, size: Tuple[int, int]) -> np.ndarray:
    """dst(u, v) -> src(x, y): a patch whose +u axis points along `theta`, centred on `center`."""
    c, s = math.cos(theta), math.sin(theta)
    w, h = size
    cx, cy = center
    return np.array(
        [[c, -s, cx - c * w / 2 + s * h / 2], [s, c, cy - s * w / 2 - c * h / 2]],
        dtype=np.float64,
    )


def _invert_affine(m: np.ndarray) -> np.ndarray:
    return cv2.invertAffineTransform(m)


def _roi(bbox_px: Sequence[float], shape: Tuple[int, ...], pad_ratio: float) -> Tuple[float, float, float, float]:
    H, W = shape[:2]
    x1, y1, x2, y2 = (float(v) for v in bbox_px)
    bw, bh = max(4.0, x2 - x1), max(4.0, y2 - y1)
    pad = max(40.0, pad_ratio * max(bw, bh))
    return max(0.0, x1 - pad), max(0.0, y1 - pad), min(float(W), x2 + pad), min(float(H), y2 + pad)


# Context around a part used to find the local board shift (px a side, at least).
LOCAL_CONTEXT_PX = 640
# Longest ROI side matched at full resolution (px); larger parts are matched scaled down.
MATCH_MAX_SIDE = 640
# Extra disparity searched on both sides (px) beyond the tallest part's.
SEARCH_MARGIN_PX = 24
# A surface counts as "the board" when it covers at least this share of the part's surroundings.
BOARD_MIN_SHARE = 0.12


def lowest_surface(values: np.ndarray, min_share: float = BOARD_MIN_SHARE) -> float:
    """The lowest surface (smallest residual disparity) that covers a real share of `values`.

    The board is always the lowest thing in the picture; its neighbours (connectors, ICs,
    other capacitors) only ever add higher surfaces, so a plain median drifts up whenever
    they fill much of the margin around a part.
    """
    v = values[np.isfinite(values)]
    lo, hi = float(np.floor(v.min())), float(np.ceil(v.max()))
    if hi - lo < 2:
        return float(np.median(v))
    hist, edges = np.histogram(v, bins=int(hi - lo) + 1, range=(lo, hi + 1))
    smooth = np.convolve(hist, np.ones(5) / 5, mode="same")
    need = min_share * v.size / 5  # per-bin density of a surface holding min_share over ~5 bins
    for i in range(len(smooth)):
        left = smooth[i - 1] if i else 0
        right = smooth[i + 1] if i + 1 < len(smooth) else 0
        if smooth[i] >= need and smooth[i] >= left and smooth[i] >= right:
            near = v[np.abs(v - (edges[i] + 0.5)) <= 3]
            if near.size >= min_share * v.size * 0.5:
                return float(np.median(near))
    return float(np.median(v))


def local_board_shift(
    ga: np.ndarray,
    gb: np.ndarray,
    shift: Tuple[float, float],
    roi: Tuple[float, float, float, float],
    box: Sequence[float],
) -> Tuple[float, float, float]:
    """The board's shift right around a part, refining a frame-wide (or predicted) `shift`.

    A whole-frame correlation follows whatever dominates the picture, which on a board with
    tall connectors and ICs can be their tops rather than the board, and differs per view.
    Here only a window around the part is used, with the part itself blanked out, so the
    board around it decides. Returns (dx, dy, peak strength); the input on failure.
    """
    H, W = ga.shape[:2]
    rx1, ry1, rx2, ry2 = roi
    cx, cy = (rx1 + rx2) / 2, (ry1 + ry2) / 2
    half = max(LOCAL_CONTEXT_PX, rx2 - rx1, ry2 - ry1) / 2
    dx, dy = shift
    # The window must lie inside both frames.
    x1 = max(0.0, cx - half, -dx)
    y1 = max(0.0, cy - half, -dy)
    x2 = min(float(W), cx + half, W - dx)
    y2 = min(float(H), cy + half, H - dy)
    if x2 - x1 < 64 or y2 - y1 < 64:
        return dx, dy, 0.0
    ix, iy, w, h = int(x1), int(y1), int(x2 - x1), int(y2 - y1)
    a = ga[iy:iy + h, ix:ix + w].astype(np.float32)
    m = np.float32([[1, 0, -(ix + dx)], [0, 1, -(iy + dy)]])
    b = cv2.warpAffine(gb.astype(np.float32), m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    # Blank the part (plus a margin for its own disparity) to the window mean.
    bx1, by1, bx2, by2 = box
    margin = 0.15 * max(bx2 - bx1, by2 - by1) + 8
    sx1, sy1 = int(max(0, bx1 - margin - ix)), int(max(0, by1 - margin - iy))
    sx2, sy2 = int(min(w, bx2 + margin - ix)), int(min(h, by2 + margin - iy))
    for img in (a, b):
        if sx2 > sx1 and sy2 > sy1:
            img[sy1:sy2, sx1:sx2] = float(img.mean())
    window = cv2.createHanningWindow((w, h), cv2.CV_32F)
    (rx, ry), response = cv2.phaseCorrelate(a, b, window)
    if response < 0.05 or math.hypot(rx, ry) > 0.25 * min(w, h):
        return dx, dy, float(response)
    return dx + rx, dy + ry, float(response)


def _view_heights(
    ga: np.ndarray,
    gb: np.ndarray,
    shift: Tuple[float, float],
    roi: Tuple[float, float, float, float],
    inside: np.ndarray,
    box: Sequence[float],
    camera_distance_mm: float,
) -> Tuple[np.ndarray, float]:
    """Heights (mm, NaN where unmatched) over the ROI from one A/B pair, and its board residual."""
    if math.hypot(*shift) < 3:
        raise ValueError("ภาพสองภาพแทบไม่เลื่อน — ระยะเลื่อนสเตจน้อยเกินไป")
    dx, dy, _ = local_board_shift(ga, gb, shift, roi, box)
    d0 = math.hypot(dx, dy)
    theta = math.atan2(dy, dx)
    H, W = ga.shape[:2]
    rx1, ry1, rx2, ry2 = roi
    roi_w, roi_h = int(rx2 - rx1), int(ry2 - ry1)
    cx, cy = (rx1 + rx2) / 2, (ry1 + ry2) / 2
    if not (0 <= cx + dx < W and 0 <= cy + dy < H):
        raise ValueError("ชิ้นนี้หลุดขอบภาพที่สองหลังเลื่อนสเตจ")

    # Large parts are matched on a reduced patch (the map is at most grid_max cells anyway):
    # an IC spanning 1000 px otherwise takes seconds per view on the Jetson. Upsampling small
    # parts was tried and lost most matches on real, slightly blurred frames.
    up = min(1.0, MATCH_MAX_SIDE / max(roi_w, roi_h))
    # Expected extra disparity of the tallest part, rounded up for SGBM (multiple of 16).
    max_extra = up * d0 * (camera_distance_mm / max(1.0, camera_distance_mm - MAX_PART_HEIGHT_MM) - 1)
    # Search as far below zero as above: the pre-alignment may have followed the tops of tall
    # neighbours instead of the board, which then sits that much lower.
    min_disp = -int(math.ceil(max_extra)) - SEARCH_MARGIN_PX
    num_disp = int(math.ceil((max_extra - min_disp + 8) / 16.0)) * 16
    num_disp = max(32, min(num_disp, 256))

    # Rotated patches with the board shift along +u; B is pre-shifted by the board shift so
    # the board has ~0 residual disparity and taller parts have a positive one.
    diag = int(math.ceil(math.hypot(roi_w, roi_h)))
    # SGBM leaves a num_disp-wide band unmatched on one side: keep it clear of the ROI.
    pw, ph = int(round(up * diag)) + 2 * (num_disp + 16), int(round(up * diag))
    scale = np.diag([1.0 / up, 1.0 / up, 1.0])
    m_a = _patch_matrix((cx, cy), theta, (pw / up, ph / up)) @ scale
    m_b = _patch_matrix((cx + dx, cy + dy), theta, (pw / up, ph / up)) @ scale
    flags = cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP
    pa = cv2.warpAffine(ga, m_a, (pw, ph), flags=flags, borderMode=cv2.BORDER_REPLICATE)
    pb = cv2.warpAffine(gb, m_b, (pw, ph), flags=flags, borderMode=cv2.BORDER_REPLICATE)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    pa, pb = clahe.apply(pa), clahe.apply(pb)

    block = 9
    sgbm = cv2.StereoSGBM_create(
        minDisparity=min_disp,
        numDisparities=num_disp,
        blockSize=block,
        P1=8 * block * block,
        P2=48 * block * block,
        disp12MaxDiff=1,
        # Tuned on station frames: stricter settings threw away most of the board; the
        # outlier filter and the multi-view fusion catch what these let through.
        uniquenessRatio=8,
        speckleWindowSize=50,
        speckleRange=2,
        mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY,
    )
    # A point at u in A sits at u + r in B (r > 0 for taller parts). SGBM finds, for each
    # left pixel x, its match at x - d in the right image; mirroring both patches gives exactly
    # that with A on the left, so the disparity map is indexed by A's pixels (with B on the left
    # it would be in B's, putting every tall part r pixels off).
    raw = cv2.flip(sgbm.compute(cv2.flip(pa, 1), cv2.flip(pb, 1)), 1).astype(np.float32) / 16.0
    # Local contrast of the reference patch: texture-less areas give unreliable matches.
    paf = pa.astype(np.float32)
    mean = cv2.blur(paf, (block, block))
    std = np.sqrt(np.maximum(cv2.blur(paf * paf, (block, block)) - mean * mean, 0))
    invalid = (raw < min_disp) | (std < MIN_TEXTURE_STD)
    residual = np.where(invalid, np.nan, raw / up)

    # Back to frame-A orientation over the ROI: roi(x, y) -> patch(u, v).
    to_patch = _invert_affine(m_a[:2])
    shift_roi = np.array([[1, 0, rx1], [0, 1, ry1]], dtype=np.float64)
    m_roi = to_patch @ np.vstack([shift_roi, [0, 0, 1]])
    sentinel = -1e4
    filled = np.where(np.isnan(residual), sentinel, residual).astype(np.float32)
    res_roi = cv2.warpAffine(filled, m_roi, (roi_w, roi_h), flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=sentinel)
    res_roi[res_roi <= sentinel / 2] = np.nan

    # Local board level: the margin around the part's box.
    ring = res_roi[~inside]
    ring = ring[np.isfinite(ring)]
    if ring.size < 50:
        raise ValueError("รอบชิ้นนี้มีลายให้จับคู่ไม่พอ วัดระดับบอร์ดไม่ได้")
    board_residual = lowest_surface(ring)

    d = d0 + res_roi
    heights = camera_distance_mm * (1.0 - (d0 + board_residual) / d)
    valid = np.isfinite(heights) & (heights > -5.0) & (heights < MAX_PART_HEIGHT_MM + 5)
    valid = reject_outliers(np.nan_to_num(heights), valid)
    return np.where(valid, heights, np.nan).astype(np.float32), board_residual


def _fuse(stack: np.ndarray, agree_mm: float = 1.0) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-cell fusion of several views: mean of the views that agree with the median.

    Returns (heights with NaN where no view matched, number of agreeing views, their spread).
    """
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(stack, axis=0)
        close = np.isfinite(stack) & (np.abs(stack - med) <= agree_mm)
        count = close.sum(axis=0)
        kept = np.where(close, stack, np.nan)
        fused = np.nanmean(kept, axis=0)
        spread = np.nanstd(kept, axis=0)
    return fused.astype(np.float32), count, spread


def _consistent_views(per_view: List[np.ndarray], residuals: List[float], inside: np.ndarray):
    """Drop views whose idea of the part's height disagrees with the rest (a mismatched view
    shifts the whole part, which the per-cell fusion alone would average in)."""
    if len(per_view) < 3:
        return per_view, residuals, 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        meds = np.array([np.nanmedian(h[inside]) if np.isfinite(h[inside]).any() else np.nan for h in per_view])
    ok = np.isfinite(meds)
    if ok.sum() < 3:
        return per_view, residuals, 0
    center = float(np.median(meds[ok]))
    tol = max(1.0, 0.25 * abs(center))
    keep = [i for i in range(len(per_view)) if ok[i] and abs(meds[i] - center) <= tol]
    if len(keep) < 2:
        return per_view, residuals, 0
    return [per_view[i] for i in keep], [residuals[i] for i in keep], len(per_view) - len(keep)


def height_map_views(
    frame_a: np.ndarray,
    views: Sequence[Tuple[np.ndarray, Tuple[float, float]]],
    bbox_px: Sequence[float],
    camera_distance_mm: float,
    pad_ratio: float = 0.6,
    grid_max: int = 240,
) -> Dict[str, Any]:
    """Height (mm above the surrounding board) over a part's box and a margin of board.

    `views` are (frame B, board shift A->B) pairs taken after moving the stage in different
    directions. Each view is matched against A on its own; fusing them fills the holes one
    direction leaves (occluded sides, edges parallel to the move) and averages out noise.
    Views the part left, or that cannot see enough board, are skipped.

    Returns the map in frame-A orientation, downsampled to at most `grid_max` cells a side.
    """
    if not views:
        raise ValueError("ไม่มีภาพที่สองให้เทียบ")
    rx1, ry1, rx2, ry2 = _roi(bbox_px, frame_a.shape, pad_ratio)
    roi_w, roi_h = int(rx2 - rx1), int(ry2 - ry1)
    if roi_w < 16 or roi_h < 16:
        raise ValueError("กรอบเล็กเกินไป")
    x1, y1, x2, y2 = (float(v) for v in bbox_px)
    yy, xx = np.mgrid[0:roi_h, 0:roi_w]
    inside = (xx + rx1 >= x1) & (xx + rx1 <= x2) & (yy + ry1 >= y1) & (yy + ry1 <= y2)

    ga = to_gray(frame_a)
    per_view, residuals, errors = [], [], []
    for frame_b, shift in views:
        try:
            h, res = _view_heights(ga, to_gray(frame_b), shift, (rx1, ry1, rx2, ry2), inside, (x1, y1, x2, y2), camera_distance_mm)
        except ValueError as exc:
            errors.append(exc)
            continue
        per_view.append(h)
        residuals.append(res)
    if not per_view:
        raise errors[0]
    per_view, residuals, dropped = _consistent_views(per_view, residuals, inside)

    if len(per_view) == 1:
        heights = per_view[0]
        count = np.isfinite(heights).astype(np.int32)
        spread = np.full_like(heights, np.nan)
    else:
        heights, count, spread = _fuse(np.stack(per_view))
    valid = count > 0
    valid = reject_outliers(np.nan_to_num(heights), valid)
    heights = np.clip(np.nan_to_num(heights), -5.0, MAX_PART_HEIGHT_MM)

    valid_ratio = float(valid.mean())
    if valid_ratio < 0.15:
        raise ValueError("จับคู่ภาพได้น้อยเกินไป (ผิวเรียบหรือสะท้อนแสง)")
    # Fill holes from their surroundings, then smooth (lighter with several views: they are
    # already averaged, and heavy smoothing would round off the part's edges).
    hole_mask = (~valid).astype(np.uint8)
    base = np.where(valid, heights, 0).astype(np.float32)
    if hole_mask.any():
        base = cv2.inpaint(base, hole_mask, 5, cv2.INPAINT_TELEA)
    if len(per_view) == 1:
        base = cv2.medianBlur(base, 5)
        base = cv2.GaussianBlur(base, (0, 0), 1.0)
    else:
        base = cv2.medianBlur(base, 3)
        base = cv2.GaussianBlur(base, (0, 0), 0.6)

    inside_vals = base[inside]
    inside_valid = valid[inside]
    measured = inside_vals[inside_valid] if inside_valid.any() else inside_vals
    spread_ok = spread[valid & np.isfinite(spread) & (count >= 2)]
    stats = {
        # 95th percentile: the top of the part without the last few stray matches.
        "max_mm": round(float(np.percentile(measured, 95)), 2) if measured.size else None,
        "median_mm": round(float(np.median(measured)), 2) if measured.size else None,
        "valid_ratio": round(valid_ratio, 3),
        "box_valid_ratio": round(float(inside_valid.mean()), 3) if inside_valid.size else 0.0,
        "board_shift_px": round(float(np.mean([math.hypot(*s) for _, s in views])), 2),
        "board_residual_px": round(float(np.median(residuals)), 2),
        "views_used": len(per_view),
        "views_total": len(views),
        # Views left out because they disagreed with the others about the part's height.
        "views_dropped": dropped,
        # How much the views disagree (mm, typical cell): a rough precision figure.
        "spread_mm": round(float(np.median(spread_ok)), 2) if spread_ok.size else None,
    }

    scale = min(1.0, grid_max / max(roi_w, roi_h))
    gw, gh = max(2, int(round(roi_w * scale))), max(2, int(round(roi_h * scale)))
    grid = cv2.resize(base, (gw, gh), interpolation=cv2.INTER_AREA)
    vgrid = cv2.resize(valid.astype(np.float32), (gw, gh), interpolation=cv2.INTER_AREA) > 0.5
    return {
        "roi_px": [rx1, ry1, rx2, ry2],
        "grid_w": gw,
        "grid_h": gh,
        "heights": [round(float(v), 2) for v in grid.ravel()],
        "valid": [bool(v) for v in vgrid.ravel()],
        "box_in_roi": [(x1 - rx1) / roi_w, (y1 - ry1) / roi_h, (x2 - rx1) / roi_w, (y2 - ry1) / roi_h],
        "stats": stats,
    }


def height_map(
    frame_a: np.ndarray,
    frame_b: np.ndarray,
    shift: Tuple[float, float],
    bbox_px: Sequence[float],
    camera_distance_mm: float,
    pad_ratio: float = 0.6,
    grid_max: int = 240,
) -> Dict[str, Any]:
    """Single-pair height map (see `height_map_views`)."""
    return height_map_views(frame_a, [(frame_b, shift)], bbox_px, camera_distance_mm, pad_ratio, grid_max)


def crop_texture(frame: np.ndarray, roi_px: Sequence[float], max_side: int = 768) -> Optional[bytes]:
    """JPEG of frame A over the ROI (the 3D view drapes it over the height map)."""
    x1, y1, x2, y2 = (int(round(v)) for v in roi_px)
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    h, w = crop.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1:
        crop = cv2.resize(crop, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, jpeg = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return jpeg.tobytes() if ok else None
