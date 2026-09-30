"""Camera service: single hardware owner, fresh frame acquisition, and MJPEG preview."""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import threading
import time
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional, Tuple
import cv2
import numpy as np

logger = logging.getLogger("camera_service")

_KEEP: Any = object()  # sentinel: keep the previous output size


class CameraService:
    """Thread-safe camera service managing frame acquisition and streaming."""

    def __init__(self):
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._generation = 0
        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_jpeg: Optional[bytes] = None
        self._latest_timestamp: float = 0.0
        self._actual_width: int = 0
        self._actual_height: int = 0
        self._requested_width: int = 1920
        self._requested_height: int = 1080
        self._requested_fps: int = 30
        self._output_size: Optional[Tuple[int, int]] = None  # (w, h) center-crop + resize of every frame
        self._actual_fps: float = 0.0
        self._fps_count: int = 0
        self._fps_timer: float = 0.0
        self._is_mock = False
        self._device_index = 0

    @property
    def is_active(self) -> bool:
        return self._running and ((self._cap is not None and self._cap.isOpened()) or self._is_mock)

    @property
    def is_mock(self) -> bool:
        return self._is_mock

    @property
    def resolution(self) -> Tuple[int, int]:
        """Size of the frames handed to streaming, inspection and AOI (after any output crop)."""
        return self._output_size or (self._actual_width, self._actual_height)

    @property
    def fps(self) -> float:
        return round(self._actual_fps, 1)

    @property
    def latest_timestamp(self) -> float:
        return self._latest_timestamp

    @property
    def device_index(self) -> int:
        return self._device_index

    def list_devices(self) -> List[Dict[str, Any]]:
        """List available physical camera devices and their active status."""
        names: List[str] = []
        if sys.platform == "darwin":
            try:
                out = subprocess.check_output(
                    ["system_profiler", "SPCameraDataType"],
                    text=True,
                    timeout=2.0,
                    stderr=subprocess.DEVNULL
                )
                for line in out.splitlines():
                    line = line.strip()
                    if line.endswith(":") and not line.startswith(("Model ID", "Unique ID", "Camera:")):
                        names.append(line[:-1])
            except Exception:
                pass

        devices: List[Dict[str, Any]] = []
        if names:
            for i, name in enumerate(names):
                devices.append({
                    "index": i,
                    "name": f"{name} (Index {i})",
                    "active": (self._device_index == i and self._running and not self._is_mock)
                })
            return devices

        # Fallback if system_profiler not available
        for i in range(2):
            if self._running and self._device_index == i and not self._is_mock:
                devices.append({
                    "index": i,
                    "name": f"Camera Device {i}",
                    "active": True
                })
            else:
                devices.append({
                    "index": i,
                    "name": f"Camera Device {i}",
                    "active": False
                })

        return devices

    def start(
        self,
        device_index: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        fps: Optional[int] = None,
        output_size: Optional[Tuple[int, int]] = _KEEP,
    ) -> bool:
        """Open the camera. Omitted arguments reuse the last requested settings.

        Endpoints such as /stream and /snapshot call start() with no arguments when the
        camera is momentarily inactive; they used to reset to camera 0 / 1080p and
        silently switch the operator away from the USB camera they had selected.
        """
        with self._lifecycle_lock:
            device_index = self._device_index if device_index is None else device_index
            width = self._requested_width if width is None else width
            height = self._requested_height if height is None else height
            fps = self._requested_fps if fps is None else fps
            if output_size is _KEEP:
                output_size = self._output_size
            if self._running:
                if (
                    self._device_index == device_index
                    and self._requested_width == width
                    and self._requested_height == height
                    and self._requested_fps == fps
                    and self._output_size == output_size
                ):
                    return True
                self.stop()
            self._output_size = output_size

            self._device_index = device_index
            self._requested_width = width
            self._requested_height = height
            self._requested_fps = fps
            logger.info("Opening camera index %d (%dx%d@%dfps)...", device_index, width, height, fps)

            # Try opening real camera via OpenCV
            cap = None if os.environ.get("PCB_CAMERA_SIMULATION") == "1" else cv2.VideoCapture(device_index)
            if cap is not None and cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                cap.set(cv2.CAP_PROP_FPS, fps)
                actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                self._actual_width = actual_w if actual_w > 0 else width
                self._actual_height = actual_h if actual_h > 0 else height
                self._cap = cap
                self._is_mock = False
                logger.info("Real camera opened: %dx%d", self._actual_width, self._actual_height)
            else:
                logger.warning("Camera %d could not be opened. Using software test generator.", device_index)
                if cap is not None:
                    cap.release()
                self._cap = None
                self._is_mock = True
                self._actual_width = width
                self._actual_height = height

            self._running = True
            self._fps_timer = time.monotonic()
            self._fps_count = 0
            self._thread = threading.Thread(target=self._capture_loop, args=(self._generation, self._cap, self._is_mock), daemon=True, name="CameraCaptureWorker")
            self._thread.start()
            return True

    def stop(self):
        with self._lifecycle_lock:
            with self._lock:
                self._running = False
                self._generation += 1
                old_thread, old_cap = self._thread, self._cap
                self._thread = self._cap = None
                self._latest_frame = self._latest_jpeg = None
                self._latest_timestamp = 0.0
                self._actual_fps = 0.0
                self._is_mock = False
            # The worker owns its VideoCapture and releases it on exit. Releasing it here
            # while the worker is blocked in cap.read() crashed the process (SIGSEGV in
            # OpenCV/AVFoundation) on every camera switch. Never join while holding _lock.
            if old_thread and old_thread is not threading.current_thread():
                old_thread.join(timeout=5)
                if old_thread.is_alive():
                    logger.warning("Camera worker still busy; it will release the device when it exits.")
            elif old_cap is not None:
                old_cap.release()

    def _generate_mock_frame(self, t: float) -> np.ndarray:
        """Create a synthetic test pattern frame when no USB camera is plugged in."""
        w, h = self._actual_width, self._actual_height
        img = np.zeros((h, w, 3), dtype=np.uint8)
        # Background slate
        img[:] = (30, 35, 45)

        # Draw a PCB outline
        margin_x, margin_y = int(w * 0.1), int(h * 0.1)
        cv2.rectangle(
            img,
            (margin_x, margin_y),
            (w - margin_x, h - margin_y),
            (20, 90, 40),
            -1
        )
        cv2.rectangle(
            img,
            (margin_x, margin_y),
            (w - margin_x, h - margin_y),
            (60, 160, 80),
            3
        )

        # Animated crosshair and timestamp
        cx, cy = w // 2, h // 2
        cv2.line(img, (cx - 30, cy), (cx + 30, cy), (200, 200, 200), 1)
        cv2.line(img, (cx, cy - 30), (cx, cy + 30), (200, 200, 200), 1)

        text = f"SIMULATED CAMERA - NO USB DEVICE ({w}x{h})"
        cv2.putText(img, text, (margin_x + 20, margin_y + 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(img, f"Timestamp: {t:.3f}", (margin_x + 20, margin_y + 80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 240, 180), 1)
        return img

    def _capture_loop(self, generation, cap, is_mock):
        try:
            self._capture_frames(generation, cap, is_mock)
        finally:
            if cap is not None:
                cap.release()

    @staticmethod
    def _fit_output(frame: np.ndarray, size: Optional[Tuple[int, int]]) -> np.ndarray:
        """Center-crop to the output aspect ratio, then resize (cameras rarely offer e.g. 640x640 natively)."""
        if not size:
            return frame
        out_w, out_h = size
        h, w = frame.shape[:2]
        if (w, h) == (out_w, out_h):
            return frame
        target = out_w / out_h
        if w / h > target:
            crop_w, crop_h = int(round(h * target)), h
        else:
            crop_w, crop_h = w, int(round(w / target))
        x, y = (w - crop_w) // 2, (h - crop_h) // 2
        frame = frame[y:y + crop_h, x:x + crop_w]
        return cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA)

    def _capture_frames(self, generation, cap, is_mock):
        while self._running and generation == self._generation:
            now = time.monotonic()
            frame = None

            if cap is not None and cap.isOpened():
                ret, raw_frame = cap.read()
                if ret and raw_frame is not None:
                    frame = raw_frame
                else:
                    time.sleep(0.02)
                    continue
            elif is_mock:
                frame = self._generate_mock_frame(now)
                time.sleep(0.033)  # ~30 fps

            if frame is not None:
                frame = self._fit_output(frame, self._output_size)
                # Downscale large frames for smooth web streaming
                h, w = frame.shape[:2]
                if w > 1280:
                    scale = 1280.0 / w
                    preview = cv2.resize(frame, (1280, int(h * scale)))
                else:
                    preview = frame

                ret, jpeg = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                jpeg_bytes = jpeg.tobytes() if ret else None

                with self._lock:
                    if generation != self._generation or not self._running:
                        return
                    self._latest_frame = frame
                    self._latest_jpeg = jpeg_bytes
                    self._latest_timestamp = time.monotonic()
                    self._fps_count += 1
                    elapsed = now - self._fps_timer
                    if elapsed >= 1.0:
                        self._actual_fps = self._fps_count / elapsed
                        self._fps_count = 0
                        self._fps_timer = now

    def get_latest_frame(self) -> Tuple[Optional[float], Optional[np.ndarray]]:
        """Get the most recently captured frame and its timestamp."""
        with self._lock:
            if self._latest_frame is None:
                return (None, None)
            return (self._latest_timestamp, self._latest_frame.copy())

    def get_fresh_frame(self, after_timestamp: float, timeout_sec: float = 2.5) -> Tuple[float, np.ndarray]:
        """Block until a newly captured frame arriving strictly AFTER `after_timestamp` is available.
        
        Essential for AOI motion: guarantees we do not inspect a stale frame
        captured before the stage arrived and settled.
        """
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if not self.is_active:
                raise RuntimeError("Camera stopped while waiting for a fresh frame")
            t, frame = self.get_latest_frame()
            if t is not None and t > after_timestamp and frame is not None:
                return (t, frame)
            time.sleep(0.015)
        raise TimeoutError(f"Could not acquire fresh camera frame within {timeout_sec}s timeout.")

    async def generate_mjpeg_stream(self, max_fps: int = 25) -> AsyncGenerator[bytes, None]:
        """Yield multipart MJPEG chunks for real-time browser preview."""
        interval = 1.0 / max_fps

        while True:
            if not self._running:
                # Wait briefly during camera switch / restart before exiting
                await asyncio.sleep(0.3)
                if not self._running:
                    break

            with self._lock:
                jpeg = self._latest_jpeg

            if jpeg is not None:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                )

            await asyncio.sleep(interval)


# Global singleton instance
camera_service = CameraService()
