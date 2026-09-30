"""Reference profile management endpoints (Golden board references)."""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Header, HTTPException

from ..config import DEFAULT_REFS_PATH
from ..core.schemas import ReferencePoint, ReferenceProfile, ReferenceSummary
from ..core.security import lease_manager
from ..services.storage_service import storage_service

router = APIRouter(prefix="/api/references", tags=["references"])


def _check_operator(token: Optional[str]):
    lease = lease_manager.get_lease_info()
    if lease.is_controlled and not lease_manager.is_operator(token):
        raise HTTPException(status_code=403, detail="Active operator token required.")


@router.get("", response_model=List[ReferenceSummary])
def list_references():
    return storage_service.list_references()


@router.get("/{ref_id}", response_model=ReferenceProfile)
def get_reference(ref_id: str):
    profile = storage_service.get_reference(ref_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Reference profile not found.")
    return profile


@router.post("", response_model=ReferenceProfile)
def save_reference(
    profile: ReferenceProfile,
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id")
):
    _check_operator(x_operator_token or x_operator_id)
    try:
        storage_service.save_reference(profile)
        return profile
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save reference profile: {exc}")


@router.delete("/{ref_id}")
def delete_reference(
    ref_id: str,
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id")
):
    _check_operator(x_operator_token or x_operator_id)
    success = storage_service.delete_reference(ref_id)
    if not success:
        raise HTTPException(status_code=404, detail="Reference profile not found or invalid.")
    return {"success": True}


@router.post("/import-desktop", response_model=ReferenceProfile)
def import_desktop_reference(
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id")
):
    """Import existing desktop Refs.json into a web profile (Read-only copy)."""
    _check_operator(x_operator_token or x_operator_id)
    p = Path(DEFAULT_REFS_PATH)
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"Desktop Refs.json not found at {DEFAULT_REFS_PATH}")

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        points: List[ReferencePoint] = []
        for idx, item in enumerate(data):
            points.append(ReferencePoint(
                id=f"ref_{idx + 1}",
                x=float(item.get("x", 0)),
                y=float(item.get("y", 0)),
                label=str(item.get("label", "component")),
                tolerance_px=float(item["tolerance_px"]) if item.get("tolerance_px") else None
            ))

        profile = ReferenceProfile(
            id="desktop_refs_imported",
            name="Imported Desktop Refs.json",
            description="Imported read-only snapshot from desktop Refs.json",
            profile_type="single",
            points=points
        )
        storage_service.save_reference(profile)
        return profile
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to import desktop reference: {exc}")

