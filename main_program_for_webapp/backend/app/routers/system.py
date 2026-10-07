import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field
from typing import Literal
import uuid
import asyncio
import torch

from ..config import REPO_ROOT, STORAGE_DIR, save_settings_to_disk, settings
from ..core import hub
from ..core.device import select_device
from ..core.model_catalog import discover_models
from ..core.schemas import SystemStatus
from ..core.security import lease_manager
from ..services.aoi_scan_service import aoi_scan_service
from ..services.camera_service import camera_service
from ..services.inference_service import inference_service
from ..services.machine_service import machine_service
from ..services.hardware_service import HardwareError, hardware_service
from ..services import tunnel_service
from fastapi import Query
from fastapi.responses import Response

router = APIRouter(prefix="/api/system", tags=["system"])


class SettingsUpdateRequest(BaseModel):
    default_conf: Optional[float] = Field(None, ge=0, le=1)
    default_match_dist: Optional[float] = Field(None, gt=0, le=10000)
    default_fail_on_extra: Optional[bool] = None
    station_name: Optional[str] = None
    default_operator: Optional[str] = None
    soft_limit_x_mm: Optional[float] = Field(None, gt=0, le=1000)
    soft_limit_y_mm: Optional[float] = Field(None, gt=0, le=1000)
    model_path: Optional[str] = None
    model_search_dirs: Optional[List[str]] = Field(None, max_length=20)
    depth_camera_distance_mm: Optional[float] = Field(None, ge=20, le=2000)
    depth_baseline_mm: Optional[float] = Field(None, ge=0.5, le=30)
    depth_views: Optional[int] = Field(None, ge=1, le=8)
    stage_approach_mm: Optional[float] = Field(None, ge=0, le=3)
    stage_monitor_enabled: Optional[bool] = None
    stabilize_enabled: Optional[bool] = None
    board_align_enabled: Optional[bool] = None
    camera_rotate_deg: Optional[float] = Field(None, ge=-15, le=15)
    stage_sound_enabled: Optional[bool] = None
    board_align_max_deg: Optional[float] = Field(None, gt=0, le=45)
    board_align_max_mm: Optional[float] = Field(None, gt=0, le=100)
    stabilize_max_wait_sec: Optional[float] = Field(None, ge=0.1, le=10)
    stabilize_threshold_px: Optional[float] = Field(None, gt=0, le=50)


class DeviceChangeRequest(BaseModel):
    preference: Literal["auto", "mps", "cuda", "cpu"]


class ModelChangeRequest(BaseModel):
    model_path: str


def _safe_settings_dict() -> Dict[str, Any]:
    """Return settings dictionary without exposing sensitive passcodes."""
    data = settings.model_dump()
    has_pass = bool(data.pop("operator_passcode", None))
    data["has_passcode"] = has_pass
    return data


@router.get("/status", response_model=SystemStatus)
def get_system_status():
    """Get complete status of camera, model, stage, lease, and active scan."""
    cam_res = camera_service.resolution if camera_service.is_active else None
    device_info = inference_service.device_info
    active_scan = None
    if aoi_scan_service.current_run:
        r = aoi_scan_service.current_run
        active_scan = {
            "id": r.id,
            "status": r.status,
            "point_index": r.current_point_index,
            "total_points": r.total_points,
            "pass_count": r.pass_count,
            "fail_count": r.fail_count,
            "review_count": r.review_count,
            "error_count": r.error_count,
            "overall_verdict": r.overall_verdict
        }

    return SystemStatus(
        camera_active=camera_service.is_active,
        camera_is_mock=camera_service.is_mock,
        camera_resolution=cam_res,
        camera_fps=camera_service.fps,
        model_loaded=inference_service.is_loaded,
        model_path=inference_service.model_path,
        active_device=device_info.label,
        device_detail=device_info.detail,
        machine=machine_service.get_state(),
        control_lease=lease_manager.get_lease_info(),
        active_scan=active_scan
    )


@router.get("/settings")
def get_settings():
    """Get station settings with credentials stripped."""
    return _safe_settings_dict()


