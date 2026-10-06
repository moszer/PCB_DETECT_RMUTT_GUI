"""Wait for the picture to stop shaking after a stage move (instead of a fixed settle time).

The camera hangs on the frame above the moving stage: after a move the whole picture keeps
wobbling for a while, longer after long or fast moves, and a frame taken then is shifted
or smeared. Consecutive frames are compared on small copies with phase correlation; the
picture counts as still once several frames in a row (and across that window) moved less
than `motion_px` (full-resolution pixels).
"""
from __future__ import annotations

import math
import time
from typing import Any, Callable, Dict, Optional, Tuple

import cv2
import numpy as np

WORK_SIDE = 480
# Frames that must agree (~0.1 s at 30 fps): one quiet pair can be the turning point of a swing.
STILL_FRAMES = 3


def small_gray(frame: np.ndarray, side: int = WORK_SIDE) -> Tuple[np.ndarray, float]:
    g = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = g.shape[:2]
    scale = min(1.0, side / max(h, w))
    if scale < 1:
        g = cv2.resize(g, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    return g.astype(np.float32), scale


def motion_px(a: np.ndarray, b: np.ndarray, scale: float) -> float:
    """Whole-picture shift between two small frames, in full-resolution pixels."""
    window = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(a, b, window)
    if response < 0.02:  # nothing to lock onto (blank view): don't hold the stage forever
        return 0.0
    return math.hypot(dx, dy) / scale


def wait_until_still(
    next_frame: Callable[[float], Tuple[float, np.ndarray]],
    after: float,
    max_wait_sec: float = 2.0,
    threshold_px: float = 1.5,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """Read frames (newer than `after`) until the picture is still or `max_wait_sec` passes.

    `next_frame(after_ts) -> (ts, frame)` returns the first frame captured after `after_ts`.
    Returns {still, waited_sec, frames, motion_px, timestamp}; `timestamp` is when the last
    frame looked at was taken, so later captures can ask for frames after it.
    """
    started = time.monotonic()
    window: list = []
    last_ts = after
    last_motion = 0.0
    frames = 0
    while True:
        last_ts, frame = next_frame(last_ts)
        frames += 1
        small, scale = small_gray(frame)
        if window and window[-1].shape != small.shape:
            window = []
        window.append(small)
        window = window[-STILL_FRAMES:]
        if len(window) >= 2:
            last_motion = motion_px(window[-2], window[-1], scale)
        if len(window) == STILL_FRAMES:
            pairs = [motion_px(window[i], window[i + 1], scale) for i in range(STILL_FRAMES - 1)]
            span = motion_px(window[0], window[-1], scale)
            if max(pairs + [span]) < threshold_px:
                return _result(True, started, frames, max(pairs + [span]), last_ts)
        if time.monotonic() - started >= max_wait_sec or (should_stop and should_stop()):
            return _result(False, started, frames, last_motion, last_ts)


def _result(still: bool, started: float, frames: int, motion: float, ts: float) -> Dict[str, Any]:
    return {
        "still": still,
        "waited_sec": round(time.monotonic() - started, 3),
        "frames": frames,
        "motion_px": round(float(motion), 2),
        "timestamp": ts,
    }
