"""Boards page: every saved board (named set of taught points) with pictures, readiness and history.

A board's scans are found by its point ids: the AOI screen sends the board's points (with
their ids) as the custom scan plan, so a run whose plan points are mostly this board's
belongs to it. Pictures are the taught reference images with the taught boxes drawn on,
cached as small JPEGs under .thumbs.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import Counter, OrderedDict
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import Field

from ..config import settings
from ..core.inspection import get_class_color_bgr as class_color
from ..core.registration import decode_image
from ..core.schemas import BaseModel
from ..core.thumbs import THUMB_DIR
from ..services import point_set_store
from ..services.camera_service import camera_service
from ..services.machine_service import machine_service
from ..services.storage_service import storage_service
from .aoi import _require_operator_lease

router = APIRouter(prefix="/api/boards", tags=["boards"])

EXPORT_FORMAT = "rmutt-aoi-board"
_cache: "OrderedDict[tuple, Dict[str, Any]]" = OrderedDict()
_cache_lock = threading.Lock()


def _image_size(data_url: Optional[str]) -> Optional[List[int]]:
    """Pixel size of a taught picture (decoded once per board version, see _analyse)."""
    img = decode_image(data_url) if data_url else None
    return [int(img.shape[1]), int(img.shape[0])] if img is not None else None


def _camera_aspect() -> Optional[float]:
    if camera_service.is_active:
        w, h = camera_service.resolution
    else:
        w, h = settings.camera_output_width or settings.camera_width, settings.camera_output_height or settings.camera_height
    return (w / h) if w and h else None


def _point_issues(p: Dict[str, Any], size: Optional[List[int]], aspect: Optional[float], limits: tuple) -> List[str]:
    issues = []
    if not p.get("reference_image"):
        issues.append("ยังไม่มีภาพต้นแบบ — ชดเชยการวางบอร์ดและจัดภาพจุดนี้ไม่ได้")
    if not p.get("expected_components"):
        issues.append("ยังไม่ได้สอนชิ้นส่วน — สแกนจุดนี้ไม่มีอะไรให้เทียบ")
    if size and aspect and abs(size[0] / size[1] - aspect) > 0.02 * aspect:
        issues.append(f"ภาพต้นแบบสัดส่วน {size[0]}×{size[1]} ไม่ตรงกับกล้องตอนนี้ — ควรสอนใหม่")
    x, y = p.get("x_mm") or 0, p.get("y_mm") or 0
    if not (0 <= x <= limits[0] and 0 <= y <= limits[1]):
        issues.append(f"อยู่นอกระยะเคลื่อนที่ ({x:.1f}, {y:.1f} mm)")
    return issues


def _runs_of(point_ids: set) -> List[Dict[str, Any]]:
    """Scan runs whose custom points are mostly this board's (newest first)."""
    if not point_ids:
        return []
    with storage_service._get_connection() as conn:
        rows = conn.execute(
            "SELECT id, status, is_golden_scan, created_at, overall_verdict, total_points, pass_count, fail_count, "
            "review_count, error_count, plan_json FROM runs ORDER BY created_at DESC"
        ).fetchall()
    out = []
    for r in rows:
        try:
            ids = [c.get("id") for c in (json.loads(r["plan_json"] or "{}").get("custom_points") or [])]
        except ValueError:
            continue
        ids = [i for i in ids if i]
        if ids and sum(i in point_ids for i in ids) >= max(1, 0.5 * len(ids)):
            out.append({**{k: r[k] for k in r.keys() if k != "plan_json"}, "point_ids": ids})
    return out


