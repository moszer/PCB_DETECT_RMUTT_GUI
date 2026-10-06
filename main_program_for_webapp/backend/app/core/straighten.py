"""Straighten the camera picture: a camera mounted a little turned shows the board slanted.

`estimate_skew_deg(frame)` finds how far the board's dominant directions (traces, pad rows,
part edges — nearly all at 0°/90°) are from the image axes, from a magnitude-weighted
histogram of gradient directions folded to ±45°. It returns the angle to rotate the picture
by (cv2.getRotationMatrix2D convention: positive = counter-clockwise) to make them level.
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

import cv2
import numpy as np

MAX_SKEW_DEG = 15.0


def rotation_matrix(shape: Tuple[int, ...], angle_deg: float) -> np.ndarray:
    h, w = shape[:2]
    return cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle_deg, 1.0)


def rotate(frame: np.ndarray, angle_deg: float) -> np.ndarray:
    """The picture turned by `angle_deg` about its centre, same size (edges replicated)."""
    if not angle_deg:
        return frame
    h, w = frame.shape[:2]
    return cv2.warpAffine(frame, rotation_matrix(frame.shape, angle_deg), (w, h),
                          flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def estimate_skew_deg(frame: np.ndarray, work_side: int = 1024) -> Optional[float]:
    """Rotation that levels the board's lines, or None when there is no clear direction.

    The histogram is pulled a little toward 0° by the pixel grid, so the estimate is
    iterated: level by it, measure what is left, add (converges in 2–3 rounds).
    """
    g = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = g.shape[:2]
    k = min(1.0, work_side / max(h, w))
    if k < 1:
        g = cv2.resize(g, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
    total = 0.0
    for _ in range(4):
        step = _skew_once(rotate(g, total))
        if step is None:
            return None if total == 0.0 else round(total, 3)
        total += step
        if abs(step) < 0.02:
            break
    return round(total, 3) if abs(total) <= MAX_SKEW_DEG else None


def _skew_once(g: np.ndarray) -> Optional[float]:
    # Leave out the rim (vignetting; replicated edges of an already-rotated frame are exactly
    # axis-aligned) and smooth enough that the pixel grid itself does not pull toward 0°.
    mh, mw = int(g.shape[0] * 0.08), int(g.shape[1] * 0.08)
    g = cv2.GaussianBlur(g[mh:g.shape[0] - mh, mw:g.shape[1] - mw], (0, 0), 1.5).astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=5)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=5)
    mag = np.hypot(gx, gy)
    strong = mag > np.percentile(mag, 90)  # edges only, not the texture of the substrate
    if strong.sum() < 500:
        return None
    ang = np.degrees(np.arctan2(gy[strong], gx[strong]))
    ang = (ang + 45.0) % 90.0 - 45.0  # 0° and 90° (and 180°, 270°) fold together
    weights = mag[strong]
    bins = np.arange(-MAX_SKEW_DEG, MAX_SKEW_DEG + 0.05, 0.05)
    hist, edges = np.histogram(ang, bins=bins, weights=weights)
    hist = np.convolve(hist, np.ones(9) / 9, mode="same")
    i = int(np.argmax(hist))
    if hist[i] <= 2.0 * np.median(hist):  # no dominant direction
        return None
    # Parabolic refinement of the peak.
    centre = (edges[i] + edges[i + 1]) / 2
    if 0 < i < len(hist) - 1:
        a, b, c = hist[i - 1], hist[i], hist[i + 1]
        denom = a - 2 * b + c
        if denom:
            centre += 0.5 * (a - c) / denom * (edges[1] - edges[0])
    # Gradients are perpendicular to the lines and share their skew; with image y pointing
    # down, the measured skew is already the rotation that undoes it.
    return round(float(centre), 3)


def rotate_vectors(matrix_px_per_mm: np.ndarray, angle_deg: float) -> np.ndarray:
    """A stage→image matrix measured on unrotated frames, for frames rotated by `angle_deg`."""
    r = rotation_matrix((2, 2), angle_deg)[:, :2]
    return r @ matrix_px_per_mm
