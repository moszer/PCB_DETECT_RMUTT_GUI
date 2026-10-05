"""Capture motion-stereo shots with the XY stage and turn them into per-part height maps."""
from __future__ import annotations

import base64
import json
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from ..config import STORAGE_DIR, settings
from ..core.depth import crop_texture, estimate_shift, height_map_views
from ..core.inspection import digital_zoom
from ..core.stage_calibration import measure_shift
from .camera_service import camera_service
from .machine_service import machine_service

logger = logging.getLogger(__name__)

# Short: a different board may be placed after a while (a new scan also clears the cache).
PAIR_TTL_SEC = 5 * 60
# The latest set is kept on disk (overwritten each time) to diagnose odd heights offline.
DEBUG_DIR = STORAGE_DIR / "depth"
# Frames averaged per stage position: halves the sensor-noise variance for one extra frame time.
FRAMES_PER_SHOT = 2


def _save_debug_set(pair: "StereoPair", x_mm: float, y_mm: float, zoom: float) -> None:
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        for old in DEBUG_DIR.glob("last_b*.jpg"):
            old.unlink()
        cv2.imwrite(str(DEBUG_DIR / "last_a.jpg"), pair.frame_a, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        for i, v in enumerate(pair.views):
            cv2.imwrite(str(DEBUG_DIR / f"last_b{i}.jpg"), v.frame_b, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        (DEBUG_DIR / "last.json").write_text(json.dumps({
            "x_mm": x_mm, "y_mm": y_mm, "zoom": zoom,
            "views": [{"move_mm": v.move_mm, "shift_px": v.shift, "response": v.response} for v in pair.views],
            "camera_distance_mm": settings.depth_camera_distance_mm, "time": time.time(),
        }, indent=2))
    except OSError:
        logger.warning("Could not save the stereo debug shots", exc_info=True)


@dataclass
class StereoView:
    frame_b: np.ndarray
    shift: Tuple[float, float]
    response: float
    move_mm: Tuple[float, float]


@dataclass
class StereoPair:
    """Frame A at the point plus one frame B per side move."""
    key: str
    frame_a: np.ndarray
    views: List[StereoView]
    created: float = field(default_factory=time.monotonic)
    cache: Dict[Tuple[float, ...], Dict[str, Any]] = field(default_factory=dict)


def move_directions(n: int) -> List[Tuple[float, float]]:
    """Unit stage moves evenly around the point: 2 = ±X, 4 = ±X ±Y, 8 adds the diagonals."""
    return [(round(math.cos(2 * math.pi * k / n), 6) + 0.0, round(math.sin(2 * math.pi * k / n), 6) + 0.0)
            for k in range(n)]


class DepthService:
    def __init__(self):
        self._lock = threading.Lock()  # one capture at a time (it moves the stage)
        self._pairs: Dict[str, StereoPair] = {}
        # Image shift (px, zoom 1) per mm of stage +X, learned from the last capture; used to
        # pick the move direction that keeps the part inside the second frame (single view).
        self._px_per_mm: Optional[Tuple[float, float]] = None

    @staticmethod
    def _key(x_mm: float, y_mm: float, zoom: float) -> str:
        return f"{x_mm:.3f}:{y_mm:.3f}:{zoom:.2f}:{settings.depth_views}:{settings.depth_baseline_mm}"

    def clear(self) -> None:
        with self._lock:
            had = bool(self._pairs)
            self._pairs.clear()
        if had:
            from .inference_service import release_memory

            release_memory()

    def _shot(self, zoom: float) -> np.ndarray:
        frames = [self._fresh_frame(zoom) for _ in range(FRAMES_PER_SHOT)]
        if len(frames) == 1:
            return frames[0]
        return np.mean(np.stack(frames).astype(np.float32), axis=0).round().astype(np.uint8)

    def _fresh_frame(self, zoom: float) -> np.ndarray:
        _, frame = camera_service.get_fresh_frame(time.monotonic(), timeout_sec=3.0)
        return digital_zoom(frame, zoom)

    def _move_mm(self, x_mm: float, y_mm: float) -> None:
        spm = machine_service.steps_per_mm
        machine_service.move_to_steps(int(round(x_mm * spm)), int(round(y_mm * spm)), speed=settings.default_speed)

    @staticmethod
    def _stage_matrix(shape) -> Optional[np.ndarray]:
        """Stage mm -> image px (zoom 1) from the last stage calibration.

        Calibrated at another capture size, it is scaled by the image height: the station
        camera's square and wide modes are crops of one sensor (same px per mm; checked on
        2160x2160 vs 3840x2160). It only seeds the shift search, which is refined locally.
        """
        from .stage_calibration_service import stage_calibration_service

        cal = stage_calibration_service.last_result()
        try:
            m = np.asarray(cal["stage_to_image"], np.float64).reshape(2, 2)
            cal_w, cal_h = (int(v) for v in cal["image_size"])
        except (KeyError, TypeError, ValueError):
            return None
        if cal_h <= 0:
            return None
        return m * (int(shape[0]) / cal_h)

    def _travel(self) -> Tuple[float, float]:
        state = machine_service.get_state()
        spm = machine_service.steps_per_mm
        return (min(state.limits_steps[0] / spm, state.soft_limits_mm[0]),
                min(state.limits_steps[1] / spm, state.soft_limits_mm[1]))

    def _moves(self, x_mm: float, y_mm: float, baseline: float, center_norm: Tuple[float, float], zoom: float,
               avoid_sign: Optional[float]) -> List[Tuple[float, float]]:
        """Side moves (mm) to shoot from, within the stage travel."""
        max_x, max_y = self._travel()
        n = settings.depth_views
        if n == 1:
            # One move along X: try the side that keeps the part in frame first.
            order = [1, -1]
            if self._px_per_mm:
                px = self._px_per_mm[0] * zoom, self._px_per_mm[1] * zoom
                toward_center = (0.5 - center_norm[0]) * px[0] + (0.5 - center_norm[1]) * px[1]
                order = [1, -1] if toward_center >= 0 else [-1, 1]
            if avoid_sign is not None:
                order = [s for s in order if s != (1 if avoid_sign > 0 else -1)]
            candidates = [(s * baseline, 0.0) for s in order]
        else:
            candidates = [(ux * baseline, uy * baseline) for ux, uy in move_directions(n)]
        moves = [(mx, my) for mx, my in candidates
                 if -1e-6 <= x_mm + mx <= max_x + 1e-6 and -1e-6 <= y_mm + my <= max_y + 1e-6]
        return moves[:1] if n == 1 else moves

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
            moves = self._moves(x_mm, y_mm, baseline, center_norm, zoom, avoid_sign)
            if not moves:
                raise ValueError("เลื่อนสเตจไปด้านข้างไม่ได้ (ชนขอบระยะเคลื่อนที่) — ลดค่าระยะเลื่อนในการตั้งค่า")

            settle = max(0.4, settings.default_settle_sec)
            self._move_mm(x_mm, y_mm)
            time.sleep(settle)
            frame_a = self._shot(zoom)
            shots = []
            try:
                for mx, my in moves:
                    self._move_mm(x_mm + mx, y_mm + my)
                    time.sleep(settle)
                    shots.append(((mx, my), self._shot(zoom)))
            finally:
                self._move_mm(x_mm, y_mm)  # always come back to the point

            views = []
            matrix = self._stage_matrix(frame_a.shape)
            for (mx, my), frame_b in shots:
                if matrix is not None:
                    # Calibrated: predict the shift from the stage move and only measure the rest
                    # (a whole-frame correlation can lock onto a wrong peak for large Y shifts).
                    px, py = matrix @ np.array([mx, my]) * zoom
                    dx, dy, response = measure_shift(frame_a, frame_b, (float(px), float(py)))
                else:
                    dx, dy, response = estimate_shift(frame_a, frame_b)
                if response < 0.03 or np.hypot(dx, dy) < 3:
                    logger.info("Stereo view (%.1f, %.1f) mm dropped: shift (%.1f, %.1f) px, response %.2f",
                                mx, my, dx, dy, response)
                    continue
                if my == 0 and mx != 0:
                    self._px_per_mm = (dx / mx / zoom, dy / mx / zoom)
                views.append(StereoView(frame_b, (dx, dy), response, (mx, my)))
            if not views:
                raise ValueError("จับการเลื่อนของภาพไม่ได้ — ตรวจว่ากล้องยึดแน่นและบอร์ดอยู่ในภาพ")
            pair = StereoPair(key, frame_a, views)
            # One set only: 9 frames of 4K are ~220 MB, and the Jetson's GPU needs that RAM too.
            self._pairs = {key: pair}
            _save_debug_set(pair, x_mm, y_mm, zoom)
            logger.info("Stereo set at %s: %d/%d views", key, len(views), len(moves))
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
            result = self._height_map(pair, box_px)
        except ValueError as exc:
            if "หลุดขอบ" not in str(exc) or len(pair.views) != 1:
                raise
            # The part left the second frame: shoot the pair again moving the other way.
            pair = self.capture(x_mm, y_mm, zoom, center, recapture=True, avoid_sign=pair.views[0].move_mm[0])
            result = self._height_map(pair, box_px)
        jpeg = crop_texture(pair.frame_a, result["roi_px"])
        rx1, ry1, rx2, ry2 = result.pop("roi_px")
        result.update({
            "roi": [rx1 / w, ry1 / h, rx2 / w, ry2 / h],
            "roi_size_px": [int(rx2 - rx1), int(ry2 - ry1)],
            "texture": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode() if jpeg else None,
            "camera_distance_mm": settings.depth_camera_distance_mm,
            "baseline_mm": settings.depth_baseline_mm,
            # Board-plane scale from the known stage moves (backlash makes it approximate).
            "mm_per_px": float(np.mean([math.hypot(*v.move_mm) / max(1e-6, math.hypot(*v.shift)) for v in pair.views])),
            "captured_ago_sec": round(time.monotonic() - pair.created, 1),
        })
        pair.cache[cache_key] = result
        return result

    @staticmethod
    def _height_map(pair: StereoPair, box_px: Sequence[float]) -> Dict[str, Any]:
        views = [(v.frame_b, v.shift) for v in pair.views]
        return height_map_views(pair.frame_a, views, box_px, settings.depth_camera_distance_mm)


depth_service = DepthService()
