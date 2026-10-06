"""Board registration: how the board on the stage is turned and shifted vs. its golden placement.

Image level — `register_images(ref, frame)`: the similarity transform (rotation + shift, scale
≈ 1) that maps a point's reference picture onto a new frame of the same point. ORB features +
RANSAC find it even for a few mm / degrees of misplacement; ECC then refines it to a fraction
of a pixel. The frame can then be warped back onto the reference (`warp_to_reference`), so the
taught boxes sit on the parts again.

Board level — `solve_board_pose(samples)`: with the stage calibration (stage mm → image px) the
image shifts at two or more points far apart give the board's rotation and offset in stage
coordinates, and `corrected_position` where to send the stage so each point sees what it saw
when it was taught.

Conventions: a board feature under the camera with the stage at P has board coordinate b = −P
(the board moves with the stage). A board displaced by d (stage mm) shifts the picture as a
stage move of d would: M @ d px. The board's placement maps b to R b + t.
"""
from __future__ import annotations

import base64
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

WORK_SIDE = 1280
MIN_INLIERS = 15


def decode_image(data: str) -> Optional[np.ndarray]:
    """A reference picture from a data: URL (as taught in the browser) or a file path."""
    if not data:
        return None
    if data.startswith("data:"):
        try:
            raw = base64.b64decode(data.split(",", 1)[1])
        except (ValueError, IndexError):
            return None
        return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    return cv2.imread(data, cv2.IMREAD_COLOR)


def _gray(img: np.ndarray, size: Tuple[int, int]) -> np.ndarray:
    g = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if (g.shape[1], g.shape[0]) != size:
        g = cv2.resize(g, size, interpolation=cv2.INTER_AREA)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(g)


def _similarity_parts(a: np.ndarray) -> Tuple[float, float]:
    """(rotation rad, scale) of a 2x3 similarity matrix."""
    return math.atan2(a[1, 0], a[0, 0]), math.hypot(a[0, 0], a[1, 0])


def register_images(ref: np.ndarray, frame: np.ndarray, work_side: int = WORK_SIDE) -> Optional[Dict[str, Any]]:
    """Transform mapping reference pixels onto the frame (both seen at the same zoom).

    Returns {matrix (2x3, in FRAME pixels, ref→frame), angle_deg, shift_px (of the frame
    centre), scale, inliers, method} or None when the two pictures cannot be matched.
    """
    fh, fw = frame.shape[:2]
    k = min(1.0, work_side / max(fh, fw))
    size = (max(16, int(round(fw * k))), max(16, int(round(fh * k))))
    a, b = _gray(ref, size), _gray(frame, size)

    orb = cv2.ORB_create(nfeatures=4000, scaleFactor=1.2, nlevels=8, fastThreshold=12)
    ka, da = orb.detectAndCompute(a, None)
    kb, db = orb.detectAndCompute(b, None)
    if da is None or db is None or len(ka) < MIN_INLIERS or len(kb) < MIN_INLIERS:
        return None
    matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2)
    good = [m[0] for m in matches if len(m) == 2 and m[0].distance < 0.8 * m[1].distance]
    if len(good) < MIN_INLIERS:
        return None
    src = np.float32([ka[m.queryIdx].pt for m in good])
    dst = np.float32([kb[m.trainIdx].pt for m in good])
    est, mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0,
                                            maxIters=4000, confidence=0.995)
    if est is None or mask is None or int(mask.sum()) < MIN_INLIERS:
        return None
    _, scale = _similarity_parts(est)
    if not 0.95 <= scale <= 1.05:  # the same point at the same zoom: anything else is a mismatch
        return None
    inliers = int(mask.sum())
    method = "orb"

    # Sub-pixel refinement (rotation + shift only) on a smaller copy, started from ORB's answer.
    rs = min(1.0, 640 / max(size))
    small = (max(16, int(size[0] * rs)), max(16, int(size[1] * rs)))
    sa, sb = cv2.resize(a, small).astype(np.float32), cv2.resize(b, small).astype(np.float32)
    angle, _ = _similarity_parts(est)
    c, s = math.cos(angle), math.sin(angle)
    warp = np.float32([[c, -s, est[0, 2] * rs], [s, c, est[1, 2] * rs]])
    try:
        _, warp = cv2.findTransformECC(sa, sb, warp, cv2.MOTION_EUCLIDEAN,
                                       (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 80, 1e-5), None, 5)
        refined = np.float64(warp)
        refined[:, 2] /= rs
        # Keep ECC only if it agrees with the feature match (it can slide along repetitive pins).
        if abs(math.atan2(refined[1, 0], refined[0, 0]) - angle) < math.radians(0.5) and \
                np.hypot(*(refined[:, 2] - est[:, 2])) < 6:
            est = refined
            method = "orb+ecc"
    except cv2.error:
        pass

    # Back to full frame pixels.
    m = np.float64(est).copy()
    m[:, 2] /= k
    centre = np.array([fw / 2, fh / 2])
    shift = m[:, :2] @ centre + m[:, 2] - centre
    angle, scale = _similarity_parts(m)
    return {
        "matrix": m.tolist(),
        "angle_deg": round(math.degrees(angle), 4),
        "shift_px": [round(float(shift[0]), 2), round(float(shift[1]), 2)],
        "scale": round(scale, 5),
        "inliers": inliers,
        "method": method,
    }


