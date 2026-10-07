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


def find_checkerboard(frame: np.ndarray, inner_corners: Tuple[int, int], square_mm: float) -> Optional[Dict[str, Any]]:
    """Camera scale from a checkerboard of known square size: {mm_per_px, pattern} or None.

    Searched on a ~1600 px copy (a 4K frame is slow and less reliable), with the counts as
    given, swapped (landscape/portrait), and one less each way (squares counted instead of
    the inner corners — a common slip).
    """
    gray = to_gray(frame)
    h, w = gray.shape[:2]
    scale = min(1.0, 1600 / max(h, w))
    small = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else gray
    cols, rows = inner_corners
    tries = [(cols, rows), (rows, cols), (cols - 1, rows - 1), (rows - 1, cols - 1)]
    flags = cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY
    for pattern in dict.fromkeys(t for t in tries if min(t) >= 2):
        found, corners = cv2.findChessboardCornersSB(small, pattern, flags=flags)
        if not found:
            continue
        c = corners.reshape(pattern[1], pattern[0], 2) / scale
        steps = np.concatenate([
            np.linalg.norm(np.diff(c, axis=1), axis=2).ravel(),
            np.linalg.norm(np.diff(c, axis=0), axis=2).ravel(),
        ])
        return {"mm_per_px": float(square_mm / np.median(steps)), "pattern": [int(pattern[0]), int(pattern[1])]}
    return None


def checkerboard_mm_per_px(frame: np.ndarray, inner_corners: Tuple[int, int], square_mm: float) -> Optional[float]:
    """Camera scale from a checkerboard (inner corners cols x rows) of known square size."""
    found = find_checkerboard(frame, inner_corners, square_mm)
    return found["mm_per_px"] if found else None


def checkerboard_image(inner_corners: Tuple[int, int], square_mm: float, dpi: int = 300, margin_mm: float = 10.0) -> np.ndarray:
    """A printable board (white margin, black/white squares) at `dpi`: inner corners cols x rows."""
    cols, rows = inner_corners
    px = square_mm / 25.4 * dpi
    m = int(round(margin_mm / 25.4 * dpi))
    w, h = int(round((cols + 1) * px)), int(round((rows + 1) * px))
    img = np.full((h + 2 * m, w + 2 * m), 255, np.uint8)
    for r in range(rows + 1):
        for c in range(cols + 1):
            if (r + c) % 2 == 0:
                x0, y0 = m + int(round(c * px)), m + int(round(r * px))
                img[y0:m + int(round((r + 1) * px)), x0:m + int(round((c + 1) * px))] = 0
    return img


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


# ── Whole-travel map ──────────────────────────────────────────────────────────
# The axis passes above measure ±2 mm around one spot. The map visits a grid of nodes over the
# whole travel; neighbouring nodes' pictures overlap, so the image shift between them measures
# the move between them. Solving all those shifts together (like stitching a panorama) gives
# where every node really is, and what is left after the best straight-line (affine) fit is the
# rail's position error at that node: lead/rack pitch errors, pinion run-out, a bent rail.


def measure_offset(
    ref: np.ndarray,
    frame: np.ndarray,
    predicted: Tuple[float, float],
    work_side: int = 2048,
) -> Tuple[float, float, float]:
    """Image shift of `frame` vs `ref` for large moves (up to ~70 % of the frame).

    Only the part both pictures saw at the predicted shift is correlated, so the result stays
    reliable when the overlap is small (measure_shift crops symmetrically, which loses most of
    the shared area for big shifts).
    """
    h, w = ref.shape[:2]
    scale = min(1.0, work_side / max(h, w))
    a, b = _prep(ref, scale), _prep(frame, scale)
    ph, pw = a.shape[:2]
    px, py = int(round(predicted[0] * scale)), int(round(predicted[1] * scale))
    x0, x1 = max(0, -px), min(pw, pw - px)
    y0, y1 = max(0, -py), min(ph, ph - py)
    if x1 - x0 < 0.2 * pw or y1 - y0 < 0.2 * ph:
        return float(predicted[0]), float(predicted[1]), 0.0
    a = a[y0:y1, x0:x1]
    b = b[y0 + py:y1 + py, x0 + px:x1 + px]
    window = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(a, b, window)
    return (px + dx) / scale, (py + dy) / scale, float(response)


