"""Capture motion-stereo pairs with the XY stage and turn them into per-part height maps."""
from __future__ import annotations

import base64
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np

from ..config import settings
from ..core.depth import crop_texture, estimate_shift, height_map
from ..core.inspection import digital_zoom
from .camera_service import camera_service
from .machine_service import machine_service

logger = logging.getLogger(__name__)

# Short: a different board may be placed after a while (a new scan also clears the cache).
PAIR_TTL_SEC = 5 * 60


@dataclass
class StereoPair:
    key: str
    frame_a: np.ndarray
    frame_b: np.ndarray
    shift: Tuple[float, float]
    response: float
    baseline_mm: float
    created: float = field(default_factory=time.monotonic)
    cache: Dict[Tuple[float, ...], Dict[str, Any]] = field(default_factory=dict)


class DepthService:
    def __init__(self):
        self._lock = threading.Lock()  # one capture at a time (it moves the stage)
        self._pairs: Dict[str, StereoPair] = {}
        # Image shift (px, zoom 1) per mm of stage +X, learned from the last capture; used to
        # pick the move direction that keeps the part inside the second frame.
        self._px_per_mm: Optional[Tuple[float, float]] = None

    @staticmethod
    def _key(x_mm: float, y_mm: float, zoom: float) -> str:
        return f"{x_mm:.3f}:{y_mm:.3f}:{zoom:.2f}"

    def clear(self) -> None:
        with self._lock:
            self._pairs.clear()

    def _fresh_frame(self, zoom: float) -> np.ndarray:
        _, frame = camera_service.get_fresh_frame(time.monotonic(), timeout_sec=3.0)
        return digital_zoom(frame, zoom)

    def _move_mm(self, x_mm: float, y_mm: float) -> None:
        spm = machine_service.steps_per_mm
        machine_service.move_to_steps(int(round(x_mm * spm)), int(round(y_mm * spm)), speed=settings.default_speed)

    def _pick_direction(self, x_mm: float, baseline: float, center_norm: Tuple[float, float], zoom: float) -> Sequence[int]:
        """Try the move direction that keeps the part in frame first (and stays within travel)."""
        state = machine_service.get_state()
        max_x = min(state.limits_steps[0] / machine_service.steps_per_mm, state.soft_limits_mm[0])
        order = [1, -1]
        if self._px_per_mm:
            # Which way does the part travel in the image for +X? Prefer moving it toward the centre.
            px = self._px_per_mm[0] * zoom, self._px_per_mm[1] * zoom
            toward_center = (0.5 - center_norm[0]) * px[0] + (0.5 - center_norm[1]) * px[1]
            order = [1, -1] if toward_center >= 0 else [-1, 1]
        return [s for s in order if 0 <= x_mm + s * baseline <= max_x]

    def capture(
        self,
        x_mm: float,
        y_mm: float,
        zoom: float,
        center_norm: Tuple[float, float],
        recapture: bool = False,
        avoid_sign: Optional[float] = None,
    ) -> StereoPair:
        key = self._key(x_mm, y_mm, zoom)
        with self._lock:
            pair = self._pairs.get(key)
            if pair and not recapture and time.monotonic() - pair.created < PAIR_TTL_SEC:
                return pair
            state = machine_service.get_state()
            if not state.connected or not state.homed:
                raise ValueError("ต้องเชื่อมต่อและ HOME สเตจก่อน (การวัด 3D ต้องเลื่อนสเตจ)")
            if not camera_service.is_active or camera_service.is_mock:
                raise ValueError("ต้องใช้กล้องจริง")
            baseline = settings.depth_baseline_mm
            directions = self._pick_direction(x_mm, baseline, center_norm, zoom)
            if avoid_sign is not None:
                directions = [s for s in directions if s != (1 if avoid_sign > 0 else -1)]
            if not directions:
                raise ValueError("เลื่อนสเตจไปด้านข้างไม่ได้ (ชนขอบระยะเคลื่อนที่) — ลดค่าระยะเลื่อนในการตั้งค่า")

            settle = max(0.4, settings.default_settle_sec)
            self._move_mm(x_mm, y_mm)
            time.sleep(settle)
            frame_a = self._fresh_frame(zoom)
            sign = directions[0]
            try:
                self._move_mm(x_mm + sign * baseline, y_mm)
                time.sleep(settle)
                frame_b = self._fresh_frame(zoom)
            finally:
                self._move_mm(x_mm, y_mm)  # always come back to the point

            dx, dy, response = estimate_shift(frame_a, frame_b)
            if response < 0.03 or np.hypot(dx, dy) < 3:
                raise ValueError("จับการเลื่อนของภาพไม่ได้ — ตรวจว่ากล้องยึดแน่นและบอร์ดอยู่ในภาพ")
            self._px_per_mm = (dx / (sign * baseline) / zoom, dy / (sign * baseline) / zoom)
            pair = StereoPair(key, frame_a, frame_b, (dx, dy), response, sign * baseline)
            self._pairs = {k: p for k, p in self._pairs.items() if time.monotonic() - p.created < PAIR_TTL_SEC}
            self._pairs[key] = pair
            logger.info("Stereo pair at %s: shift (%.1f, %.1f) px, response %.2f", key, dx, dy, response)
            return pair

    def measure(
        self,
        x_mm: float,
        y_mm: float,
        zoom: float,
        bbox_norm: Sequence[float],
        recapture: bool = False,
    ) -> Dict[str, Any]:
        center = ((bbox_norm[0] + bbox_norm[2]) / 2, (bbox_norm[1] + bbox_norm[3]) / 2)
        pair = self.capture(x_mm, y_mm, zoom, center, recapture)
        h, w = pair.frame_a.shape[:2]
        box_px = [bbox_norm[0] * w, bbox_norm[1] * h, bbox_norm[2] * w, bbox_norm[3] * h]
        cache_key = tuple(round(v, 4) for v in bbox_norm) + (settings.depth_camera_distance_mm,)
        if cache_key in pair.cache:
            return pair.cache[cache_key]
        try:
            result = height_map(pair.frame_a, pair.frame_b, pair.shift, box_px, settings.depth_camera_distance_mm)
        except ValueError as exc:
            if "หลุดขอบ" not in str(exc):
                raise
            # The part left the second frame: shoot the pair again moving the other way.
            pair = self.capture(x_mm, y_mm, zoom, center, recapture=True, avoid_sign=pair.baseline_mm)
            result = height_map(pair.frame_a, pair.frame_b, pair.shift, box_px, settings.depth_camera_distance_mm)
        jpeg = crop_texture(pair.frame_a, result["roi_px"])
        rx1, ry1, rx2, ry2 = result.pop("roi_px")
        result.update({
            "roi": [rx1 / w, ry1 / h, rx2 / w, ry2 / h],
            "roi_size_px": [int(rx2 - rx1), int(ry2 - ry1)],
            "texture": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode() if jpeg else None,
            "camera_distance_mm": settings.depth_camera_distance_mm,
            "baseline_mm": pair.baseline_mm,
            # Board-plane scale from the known stage move (backlash makes it approximate).
            "mm_per_px": abs(pair.baseline_mm) / max(1e-6, float(np.hypot(*pair.shift))),
            "captured_ago_sec": round(time.monotonic() - pair.created, 1),
        })
        pair.cache[cache_key] = result
        return result


depth_service = DepthService()
