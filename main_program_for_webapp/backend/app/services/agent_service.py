"""Station-wide AI agent: answers questions about anything in the web app by calling tools.

Gemini function calling. Every tool is read-only (history, yield, scan results, references,
datasets, models, settings, live status) except `navigate`, which only asks the browser to
switch page. The agent can never move the stage, start scans or change settings.
Tool results are compacted: a full run report is ~400 KB of boxes; the model gets the facts.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

import httpx

from . import chat_service

logger = logging.getLogger(__name__)

GEMINI_GENERATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_TOOL_ROUNDS = 8

PAGES = {
    "aoi": "สแกน AOI (มาร์คจุด สอนต้นแบบ สแกนบอร์ดด้วยสเตจ XY)",
    "inspect": "ตรวจภาพเดี่ยว (อัปโหลด/ถ่ายภาพแล้วตรวจ)",
    "dataset": "ชุดข้อมูลเทรน (ถ่ายภาพทั้งบอร์ด แก้ label ดาวน์โหลด)",
    "references": "โปรไฟล์อ้างอิง",
    "history": "ประวัติ & Yield",
    "settings": "ตั้งค่าสถานี (โมเดล ฮาร์ดแวร์ กล้อง 3D เสียง)",
}

SYSTEM_PROMPT = f"""คุณคือผู้ช่วย AI ของสถานีตรวจ PCB (AOI) ของ RMUTT อยู่ในเว็บแอปนี้ทุกหน้า
ตอบภาษาไทย กระชับ เป็นกันเอง ใช้ตัวเลขจริงจากเครื่องมือเท่านั้น ห้ามเดาตัวเลข

