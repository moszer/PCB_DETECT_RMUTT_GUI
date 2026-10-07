"""Training dataset capture, labeling and export endpoints."""
import re
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field, field_validator

from ..core.schemas import BaseModel
from ..core.security import lease_manager
from ..services.dataset_service import dataset_service

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def _require_operator(token: Optional[str]):
    if not lease_manager.is_operator(token):
        raise HTTPException(403, "Active operator token required.")


class CaptureRequest(BaseModel):
    name: str = ""
    corners: List[List[float]] = Field(min_length=4, max_length=4)
    pitch_x_mm: float = Field(5.0, gt=0, le=100)
    pitch_y_mm: float = Field(5.0, gt=0, le=100)
    speed: int = Field(800, ge=20, le=1500)
    settle_sec: float = Field(0.5, ge=0, le=10)
    auto_label: bool = True
    conf: float = Field(0.25, ge=0, le=1)
    imgsz: Optional[int] = Field(None, ge=128, le=4096)

    @field_validator("corners")
    @classmethod
    def check_corners(cls, corners):
        for c in corners:
            if len(c) != 2 or min(c) < 0:
                raise ValueError("Each corner must be [x_mm, y_mm] with non-negative values")
        return corners


class LabelBox(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    bbox: List[float] = Field(min_length=4, max_length=4)


class LabelsRequest(BaseModel):
    boxes: List[LabelBox]


@router.get("")
def list_datasets():
    return {"datasets": dataset_service.list(), "running": dataset_service.current_id}


@router.post("/capture")
def start_capture(req: CaptureRequest, x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token")):
    _require_operator(x_operator_token)
    try:
        return dataset_service.start_capture(
            name=req.name,
            corners=[(c[0], c[1]) for c in req.corners],
            pitch_x_mm=req.pitch_x_mm,
            pitch_y_mm=req.pitch_y_mm,
            speed=req.speed,
            settle_sec=req.settle_sec,
            auto_label=req.auto_label,
            conf=req.conf,
            imgsz=req.imgsz,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/capture/stop")
def stop_capture():
    """Like the global STOP, anyone may stop a capture."""
    dataset_service.stop_capture()
    return {"success": True}


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str):
    meta = dataset_service.get(dataset_id)
    if not meta:
        raise HTTPException(404, "Dataset not found")
    return meta


@router.delete("/{dataset_id}")
def delete_dataset(dataset_id: str, x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token")):
    _require_operator(x_operator_token)
    try:
        if not dataset_service.delete(dataset_id):
            raise HTTPException(404, "Dataset not found")
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"success": True}


@router.get("/{dataset_id}/labels/{file}")
def get_labels(dataset_id: str, file: str):
    try:
        return dataset_service.get_labels(dataset_id, file)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/{dataset_id}/labels/{file}")
def save_labels(
    dataset_id: str, file: str, req: LabelsRequest, x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token")
):
    _require_operator(x_operator_token)
    try:
        return dataset_service.save_labels(dataset_id, file, [b.model_dump() for b in req.boxes])
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.delete("/{dataset_id}/images/{file}")
def delete_image(dataset_id: str, file: str, x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token")):
    _require_operator(x_operator_token)
    try:
        dataset_service.delete_image(dataset_id, file)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"success": True}


@router.get("/{dataset_id}/download")
def download(dataset_id: str, background: BackgroundTasks, val_ratio: float = 0.2):
    if not 0 <= val_ratio <= 0.5:
        raise HTTPException(400, "val_ratio must be between 0 and 0.5")
    try:
        meta = dataset_service.get(dataset_id)
        path = dataset_service.export_zip(dataset_id, val_ratio)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    background.add_task(path.unlink, missing_ok=True)
    # Keep Thai and other letters; only drop characters that are unsafe in file names.
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", meta["name"]).strip("_.") or dataset_id
    return FileResponse(path, media_type="application/zip", filename=f"{safe}_yolo.zip")
