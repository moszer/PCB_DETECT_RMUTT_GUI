import asyncio
import time
import math
from typing import Any, Dict, List, Optional
import cv2
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
import numpy as np

from collections import OrderedDict
from pathlib import Path

from pydantic import BaseModel, Field

from ..config import STORAGE_DIR, UPLOADS_DIR, settings
from ..core.ocr import engine_name, read_part_text
from ..core.inspection import (
    draw_annotated_image,
    evaluate_inspection,
    evaluate_multiframe_round,
    match_frame_detections,
    normalized_detections,
    reference_components,
)
from ..core.schemas import InspectionResult
from ..services.camera_service import camera_service
from ..services.inference_service import inference_service
from ..services.storage_service import storage_service

router = APIRouter(prefix="/api/inspection", tags=["inspection"])


# ── OCR of part markings ──

OCR_ASSET_DIRS = ("uploads", "runs", "references", "datasets")
_ocr_cache: "OrderedDict[tuple, Dict[str, Any]]" = OrderedDict()


class OcrRequest(BaseModel):
    image_url: str
    # Normalized [x1, y1, x2, y2] boxes in that image.
    boxes: List[List[float]] = Field(..., min_length=1, max_length=300)


def _storage_image(url: str) -> Path:
    """Map an /api/storage/... image URL back to its file, refusing anything outside storage."""
    prefix = "/api/storage/"
    rel = url.split("?", 1)[0]
    if not rel.startswith(prefix):
        raise HTTPException(400, "image_url must be a station image (/api/storage/...)")
    rel = rel[len(prefix):]
    top = rel.split("/", 1)[0]
    if top not in OCR_ASSET_DIRS:
        raise HTTPException(400, "Unsupported image location")
    root = (STORAGE_DIR / top).resolve()
    path = (STORAGE_DIR / rel).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, "Image not found")
    return path


@router.post("/ocr")
def read_markings(req: OcrRequest):
    """Text printed on each part (IC codes, capacitor values...), read in any orientation."""
    engine = engine_name()
    if not engine:
        raise HTTPException(503, "No OCR engine available (Apple Vision or tesseract)")
    path = _storage_image(req.image_url)
    image = None
    results = []
    for box in req.boxes:
        if len(box) != 4 or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
            raise HTTPException(400, "boxes must be normalized [x1, y1, x2, y2]")
        key = (str(path), path.stat().st_mtime, *(round(v, 4) for v in box))
        if key in _ocr_cache:
            _ocr_cache.move_to_end(key)
            results.append(_ocr_cache[key])
            continue
        if image is None:
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is None:
                raise HTTPException(400, "Image could not be read")
        result = read_part_text(image, box)
        _ocr_cache[key] = result
        if len(_ocr_cache) > 2000:
            _ocr_cache.popitem(last=False)
        results.append(result)
    return {"engine": engine, "results": results}

# Limit concurrent inference to prevent GPU/RAM saturation while keeping event loop free
_INSPECTION_SEMAPHORE = asyncio.Semaphore(2)


def _ensure_model_loaded():
    if not inference_service.is_loaded:
        inference_service.load_model(settings.default_model, settings.device_preference)


def _process_image_sync(
    image_bgr: np.ndarray,
    raw_bytes: bytes,
    filename: str,
    conf: float,
    match_dist: float,
    fail_on_extra: bool,
    reference_id: Optional[str],
    imgsz: Optional[int] = None,
    persist: bool = True,
    is_simulation: bool = False
) -> InspectionResult:
    """Synchronous CPU/GPU heavy inspection pipeline to be run in a thread pool."""
    _ensure_model_loaded()

    h, w = image_bgr.shape[:2]

    profile = storage_service.get_reference(reference_id) if reference_id else None
    if reference_id and profile is None:
        raise ValueError("Reference profile not found")
    if profile and profile.profile_type != "single":
        raise ValueError("Select a single-image reference for this inspection")
    if profile and profile.image_width and profile.image_height and (profile.image_width, profile.image_height) != (w,h):
        raise ValueError("Image resolution does not match the reference")

    detections, speed = inference_service.predict(image_bgr, conf=conf, imgsz=imgsz)

    verdict, reason, summary, ref_eval, detections = evaluate_inspection(
        reference_points=profile.points if profile else None,
        detections=detections,
        match_dist=match_dist,
        fail_on_extra=fail_on_extra
    )

    if is_simulation:
        verdict, reason = "REVIEW", "Simulation camera: this is not a production inspection"

    image_url = annotated_url = None
    if persist:
        saved_path, image_url = storage_service.save_upload_image(raw_bytes, filename)
        annotated = draw_annotated_image(image_bgr, detections, ref_eval)
        annotated_filename = f"annotated_{saved_path.name}"
        annotated_path, annotated_url = storage_service.save_image_array(
            annotated, UPLOADS_DIR, annotated_filename
        )

        # Persist in DB
        storage_service.save_single_inspection(
            verdict=verdict,
            reason=reason,
            model_used=inference_service.model_path,
            device_used=inference_service.device_info.label,
            image_path=str(saved_path),
            annotated_path=str(annotated_path),
            detections=detections,
            summary=summary,
            speed_ms=speed
        )

    return InspectionResult(
        verdict=verdict,
        reason=reason,
        summary=summary,
        detections=detections,
        reference_eval=ref_eval,
        speed_ms=speed,
        image_width=w,
        image_height=h,
        image_url=image_url,
        annotated_url=annotated_url,
        device_used=inference_service.device_info.label,
        model_used=inference_service.model_path,
        timestamp=time.time(),
        is_simulation=is_simulation
    )