เว็บแอปมีหน้าต่างๆ: {json.dumps(PAGES, ensure_ascii=False)}
- ถ้าคำถามต้องใช้ข้อมูล ให้เรียกเครื่องมือก่อนตอบ (เรียกได้หลายตัว/หลายรอบ)
- ถ้าผู้ใช้ขอให้ไป/เปิดหน้าใด หรือคำตอบจะดูต่อได้ดีที่หน้าใด ให้เรียก navigate
- คุณอ่านข้อมูลได้อย่างเดียว สั่งเครื่อง/สแกน/แก้การตั้งค่าไม่ได้ ถ้าถูกขอให้บอกว่าต้องทำที่หน้าไหน
- เวลาเป็นเวลาท้องถิ่นของสถานี ตอบสรุปเป็นข้อๆ หรือตารางเมื่อเหมาะสม"""


def _time(ts: Optional[float]) -> Optional[str]:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else None


def _base(path: Optional[str]) -> Optional[str]:
    return Path(path).name if path else None


def _parent_run_name(path: Optional[str]) -> Optional[str]:
    """runs/<name>/weights/best.pt -> <name>."""
    if not path:
        return None
    p = Path(path)
    return p.parent.parent.name if p.parent.name == "weights" else p.name


# ── Tools ──

def get_station_status() -> Dict[str, Any]:
    from ..routers.system import get_system_status
    from .aoi_scan_service import aoi_scan_service

    s = get_system_status().model_dump()
    m = s.get("machine") or {}
    return {
        "camera": {"active": s.get("camera_active"), "simulated": s.get("camera_is_mock"), "resolution": s.get("camera_resolution"), "fps": s.get("camera_fps")},
        "model": {"loaded": s.get("model_loaded"), "name": _parent_run_name(s.get("model_path")), "file": _base(s.get("model_path")), "device": s.get("active_device")},
        "stage": {k: m.get(k) for k in ("connected", "mode", "port", "homed", "position_mm", "is_moving", "last_error")},
        "scan_running": aoi_scan_service.is_running,
        "server_time": _time(s.get("server_time")),
    }


def get_statistics() -> Dict[str, Any]:
    from ..routers.history import get_statistics as stats

    return stats()


def _run_row(r: Dict[str, Any]) -> Dict[str, Any]:
    plan = {}
    try:
        plan = json.loads(r.get("plan_json") or "{}")
    except ValueError:
        pass
    return {
        "run_id": r.get("id"),
        "started": _time(r.get("created_at")),
        "duration_sec": round(r["completed_at"] - r["created_at"]) if r.get("completed_at") and r.get("created_at") else None,
        "status": r.get("status"),
        "verdict": r.get("overall_verdict"),
        "points": r.get("total_points"),
        "pass": r.get("pass_count"), "fail": r.get("fail_count"), "review": r.get("review_count"), "error": r.get("error_count"),
        "golden_scan": bool(r.get("is_golden_scan")), "simulation": bool(r.get("is_simulation")),
        "plan": plan.get("plan_mode"),
    }


def list_scan_runs(limit: int = 10, verdict: Optional[str] = None) -> Dict[str, Any]:
    from ..routers.history import list_runs

    res = list_runs(verdict.upper() if verdict else None, max(1, min(int(limit or 10), 100)), 0)
    return {"total": res.get("total"), "runs": [_run_row(r) for r in res.get("runs", [])]}


def _point_summary(p: Dict[str, Any]) -> Dict[str, Any]:
    counts = Counter(d.get("label") for d in p.get("detections") or [])
    out: Dict[str, Any] = {
        "index": p.get("point_index"), "name": p.get("name"), "x_mm": p.get("x_mm"), "y_mm": p.get("y_mm"),
        "verdict": p.get("verdict"), "reason": p.get("reason"), "detected": dict(counts),
    }
    slots = p.get("component_eval") or []
    if slots:
        by_status = Counter(s.get("status") for s in slots)
        out["taught_slots"] = dict(by_status)
        bad = [s for s in slots if s.get("status") != "confirmed"]
        out["problem_slots"] = [
            {"id": s.get("expected", {}).get("id"), "class": s.get("expected", {}).get("name"), "status": s.get("status"),
             "hits": f"{s.get('hits')}/{s.get('target_frames')}", "wrong_label": s.get("wrong_label")}
            for s in bad[:30]
        ]
    if p.get("multiframe_info"):
        mf = p["multiframe_info"]
        out["frames"] = {k: mf.get(k) for k in ("total_frames", "target_frames", "pass_threshold", "max_offset_px")}
    return out


def get_scan_run(run_id: str) -> Dict[str, Any]:
    from ..routers.history import get_run_details

    r = get_run_details(run_id)
    report = r.get("report") if isinstance(r.get("report"), dict) else r
    points = report.get("results") or r.get("points") or []
    return {**_run_row(r), "point_results": [_point_summary(p) for p in points]}


def list_single_inspections(limit: int = 10) -> Dict[str, Any]:
    from ..routers.history import list_single_inspections as singles

    res = singles(max(1, min(int(limit or 10), 100)), 0)
    rows = []
    for i in res.get("inspections", []):
        counts = Counter(d.get("label") for d in i.get("detections") or [])
        rows.append({"id": i.get("id"), "time": _time(i.get("timestamp") or i.get("created_at")), "verdict": i.get("verdict"),
                     "reason": i.get("reason"), "detected": dict(counts), "model": _parent_run_name(i.get("model_used"))})
    return {"total": res.get("total"), "inspections": rows}


def list_reference_profiles() -> List[Dict[str, Any]]:
    from ..routers.references import list_references

    return [{**r.model_dump(), "created_at": _time(r.created_at), "updated_at": _time(r.updated_at)} for r in list_references()]


def get_reference_profile(ref_id: str) -> Dict[str, Any]:
    from ..routers.references import get_reference

    p = get_reference(ref_id).model_dump()
    labels = Counter(pt.get("label") for pt in p.get("points") or [])
    grid = p.get("grid_points") or {}
    for pts in grid.values():
        labels.update(pt.get("label") for pt in pts)
    return {"id": p.get("id"), "name": p.get("name"), "description": p.get("description"), "type": p.get("profile_type"),
            "image_size": [p.get("image_width"), p.get("image_height")], "points": sum(labels.values()),
            "grid_cells": len(grid), "components_by_class": dict(labels)}


def list_datasets() -> List[Dict[str, Any]]:
    from ..routers.datasets import list_datasets as ds

    return [{k: d.get(k) for k in ("id", "name", "status", "image_count", "planned", "box_count")} | {"created": _time(d.get("created_at"))}
            for d in ds().get("datasets", [])]


def get_dataset(dataset_id: str) -> Dict[str, Any]:
    from ..routers.datasets import get_dataset as ds

    d = ds(dataset_id)
    images = d.get("images") or []
    return {"id": d.get("id"), "name": d.get("name"), "status": d.get("status"), "created": _time(d.get("created_at")),
            "classes": d.get("classes"), "images": len(images),
            "labeled_by": dict(Counter(i.get("labeled_by") for i in images)),
            "boxes": sum(int(i.get("box_count") or 0) for i in images), "error": d.get("error")}


def list_models() -> Dict[str, Any]:
    from ..routers.system import list_available_models

    res = list_available_models()
    models = []
    for m in res.get("models", []):
        if m.get("kind") == "last":  # best.pt is the one to use; last.pt duplicates every run
            continue
        run = m.get("run") or {}
        row = {"name": run.get("run") or m.get("filename"), "file": m.get("filename"), "trained": _time(m.get("modified_at")),
               "mAP50": run.get("map50"), "mAP50_95": run.get("map50_95"), "epochs": run.get("epochs_done"),
               "base": run.get("train_model"), "imgsz": run.get("train_imgsz")}
        if m.get("path") == res.get("current_model"):
            row["current"] = True
        models.append({k: v for k, v in row.items() if v is not None})
    return {"current_model": _parent_run_name(res.get("current_model")), "count": len(models), "models": models[:40]}


def get_settings() -> Dict[str, Any]:
    from ..routers.system import get_settings as settings_dict

    s = dict(settings_dict())
    for k in ("cors_origins", "host", "port", "model_search_dirs"):
        s.pop(k, None)
    s["default_model"] = _parent_run_name(s.get("default_model"))
    return s


def navigate(page: str) -> Dict[str, Any]:
    if page not in PAGES:
        return {"ok": False, "error": f"unknown page; use one of {list(PAGES)}"}
    return {"ok": True, "page": page}


TOOLS: Dict[str, Callable[..., Any]] = {
    "get_station_status": get_station_status,
    "get_statistics": get_statistics,
    "list_scan_runs": list_scan_runs,
    "get_scan_run": get_scan_run,
    "list_single_inspections": list_single_inspections,
    "list_reference_profiles": list_reference_profiles,
    "get_reference_profile": get_reference_profile,
    "list_datasets": list_datasets,
    "get_dataset": get_dataset,
    "list_models": list_models,
    "get_settings": get_settings,
    "navigate": navigate,
}

_STR = {"type": "string"}
DECLARATIONS = [
    {"name": "get_station_status", "description": "สถานะสดของสถานี: กล้อง, โมเดลที่โหลด, สเตจ XY (เชื่อมต่อ/HOME/ตำแหน่ง), มีสแกนรันอยู่ไหม"},
    {"name": "get_statistics", "description": "สถิติรวม/Yield: จำนวนรอบสแกน ผ่าน/ไม่ผ่าน/ตรวจซ้ำ, board yield %, point yield %, จำนวนตรวจภาพเดี่ยว"},
    {"name": "list_scan_runs", "description": "รายการรอบสแกน AOI ล่าสุด (ใหม่สุดก่อน) พร้อมผลและจำนวนจุด",
     "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "description": "จำนวน (1-100, ค่าเริ่ม 10)"},
                                                     "verdict": {"type": "string", "enum": ["PASS", "FAIL", "REVIEW", "ERROR"]}}}},
    {"name": "get_scan_run", "description": "รายละเอียดรอบสแกนหนึ่งรอบ: ผลทุกจุด เหตุผล ชิ้นที่พบ ชิ้นที่ขาด/ผิด",
     "parameters": {"type": "object", "properties": {"run_id": _STR}, "required": ["run_id"]}},
    {"name": "list_single_inspections", "description": "รายการตรวจภาพเดี่ยวล่าสุด (รวมถ่ายทดสอบ)",
     "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    {"name": "list_reference_profiles", "description": "รายการโปรไฟล์อ้างอิง (ต้นแบบ)"},
    {"name": "get_reference_profile", "description": "รายละเอียดโปรไฟล์อ้างอิงหนึ่งตัว: จำนวนจุด ชิ้นแต่ละคลาส",
     "parameters": {"type": "object", "properties": {"ref_id": _STR}, "required": ["ref_id"]}},
    {"name": "list_datasets", "description": "รายการชุดข้อมูลเทรนที่ถ่ายจากสถานี"},
    {"name": "get_dataset", "description": "รายละเอียดชุดข้อมูลหนึ่งชุด: คลาส จำนวนภาพ/กรอบ ติด label อย่างไร",
     "parameters": {"type": "object", "properties": {"dataset_id": _STR}, "required": ["dataset_id"]}},
    {"name": "list_models", "description": "โมเดล YOLO ที่มีให้เลือก (จาก runs การเทรน) และตัวที่ใช้อยู่"},
    {"name": "get_settings", "description": "การตั้งค่าสถานี: ชื่อสถานี ค่า default ของการตรวจ กล้อง ขอบเขตสเตจ 3D"},
    {"name": "navigate", "description": "พาผู้ใช้ไปหน้าในเว็บแอป",
     "parameters": {"type": "object", "properties": {"page": {"type": "string", "enum": list(PAGES)}}, "required": ["page"]}},
]

TOOL_LABELS = {
    "get_station_status": "ดูสถานะสถานี", "get_statistics": "ดูสถิติ Yield", "list_scan_runs": "ดูรายการรอบสแกน",
    "get_scan_run": "ดูผลรอบสแกน", "list_single_inspections": "ดูการตรวจภาพเดี่ยว", "list_reference_profiles": "ดูโปรไฟล์อ้างอิง",
    "get_reference_profile": "ดูรายละเอียดโปรไฟล์", "list_datasets": "ดูชุดข้อมูล", "get_dataset": "ดูรายละเอียดชุดข้อมูล",
    "list_models": "ดูรายการโมเดล", "get_settings": "ดูการตั้งค่า", "navigate": "เปิดหน้า",
}


def run_tool(name: str, args: Dict[str, Any]) -> Any:
    fn = TOOLS.get(name)
    if not fn:
        return {"error": f"unknown tool {name}"}
    try:
        return fn(**(args or {}))
    except Exception as exc:  # the model sees the error and can recover (e.g. a wrong id)
        detail = getattr(exc, "detail", None) or str(exc)
        return {"error": f"{exc.__class__.__name__}: {detail}"[:300]}


def _event(kind: str, **data: Any) -> str:
    return json.dumps({"type": kind, **data}, ensure_ascii=False, default=str) + "\n"


RETRY_DELAYS_SEC = (2, 4, 6)


class _ModelBusy(Exception):
    pass


async def _generate(client: httpx.AsyncClient, model: str, headers: Dict[str, str], body: Dict[str, Any]) -> Dict[str, Any]:
    """One generateContent call, retried on busy errors; raises _ModelBusy when the model stays busy."""
    last = ""
    for delay in (0, *RETRY_DELAYS_SEC):
        if delay:
            await asyncio.sleep(delay)
        res = await client.post(GEMINI_GENERATE.format(model=model), headers=headers, json=body)
        if res.status_code == 200:
            return res.json()
        last = f"HTTP {res.status_code} ({model}): {res.text[:200]}"
        if res.status_code not in chat_service.RETRYABLE:
            raise RuntimeError(last)
        logger.info("Agent model %s busy (%s), retrying", model, res.status_code)
    raise _ModelBusy(last)


async def run_agent(history: List[Dict[str, str]], page: Optional[str]) -> AsyncIterator[str]:
    """NDJSON events: tool (a step), navigate, text (the answer), error.

    A conversation sticks to one model (Gemini thought signatures are model-bound); if that
    model stays overloaded the whole turn restarts on the next one - the tools are read-only.
    """
    if chat_service.provider() != "gemini" or not os.environ.get("GEMINI_API_KEY"):
        yield _event("error", message="AI agent ใช้ Gemini — ตั้งค่า GEMINI_API_KEY และ AI_PROVIDER=gemini ใน backend/.env")
        return
    system = SYSTEM_PROMPT + (f"\nผู้ใช้กำลังอยู่ที่หน้า: {page} ({PAGES.get(page, '')})" if page else "")
    base = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
            for m in history[-20:] if m.get("content")]
    headers = {"x-goog-api-key": os.environ.get("GEMINI_API_KEY", ""), "Content-Type": "application/json"}
    navigated: set = set()
    last_error = ""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15)) as client:
            for model in chat_service.gemini_models():
                contents = list(base)
                body: Dict[str, Any] = {
                    "systemInstruction": {"parts": [{"text": system}]},
                    "tools": [{"functionDeclarations": DECLARATIONS}],
                    "generationConfig": {"maxOutputTokens": 8192},
                    "contents": contents,
                }
                try:
                    for _ in range(MAX_TOOL_ROUNDS + 1):
                        data = await _generate(client, model, headers, body)
                        content = ((data.get("candidates") or [{}])[0]).get("content") or {"role": "model", "parts": []}
                        content.setdefault("role", "model")
                        parts = content.get("parts") or []
                        calls = [p["functionCall"] for p in parts if p.get("functionCall")]
                        if not calls:
                            text = "".join(p.get("text", "") for p in parts if p.get("text") and not p.get("thought")).strip()
                            yield _event("text", text=text or "(ไม่มีคำตอบ)", model=model)
                            return
                        contents.append(content)  # keep thought signatures exactly as returned
                        responses = []
                        for call in calls:
                            name, args = call.get("name", ""), call.get("args") or {}
                            yield _event("tool", name=name, label=TOOL_LABELS.get(name, name), args=args)
                            result = await asyncio.to_thread(run_tool, name, args)
                            if name == "navigate" and isinstance(result, dict) and result.get("ok") and result["page"] not in navigated:
                                navigated.add(result["page"])
                                yield _event("navigate", page=result["page"])
                            response = {"name": name, "response": {"result": result}}
                            if call.get("id"):
                                response["id"] = call["id"]
                            responses.append({"functionResponse": response})
                        contents.append({"role": "user", "parts": responses})
                    yield _event("error", message="ใช้เครื่องมือหลายรอบเกินไป ลองถามให้เจาะจงขึ้น")
                    return
                except _ModelBusy as exc:
                    last_error = str(exc)
                    yield _event("tool", name="retry", label=f"{model} ไม่ว่าง — เปลี่ยนรุ่น AI แล้วลองใหม่", args={})
                    continue
                except RuntimeError as exc:
                    yield _event("error", message=f"AI ตอบไม่ได้ — {exc}")
                    return
            yield _event("error", message=f"Gemini ทุกรุ่นไม่ว่างตอนนี้ ลองใหม่ในอีกสักครู่ — {last_error}")
    except httpx.HTTPError as exc:
        logger.warning("Agent request failed: %s", exc)
        yield _event("error", message=f"เชื่อมต่อ AI ไม่ได้: {exc.__class__.__name__}")
