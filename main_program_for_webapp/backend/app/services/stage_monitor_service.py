"""Live positioning error of the XY stage, measured with the camera after every move.

When the stage comes to rest, a frame is compared with the one taken at the previous stop.
The stage calibration's stage→image matrix says how far the picture should have shifted
for the commanded move; what phase correlation measures beyond that is the error of the
move (lost steps, backlash, slip), converted back to stage µm and pushed to the UI.

It only needs a textured board under the camera and a stage calibration. Moves longer than
about half the picture leave no overlap to compare and are just used as the next reference.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

import cv2
import numpy as np

from ..config import settings
from ..core.stage_calibration import measure_shift
from .camera_service import camera_service
from .machine_service import machine_service

logger = logging.getLogger(__name__)

SETTLE_SEC = 0.35
WORK_SIDE = 1280  # px, long side of the frames compared (enough for ~µm at 130 px/mm)
HISTORY = 60


class StageMonitorService:
    def __init__(self):
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._subscribers: List[Callable[[Dict[str, Any]], None]] = []
        self._samples: Deque[Dict[str, Any]] = deque(maxlen=HISTORY)
        self._ref: Optional[Tuple[np.ndarray, Tuple[int, int]]] = None  # gray frame, stage steps
        self._was_moving = False
        self._stopped_at: Optional[Tuple[float, Tuple[int, int]]] = None
        self._status = "idle"
        self._thread: Optional[threading.Thread] = None
        machine_service.subscribe(self._on_state)

    # ── public ─────────────────────────────────────────────────────────────────
    def subscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._subscribers.append(callback)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            samples = list(self._samples)
            status = self._status
        return {"enabled": settings.stage_monitor_enabled, "status": status, "samples": samples, "summary": _summary(samples)}

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()
            self._ref = None
        self._publish({"event": "reset"})

    # ── machine events ─────────────────────────────────────────────────────────
    def _on_state(self, state) -> None:
        moving = bool(state.is_moving)
        if not state.connected or not state.homed:
            self._was_moving = False
            with self._lock:
                self._ref = None  # positions before a new HOME are not comparable
            return
        if self._was_moving and not moving:
            self._stopped_at = (time.monotonic(), tuple(state.position_steps))
            self._ensure_thread()
            self._wake.set()
        self._was_moving = moving

    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name="stage-monitor", daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()
            try:
                self._sample()
            except Exception:  # a measurement problem must never touch motion
                logger.warning("Stage monitor sample failed", exc_info=True)

    # ── measurement ────────────────────────────────────────────────────────────
    def _sample(self) -> None:
        if not settings.stage_monitor_enabled or not self._stopped_at:
            return
        stopped, pos = self._stopped_at
        wait = SETTLE_SEC - (time.monotonic() - stopped)
        if wait > 0:
            time.sleep(wait)
        state = machine_service.get_state()
        if state.is_moving or tuple(state.position_steps) != pos or self._stopped_at[1] != pos:
            return  # already on the way somewhere else (e.g. the overshoot of an approach move)
        from .stage_calibration_service import stage_calibration_service

        if stage_calibration_service.is_running:
            return  # it is measuring the stage itself
        if not camera_service.is_active or camera_service.is_mock:
            self._set_status("no_camera")
            return
        stab = camera_service.wait_until_still(time.monotonic(), max_wait_sec=1.0)
        if machine_service.get_state().is_moving:
            return
        _, frame = camera_service.get_fresh_frame(stab["timestamp"], timeout_sec=2.0)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        h, w = gray.shape[:2]
        scale = min(1.0, WORK_SIDE / max(h, w))
        small = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else gray

        with self._lock:
            ref = self._ref
            self._ref = (small, pos)
        matrix = _stage_matrix(h, scale)
        if matrix is None:
            self._set_status("needs_calibration")
            return
        if ref is None or ref[0].shape != small.shape:
            self._set_status("ready")
            return
        spm = machine_service.steps_per_mm
        move_mm = np.array([(pos[0] - ref[1][0]) / spm, (pos[1] - ref[1][1]) / spm])
        if not move_mm.any():
            return
        expected = matrix @ move_mm
        sh, sw = small.shape[:2]
        if abs(expected[0]) > 0.5 * sw or abs(expected[1]) > 0.5 * sh:
            self._set_status("ready")  # too far to overlap; this frame is the new reference
            return
        dx, dy, response = measure_shift(ref[0], small, (float(expected[0]), float(expected[1])), work_side=max(sw, sh))
        if response < 0.08:
            self._set_status("no_texture")
            return
        err_mm = np.linalg.solve(matrix, np.array([dx, dy]) - expected)
        sample = {
            "time": time.time(),
            "from_mm": [round(ref[1][0] / spm, 3), round(ref[1][1] / spm, 3)],
            "to_mm": [round(pos[0] / spm, 3), round(pos[1] / spm, 3)],
            "move_mm": [round(float(move_mm[0]), 3), round(float(move_mm[1]), 3)],
            # Where the carriage ended up vs. where it was sent, in stage mm (+X: further along +X).
            "error_mm": [round(float(err_mm[0]), 4), round(float(err_mm[1]), 4)],
            "error_um": round(float(math.hypot(*err_mm)) * 1000, 1),
            "response": round(response, 3),
        }
        with self._lock:
            self._samples.append(sample)
            self._status = "measuring"
            summary = _summary(list(self._samples))
        self._publish({"event": "sample", "sample": sample, "summary": summary})

    def _set_status(self, status: str) -> None:
        changed = False
        with self._lock:
            if self._status != status:
                self._status, changed = status, True
        if changed:
            self._publish({"event": "status", "status": status})

    def _publish(self, payload: Dict[str, Any]) -> None:
        for cb in list(self._subscribers):
            try:
                cb(payload)
            except Exception:
                pass


def _stage_matrix(frame_h: int, scale: float) -> Optional[np.ndarray]:
    """Stage mm -> px of the compared (scaled) frames, from the last stage calibration."""
    from .stage_calibration_service import stage_matrix

    return stage_matrix((frame_h, 0), 1.0, scale)


def _summary(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not samples:
        return {"n": 0}
    err = np.array([s["error_mm"] for s in samples]) * 1000
    mag = np.hypot(err[:, 0], err[:, 1])
    return {
        "n": len(samples),
        "rms_um": [round(float(np.sqrt(np.mean(err[:, 0] ** 2))), 1), round(float(np.sqrt(np.mean(err[:, 1] ** 2))), 1)],
        "max_um": round(float(mag.max()), 1),
        "last_um": round(float(mag[-1]), 1),
    }


stage_monitor_service = StageMonitorService()
