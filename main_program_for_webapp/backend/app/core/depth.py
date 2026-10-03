"""Rough component heights from two top-down frames taken a few mm apart (motion stereo).

The camera looks straight down and the XY stage moves the board sideways between the two
frames. Everything shifts in the image, but parts closer to the camera (taller) shift more:

    disparity d = f * B / Z      (f: focal length px, B: stage move mm, Z: distance to camera)

With the board surface at distance Z0 and a local board disparity d_b, a point with
disparity d sits at height

    h = Z0 * (1 - d_b / d)

so only pixel disparities and Z0 are needed — f and the exact stage distance cancel out,
which also makes the measurement immune to stage backlash. d_b is measured on the board
around each part, absorbing lens distortion and board tilt.

Accuracy is coarse (about 1 mm at 200 mm working distance and a 5 mm move); flat, shiny
or texture-less tops give holes that are filled from their surroundings.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional, Sequence, Tuple

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


def height_map(
    frame_a: np.ndarray,
    frame_b: np.ndarray,
    shift: Tuple[float, float],
    bbox_px: Sequence[float],
    camera_distance_mm: float,
    pad_ratio: float = 0.6,
    grid_max: int = 160,
) -> Dict[str, Any]:
    """Height (mm above the surrounding board) over a part's box and a margin of board.

    Returns the map in frame-A orientation, downsampled to at most `grid_max` cells a side.
    """
    dx, dy = shift
    d0 = math.hypot(dx, dy)
    if d0 < 3:
        raise ValueError("ภาพสองภาพแทบไม่เลื่อน — ระยะเลื่อนสเตจน้อยเกินไป")
    theta = math.atan2(dy, dx)
    H, W = frame_a.shape[:2]

    x1, y1, x2, y2 = (float(v) for v in bbox_px)
    bw, bh = max(4.0, x2 - x1), max(4.0, y2 - y1)
    pad = max(40.0, pad_ratio * max(bw, bh))
    rx1, ry1 = max(0.0, x1 - pad), max(0.0, y1 - pad)
    rx2, ry2 = min(float(W), x2 + pad), min(float(H), y2 + pad)
    roi_w, roi_h = int(rx2 - rx1), int(ry2 - ry1)
    if roi_w < 16 or roi_h < 16:
        raise ValueError("กรอบเล็กเกินไป")
    cx, cy = (rx1 + rx2) / 2, (ry1 + ry2) / 2
    if not (0 <= cx + dx < W and 0 <= cy + dy < H):
        raise ValueError("ชิ้นนี้หลุดขอบภาพที่สองหลังเลื่อนสเตจ")

    # Expected extra disparity of the tallest part, rounded up for SGBM (multiple of 16).
    max_extra = d0 * (camera_distance_mm / max(1.0, camera_distance_mm - MAX_PART_HEIGHT_MM) - 1)
    min_disp = -8
    num_disp = int(math.ceil((max_extra - min_disp + 8) / 16.0)) * 16
    num_disp = max(32, min(num_disp, 256))

    # Rotated patches with the board shift along +u; B is pre-shifted by the board shift so
    # the board has ~0 residual disparity and taller parts have a positive one.
    diag = int(math.ceil(math.hypot(roi_w, roi_h)))
    pw, ph = diag + num_disp + 16, diag
    m_a = _patch_matrix((cx, cy), theta, (pw, ph))
    m_b = _patch_matrix((cx + dx, cy + dy), theta, (pw, ph))
    flags = cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP
    ga, gb = to_gray(frame_a), to_gray(frame_b)
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
        uniquenessRatio=12,
        speckleWindowSize=150,
        speckleRange=1,
        mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY,
    )
    # left = B, right = A: a point at u in B is at u - disp in A.
    raw = sgbm.compute(pb, pa).astype(np.float32) / 16.0
    # Local contrast of the reference patch: texture-less areas give unreliable matches.
    pbf = pb.astype(np.float32)
    mean = cv2.blur(pbf, (block, block))
    std = np.sqrt(np.maximum(cv2.blur(pbf * pbf, (block, block)) - mean * mean, 0))
    invalid = (raw < min_disp) | (std < MIN_TEXTURE_STD)
    residual = np.where(invalid, np.nan, raw)

    # Back to frame-A orientation over the ROI: roi(x, y) -> patch(u, v).
    to_patch = _invert_affine(m_a)
    shift_roi = np.array([[1, 0, rx1], [0, 1, ry1]], dtype=np.float64)
    m_roi = to_patch @ np.vstack([shift_roi, [0, 0, 1]])
    sentinel = -1e4
    filled = np.where(np.isnan(residual), sentinel, residual).astype(np.float32)
    res_roi = cv2.warpAffine(filled, m_roi, (roi_w, roi_h), flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=sentinel)
    res_roi[res_roi <= sentinel / 2] = np.nan

    # Local board level: the margin around the part's box.
    yy, xx = np.mgrid[0:roi_h, 0:roi_w]
    inside = (xx + rx1 >= x1) & (xx + rx1 <= x2) & (yy + ry1 >= y1) & (yy + ry1 <= y2)
    ring = res_roi[~inside]
    ring = ring[np.isfinite(ring)]
    if ring.size < 50:
        raise ValueError("รอบชิ้นนี้มีลายให้จับคู่ไม่พอ วัดระดับบอร์ดไม่ได้")
    board_residual = float(np.median(ring))

    d = d0 + res_roi
    d_board = d0 + board_residual
    heights = camera_distance_mm * (1.0 - d_board / d)
    heights[~np.isfinite(heights)] = np.nan
    valid = np.isfinite(heights) & (heights > -5.0) & (heights < MAX_PART_HEIGHT_MM + 5)
    valid = reject_outliers(np.nan_to_num(heights), valid)
    heights = np.clip(np.nan_to_num(heights), -5.0, MAX_PART_HEIGHT_MM)

    valid_ratio = float(valid.mean())
    if valid_ratio < 0.15:
        raise ValueError("จับคู่ภาพได้น้อยเกินไป (ผิวเรียบหรือสะท้อนแสง)")
    # Fill holes from their surroundings, then smooth.
    hole_mask = (~valid).astype(np.uint8)
    base = np.where(valid, heights, 0).astype(np.float32)
    if hole_mask.any():
        base = cv2.inpaint(base, hole_mask, 5, cv2.INPAINT_TELEA)
    base = cv2.medianBlur(base, 5)
    base = cv2.GaussianBlur(base, (0, 0), 1.0)

    inside_vals = base[inside]
    inside_valid = valid[inside]
    measured = inside_vals[inside_valid] if inside_valid.any() else inside_vals
    stats = {
        # 95th percentile: the top of the part without the last few stray matches.
        "max_mm": round(float(np.percentile(measured, 95)), 2) if measured.size else None,
        "median_mm": round(float(np.median(measured)), 2) if measured.size else None,
        "valid_ratio": round(valid_ratio, 3),
        "box_valid_ratio": round(float(inside_valid.mean()), 3) if inside_valid.size else 0.0,
        "board_shift_px": round(d0, 2),
        "board_residual_px": round(board_residual, 2),
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