def warp_to_reference(frame: np.ndarray, matrix: Sequence[Sequence[float]]) -> np.ndarray:
    """The frame resampled into the reference picture's geometry (inverse of ref→frame)."""
    inv = cv2.invertAffineTransform(np.float64(matrix))
    h, w = frame.shape[:2]
    return cv2.warpAffine(frame, inv, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def _rot(theta: float) -> np.ndarray:
    c, s = math.cos(theta), math.sin(theta)
    return np.array([[c, -s], [s, c]])


def solve_board_pose(samples: Sequence[Dict[str, Any]], min_baseline_mm: float = 4.0) -> Dict[str, Any]:
    """Board rotation and offset (stage coordinates) from registered points.

    Each sample: {stage_mm: [x, y] (where the point was taught), shift_px: [dx, dy] and
    angle_deg (from register_images), matrix_px_per_mm: 2x2 stage→image at that zoom}.
    """
    if not samples:
        raise ValueError("no registered points")
    disp, boards, angles = [], [], []
    for smp in samples:
        m = np.asarray(smp["matrix_px_per_mm"], np.float64)
        m_inv = np.linalg.inv(m)
        disp.append(m_inv @ np.asarray(smp["shift_px"], np.float64))
        boards.append(-np.asarray(smp["stage_mm"], np.float64))
        # Image rotation seen in stage coordinates (the camera may be mirrored vs. the stage).
        r_stage = m_inv @ _rot(math.radians(smp["angle_deg"])) @ m
        angles.append(math.atan2(r_stage[1, 0] - r_stage[0, 1], r_stage[0, 0] + r_stage[1, 1]))
    theta = float(np.mean(angles))
    source = "image"
    if len(samples) >= 2:
        # Two points far apart pin the angle down much better than one picture's rotation.
        i, j = max(((i, j) for i in range(len(boards)) for j in range(i + 1, len(boards))),
                   key=lambda p: np.linalg.norm(boards[p[0]] - boards[p[1]]))
        v = boards[i] - boards[j]
        if np.linalg.norm(v) >= min_baseline_mm:
            v2 = v + (disp[i] - disp[j])
            theta = math.atan2(v2[1], v2[0]) - math.atan2(v[1], v[0])
            theta = (theta + math.pi) % (2 * math.pi) - math.pi
            source = "two_points"
    r = _rot(theta)
    t = np.mean([d - (r - np.eye(2)) @ b for d, b in zip(disp, boards)], axis=0)
    residual = max(float(np.linalg.norm(d - ((r - np.eye(2)) @ b + t))) for d, b in zip(disp, boards))
    return {
        "angle_deg": round(math.degrees(theta), 4),
        "offset_mm": [round(float(t[0]), 4), round(float(t[1]), 4)],
        "residual_mm": round(residual, 4),
        "angle_source": source,
        "points": len(samples),
    }


def corrected_position(stage_mm: Sequence[float], pose: Dict[str, Any]) -> Tuple[float, float]:
    """Where to send the stage so it sees what it saw at `stage_mm` with the golden board."""
    r = _rot(math.radians(pose["angle_deg"]))
    p = r @ np.asarray(stage_mm, np.float64) - np.asarray(pose["offset_mm"], np.float64)
    return float(p[0]), float(p[1])