@router.post("/settings")
def update_settings(
    req: SettingsUpdateRequest,
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id")
):
    token = x_operator_token or x_operator_id
    if not lease_manager.is_operator(token):
        raise HTTPException(status_code=403, detail="Active operator token required to modify settings.")

    if aoi_scan_service.is_running:
        raise HTTPException(409,"Stop the active scan before changing station settings")
    # Validate/load the model before committing any new settings.
    if req.model_path and req.model_path != inference_service.model_path:
        try:
            inference_service.load_model(req.model_path, settings.device_preference)
        except Exception as exc:
            raise HTTPException(400,f"Failed to load model: {exc}") from exc
    if req.model_search_dirs is not None:
        cleaned = []
        for raw in req.model_search_dirs:
            folder = Path(raw.strip()).expanduser()
            if not folder.is_dir():
                raise HTTPException(400, f"Folder not found: {raw}")
            if str(folder.resolve()) not in cleaned:
                cleaned.append(str(folder.resolve()))
        req.model_search_dirs = cleaned
    changes = req.model_dump(exclude_none=True)
    if "model_path" in changes:
        changes["default_model"] = changes.pop("model_path")
    candidate = settings.model_copy(update=changes)
    save_settings_to_disk(candidate)
    for key,value in changes.items():
        setattr(settings,key,value)
    machine_service.set_soft_limits(settings.soft_limit_x_mm,settings.soft_limit_y_mm)

    return {"success": True, "settings": _safe_settings_dict()}


@router.get("/devices")
def list_available_devices():
    """Detect real hardware acceleration support."""
    devices = [{"id": "cpu", "label": "CPU", "available": True, "detail": "CPU execution fallback"}]

    # Check Apple Metal (MPS)
    mps_available = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    devices.append({
        "id": "mps",
        "label": "Apple GPU (MPS)",
        "available": mps_available,
        "detail": "Metal Performance Shaders on Apple Silicon" if mps_available else "Not supported on this platform"
    })

    # Check NVIDIA CUDA
    cuda_available = torch.cuda.is_available()
    cuda_count = torch.cuda.device_count() if cuda_available else 0
    devices.append({
        "id": "cuda",
        "label": f"NVIDIA CUDA ({cuda_count} GPU)",
        "available": cuda_available,
        "detail": torch.cuda.get_device_name(0) if cuda_available else "No CUDA GPUs detected"
    })

    return {
        "current_device": inference_service.device_info.label,
        "preference": settings.device_preference,
        "devices": devices
    }


@router.post("/device")
def set_device_preference(
    req: DeviceChangeRequest,
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id")
):
    token = x_operator_token or x_operator_id
    if not lease_manager.is_operator(token):
        raise HTTPException(status_code=403, detail="Active operator token required.")

    if aoi_scan_service.is_running:
        raise HTTPException(status_code=400, detail="Cannot change device during an active AOI scan.")
    try:
        select_device(req.preference)
        # Reload model if loaded
        if inference_service.is_loaded:
            inference_service.load_model(inference_service.model_path, req.preference)
        settings.device_preference = req.preference
        save_settings_to_disk(settings)
        return {"success": True, "device": inference_service.device_info}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/model")