@router.post("/inspect-upload", response_model=InspectionResult)
async def inspect_uploaded_image(
    file: UploadFile = File(...),
    conf: float = Form(0.25, ge=0, le=1),
    match_dist: float = Form(50.0, gt=0, le=10000),
    fail_on_extra: bool = Form(True),
    reference_id: Optional[str] = Form(None),
    imgsz: Optional[int] = Form(None, ge=128, le=4096),
    persist: bool = Form(True)
):
    """Upload and inspect a PCB image against an optional golden reference."""
    file_bytes = await file.read(50 * 1024 * 1024 + 1)
    if len(file_bytes) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image file exceeds 50MB limit.")

    # Decode image in thread to avoid blocking event loop
    def _decode_and_run():
        if not file_bytes:
            raise ValueError("Empty image file")
        nparr = np.frombuffer(file_bytes, np.uint8)
        image_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if image_bgr is None:
            raise ValueError("Invalid image file format.")
        return _process_image_sync(
            image_bgr=image_bgr,
            raw_bytes=file_bytes,
            filename=file.filename or "upload.jpg",
            conf=conf,
            match_dist=match_dist,
            fail_on_extra=fail_on_extra,
            reference_id=reference_id,
            imgsz=imgsz,
            persist=persist
        )

    async with _INSPECTION_SEMAPHORE:
        try:
            return await asyncio.to_thread(_decode_and_run)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Inspection failed: {exc}")


@router.post("/inspect-live", response_model=InspectionResult)
async def inspect_live_frame(
    conf: float = Form(0.25, ge=0, le=1),
    match_dist: float = Form(50.0, gt=0, le=10000),
    fail_on_extra: bool = Form(True),
    reference_id: Optional[str] = Form(None),
    imgsz: Optional[int] = Form(None, ge=128, le=4096)
):
    """Capture a snapshot from the live camera and inspect it asynchronously."""
    def _encode_and_run():
        if not camera_service.is_active:
            camera_service.start()
        _, frame = camera_service.get_fresh_frame(time.monotonic())
        ret, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        if not ret:
            raise ValueError("Failed to encode camera frame to JPEG.")
        return _process_image_sync(
            image_bgr=frame,
            raw_bytes=jpeg.tobytes(),
            is_simulation=camera_service.is_mock,
            filename="live_capture.jpg",
            conf=conf,
            match_dist=match_dist,
            fail_on_extra=fail_on_extra,
            reference_id=reference_id,
            imgsz=imgsz
        )

    async with _INSPECTION_SEMAPHORE:
        try:
            return await asyncio.to_thread(_encode_and_run)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Inspection failed: {exc}")


@router.post("/inspect-multiframe")
async def inspect_multiframe_live(
    target_frames: int = Form(10, ge=1, le=50),
    pass_ratio: float = Form(0.8, gt=0, le=1),
    conf: float = Form(0.25, ge=0, le=1),
    reference_id: Optional[str] = Form(None),
    imgsz: Optional[int] = Form(None, ge=128, le=4096)
):
    """Inspect distinct frames in a worker thread; never block STOP/heartbeat handling."""
    profile = storage_service.get_reference(reference_id) if reference_id else None
    if reference_id and not profile:
        raise HTTPException(404, "Reference profile not found")
    if profile and profile.profile_type != "single":
        raise HTTPException(400, "Select a single-image reference")
    def run():
        _ensure_model_loaded()
        if not camera_service.is_active:
            camera_service.start()
        after = time.monotonic()
        results, captured, expected = [], [], []
        for index in range(target_frames):
            after, frame = camera_service.get_fresh_frame(after, timeout_sec=3)
            h,w = frame.shape[:2]
            if profile:
                if profile.image_width and profile.image_height and (w,h) != (profile.image_width,profile.image_height):
                    raise ValueError("Camera resolution does not match the reference")
                expected = reference_components(profile.points,w,h)
            detections, _ = inference_service.predict(frame,conf=conf,imgsz=imgsz)
            boxes = normalized_detections(detections,w,h)
            results.append(boxes)
            captured.append({"frame_index":index,"timestamp":after,"width":w,"height":h,"detections_count":len(boxes),"matched_indices":list(match_frame_detections(expected,boxes)["matched_expected"])})
        evaluation = evaluate_multiframe_round(expected,results,target_frames,math.ceil(target_frames*pass_ratio))
        if camera_service.is_mock:
            evaluation.update(verdict="REVIEW", reason="Simulation camera: this is not a production inspection")
        return {**evaluation,"captured_frames":captured,"model_used":inference_service.model_path,"device_used":inference_service.device_info.label,"is_simulation":camera_service.is_mock}
    async with _INSPECTION_SEMAPHORE:
        try:
            return await asyncio.to_thread(run)
        except (ValueError,TimeoutError,RuntimeError) as exc:
            raise HTTPException(400, str(exc)) from exc