def _history(runs: List[Dict[str, Any]], names: Dict[str, str]) -> Dict[str, Any]:
    done = [r for r in runs if r["status"] == "complete" and not r["is_golden_scan"]]
    verdicts = Counter(r["overall_verdict"] for r in done)
    point_fail: Counter = Counter()
    part_fail: Counter = Counter()
    if done:
        ids = {r["id"]: r["point_ids"] for r in done[:200]}
        marks = ",".join("?" * len(ids))
        with storage_service._get_connection() as conn:
            rows = conn.execute(
                f"SELECT run_id, point_index, verdict, details_json FROM point_results WHERE run_id IN ({marks})", list(ids)
            ).fetchall()
        for row in rows:
            pids = ids.get(row["run_id"]) or []
            pid = pids[row["point_index"]] if row["point_index"] is not None and row["point_index"] < len(pids) else None
            if row["verdict"] == "FAIL" and pid:
                point_fail[pid] += 1
            try:
                evals = (json.loads(row["details_json"] or "{}") or {}).get("component_eval") or []
            except ValueError:
                evals = []
            for c in evals:
                if c.get("status") in ("missing", "wrong") and pid:
                    exp = c.get("expected") or {}
                    part_fail[(pid, exp.get("id"), exp.get("name"), c.get("status"))] += 1
    total = len(done)
    return {
        "runs": len(runs),
        "completed": total,
        "pass": verdicts.get("PASS", 0),
        "fail": verdicts.get("FAIL", 0),
        "review": verdicts.get("REVIEW", 0),
        "yield_pct": round(100 * verdicts.get("PASS", 0) / total, 1) if total else None,
        "last": {k: runs[0][k] for k in ("id", "created_at", "overall_verdict", "status")} if runs else None,
        "recent": [{k: r[k] for k in ("id", "created_at", "overall_verdict", "status", "pass_count", "fail_count", "review_count", "total_points")}
                   for r in runs[:12]],
        "top_failing_points": [{"point_id": pid, "name": names.get(pid, pid), "fails": n} for pid, n in point_fail.most_common(5)],
        "top_failing_parts": [{"point": names.get(pid, pid), "part": part, "class": cls, "status": st, "count": n}
                              for (pid, part, cls, st), n in part_fail.most_common(8)],
    }