def load_model(
    req: ModelChangeRequest,
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id")
):
    token = x_operator_token or x_operator_id
    if not lease_manager.is_operator(token):
        raise HTTPException(status_code=403, detail="Active operator token required.")

    if aoi_scan_service.is_running:
        raise HTTPException(status_code=400, detail="Cannot change model during an active AOI scan.")
    try:
        inference_service.load_model(req.model_path, settings.device_preference)
        settings.default_model = req.model_path
        save_settings_to_disk(settings)
        return {
            "success": True,
            "model_path": inference_service.model_path,
            "device": inference_service.device_info.label
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _model_roots() -> List[Path]:
    project = REPO_ROOT.parent  # "defect detection yolo" (desktop app, web app, training/trained, training/runs)
    return [project, STORAGE_DIR / "models", project.parent / "PCB Electronic components"]


@router.get("/models")
def list_available_models():
    """YOLO weights found in the project, training runs (runs/<name>/weights/*.pt) and user-added folders."""
    return {
        "current_model": inference_service.model_path,
        "search_dirs": [str(p) for p in _model_roots()] + list(settings.model_search_dirs),
        "custom_dirs": list(settings.model_search_dirs),
        "models": discover_models(_model_roots(), settings.model_search_dirs),
    }


@router.post("/models/upload")
async def upload_model_file(
    file: UploadFile = File(...),
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id")
):
    """Upload a new .pt weights file directly to backend/data/models and return its path."""
    token = x_operator_token or x_operator_id
    if not lease_manager.is_operator(token):
        raise HTTPException(status_code=403, detail="Active operator token required to upload models.")

    if aoi_scan_service.is_running:
        raise HTTPException(status_code=400, detail="Cannot upload or change model during an active AOI scan.")

    if not file.filename or not file.filename.endswith(".pt"):
        raise HTTPException(status_code=400, detail="Only PyTorch .pt weights files are accepted.")

    safe_filename = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', Path(file.filename).name)
    models_dir = STORAGE_DIR / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    target_path = models_dir / f"{uuid.uuid4().hex[:10]}_{safe_filename}"

    size = 0
    try:
        with target_path.open("wb") as buffer:
            while chunk := await file.read(1024*1024):
                size += len(chunk)
                if size > 1024*1024*1024:
                    raise HTTPException(413,"Weights exceed 1 GB")
                buffer.write(chunk)
    except Exception:
        target_path.unlink(missing_ok=True)
        raise

    try:
        await asyncio.to_thread(inference_service.load_model, str(target_path), settings.device_preference)
        settings.default_model = str(target_path)
        save_settings_to_disk(settings)
    except Exception as exc:
        target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Model failed to load; previous model retained: {exc}")

    return {
        "success": True,
        "filename": safe_filename,
        "path": str(target_path),
        "size_mb": round(target_path.stat().st_size / (1024 * 1024), 2),
        "message": f"Successfully uploaded and loaded model {safe_filename}"
    }


def _hub_dir() -> Path:
    return STORAGE_DIR / "models" / "hub" / hub.DEFAULT_REPO.replace("/", "__")


class HubDownloadRequest(BaseModel):
    file: str = Field(min_length=4, max_length=300)


@router.get("/models/hub")
async def list_hub_models():
    """Weights available in the station's Hugging Face model repo (PCB_MODEL_REPO) and whether each is already downloaded."""
    try:
        files = await asyncio.to_thread(hub.list_models, hub.DEFAULT_REPO)
    except hub.HubError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    models = []
    for f in files:
        local = _hub_dir() / hub.local_name(f["path"])
        models.append(
            {
                **f,
                "size_mb": round(f["size"] / (1024 * 1024), 1),
                "downloaded": local.is_file() and local.stat().st_size == f["size"],
                "local_path": str(local),
            }
        )
    return {"repo": hub.DEFAULT_REPO, "url": f"{hub.HUB}/{hub.DEFAULT_REPO}", "models": models}


@router.post("/models/hub/download")
async def download_hub_model(
    req: HubDownloadRequest,
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id"),
):
    """Download one weights file from the configured Hugging Face repo into backend/data/models/hub/.

    Only the repo set in PCB_MODEL_REPO is allowed (a .pt file can run code when loaded, so
    arbitrary repos are not accepted over the network). The file is not loaded; use /models to switch.
    """
    token = x_operator_token or x_operator_id
    if not lease_manager.is_operator(token):
        raise HTTPException(status_code=403, detail="Active operator token required to download models.")
    if aoi_scan_service.is_running:
        raise HTTPException(status_code=400, detail="Cannot download models during an active AOI scan.")
    try:
        hub.check_file(req.file)
        path = await asyncio.to_thread(hub.download, req.file, _hub_dir() / hub.local_name(req.file), hub.DEFAULT_REPO)
    except hub.HubError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"success": True, "path": str(path), "size_mb": round(path.stat().st_size / (1024 * 1024), 1)}


# ── Performance & Jetson power ─────────────────────────────────────────────────

def _require_lease(token: Optional[str]) -> None:
    """Power, clocks and fan change the machine: the operator lease (passcode) is required."""
    if not lease_manager.is_operator(token):
        raise HTTPException(status_code=403, detail="ต้องขอสิทธิ์ควบคุมสถานี (รหัสผ่าน) ก่อนเปลี่ยนการตั้งค่าพลังงาน")


def _apply(action):
    try:
        output = action()
    except HardwareError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, "output": output[-2000:], "hardware": hardware_service.snapshot()}


