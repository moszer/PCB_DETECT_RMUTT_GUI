"""Camera control and MJPEG streaming endpoints."""
from fastapi import APIRouter, HTTPException, Response, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import time
from typing import Optional
import cv2

from ..core.inspection import digital_zoom
from ..services.camera_service import camera_service

router = APIRouter(prefix="/api/camera", tags=["camera"])


class CameraStartRequest(BaseModel):
    device_index: int = Field(0, ge=0, le=64)
    width: int = Field(1920, ge=128, le=8192)
    height: int = Field(1080, ge=128, le=8192)
    fps: int = Field(30, ge=1, le=120)


@router.get("/stream")
async def get_camera_stream():
    """Live MJPEG video stream for HTML <img> tag preview."""
    if not camera_service.is_active:
        camera_service.start()
    return StreamingResponse(
        camera_service.generate_mjpeg_stream(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )


@router.get("/snapshot")
def get_camera_snapshot(after_timestamp: Optional[float] = Query(None), zoom: float = Query(1, ge=1, le=5)):
    """Retrieve the latest captured frame as JPEG."""
    if not camera_service.is_active:
        camera_service.start()
    try:
        t, frame = camera_service.get_fresh_frame(after_timestamp if after_timestamp is not None else time.monotonic())
    except (TimeoutError,RuntimeError) as exc:
        raise HTTPException(503,str(exc)) from exc
    frame = digital_zoom(frame, zoom)
    ret, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ret:
        raise HTTPException(status_code=500, detail="Failed to encode frame as JPEG.")
    return Response(content=jpeg.tobytes(), media_type="image/jpeg", headers={"Cache-Control":"no-store", "X-Frame-Timestamp":str(t), "X-Camera-Mock":str(camera_service.is_mock).lower()})


@router.get("/status")
def get_camera_status():
    return {
        "active": camera_service.is_active,
        "is_mock": camera_service.is_mock,
        "device_index": camera_service.device_index,
        "resolution": camera_service.resolution,
        "fps": camera_service.fps
    }


@router.get("/devices")
def list_camera_devices():
    """Enumerate connected physical cameras with friendly device names."""
    return {
        "devices": camera_service.list_devices(),
        "current_index": camera_service.device_index,
        "is_mock": camera_service.is_mock,
        "resolution": camera_service.resolution,
        "fps": camera_service.fps
    }


@router.post("/start")
def start_camera(req: CameraStartRequest):
    from ..services.aoi_scan_service import aoi_scan_service
    if aoi_scan_service.is_running:
        raise HTTPException(409, "Stop the AOI scan before changing camera settings")
    success = camera_service.start(
        device_index=req.device_index,
        width=req.width,
        height=req.height,
        fps=req.fps
    )
    return {
        "success": success,
        "is_mock": camera_service.is_mock,
        "resolution": camera_service.resolution,
        "fps": camera_service.fps
    }


@router.post("/stop")
def stop_camera():
    from ..services.aoi_scan_service import aoi_scan_service
    if aoi_scan_service.is_running:
        raise HTTPException(409, "Stop the AOI scan before stopping the camera")
    camera_service.stop()
    return {"success": True, "message": "Camera stopped."}

