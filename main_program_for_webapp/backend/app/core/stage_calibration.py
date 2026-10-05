"""XY stage accuracy from the camera: the board moves under a fixed camera, so every stage
move shows up as an image shift that phase correlation measures to a fraction of a pixel.

From passes along each axis (approached in + and then in -) this gives, per axis:
  * scale   — image px per commanded mm (a 2D vector; together they form the stage→image
              matrix M, which also gives the camera's rotation and the axes' squareness)
  * backlash — the gap between the + and - passes (lost motion on reversal)
  * linearity / straightness — how far the points stray from a straight line, along and
              across the axis
and, from repeated returns to the centre, the repeatability from each side.

All lengths are in commanded stage mm (via M⁻¹). An optional checkerboard of known square size
gives the camera's mm per px, and with it the true mm moved per commanded mm.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .depth import to_gray


def _prep(frame: np.ndarray, scale: float) -> np.ndarray:
    g = to_gray(frame).astype(np.float32)
    if scale < 1:
        g = cv2.resize(g, (max(1, int(g.shape[1] * scale)), max(1, int(g.shape[0] * scale))), interpolation=cv2.INTER_AREA)
    return g


def measure_shift(
    ref: np.ndarray,
    frame: np.ndarray,
    predicted: Optional[Tuple[float, float]] = None,
    work_side: int = 2048,
) -> Tuple[float, float, float]:
    """Image shift (px) of `frame` relative to `ref`, and the correlation peak strength.

    With a predicted shift the frame is moved back by it first and only the small remainder is
    correlated (over the overlapping area), which stays reliable for shifts too large for a
    plain whole-frame correlation.
    """
    h, w = ref.shape[:2]
    scale = min(1.0, work_side / max(h, w))
    a, b = _prep(ref, scale), _prep(frame, scale)
    px, py = (0.0, 0.0) if predicted is None else predicted
    if predicted is not None:
        m = np.float32([[1, 0, -px * scale], [0, 1, -py * scale]])
        b = cv2.warpAffine(b, m, (b.shape[1], b.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        # Only the part both frames saw.
        mx, my = int(min(a.shape[1] // 3, abs(px) * scale + 8)), int(min(a.shape[0] // 3, abs(py) * scale + 8))
        a, b = a[my:a.shape[0] - my, mx:a.shape[1] - mx], b[my:b.shape[0] - my, mx:b.shape[1] - mx]
    window = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(a, b, window)
    return px + dx / scale, py + dy / scale, float(response)


def fit_axis(positions_mm: Sequence[float], shifts_px: Sequence[Sequence[float]], forward: Sequence[bool]) -> Dict[str, Any]:
    """One slope (px per mm, 2D) shared by both passes, one offset per approach direction."""
    p = np.asarray(positions_mm, np.float64)
    s = np.asarray(shifts_px, np.float64)
    f = np.asarray(forward, bool)
    if f.sum() < 2 or (~f).sum() < 2:
        raise ValueError("ต้องมีจุดวัดทั้งขาไปและขากลับอย่างน้อยทิศละ 2 จุด")
    p0 = float(p.mean())
    design = np.column_stack([p - p0, f.astype(np.float64), (~f).astype(np.float64)])
    coef, *_ = np.linalg.lstsq(design, s, rcond=None)
    slope, off_fwd, off_back = coef[0], coef[1], coef[2]
    return {
        "slope_px_per_mm": slope.tolist(),
        "offset_forward_px": off_fwd.tolist(),
        "offset_backward_px": off_back.tolist(),
        "residuals_px": (s - design @ coef).tolist(),
        "center_mm": p0,
        "positions_mm": p.tolist(),
        "forward": f.tolist(),
    }


def stage_matrix(fit_x: Dict[str, Any], fit_y: Dict[str, Any]) -> np.ndarray:
    """M: image px = M @ stage mm (columns = image motion per mm of X and of Y)."""
    return np.column_stack([fit_x["slope_px_per_mm"], fit_y["slope_px_per_mm"]])


def _to_mm(m_inv: np.ndarray, vec_px: Sequence[float]) -> np.ndarray:
    return m_inv @ np.asarray(vec_px, np.float64)


def checkerboard_mm_per_px(frame: np.ndarray, inner_corners: Tuple[int, int], square_mm: float) -> Optional[float]:
    """Camera scale from a checkerboard (inner corners cols x rows) of known square size."""
    gray = to_gray(frame)
    found, corners = cv2.findChessboardCornersSB(gray, inner_corners, flags=cv2.CALIB_CB_NORMALIZE_IMAGE)
    if not found:
        return None
    c = corners.reshape(inner_corners[1], inner_corners[0], 2)
    steps = np.concatenate([
        np.linalg.norm(np.diff(c, axis=1), axis=2).ravel(),
        np.linalg.norm(np.diff(c, axis=0), axis=2).ravel(),
    ])
    return float(square_mm / np.median(steps))


def summarize(
    fit_x: Dict[str, Any],
    fit_y: Dict[str, Any],
    repeat: Dict[str, List[Sequence[float]]],
    mm_per_px: Optional[float] = None,
    steps_per_mm: Optional[float] = None,
) -> Dict[str, Any]:
    """Accuracy figures (commanded mm unless noted) from both axis fits and the repeat test.

    `repeat` maps an approach label ("plus", "minus", optionally "compensated") to the image
    shifts (px, vs the reference frame) of the returns to the centre made that way.
    """
    m = stage_matrix(fit_x, fit_y)
    if abs(np.linalg.det(m)) < 1e-6:
        raise ValueError("ภาพไม่เลื่อนตามสเตจ (แกน X กับ Y ไปทางเดียวกัน) — ตรวจกล้องและบอร์ด")
    m_inv = np.linalg.inv(m)
    axes: Dict[str, Any] = {}
    for name, fit, k in (("x", fit_x, 0), ("y", fit_y, 1)):
        gap_mm = _to_mm(m_inv, np.subtract(fit["offset_forward_px"], fit["offset_backward_px"]))
        res_mm = np.array([_to_mm(m_inv, r) for r in fit["residuals_px"]])
        along, across = res_mm[:, k], res_mm[:, 1 - k]
        slope = np.asarray(fit["slope_px_per_mm"])
        axis = {
            "px_per_mm": round(float(np.linalg.norm(slope)), 3),
            # Lost motion on reversal: the backward pass lags the forward pass by this much.
            "backlash_mm": round(float(abs(gap_mm[k])), 4),
            "backlash_cross_mm": round(float(gap_mm[1 - k]), 4),
            # Worst deviation from a straight, evenly spaced line.
            "linearity_mm": round(float(np.max(np.abs(along))), 4),
            "straightness_mm": round(float(np.max(np.abs(across))), 4),
            "points": len(fit["residuals_px"]),
        }
        # Each point's position error along the axis vs the forward pass's straight line (mm):
        # the forward points show the linearity, the backward ones sit lower by the backlash.
        if "positions_mm" in fit:
            line_fwd = np.outer(np.asarray(fit["positions_mm"]) - fit["center_mm"], slope) + np.asarray(fit["offset_forward_px"])
            shifts = line_fwd + np.asarray(fit["residuals_px"]) + np.outer(
                ~np.asarray(fit["forward"]), np.subtract(fit["offset_backward_px"], fit["offset_forward_px"]))
            err = np.array([_to_mm(m_inv, d)[k] for d in shifts - line_fwd])
            axis["errors"] = [[round(float(p), 3), round(float(e), 4), bool(f)]
                              for p, e, f in zip(fit["positions_mm"], err, fit["forward"])]
        if mm_per_px:
            true_ratio = float(np.linalg.norm(slope)) * mm_per_px  # mm moved per commanded mm
            axis["scale_error_pct"] = round((true_ratio - 1) * 100, 3)
            if steps_per_mm:
                axis["suggested_steps_per_mm"] = round(steps_per_mm / true_ratio, 3)
        axes[name] = axis

    vx, vy = m[:, 0], m[:, 1]
    cos = float(vx @ vy / (np.linalg.norm(vx) * np.linalg.norm(vy)))
    # The board may move either way in the image; the rotation is that of the X motion line.
    sx = vx if vx[0] >= 0 else -vx
    result: Dict[str, Any] = {
        "x": axes["x"],
        "y": axes["y"],
        # Rotation of the camera's image x axis relative to stage X (deg).
        "camera_rotation_deg": round(math.degrees(math.atan2(sx[1], sx[0])), 3),
        # How far the angle between the stage axes is from 90° (as seen by the camera).
        "squareness_deg": round(90.0 - math.degrees(math.acos(max(-1.0, min(1.0, abs(cos))))), 3),
        # Y scale relative to X (with square pixels): a lead/belt or steps/mm mismatch between axes.
        "xy_scale_ratio": round(float(np.linalg.norm(vy) / np.linalg.norm(vx)), 5),
        "stage_to_image": m.round(4).tolist(),
        "mm_per_px": mm_per_px,
    }
    rep: Dict[str, Any] = {}
    means = {}
    for label, shots in repeat.items():
        if not shots:
            continue
        mm = np.array([_to_mm(m_inv, s) for s in shots])
        means[label] = mm.mean(axis=0)
        spread = np.linalg.norm(mm - mm.mean(axis=0), axis=1)
        rep[label] = {
            "n": len(shots),
            # Typical (RMS) and worst distance of a return from the mean of its group.
            "rms_mm": round(float(np.sqrt(np.mean(spread ** 2))), 4),
            "max_mm": round(float(spread.max()), 4),
        }
    if "plus" in means and "minus" in means:
        gap = means["plus"] - means["minus"]
        rep["direction_gap_mm"] = [round(float(gap[0]), 4), round(float(gap[1]), 4)]
    if "compensated" in repeat and repeat["compensated"]:
        mm = np.array([_to_mm(m_inv, s) for s in repeat["compensated"]])
        rep["compensated"]["worst_pair_mm"] = round(float(max(
            np.linalg.norm(a - b) for i, a in enumerate(mm) for b in mm[i + 1:]
        )) if len(mm) > 1 else 0.0, 4)
    result["repeatability"] = rep
    worst = max(axes["x"]["backlash_mm"], axes["y"]["backlash_mm"])
    # Approach overshoot that takes up the measured backlash with some margin.
    result["suggested_approach_mm"] = round(min(2.0, max(0.1, worst * 1.5 + 0.05)), 2)
    return result
