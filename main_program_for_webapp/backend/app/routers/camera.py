"""Camera control and MJPEG streaming endpoints."""
from fastapi import APIRouter, Header, HTTPException, Request, Response, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
import logging
import time
from typing import Literal, Optional
import cv2

from ..core.inspection import digital_zoom
from ..config import save_settings_to_disk, settings
from ..services.camera_service import camera_service
from ..core.security import lease_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/camera", tags=["camera"])


class CameraStartRequest(BaseModel):
    device_index: int = Field(0, ge=0, le=64)
    width: int = Field(1920, ge=128, le=8192)
    height: int = Field(1080, ge=128, le=8192)
    fps: int = Field(30, ge=1, le=120)
    # Optional output size: frames are center-cropped to this aspect and resized (e.g. 640x640).
    output_width: Optional[int] = Field(None, ge=64, le=8192)
    output_height: Optional[int] = Field(None, ge=64, le=8192)
    # fit = crop to aspect + resize (same field of view); crop = exact 1:1 center cut (zoom).
    output_mode: Literal["fit", "crop"] = "fit"

    @model_validator(mode="after")
    def both_or_neither(self):
        if (self.output_width is None) != (self.output_height is None):
            raise ValueError("Set both output_width and output_height, or neither")
        return self


@router.get("/stream")
async def get_camera_stream(request: Request):
    """Live MJPEG video stream for HTML <img> tag preview."""
    if not camera_service.is_active:
        camera_service.start()
    # Behind the Next.js proxy every request comes from 127.0.0.1; the browser is in X-Forwarded-For.
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    client = forwarded or (request.client.host if request.client else "")
    return StreamingResponse(
        camera_service.generate_mjpeg_stream(client=client),
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
        "capture_resolution": camera_service.capture_resolution,
        "output_mode": camera_service.output_mode,
        "fps": camera_service.fps,
        "live_streams": camera_service.stream_count,
    }


@router.get("/devices")
def list_camera_devices():
    """Enumerate connected physical cameras with friendly device names."""
    return {
        "devices": camera_service.list_devices(),
        "current_index": camera_service.device_index,
        "is_mock": camera_service.is_mock,
        "resolution": camera_service.resolution,
        "capture_resolution": camera_service.capture_resolution,
        "output_mode": camera_service.output_mode,
        "fps": camera_service.fps
    }


@router.post("/start")
def start_camera(req: CameraStartRequest, x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token")):
    if not lease_manager.is_operator(x_operator_token):
        raise HTTPException(403, "Active operator token required.")
    from ..services.aoi_scan_service import aoi_scan_service
    if aoi_scan_service.is_running:
        raise HTTPException(409, "Stop the AOI scan before changing camera settings")
    success = camera_service.start(
        device_index=req.device_index,
        width=req.width,
        height=req.height,
        fps=req.fps,
        output_size=(req.output_width, req.output_height) if req.output_width else None,
        output_mode=req.output_mode,
    )
    if success and not camera_service.is_mock:
        _remember_camera_format(req)
    return {
        "success": success,
        "is_mock": camera_service.is_mock,
        "resolution": camera_service.resolution,
        "capture_resolution": camera_service.capture_resolution,
        "output_mode": camera_service.output_mode,
        "fps": camera_service.fps
    }


def _remember_camera_format(req: CameraStartRequest) -> None:
    """The format the operator just applied becomes the station default (survives restarts)."""
    name = next((d["name"] for d in camera_service.list_devices() if d["index"] == req.device_index), "")
    name = name.split(" (Index", 1)[0].strip()
    changes = {
        "camera_index": req.device_index,
        "camera_width": req.width,
        "camera_height": req.height,
        "camera_fps": req.fps,
        "camera_output_width": req.output_width,
        "camera_output_height": req.output_height,
        "camera_output_mode": req.output_mode,
    }
    if name and not name.startswith("Camera Device"):
        changes["camera_device_name"] = name
    try:
        candidate = settings.model_copy(update=changes)
        save_settings_to_disk(candidate)
        for key, value in changes.items():
            setattr(settings, key, value)
    except RuntimeError:
        logger.warning("Could not save the camera format as default", exc_info=True)


@router.post("/stop")
def stop_camera(x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token")):
    if not lease_manager.is_operator(x_operator_token):
        raise HTTPException(403, "Active operator token required.")
    from ..services.aoi_scan_service import aoi_scan_service
    if aoi_scan_service.is_running:
        raise HTTPException(409, "Stop the AOI scan before stopping the camera")
    camera_service.stop()
    return {"success": True, "message": "Camera stopped."}



# ── straightening (camera mounted a little turned) ──

@router.get("/straighten/detect")
def detect_straighten():
    """Suggested settings.camera_rotate_deg: levels the board's lines in the current picture."""
    from ..config import settings
    from ..core.straighten import estimate_skew_deg

    if not camera_service.is_active:
        raise HTTPException(status_code=503, detail="Camera is not active")
    _, frame = camera_service.get_fresh_frame(time.monotonic(), timeout_sec=3.0, raw=True)
    skew = estimate_skew_deg(frame)
    if skew is None:
        raise HTTPException(status_code=422, detail="หาแนวเส้นของบอร์ดในภาพไม่ได้ — วางบอร์ดใต้กล้องให้เต็มภาพ")
    return {"angle_deg": round(skew, 2), "current_deg": settings.camera_rotate_deg}


@router.get("/straighten/preview")
def straighten_preview(angle: float = 0.0, grid: int = 12):
    """The current picture rotated by `angle` with level guide lines (JPEG), to check by eye."""
    import cv2
    from fastapi.responses import Response

    from ..core.straighten import rotate

    if not camera_service.is_active:
        raise HTTPException(status_code=503, detail="Camera is not active")
    if not -15 <= angle <= 15 or not 2 <= grid <= 40:
        raise HTTPException(status_code=400, detail="angle -15..15, grid 2..40")
    _, frame = camera_service.get_fresh_frame(time.monotonic(), timeout_sec=3.0, raw=True)
    h, w = frame.shape[:2]
    k = min(1.0, 1280 / max(h, w))
    small = cv2.resize(frame, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA) if k < 1 else frame
    out = rotate(small, angle)
    sh, sw = out.shape[:2]
    for i in range(1, grid):
        y, x = int(sh * i / grid), int(sw * i / grid)
        cv2.line(out, (0, y), (sw, y), (255, 210, 0), 1, cv2.LINE_AA)
        cv2.line(out, (x, 0), (x, sh), (255, 210, 0), 1, cv2.LINE_AA)
    ok, jpg = cv2.imencode(".jpg", out, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return Response(jpg.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})
