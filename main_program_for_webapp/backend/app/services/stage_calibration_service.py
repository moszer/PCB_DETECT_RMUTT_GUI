"""Measure the XY stage's accuracy with the camera (background job) and keep the last result."""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..config import STORAGE_DIR, settings
from ..core.stage_calibration import find_checkerboard, fit_axis, map_summary, measure_offset, measure_shift, summarize
from .camera_service import camera_service
from .machine_service import machine_service

logger = logging.getLogger(__name__)

RESULT_FILE = STORAGE_DIR / "stage_calibration.json"
MAP_FILE = STORAGE_DIR / "stage_map.json"
# Half-range of each axis pass and the number of points in it. ±2 mm keeps the image shift
# well inside the frame at ~130 px/mm (Jetson station camera at zoom 1).
RANGE_MM = 2.0
POINTS = 9
# Extra move beyond each end so the pass starts with the slack taken up in its direction.
LEAD_MM = 0.6
REPEATS = 4
FRAMES_PER_SHOT = 2
# Whole-travel map: neighbouring nodes must share at least ~40 % of the picture.
MAP_MAX_SHIFT = 0.6
MAP_MAX_NODES = 15
MAP_WORK_SIDE = 2048


class CalibrationCancelled(Exception):
    pass


class StageCalibrationService:
    def __init__(self):
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()
        self._status: Dict[str, Any] = {"state": "idle"}

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> Dict[str, Any]:
        with self._lock:
            out = dict(self._status)
        out["last"] = self.last_result()
        out["last_map"] = self.last_map()
        return out

    @staticmethod
    def last_result() -> Optional[Dict[str, Any]]:
        try:
            return json.loads(RESULT_FILE.read_text())
        except (OSError, ValueError):
            return None

    @staticmethod
    def last_map() -> Optional[Dict[str, Any]]:
        try:
            return json.loads(MAP_FILE.read_text())
        except (OSError, ValueError):
            return None

    def _set(self, **kw):
        with self._lock:
            self._status.update(kw)

    def start(self, checkerboard: Optional[Tuple[int, int]] = None, square_mm: Optional[float] = None,
              mode: str = "axes", density: int = 5) -> Dict[str, Any]:
        from .aoi_scan_service import aoi_scan_service
        from .dataset_service import dataset_service

        with self._lock:
            if self.is_running:
                raise RuntimeError("กำลัง calibrate อยู่แล้ว")
            if aoi_scan_service.is_running or dataset_service.is_running:
                raise RuntimeError("หยุดการสแกนก่อน calibrate")
            state = machine_service.get_state()
            if not state.connected or not state.homed:
                raise ValueError("ต้องเชื่อมต่อและ HOME สเตจก่อน")
            if not camera_service.is_active or camera_service.is_mock:
                raise ValueError("ต้องใช้กล้องจริง")
            self._cancel.clear()
            if mode == "map":
                plan = self._map_plan(density)
                self._status = {"state": "running", "mode": "map", "step": 0, "total": len(plan["nodes"]),
                                "message": "เริ่มวัดทั้งราง", "started": time.time(), "grid": [plan["cols"], plan["rows"]]}
                target, args = self._run_map, (plan,)
            else:
                self._status = {"state": "running", "mode": "axes", "step": 0, "total": self._total_steps(),
                                "message": "เริ่ม", "started": time.time()}
                target, args = self._run, (state.position_mm, checkerboard, square_mm)
            self._thread = threading.Thread(target=target, args=args, name="stage-calibration", daemon=True)
            self._thread.start()
        return self.status()

    def stop(self) -> None:
        self._cancel.set()

    @staticmethod
    def _total_steps() -> int:
        compensated = 2 * REPEATS if settings.stage_approach_mm > 0 else 0
        return 1 + 2 * (2 * POINTS) + 2 * REPEATS + compensated

    # ── stage / camera ─────────────────────────────────────────────────────────
    def _fresh_frame(self) -> np.ndarray:
        _, frame = camera_service.get_fresh_frame(time.monotonic(), timeout_sec=3.0)
        return frame

    def _shot(self) -> np.ndarray:
        frames = [self._fresh_frame() for _ in range(FRAMES_PER_SHOT)]
        if len(frames) == 1:
            return frames[0]
        return np.mean(np.stack(frames).astype(np.float32), axis=0).round().astype(np.uint8)

    def _move(self, x_mm: float, y_mm: float, compensate: bool = False) -> None:
        if self._cancel.is_set():
            raise CalibrationCancelled()
        spm = machine_service.steps_per_mm
        machine_service.move_to_steps(int(round(x_mm * spm)), int(round(y_mm * spm)),
                                      speed=settings.default_speed, compensate=compensate)
        time.sleep(max(0.4, settings.default_settle_sec))
        camera_service.wait_until_still(time.monotonic(), should_stop=self._cancel.is_set)

    def _advance(self, message: str) -> None:
        with self._lock:
            self._status["step"] = self._status.get("step", 0) + 1
            self._status["message"] = message

    # ── procedure ──────────────────────────────────────────────────────────────
    def _center(self, pos_mm: Sequence[float]) -> Tuple[float, float]:
        """The current position, pulled inward so every move of the test stays within travel."""
        state = machine_service.get_state()
        spm = machine_service.steps_per_mm
        limits = (min(state.limits_steps[0] / spm, state.soft_limits_mm[0]),
                  min(state.limits_steps[1] / spm, state.soft_limits_mm[1]))
        reach = RANGE_MM + LEAD_MM + max(1.0, settings.stage_approach_mm)
        out = []
        for p, lim in zip(pos_mm, limits):
            if lim < 2 * reach:
                raise ValueError(f"ระยะเคลื่อนที่ไม่พอสำหรับการ calibrate (ต้องการอย่างน้อย {2 * reach:.1f} mm ต่อแกน)")
            out.append(round(min(max(float(p), reach), lim - reach), 3))
        return out[0], out[1]

    def _run(self, pos_mm, checkerboard, square_mm) -> None:
        try:
            result = self._measure(pos_mm, checkerboard, square_mm)
            RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
            RESULT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2))
            self._set(state="done", message="เสร็จแล้ว", finished=time.time())
            machine_service.play("done")
        except CalibrationCancelled:
            self._set(state="cancelled", message="ยกเลิกแล้ว")
        except Exception as exc:  # report every failure to the UI instead of dying silently
            if self._cancel.is_set():
                self._set(state="cancelled", message="ยกเลิกแล้ว")
                return
            logger.exception("Stage calibration failed")
            self._set(state="error", message=str(exc))

    def _measure(self, pos_mm, checkerboard, square_mm) -> Dict[str, Any]:
        cx, cy = self._center(pos_mm)
        self._set(center_mm=[cx, cy])

        # Reference: the centre, reached in + on both axes.
        self._move(cx - LEAD_MM, cy - LEAD_MM)
        self._move(cx, cy)
        ref = self._shot()
        self._advance("ถ่ายภาพอ้างอิง")
        mm_per_px = None
        if checkerboard and square_mm:
            board = find_checkerboard(ref, checkerboard, square_mm)
            if board is None:
                raise ValueError(
                    f"ไม่เห็น checkerboard ({checkerboard[0]}×{checkerboard[1]} มุมด้านใน) ในภาพกล้อง — วางแผ่นให้ราบใต้กล้อง "
                    "ทั้งแผ่นอยู่ในภาพ หรือปิดตัวเลือก “ใช้ checkerboard” ถ้าไม่ต้องการวัดสเกลจริง (ค่าอื่นวัดได้ครบ)"
                )
            mm_per_px = board["mm_per_px"]
            checkerboard = tuple(board["pattern"])

        fits = {}
        for axis in ("x", "y"):
            fits[axis] = self._axis_pass(axis, cx, cy, ref)

        repeat: Dict[str, List[Tuple[float, float]]] = {"plus": [], "minus": []}
        expected = (0.0, 0.0)  # every return is to the centre, where the reference was taken
        for i in range(REPEATS):
            for label, side in (("minus", 1.0), ("plus", -1.0)):
                # Come to the centre from + (moving -) or from - (moving +) on both axes.
                self._move(cx + side, cy + side)
                self._move(cx, cy)
                repeat[label].append(self._shift(ref, self._shot(), expected))
                self._advance(f"ทดสอบกลับจุดเดิม {i + 1}/{REPEATS}")
        if settings.stage_approach_mm > 0:
            repeat["compensated"] = []
            for i in range(REPEATS):
                for side in (1.0, -1.0):
                    self._move(cx + side, cy + side, compensate=True)
                    self._move(cx, cy, compensate=True)
                    repeat["compensated"].append(self._shift(ref, self._shot(), expected))
                    self._advance(f"ทดสอบพร้อมชดเชย {i + 1}/{REPEATS}")

        summary = summarize(fits["x"], fits["y"], repeat, mm_per_px, machine_service.steps_per_mm)
        summary.update({
            "time": time.time(),
            "center_mm": [cx, cy],
            "range_mm": RANGE_MM,
            "steps_per_mm": machine_service.steps_per_mm,
            "approach_mm_during_test": settings.stage_approach_mm,
            "image_size": [int(ref.shape[1]), int(ref.shape[0])],
            # Frames were straightened by this much while measuring (see stage_matrix).
            "image_rotation_deg": settings.camera_rotate_deg,
            "checkerboard": list(checkerboard) if checkerboard else None,
            "square_mm": square_mm,
        })
        return summary

    # ── whole-travel map ───────────────────────────────────────────────────────
    def _map_plan(self, density: int) -> Dict[str, Any]:
        """Grid nodes over the whole travel, in the order they are visited (serpentine rows)."""
        matrix = stage_matrix(self._frame_shape())
        if matrix is None:
            raise ValueError("ต้อง calibrate แบบปกติ (รอบจุดเดียว) ก่อน — แผนที่ทั้งรางใช้สเกลจากผลนั้นทำนายการเลื่อนของภาพ")
        state = machine_service.get_state()
        spm = machine_service.steps_per_mm
        limits = (min(state.limits_steps[0] / spm, state.soft_limits_mm[0]),
                  min(state.limits_steps[1] / spm, state.soft_limits_mm[1]))
        margin = LEAD_MM + max(1.0, settings.stage_approach_mm)
        h, w = self._frame_shape()[:2]
        counts = []
        for k, (lim, side) in enumerate(zip(limits, (w, h))):
            span = lim - 2 * margin
            if span < 2.0:
                raise ValueError("ระยะเคลื่อนที่สั้นเกินไปสำหรับแผนที่ทั้งราง")
            # Enough nodes that neighbours overlap, however coarse the chosen density.
            per_mm = float(np.linalg.norm(matrix[:, k]))
            need = int(np.ceil(span * per_mm / (MAP_MAX_SHIFT * side))) + 1
            counts.append((margin, lim - margin, min(MAP_MAX_NODES, max(int(density), need, 2))))
        (x0, x1, cols), (y0, y1, rows) = counts
        xs, ys = np.linspace(x0, x1, cols), np.linspace(y0, y1, rows)
        nodes = []
        for r in range(rows):
            for i in range(cols):
                c = i if r % 2 == 0 else cols - 1 - i
                nodes.append((round(float(xs[c]), 3), round(float(ys[r]), 3), c, r))
        return {"cols": cols, "rows": rows, "nodes": nodes}

    def _frame_shape(self) -> Tuple[int, ...]:
        _, frame = camera_service.get_latest_frame()
        if frame is None:
            raise ValueError("ยังไม่มีภาพจากกล้อง")
        return frame.shape

    def _small(self, frame: np.ndarray) -> np.ndarray:
        """Grey copy at most MAP_WORK_SIDE px (the map keeps two rows of node pictures)."""
        import cv2

        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        k = min(1.0, MAP_WORK_SIDE / max(g.shape[:2]))
        return cv2.resize(g, (int(g.shape[1] * k), int(g.shape[0] * k)), interpolation=cv2.INTER_AREA) if k < 1 else g

    def _run_map(self, plan: Dict[str, Any]) -> None:
        try:
            result = self._measure_map(plan)
            MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
            MAP_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2))
            self._set(state="done", message="เสร็จแล้ว", finished=time.time())
            machine_service.play("done")
        except CalibrationCancelled:
            self._set(state="cancelled", message="ยกเลิกแล้ว")
        except Exception as exc:
            if self._cancel.is_set():
                self._set(state="cancelled", message="ยกเลิกแล้ว")
                return
            logger.exception("Stage map failed")
            self._set(state="error", message=str(exc))

    def _measure_map(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        cols, rows, nodes = plan["cols"], plan["rows"], plan["nodes"]
        shots: Dict[int, np.ndarray] = {}
        where = {(c, r): k for k, (_, _, c, r) in enumerate(nodes)}
        edges, backlash, failed = [], [], 0
        frame_shape = self._frame_shape()
        matrix = None
        for k, (x, y, c, r) in enumerate(nodes):
            # From + first (for the backlash), then the node's picture approached from -,
            # the way every other node is approached.
            self._move(x + LEAD_MM, y + LEAD_MM)
            self._move(x, y)
            from_plus = self._small(self._shot())
            self._move(x - LEAD_MM, y - LEAD_MM)
            self._move(x, y)
            shot = self._small(self._shot())
            k_px = frame_shape[0] / shot.shape[0]  # full-frame px per px of the small copy
            if matrix is None:
                matrix = stage_matrix(frame_shape) / k_px
            dx, dy, resp = measure_shift(shot, from_plus, work_side=MAP_WORK_SIDE)
            backlash.append([dx * k_px, dy * k_px] if resp >= 0.05 else None)
            # Edges to the node before it in this row and to the one above it.
            for nb in ((c - 1, r), (c + 1, r), (c, r - 1)):
                j = where.get(nb)
                if j is None or j not in shots:
                    continue
                pj = nodes[j]
                predicted = matrix @ np.array([x - pj[0], y - pj[1]])
                sx, sy, resp = measure_offset(shots[j], shot, (float(predicted[0]), float(predicted[1])), work_side=MAP_WORK_SIDE)
                if resp < 0.05:
                    failed += 1
                    continue
                edges.append((j, k, [sx * k_px, sy * k_px]))
            shots[k] = shot
            # Only the previous row is needed for the edges still to come.
            for old in [i for i in shots if nodes[i][3] < r - 1]:
                del shots[old]
            self._advance(f"จุด {k + 1}/{len(nodes)} ({x:.1f}, {y:.1f} mm)")
        result = map_summary(cols, rows, [(n[0], n[1]) for n in nodes], edges, backlash, failed)
        result.update({
            "time": time.time(),
            "steps_per_mm": machine_service.steps_per_mm,
            "image_size": [int(frame_shape[1]), int(frame_shape[0])],
            "lead_mm": LEAD_MM,
        })
        return result

    @staticmethod
    def _shift(ref: np.ndarray, frame: np.ndarray, predicted: Optional[Tuple[float, float]] = None) -> Tuple[float, float]:
        dx, dy, response = measure_shift(ref, frame, predicted)
        if response < 0.05:
            raise ValueError("จับการเลื่อนของภาพไม่ได้ — วางบอร์ดที่มีลวดลายใต้กล้อง และตรวจว่ากล้องยึดแน่น")
        return dx, dy

    def _axis_pass(self, axis: str, cx: float, cy: float, ref: np.ndarray) -> Dict[str, Any]:
        """Points across ±RANGE_MM approached in +, then the same points approached in -."""
        k = 0 if axis == "x" else 1
        c = (cx, cy)[k]
        targets = np.linspace(c - RANGE_MM, c + RANGE_MM, POINTS)

        def at(v: float) -> Tuple[float, float]:
            return (v, cy) if k == 0 else (cx, v)

        positions, shifts, forward = [], [], []
        prev: Optional[Tuple[np.ndarray, Tuple[float, float]]] = None
        for direction, order, start in ((True, targets, c - RANGE_MM - LEAD_MM), (False, targets[::-1], c + RANGE_MM + LEAD_MM)):
            self._move(*at(start))
            prev = None
            for t in order:
                self._move(*at(float(t)))
                frame = self._shot()
                # Predict from the previous point (a small, reliable shift), then measure against
                # the reference so errors do not add up along the pass.
                if prev is None:
                    predicted = None if abs(t - c) < 1e-9 else self._shift(ref, frame)
                else:
                    step = measure_shift(prev[0], frame)
                    predicted = (prev[1][0] + step[0], prev[1][1] + step[1])
                s = self._shift(ref, frame, predicted)
                positions.append(float(t))
                shifts.append(s)
                forward.append(direction)
                prev = (frame, s)
                self._advance(f"แกน {axis.upper()} {'ขาไป' if direction else 'ขากลับ'} {float(t):.2f} mm")
        return fit_axis(positions, shifts, forward)


stage_calibration_service = StageCalibrationService()


def stage_matrix(frame_shape, zoom: float = 1.0, scale: float = 1.0) -> Optional[np.ndarray]:
    """Stage mm -> image px for frames of this size/zoom, from the last calibration.

    Capture modes are crops of one sensor (px per mm follows the image height), digital zoom
    and a later resize (`scale`) magnify, and a change of the straightening angle since the
    calibration turns the image motion with the picture.
    """
    from ..core.straighten import rotate_vectors

    cal = stage_calibration_service.last_result()
    try:
        m = np.asarray(cal["stage_to_image"], np.float64).reshape(2, 2)
        cal_h = int(cal["image_size"][1])
    except (KeyError, TypeError, ValueError):
        return None
    if cal_h <= 0 or abs(np.linalg.det(m)) < 1e-6:
        return None
    m = m * (int(frame_shape[0]) / cal_h) * max(1.0, float(zoom or 1.0)) * scale
    turn = float(settings.camera_rotate_deg or 0.0) - float(cal.get("image_rotation_deg") or 0.0)
    return rotate_vectors(m, turn) if turn else m
