"""Inspection history and statistics reporting router."""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Response, Query

from ..services.storage_service import storage_service

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/runs")
def list_runs(verdict: Optional[str] = None, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    runs, total = storage_service.list_runs(verdict=verdict, limit=limit, offset=offset)
    return {"runs": runs, "total": total, "limit": limit, "offset": offset}


@router.get("/runs/{run_id}")
def get_run_details(run_id: str):
    run = storage_service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@router.get("/statistics")
def get_statistics():
    return storage_service.get_statistics()


@router.get("/export/csv")
def export_csv():
    csv_data = storage_service.export_runs_csv()
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=aoi_scan_history.csv"}
    )


@router.get("/single-inspections")
def list_single_inspections(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    """List single-image upload and live capture inspection history."""
    items, total = storage_service.list_single_inspections(limit=limit, offset=offset)
    return {"inspections": items, "total": total, "limit": limit, "offset": offset}


@router.get("/single-inspections/{inspection_id}")
def get_single_inspection_detail(inspection_id: int):
    """Get full details of a single-image inspection."""
    detail = storage_service.get_single_inspection(inspection_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Inspection record not found.")
    return detail


@router.get("/export/single-csv")
def export_single_csv():
    csv_data = storage_service.export_single_csv()
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=single_inspections.csv"}
    )