def _analyse(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Per-point summary, readiness and history of one board (cached per version)."""
    key = (meta["id"], meta["updated_at"], round(_camera_aspect() or 0, 3))
    with _cache_lock:
        if key in _cache:
            hit = _cache[key]
            # History changes with every scan: refresh it, keep the (expensive) picture analysis.
            names = {p["id"]: p["name"] for p in hit["points"]}
            return {**hit, "history": _history(_runs_of(set(names)), names)}
    full = point_set_store.get_set(meta["id"]) or {"points": []}
    st = machine_service.get_state()
    spm = machine_service.steps_per_mm
    limits = (min(st.limits_steps[0] / spm, st.soft_limits_mm[0]), min(st.limits_steps[1] / spm, st.soft_limits_mm[1]))
    aspect = _camera_aspect()
    points, classes = [], Counter()
    for i, p in enumerate(full["points"]):
        comps = p.get("expected_components") or []
        cls = Counter(str(c.get("name", "?")) for c in comps)
        classes.update(cls)
        size = _image_size(p.get("reference_image"))
        points.append({
            "index": i, "id": p.get("id") or f"#{i}", "name": p.get("name") or f"จุด {i + 1}",
            "x_mm": p.get("x_mm"), "y_mm": p.get("y_mm"), "zoom": p.get("zoom") or 1,
            "has_reference": bool(p.get("reference_image")), "reference_size": size,
            "components": len(comps), "classes": dict(cls.most_common()),
            "issues": _point_issues(p, size, aspect, limits),
        })
    taught = [p for p in points if p["has_reference"]]
    board_issues = []
    if len(taught) < 2 and points:
        board_issues.append("มีภาพต้นแบบน้อยกว่า 2 จุด — ชดเชยการวางบอร์ดหามุมเอียงได้ไม่แม่น (สอนต้นแบบให้ครบ)")
    if not points:
        board_issues.append("บอร์ดนี้ยังไม่มีจุดตรวจ")
    result = {
        **meta,
        "classes": dict(classes.most_common()),
        "taught_points": len(taught),
        "ready_points": sum(1 for p in points if not p["issues"]),
        "board_issues": board_issues,
        "points": points,
    }
    with _cache_lock:
        _cache[key] = result
        while len(_cache) > 32:
            _cache.popitem(last=False)
    names = {p["id"]: p["name"] for p in points}
    return {**result, "history": _history(_runs_of(set(names)), names)}


@router.get("")
def list_boards():
    """Every board with class counts, readiness and scan history (no pictures)."""
    out = []
    for meta in point_set_store.list_sets():
        a = _analyse(meta)
        out.append({**{k: v for k, v in a.items() if k != "points"},
                    "issue_points": sum(1 for p in a["points"] if p["issues"]),
                    "cover_point": next((p["index"] for p in a["points"] if p["has_reference"]), None)})
    return {"boards": out}


@router.get("/{board_id}")
def board_detail(board_id: str):
    meta = next((m for m in point_set_store.list_sets() if m["id"] == board_id), None)
    if not meta:
        raise HTTPException(404, "ไม่พบบอร์ดนี้")
    return _analyse(meta)


@router.get("/{board_id}/points/{index}/thumb.jpg")
def point_thumb(board_id: str, index: int, w: int = Query(480), boxes: bool = True):
    """The taught picture of one point, with the taught boxes drawn (cached JPEG)."""
    if w not in (240, 480, 960):
        raise HTTPException(400, "w must be 240, 480 or 960")
    meta = next((m for m in point_set_store.list_sets() if m["id"] == board_id), None)
    if not meta:
        raise HTTPException(404, "ไม่พบบอร์ดนี้")
    key = hashlib.sha1(f"board|{board_id}|{meta['updated_at']}|{index}|{w}|{boxes}".encode()).hexdigest()
    out = THUMB_DIR / key[:2] / f"{key}.jpg"
    if not out.is_file():
        full = point_set_store.get_set(board_id) or {"points": []}
        if not 0 <= index < len(full["points"]):
            raise HTTPException(404, "ไม่พบจุดนี้")
        p = full["points"][index]
        img = decode_image(p.get("reference_image") or "")
        if img is None:
            raise HTTPException(404, "จุดนี้ยังไม่มีภาพต้นแบบ")
        h0, w0 = img.shape[:2]
        img = cv2.resize(img, (w, max(1, round(h0 * w / w0))), interpolation=cv2.INTER_AREA)
        if boxes:
            h, ww = img.shape[:2]
            for c in p.get("expected_components") or []:
                b = c.get("bbox") or c.get("box")
                if not b or len(b) != 4:
                    continue
                color = class_color(str(c.get("name", "")))
                cv2.rectangle(img, (int(b[0] * ww), int(b[1] * h)), (int(b[2] * ww), int(b[3] * h)), color, max(1, w // 320), cv2.LINE_AA)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.stem + ".tmp.jpg")
        cv2.imwrite(str(tmp), img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        tmp.replace(out)
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


def _free_name(base: str) -> str:
    base = point_set_store.clean_name(base)
    if not point_set_store.name_taken(base):
        return base
    stem = re.sub(r" \(\d+\)$", "", base)[: point_set_store.MAX_NAME - 6]
    n = 2
    while point_set_store.name_taken(f"{stem} ({n})"):
        n += 1
    return f"{stem} ({n})"


class DuplicateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=200)


@router.post("/{board_id}/duplicate")
def duplicate_board(
    board_id: str,
    req: DuplicateRequest,
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id"),
):
    _require_operator_lease(x_operator_token, x_operator_id)
    src = point_set_store.get_set(board_id)
    if not src:
        raise HTTPException(404, "ไม่พบบอร์ดนี้")
    stamp = int(time.time() * 1000)
    # New point ids: the copy gets its own scan history instead of sharing the original's.
    points = [{**p, "id": f"pt_{stamp}_{i}"} for i, p in enumerate(src["points"])]
    try:
        created = point_set_store.create_set(_free_name(req.name or f"{src['name']} (สำเนา)"), points)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {k: v for k, v in created.items() if k != "points"}


@router.get("/{board_id}/export")
def export_board(board_id: str):
    """The whole board (points, taught pictures and boxes) as a JSON file to back up or move."""
    src = point_set_store.get_set(board_id)
    if not src:
        raise HTTPException(404, "ไม่พบบอร์ดนี้")
    body = {"format": EXPORT_FORMAT, "version": 1, "exported_at": time.time(), "station": settings.station_name,
            "name": src["name"], "points": src["points"]}
    safe = re.sub(r"[^\w\-]+", "_", src["name"]).strip("_") or "board"
    return Response(json.dumps(body, ensure_ascii=False), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="board_{safe}.json"'})


class ImportRequest(BaseModel):
    format: str
    version: int = 1
    name: str = Field(..., max_length=200)
    points: List[Dict[str, Any]] = Field(..., max_length=400)


@router.post("/import")
def import_board(
    req: ImportRequest,
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id"),
):
    _require_operator_lease(x_operator_token, x_operator_id)
    if req.format != EXPORT_FORMAT:
        raise HTTPException(400, "ไฟล์นี้ไม่ใช่ไฟล์บอร์ดของสถานี")
    from ..core.schemas import CustomPointRequest

    try:
        points = [CustomPointRequest(**p).model_dump() for p in req.points]
        created = point_set_store.create_set(_free_name(req.name), points)
    except ValueError as exc:
        raise HTTPException(400, f"นำเข้าไม่ได้: {exc}")
    return {k: v for k, v in created.items() if k != "points"}
