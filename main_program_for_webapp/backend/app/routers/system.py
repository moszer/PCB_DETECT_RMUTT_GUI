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
from ..core.device import select_device
from ..core.schemas import SystemStatus
from ..core.security import lease_manager
from ..services.aoi_scan_service import aoi_scan_service
from ..services.camera_service import camera_service
from ..services.inference_service import inference_service
from ..services.machine_service import machine_service

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
    lease = lease_manager.get_lease_info()
    if lease.is_controlled and not lease_manager.is_operator(token):
        raise HTTPException(status_code=403, detail="Active operator token required to modify settings.")

    if aoi_scan_service.is_running:
        raise HTTPException(409,"Stop the active scan before changing station settings")
    # Validate/load the model before committing any new settings.
    if req.model_path and req.model_path != inference_service.model_path:
        try:
            inference_service.load_model(req.model_path, settings.device_preference)
        except Exception as exc:
            raise HTTPException(400,f"Failed to load model: {exc}") from exc
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
    lease = lease_manager.get_lease_info()
    if lease.is_controlled and not lease_manager.is_operator(token):
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
    lease = lease_manager.get_lease_info()
    if lease.is_controlled and not lease_manager.is_operator(token):
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


@router.get("/models")
def list_available_models():
    """List all detected .pt YOLO model files from repository root and backend models folder."""
    models = []
    seen_paths = set()

    search_dirs = [
        REPO_ROOT,
        STORAGE_DIR / "models",
        REPO_ROOT.parent,
        REPO_ROOT.parent / "runs",
        REPO_ROOT.parent / "trained",
        REPO_ROOT.parent.parent / "PCB Electronic components",
        REPO_ROOT.parent.parent / "PCB Electronic components" / "models"
    ]

    for s_dir in search_dirs:
        if s_dir.is_dir():
            for p in s_dir.glob("*.pt"):
                if p.is_file() and p.resolve() not in seen_paths:
                    seen_paths.add(p.resolve())
                    try:
                        stat = p.stat()
                        models.append({
                            "filename": p.name,
                            "path": str(p),
                            "size_mb": round(stat.st_size / (1024 * 1024), 2),
                            "modified_at": stat.st_mtime
                        })
                    except Exception:
                        pass
            for p in s_dir.glob("*/*.pt"):
                if p.is_file() and p.resolve() not in seen_paths:
                    seen_paths.add(p.resolve())
                    try:
                        stat = p.stat()
                        models.append({
                            "filename": f"{p.parent.name}/{p.name}",
                            "path": str(p),
                            "size_mb": round(stat.st_size / (1024 * 1024), 2),
                            "modified_at": stat.st_mtime
                        })
                    except Exception:
                        pass

    # Sort so best.pt and exp.pt appear first
    models.sort(key=lambda m: (0 if "best" in m["filename"] else (1 if "exp" in m["filename"] else 2), m["filename"]))
    return {
        "current_model": inference_service.model_path,
        "models": models
    }


@router.post("/models/upload")
async def upload_model_file(
    file: UploadFile = File(...),
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id")
):
    """Upload a new .pt weights file directly to backend/data/models and return its path."""
    token = x_operator_token or x_operator_id
    lease = lease_manager.get_lease_info()
    if lease.is_controlled and not lease_manager.is_operator(token):
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