class PowerModeRequest(BaseModel):
    mode_id: int = Field(ge=0, le=99)


class ClocksRequest(BaseModel):
    max: bool


class FanRequest(BaseModel):
    mode: Literal["quiet", "cool", "manual"]
    percent: Optional[int] = Field(None, ge=20, le=100)


@router.get("/hardware")
async def hardware_snapshot():
    """Live CPU cores, GPU, memory, temperatures, power rails, fan and power mode."""
    return await asyncio.to_thread(hardware_service.snapshot)


@router.post("/hardware/power-mode")
async def set_power_mode(req: PowerModeRequest, x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token")):
    _require_lease(x_operator_token)
    if aoi_scan_service.is_running:
        raise HTTPException(status_code=400, detail="เปลี่ยนโหมดพลังงานระหว่างสแกนไม่ได้")
    return await asyncio.to_thread(_apply, lambda: hardware_service.set_power_mode(req.mode_id))


@router.post("/hardware/clocks")
async def set_clocks(req: ClocksRequest, x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token")):
    _require_lease(x_operator_token)
    return await asyncio.to_thread(_apply, lambda: hardware_service.set_clocks_max(req.max))


@router.post("/hardware/fan")
async def set_fan(req: FanRequest, x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token")):
    _require_lease(x_operator_token)
    return await asyncio.to_thread(_apply, lambda: hardware_service.set_fan(req.mode, req.percent))


# ── Remote access (LAN / Tailscale) and QR codes ───────────────────────────────

class ServeRequest(BaseModel):
    funnel: bool = False  # also publish on the public internet


def _tunnel(action):
    try:
        return action()
    except tunnel_service.TunnelError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


DEFAULT_PASSCODE = "rmutt-aoi"


def _with_passcode_flag(data: Dict[str, Any]) -> Dict[str, Any]:
    return {**data, "default_passcode": settings.operator_passcode == DEFAULT_PASSCODE}


@router.get("/remote-access")
async def remote_access():
    """LAN addresses of the station and the Tailscale state (serve/funnel entry of the station)."""
    return _with_passcode_flag(await asyncio.to_thread(_tunnel, tunnel_service.status))


@router.post("/remote-access/login")
async def tailscale_login(x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token")):
    _require_lease(x_operator_token)
    return _with_passcode_flag(await asyncio.to_thread(_tunnel, tunnel_service.login))


@router.post("/remote-access/serve")
async def tailscale_serve(req: ServeRequest, x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token")):
    _require_lease(x_operator_token)
    if req.funnel and settings.operator_passcode == DEFAULT_PASSCODE:
        # On the public internet anyone could take control with the documented default.
        raise HTTPException(status_code=400, detail="เปลี่ยนรหัสผ่านสถานีก่อนเปิดสู่อินเทอร์เน็ต: ตั้ง PCB_OPERATOR_PASSCODE ใน backend/.env แล้วรีสตาร์ท")
    return _with_passcode_flag(await asyncio.to_thread(_tunnel, lambda: tunnel_service.enable(req.funnel)))


@router.delete("/remote-access/serve")
async def tailscale_unserve(x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token")):
    _require_lease(x_operator_token)
    return _with_passcode_flag(await asyncio.to_thread(_tunnel, tunnel_service.disable))


@router.get("/qr")
def qr_code(text: str = Query(..., min_length=8, max_length=512)):
    """QR code (SVG) for an http(s) link, e.g. to open the station on a phone."""
    if not re.match(r"^https?://[^\s<>\"]+$", text):
        raise HTTPException(status_code=400, detail="QR code is only made for http(s) links")
    import io
    import segno

    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="svg", scale=8, border=2, dark="#000000", light="#ffffff", xmldecl=False)
    return Response(content=buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "max-age=3600"})


@router.get("/libraries")
def libraries():
    """Every Python / JavaScript / system library the station runs on, with the last update check."""
    from ..services.library_service import library_service

    return library_service.catalog()


@router.post("/libraries/check")
def check_libraries():
    """Ask PyPI and npm for newer releases (background job; read-only, nothing is installed)."""
    from ..services.library_service import library_service

    return library_service.check()


@router.get("/libraries/check")
def library_check_status():
    from ..services.library_service import library_service

    return library_service.job()
