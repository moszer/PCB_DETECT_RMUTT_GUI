"""Compensate a board placed turned or shifted vs. when its points were taught.

1. Before a scan, shoot the two taught points farthest apart, register each against its
   reference picture and solve the board's rotation and offset on the stage (needs the stage
   calibration for px→mm). Every scan point's stage position is then recomputed so the
   camera sees the same part of the board as when it was taught.
2. At each point, the first frame is registered against that point's reference picture and
   all of the point's frames are warped onto it (the stage cannot rotate the board, so the
   leftover rotation is undone in the image), putting the taught boxes back on the parts.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

from ..config import settings
from ..core.inspection import digital_zoom
from ..core.registration import corrected_position, decode_image, register_images, solve_board_pose
from .camera_service import camera_service
from .machine_service import machine_service

logger = logging.getLogger(__name__)


class BoardMisplaced(RuntimeError):
    """The board is turned or shifted further than the configured limits."""


def stage_matrix_for(frame_shape: Sequence[int], zoom: float) -> Optional[np.ndarray]:
    """Stage mm -> image px for a frame of this size at this digital zoom (stage calibration)."""
    from .stage_calibration_service import stage_calibration_service

    cal = stage_calibration_service.last_result()
    try:
        m = np.asarray(cal["stage_to_image"], np.float64).reshape(2, 2)
        cal_h = int(cal["image_size"][1])
    except (KeyError, TypeError, ValueError):
        return None
    if cal_h <= 0 or abs(np.linalg.det(m)) < 1e-6:
        return None
    # Capture modes are crops of one sensor (px per mm follows the height); zoom magnifies.
    return m * (int(frame_shape[0]) / cal_h) * max(1.0, float(zoom or 1.0))


def pick_reference_points(points: Sequence[Any], refs: Dict[int, str]) -> List[Any]:
    """The two taught points farthest apart (one if only one has a reference picture)."""
    taught = [p for p in points if p.index in refs]
    if len(taught) <= 1:
        return taught
    best = max(((a, b) for i, a in enumerate(taught) for b in taught[i + 1:]),
               key=lambda ab: math.hypot(ab[0].x_mm - ab[1].x_mm, ab[0].y_mm - ab[1].y_mm))
    return list(best)


def estimate_board_pose(
    points: Sequence[Any],
    refs: Dict[int, str],
    settle_sec: float,
    speed: int,
    should_stop: Callable[[], bool],
) -> Dict[str, Any]:
    """Measure how the board is placed; returns the pose plus what was measured."""
    chosen = pick_reference_points(points, refs)
    samples, measured, matrix = [], [], None
    for pt in chosen:
        if should_stop():
            raise RuntimeError("stopped")
        ref = decode_image(refs[pt.index])
        if ref is None:
            continue
        machine_service.move_to_steps(pt.x_steps, pt.y_steps, speed=speed)
        time.sleep(settle_sec)
        stab = camera_service.wait_until_still(time.monotonic(), should_stop=should_stop)
        _, frame = camera_service.get_fresh_frame(stab["timestamp"], timeout_sec=3.0)
        frame = digital_zoom(frame, pt.zoom)
        reg = register_images(ref, frame)
        measured.append({"point": pt.index, "name": pt.name, "registered": bool(reg),
                         **({k: reg[k] for k in ("angle_deg", "shift_px", "inliers", "method")} if reg else {})})
        if not reg:
            continue
        matrix = stage_matrix_for(frame.shape, pt.zoom)
        if matrix is None:
            return {"status": "no_calibration", "measured": measured}
        samples.append({"stage_mm": [pt.x_steps / machine_service.steps_per_mm, pt.y_steps / machine_service.steps_per_mm],
                        "shift_px": reg["shift_px"], "angle_deg": reg["angle_deg"], "matrix_px_per_mm": matrix.tolist()})
    if not samples:
        return {"status": "not_found", "measured": measured}
    pose = solve_board_pose(samples)
    return {"status": "ok", **pose, "measured": measured}


def apply_pose(points: Sequence[Any], pose: Dict[str, Any]) -> None:
    """Move every scan point to where its part of the board is now (in place)."""
    spm = machine_service.steps_per_mm
    state = machine_service.get_state()
    max_x = min(state.limits_steps[0], round(state.soft_limits_mm[0] * spm))
    max_y = min(state.limits_steps[1], round(state.soft_limits_mm[1] * spm))
    for pt in points:
        x, y = corrected_position((pt.x_steps / spm, pt.y_steps / spm), pose)
        xs, ys = int(round(x * spm)), int(round(y * spm))
        if not (0 <= xs <= max_x and 0 <= ys <= max_y):
            raise BoardMisplaced(f"จุด {pt.name or pt.index + 1} อยู่นอกระยะเคลื่อนที่หลังชดเชยตำแหน่งบอร์ด — วางบอร์ดให้ใกล้ตำแหน่งเดิมขึ้น")
        pt.x_steps, pt.y_steps = xs, ys
        pt.x_mm, pt.y_mm = round(xs / spm, 2), round(ys / spm, 2)


def check_limits(pose: Dict[str, Any]) -> None:
    angle = abs(pose["angle_deg"])
    offset = math.hypot(*pose["offset_mm"])
    if angle > settings.board_align_max_deg or offset > settings.board_align_max_mm:
        raise BoardMisplaced(
            f"บอร์ดวางเอียง {pose['angle_deg']:+.1f}° เลื่อน {offset:.1f} mm เกินที่ชดเชยได้ "
            f"(≤ {settings.board_align_max_deg:g}° และ ≤ {settings.board_align_max_mm:g} mm) — วางบอร์ดใหม่ให้ใกล้ตำแหน่งเดิม"
        )


class PointAligner:
    """Warps the frames of one point onto its reference picture (registration on the first)."""

    def __init__(self, reference: Optional[str]):
        self.ref = decode_image(reference) if reference else None
        self.matrix = None
        self.info: Dict[str, Any] = {"applied": False}
        self._tried = False

    def __call__(self, frame: np.ndarray) -> np.ndarray:
        if self.ref is None:
            return frame
        if not self._tried:
            self._tried = True
            reg = register_images(self.ref, frame)
            h, w = frame.shape[:2]
            if reg and (abs(reg["angle_deg"]) > settings.board_align_max_deg or
                        math.hypot(*reg["shift_px"]) > 0.3 * min(h, w)):
                reg = None  # implausible for a placed board: most likely a mismatch
            if reg:
                self.matrix = reg["matrix"]
                self.info = {"applied": True, **{k: reg[k] for k in ("angle_deg", "shift_px", "inliers", "method")}}
            else:
                self.info = {"applied": False, "reason": "จับคู่กับภาพต้นแบบไม่ได้"}
        if self.matrix is None:
            return frame
        from ..core.registration import warp_to_reference

        return warp_to_reference(frame, self.matrix)
