"""Inspection history and statistics reporting router."""
import csv
import io
import json
import time
from typing import Any, Dict, List, Literal, Optional
from fastapi import APIRouter, Header, HTTPException, Response, Query
from pydantic import BaseModel, Field

from ..core.security import lease_manager
from ..services import benchmark
from ..services.perf_log import PERF_DIR
from ..services.storage_service import storage_service

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/runs")
def list_runs(verdict: Optional[str] = None, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
              q: Optional[str] = Query(None, max_length=64)):
    runs, total = storage_service.list_runs(verdict=verdict, limit=limit, offset=offset, search=q)
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


# ── Performance comparison (computer vs Jetson, thesis table 4.13) ─────────────

class GroundTruth(BaseModel):
    truth: Optional[Literal["good", "defective"]] = None  # None clears it


class BenchmarkRequest(BaseModel):
    data_yaml: Optional[str] = Field(None, max_length=1000)
    split: Literal["test", "val"] = "test"
    rounds: int = Field(3, ge=1, le=20)
    warmup: int = Field(5, ge=0, le=50)
    max_images: int = Field(50, ge=1, le=200)
    imgsz: Optional[int] = Field(None, ge=64, le=4096)
    label: str = Field("", max_length=80)


def _require_lease(token: Optional[str]) -> None:
    if not lease_manager.is_operator(token):
        raise HTTPException(403, "Active operator token required.")


def _report(days: Optional[float], include_simulation: bool) -> Dict[str, Any]:
    since = time.time() - days * 86400 if days else 0.0
    rep = benchmark.performance_report(storage_service.performance_rows(since, include_simulation))
    rep["table"] = benchmark.table_rows(rep)
    rep["filters"] = {"days": days, "include_simulation": include_simulation}
    return rep


@router.put("/runs/{run_id}/ground-truth")
def set_ground_truth(run_id: str, req: GroundTruth, x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token")):
    """Mark the board's real condition (good / defective) for board-level accuracy and F1."""
    _require_lease(x_operator_token)
    if not storage_service.set_ground_truth(run_id, req.truth):
        raise HTTPException(404, "Run not found.")
    return {"success": True, "ground_truth": req.truth}


@router.get("/performance")
def performance(days: Optional[float] = Query(None, gt=0, le=3650), include_simulation: bool = False):
    """This machine's column of the comparison table, with the raw numbers behind it."""
    return _report(days, include_simulation)


@router.get("/performance/export.csv")
def performance_csv(days: Optional[float] = Query(None, gt=0, le=3650), include_simulation: bool = False):
    rep = _report(days, include_simulation)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["รายการเปรียบเทียบ", rep["system"].get("hostname")])
    w.writerows(rep["table"])
    name = f"performance-{rep['system'].get('hostname')}-{time.strftime('%Y%m%d-%H%M')}.csv"
    # BOM so Excel opens the Thai text as UTF-8
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/performance/export.json")
def performance_json(days: Optional[float] = Query(None, gt=0, le=3650), include_simulation: bool = False):
    rep = _report(days, include_simulation)
    name = f"performance-{rep['system'].get('hostname')}-{time.strftime('%Y%m%d-%H%M')}.json"
    return Response(json.dumps(rep, ensure_ascii=False, indent=2), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/performance/log.jsonl")
def performance_log():
    """Every inference logged on this machine (one JSON object per line)."""
    files = sorted(PERF_DIR.glob("perf-*.jsonl")) if PERF_DIR.is_dir() else []
    body = "".join(f.read_text(encoding="utf-8") for f in files)
    return Response(body, media_type="application/x-ndjson", headers={"Content-Disposition": 'attachment; filename="inference-log.jsonl"'})


@router.post("/benchmark")
def start_benchmark(req: BenchmarkRequest, x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token")):
    from ..services.aoi_scan_service import aoi_scan_service
    from ..services.inference_service import inference_service

    _require_lease(x_operator_token)
    if aoi_scan_service.is_running:
        raise HTTPException(400, "ทดสอบระหว่างสแกนไม่ได้ (เวลาที่วัดจะไม่ถูกต้อง)")
    try:
        if req.data_yaml:
            benchmark.dataset_images(req.data_yaml, req.split)  # fail fast on a wrong path
        return benchmark.benchmark_job.start(
            inference_service, data_yaml=req.data_yaml or None, split=req.split, rounds=req.rounds,
            warmup=req.warmup, max_images=req.max_images, imgsz=req.imgsz, label=req.label,
        )
    except benchmark.BenchmarkError as exc:
        raise HTTPException(400, str(exc))


@router.get("/benchmark")
def benchmark_status():
    return benchmark.benchmark_job.state
