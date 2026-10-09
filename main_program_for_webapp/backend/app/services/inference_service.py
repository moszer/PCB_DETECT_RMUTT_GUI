"""Inference service: YOLO model loading, warm-up, and thread-safe execution."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np

from ..core.device import InferenceDevice, select_device, validate_model_file
from ..core.schemas import Detection

logger = logging.getLogger("inference_service")


def is_gpu_out_of_memory(exc: BaseException) -> bool:
    """CUDA out of memory, including the form it takes on Jetson: there PyTorch's OOM path
    asks NVML for details, which Tegra lacks, and fails with an internal assert instead."""
    msg = str(exc)
    return isinstance(exc, RuntimeError) and (
        "out of memory" in msg.lower() or "NVML_SUCCESS" in msg or "CUDACachingAllocator" in msg
    )


def half_precision(device: str) -> bool:
    """FP16 on CUDA: on the Jetson it halves the GPU memory and the inference time (180 -> 85 ms
    at imgsz 1280) with the same detections. MPS/CPU stay FP32."""
    from ..config import settings

    return settings.inference_half and str(device).startswith("cuda")


def release_memory() -> None:
    """Hand cached GPU blocks and freed heap back to the system. On Jetson the GPU allocates
    from the same RAM as everything else, so memory PyTorch keeps cached for one input size
    is missing for the next (or for the camera, the 3D frames, the browser...)."""
    import gc

    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
    except Exception:  # never let the cleanup itself fail a request
        logger.debug("empty_cache failed", exc_info=True)
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass  # not glibc (macOS)


class InferenceService:
    """Thread-safe YOLO inference runner supporting MPS, CUDA, and CPU."""

    def __init__(self):
        self._lock = threading.Lock()
        self._model = None
        self._model_path: str = ""
        self._model_names: Dict[int, str] = {}
        self._device_info: Optional[InferenceDevice] = None
        self._device_preference: str = "auto"

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def model_path(self) -> str:
        return self._model_path

    @property
    def class_names(self) -> List[str]:
        """Model class names in index order (empty when no model is loaded)."""
        return [self._model_names[i] for i in sorted(self._model_names)]

    @property
    def device_info(self) -> InferenceDevice:
        if self._device_info is None:
            return InferenceDevice("cpu", "CPU (not initialized)")
        return self._device_info

    def load_model(self, model_path: str, device_preference: str = "auto") -> bool:
        """Load and warm up the YOLO model."""
        with self._lock:
            validated_path = validate_model_file(model_path)
            device = select_device(device_preference)

            logger.info("Loading YOLO weights from %s on %s...", validated_path, device.label)
            from ultralytics import YOLO

            model = YOLO(str(validated_path))
            # Extract class names
            names = getattr(model, "names", {})
            if isinstance(names, dict):
                model_names = {int(k): str(v) for k, v in names.items()}
            elif isinstance(names, list):
                model_names = {i: str(n) for i, n in enumerate(names)}
            else:
                model_names = {}

            # Warmup run with a small dummy image
            dummy = np.zeros((320, 320, 3), dtype=np.uint8)
            try:
                model.predict(source=dummy, device=device.device, verbose=False)
                if device.device.startswith("cuda"):
                    # Kernel failures can be asynchronous; do not claim a successful GPU
                    # warmup until the actual inference work has completed.
                    import torch

                    torch.cuda.synchronize(device.device)
                logger.info("Model warmup completed on %s.", device.label)
                if device.detail.startswith("Warning:"):
                    logger.warning("%s Inference warmup completed, but this build is not listed for the GPU.", device.detail)
            except Exception as e:
                raise RuntimeError(f"Model cannot run on {device.label}: {e}") from e

            self._model = model
            self._model_path = str(validated_path)
            self._model_names = model_names
            self._device_info = device
            self._device_preference = device_preference
            return True

    def _predict_with_fallback(self, predict_kwargs: Dict[str, Any]):
        """Predict, recovering from GPU out-of-memory (see is_gpu_out_of_memory).

        1) free the cached blocks and retry; 2) retry once more without cuDNN, whose per-layer
        workspace (up to 1.5 GiB seen on the station) is what no longer fits; plain CUDA
        convolutions are ~25% slower but need no workspace.
        """
        try:
            return self._model.predict(**predict_kwargs)
        except RuntimeError as exc:
            if not is_gpu_out_of_memory(exc):
                raise
            logger.warning("GPU out of memory (%s); freeing the cache and retrying", str(exc).splitlines()[0][:120])
        release_memory()
        try:
            return self._model.predict(**predict_kwargs)
        except RuntimeError as exc:
            if not is_gpu_out_of_memory(exc):
                raise
            logger.warning("Still out of GPU memory; retrying without cuDNN")
        release_memory()
        import torch

        enabled = torch.backends.cudnn.enabled
        torch.backends.cudnn.enabled = False
        try:
            return self._model.predict(**predict_kwargs)
        except RuntimeError as exc:
            if not is_gpu_out_of_memory(exc):
                raise
            release_memory()
            raise RuntimeError(
                "หน่วยความจำ GPU ไม่พอ — ปิดโปรแกรมอื่นบนเครื่อง (เช่น เบราว์เซอร์บน Jetson) หรือลดขนาดภาพ (imgsz)"
            ) from exc
        finally:
            torch.backends.cudnn.enabled = enabled

    def predict(
        self,
        image: np.ndarray,
        conf: float = 0.25,
        imgsz: Optional[int] = None,
        tag: str = "other",
    ) -> Tuple[List[Detection], Dict[str, float]]:
        """Run YOLO inference on an image array (BGR).
        
        Returns:
            detections: List of Detection objects with xyxy box and cx, cy.
            speed_ms: Timing breakdown dict {'preprocess', 'inference', 'postprocess', 'total'};
                total is the wall time of the whole call (YOLO + box conversion), per image.
        `tag` names the caller in the performance log (single / scan / dataset / other).
        """
        with self._lock:
            started = time.perf_counter()  # after the lock: waiting for another request isn't processing time
            if self._model is None:
                raise RuntimeError("Inference model is not loaded. Call load_model() first.")

            device = self._device_info.device if self._device_info else "cpu"
            predict_kwargs: Dict[str, Any] = {
                "source": image,
                "conf": conf,
                "device": device,
                "verbose": False,
                "save": False,
            }
            if imgsz is not None and int(imgsz) > 0:
                predict_kwargs["imgsz"] = int(imgsz)

            if half_precision(device):
                predict_kwargs["half"] = True
            results = self._predict_with_fallback(predict_kwargs)

            detections: List[Detection] = []
            speed_ms = {"preprocess": 0.0, "inference": 0.0, "postprocess": 0.0}

            det_id = 1
            for res in results:
                for k in speed_ms:
                    speed_ms[k] += float(res.speed.get(k, 0.0))

                for box in res.boxes:
                    cls_idx = int(box.cls[0])
                    label = self._model_names.get(cls_idx, f"class_{cls_idx}")
                    confidence = float(box.conf[0])
                    x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
                    cx = (x1 + x2) / 2.0
                    cy = (y1 + y2) / 2.0

                    detections.append(Detection(
                        id=det_id,
                        label=label,
                        conf=round(confidence, 3),
                        box=[round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                        cx=round(cx, 1),
                        cy=round(cy, 1),
                        status="UNMATCHED"
                    ))
                    det_id += 1

            speed_ms["total"] = round((time.perf_counter() - started) * 1000, 2)
        from .perf_log import record

        record(tag, speed_ms, getattr(image, "shape", None), imgsz, len(detections))
        return (detections, speed_ms)


# Global singleton
inference_service = InferenceService()
