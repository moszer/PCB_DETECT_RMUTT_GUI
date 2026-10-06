"""Measure the XY stage's accuracy with the camera (background job) and keep the last result."""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..config import STORAGE_DIR, settings
from ..core.stage_calibration import find_checkerboard, fit_axis, measure_shift, summarize
from .camera_service import camera_service
from .machine_service import machine_service

logger = logging.getLogger(__name__)

RESULT_FILE = STORAGE_DIR / "stage_calibration.json"
# Half-range of each axis pass and the number of points in it. ±2 mm keeps the image shift
# well inside the frame at ~130 px/mm (Jetson station camera at zoom 1).
RANGE_MM = 2.0
POINTS = 9
# Extra move beyond each end so the pass starts with the slack taken up in its direction.
LEAD_MM = 0.6
REPEATS = 4
FRAMES_PER_SHOT = 2


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
        return out

    @staticmethod
    def last_result() -> Optional[Dict[str, Any]]:
        try:
            return json.loads(RESULT_FILE.read_text())
        except (OSError, ValueError):
            return None

    def _set(self, **kw):
        with self._lock:
            self._status.update(kw)

    def start(self, checkerboard: Optional[Tuple[int, int]] = None, square_mm: Optional[float] = None) -> Dict[str, Any]:
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
            self._status = {"state": "running", "step": 0, "total": self._total_steps(), "message": "เริ่ม", "started": time.time()}
            self._thread = threading.Thread(
                target=self._run, args=(state.position_mm, checkerboard, square_mm), name="stage-calibration", daemon=True
            )
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
            "checkerboard": list(checkerboard) if checkerboard else None,
            "square_mm": square_mm,
        })
        return summary

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