def solve_grid(
    positions_mm: Sequence[Sequence[float]],
    edges: Sequence[Tuple[int, int, Sequence[float]]],
) -> Dict[str, Any]:
    """Node positions in the image from pairwise shifts, and each node's position error.

    `edges` are (i, j, shift px) with shift = image motion from node i's picture to node j's.
    Returns the solved image positions (px, node 0 at the origin; None where a node is not
    connected to node 0), the affine stage→image fit, the per-node error in commanded mm and
    how well the shifts agree with each other (edge residuals, mm).
    """
    c = np.asarray(positions_mm, np.float64)
    n = len(c)
    # Nodes linked to node 0 through measured edges.
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j, _ in edges:
        parent[find(i)] = find(j)
    linked = np.array([find(i) == find(0) for i in range(n)])
    if linked.sum() < 3:
        raise ValueError("จับคู่ภาพระหว่างจุดได้น้อยเกินไป — วางบอร์ดที่มีลวดลายให้ครอบคลุมทั้งระยะเคลื่อนที่")
    idx = {k: m for m, k in enumerate(int(i) for i in np.flatnonzero(linked) if i != 0)}
    use = [(i, j, s) for i, j, s in edges if linked[i] and linked[j]]
    a = np.zeros((len(use), len(idx)))
    rhs = np.zeros((len(use), 2))
    for e, (i, j, s) in enumerate(use):
        if j != 0:
            a[e, idx[j]] += 1
        if i != 0:
            a[e, idx[i]] -= 1
        rhs[e] = s
    sol, *_ = np.linalg.lstsq(a, rhs, rcond=None)
    u = np.full((n, 2), np.nan)
    u[0] = 0.0
    for k, m in idx.items():
        u[k] = sol[m]

    ok = linked
    if np.linalg.matrix_rank(np.column_stack([c[ok], np.ones(ok.sum())])) < 3:
        raise ValueError("จุดที่จับคู่ภาพได้อยู่แนวเดียวกันหมด — วัดได้ไม่ครบทั้งสองแกน")
    design = np.column_stack([c[ok], np.ones(ok.sum())])
    coef, *_ = np.linalg.lstsq(design, u[ok], rcond=None)
    m = coef[:2].T
    if abs(np.linalg.det(m)) < 1e-6:
        raise ValueError("ภาพไม่เลื่อนตามสเตจ — ตรวจกล้องและบอร์ด")
    m_inv = np.linalg.inv(m)
    err = np.full((n, 2), np.nan)
    err[ok] = (u[ok] - design @ coef) @ m_inv.T
    edge_res = [m_inv @ ((u[j] - u[i]) - np.asarray(s)) for i, j, s in use]
    return {"image_px": u, "matrix": m, "linked": ok, "error_mm": err,
            "edge_residual_mm": np.asarray(edge_res) if edge_res else np.zeros((0, 2)), "edges_used": len(use)}


def map_summary(
    cols: int,
    rows: int,
    positions_mm: Sequence[Sequence[float]],
    edges: Sequence[Tuple[int, int, Sequence[float]]],
    backlash_px: Sequence[Optional[Sequence[float]]],
    failed_edges: int = 0,
) -> Dict[str, Any]:
    """The whole-travel accuracy map (commanded mm; µm in the figures meant for reading)."""
    sol = solve_grid(positions_mm, edges)
    m, m_inv = sol["matrix"], np.linalg.inv(sol["matrix"])
    c = np.asarray(positions_mm, np.float64)
    u = sol["image_px"]
    # Local scale: how much farther (or shorter) each move between neighbours really went.
    scale: Dict[Tuple[int, int], List[float]] = {}
    for i, j, _ in edges:
        if not (sol["linked"][i] and sol["linked"][j]):
            continue
        d_cmd = c[j] - c[i]
        axis = 0 if abs(d_cmd[0]) >= abs(d_cmd[1]) else 1
        real = (m_inv @ (u[j] - u[i]))[axis]
        if abs(d_cmd[axis]) > 1e-6:
            pct = (real / d_cmd[axis] - 1) * 100
            for k in (i, j):
                scale.setdefault((k, axis), []).append(pct)
    nodes = []
    for k, (x, y) in enumerate(c):
        measured = bool(sol["linked"][k])
        e = sol["error_mm"][k]
        b = backlash_px[k] if k < len(backlash_px) else None
        bmm = (m_inv @ np.asarray(b, np.float64)) if b is not None else None
        sx, sy = scale.get((k, 0)), scale.get((k, 1))
        nodes.append({
            "col": k % cols if (k // cols) % 2 == 0 else cols - 1 - k % cols,
            "row": k // cols,
            "x_mm": round(float(x), 3), "y_mm": round(float(y), 3),
            "measured": measured,
            "err_mm": [round(float(e[0]), 4), round(float(e[1]), 4)] if measured else None,
            "err_um": round(float(np.hypot(*e)) * 1000, 1) if measured else None,
            "backlash_mm": [round(float(bmm[0]), 4), round(float(bmm[1]), 4)] if bmm is not None else None,
            "scale_x_pct": round(float(np.mean(sx)), 3) if sx else None,
            "scale_y_pct": round(float(np.mean(sy)), 3) if sy else None,
        })
    errs = np.array([n["err_um"] for n in nodes if n["err_um"] is not None])
    res = sol["edge_residual_mm"]
    back = np.array([n["backlash_mm"] for n in nodes if n["backlash_mm"] is not None])
    return {
        "mode": "map",
        "grid": [cols, rows],
        "xs": sorted({n["x_mm"] for n in nodes}),
        "ys": sorted({n["y_mm"] for n in nodes}),
        "nodes": nodes,
        "rms_um": round(float(np.sqrt(np.mean(errs ** 2))), 1) if len(errs) else None,
        "max_um": round(float(errs.max()), 1) if len(errs) else None,
        # How well the pairwise measurements agree: the noise floor of this map.
        "noise_um": round(float(np.sqrt(np.mean(np.sum(res ** 2, axis=1)))) * 1000, 1) if len(res) else None,
        "backlash_mean_mm": [round(float(v), 4) for v in back.mean(axis=0)] if len(back) else None,
        "stage_to_image": m.round(4).tolist(),
        "edges": sol["edges_used"],
        "failed_edges": int(failed_edges),
    }
