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
import re
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
    "hardware": "ประสิทธิภาพ (CPU/GPU แต่ละคอร์ อุณหภูมิ พลังงาน พัดลม โหมดพลังงาน Jetson)",
}

SYSTEM_PROMPT = f"""คุณคือผู้ช่วย AI ของสถานีตรวจ PCB (AOI) ของ RMUTT อยู่ในเว็บแอปนี้ทุกหน้า
ตอบภาษาไทย กระชับ เป็นกันเอง ใช้ตัวเลขจริงจากเครื่องมือเท่านั้น ห้ามเดาตัวเลข

เว็บแอปมีหน้าต่างๆ: {json.dumps(PAGES, ensure_ascii=False)}
- ถ้าคำถามต้องใช้ข้อมูล ให้เรียกเครื่องมือก่อนตอบ (เรียกได้หลายตัว/หลายรอบ)
- ถามเบอร์/ยี่ห้อของ IC หรือตัวอักษรบนชิ้น ให้เรียก list_scan_runs แล้ว read_part_markings (ต้องระบุ run_id; ถ้าผู้ใช้ไม่ระบุรอบ ใช้รอบล่าสุด) แล้วสรุปเบอร์ที่อ่านได้พร้อมบอกว่าชิปนั้นคืออะไรจากความรู้ของคุณ บอกด้วยว่า OCR อาจผิดบางตัวอักษร
- "บอร์ด" ที่บันทึกไว้คือชุดจุดตรวจที่ตั้งชื่อในหน้าสแกน AOI (list_boards / get_board) — การเปิดบอร์ดหรือแก้บอร์ดต้องทำเองที่หน้า aoi
- ถ้าผู้ใช้ขอให้ไป/เปิดหน้าใด หรือคำตอบจะดูต่อได้ดีที่หน้าใด ให้เรียก navigate
- ถ้าถูกขอให้สรุปภาพรวม/ทุกอย่าง/สถานะเครื่อง ให้เรียก get_full_snapshot ครั้งเดียวก่อน แล้วสรุปเป็นหมวด (สถานะ สแกน สเตจ กล้อง ความแม่นยำราง ฮาร์ดแวร์ การตั้งค่าสำคัญ ปัญหาที่ควรแก้) ชี้จุดผิดปกติให้ชัด เช่น ยังไม่ HOME, backlash สูงแต่ยังไม่เปิดชดเชย, ไม่มีผล calibrate, คำเตือน GPU/หน่วยความจำ, อุณหภูมิสูง
- อธิบายการตั้งค่าด้วยความหมายที่ get_settings ให้มา (ไม่ใช่ชื่อตัวแปร)
- ถามว่าเกิดอะไรขึ้น/ทำไม error ให้ดู get_recent_events
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


MAX_OCR_PARTS = 60
_PART_NUMBER = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/+]{4,}")


def part_number_candidates(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Tokens that look like part numbers (5+ chars, letters and digits), merged across points."""
    found: Dict[str, Dict[str, Any]] = {}
    for part in parts:
        for token in _PART_NUMBER.findall(part["text"].replace("|", " ")):
            if not (any(c.isalpha() for c in token) and any(c.isdigit() for c in token)):
                continue
            g = found.setdefault(token.upper(), {"part_number": token.upper(), "count": 0, "points": [], "class": part["class"]})
            g["count"] += 1
            if part["point"] not in g["points"]:
                g["points"].append(part["point"])
    return sorted(found.values(), key=lambda g: (-g["count"], g["part_number"]))


def read_part_markings(run_id: str, labels: Optional[List[str]] = None, point_index: Optional[int] = None) -> Dict[str, Any]:
    """OCR the text printed on parts (IC part numbers, capacitor values...) of one scan run.

    Crops each detected part out of the point's full-resolution photo and reads it in all four
    orientations (Apple Vision, or tesseract). Only YOLO's detections of the asked classes are read.
    """
    import cv2

    from ..core.ocr import engine_name, read_part_text
    from ..routers.history import get_run_details

    if not engine_name():
        return {"error": "ไม่มี OCR engine ในเครื่องนี้"}
    wanted = {l.strip().lower() for l in (labels or ["ic"]) if l and l.strip()}
    report = get_run_details(run_id)
    parts: List[Dict[str, Any]] = []
    no_text = skipped = 0
    for p in report.get("results") or []:
        if point_index is not None and p.get("point_index") != point_index:
            continue
        dets = [d for d in p.get("detections") or [] if str(d.get("label", "")).lower() in wanted]
        if not dets:
            continue
        image = cv2.imread(p.get("image_path") or "")
        if image is None:
            skipped += len(dets)
            continue
        h, w = image.shape[:2]
        for d in sorted(dets, key=lambda d: (d["box"][1], d["box"][0])):  # top-to-bottom, left-to-right
            if len(parts) + no_text >= MAX_OCR_PARTS:
                skipped += 1
                continue
            x1, y1, x2, y2 = d["box"]
            reading = read_part_text(image, [max(0, x1 / w), max(0, y1 / h), min(1, x2 / w), min(1, y2 / h)])
            if not reading["text"]:
                no_text += 1
                continue
            parts.append({"point": (p.get("point_index") or 0) + 1, "point_name": p.get("name"), "class": d.get("label"),
                          "text": " | ".join(reading["text"].split("\n"))[:200], "confidence": reading["confidence"]})
    groups: Dict[str, Dict[str, Any]] = {}
    for part in parts:
        key = "".join(ch for ch in part["text"].upper() if ch.isalnum())
        g = groups.setdefault(key, {"text": part["text"], "count": 0, "points": []})
        g["count"] += 1
        if part["point"] not in g["points"]:
            g["points"].append(part["point"])
    return {
        "run_id": run_id, "classes": sorted(wanted), "with_text": len(parts), "no_readable_text": no_text, "skipped_over_limit": skipped,
        "note": "OCR อาจอ่านผิดบางตัวอักษร และชิ้นเล็ก/ไม่มีตัวอักษรจะอ่านไม่ได้; ภาพแต่ละจุดเป็นแค่บางส่วนของบอร์ด ชิปเดียวกันอาจถูกนับซ้ำข้ามจุดที่ภาพซ้อนกัน",
        "likely_part_numbers": part_number_candidates(parts),
        "distinct_markings": sorted(groups.values(), key=lambda g: -g["count"]),
        "parts": parts,
    }


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


def list_boards() -> List[Dict[str, Any]]:
    from . import point_set_store

    return [{"id": b["id"], "name": b["name"], "points": b["point_count"], "taught_parts": b["component_count"],
             "created": _time(b["created_at"]), "updated": _time(b["updated_at"])} for b in point_set_store.list_sets()]


def get_board(board_id: Optional[str] = None, name: Optional[str] = None) -> Dict[str, Any]:
    from . import point_set_store

    boards = point_set_store.list_sets()
    if not board_id and name:
        wanted = name.strip().lower()
        match = [b for b in boards if b["name"].lower() == wanted] or [b for b in boards if wanted in b["name"].lower()]
        if not match:
            return {"error": f"ไม่พบบอร์ดชื่อ {name}", "boards": [b["name"] for b in boards]}
        board_id = match[0]["id"]
    found = point_set_store.get_set(board_id or "")
    if not found:
        return {"error": "ไม่พบบอร์ดนี้", "boards": [b["name"] for b in boards]}
    points = []
    for i, p in enumerate(found["points"]):
        comps = p.get("expected_components") or []
        points.append({"index": i + 1, "name": p.get("name"), "x_mm": p.get("x_mm"), "y_mm": p.get("y_mm"), "zoom": p.get("zoom"),
                       "taught_parts": len(comps), "parts_by_class": dict(Counter(c.get("name") for c in comps))})
    totals = Counter()
    for p in points:
        totals.update(p["parts_by_class"])
    return {"id": found["id"], "name": found["name"], "created": _time(found["created_at"]), "updated": _time(found["updated_at"]),
            "point_count": len(points), "untaught_points": sum(1 for p in points if not p["taught_parts"]),
            "parts_by_class": dict(totals), "points": points}


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


# What every setting means (Thai), grouped as on the settings page: the agent explains values.
SETTINGS_GLOSSARY: Dict[str, Dict[str, str]] = {
    "สถานี": {
        "station_name": "ชื่อสถานี", "default_operator": "ชื่อผู้ควบคุมเริ่มต้น",
        "has_passcode": "ตั้งรหัสผ่านสำหรับขอสิทธิ์ควบคุมไว้หรือไม่", "lease_ttl_seconds": "สิทธิ์ควบคุมหมดอายุถ้าไม่ต่อภายใน (วินาที)",
    },
    "โมเดลและการตรวจ": {
        "default_model": "โมเดล YOLO ที่โหลดตอนเปิดเครื่อง", "device_preference": "ฮาร์ดแวร์ประมวลผลที่เลือก (auto/cuda/mps/cpu)",
        "inference_half": "ใช้ FP16 บน GPU (ประหยัดหน่วยความจำ เร็วขึ้น ผลเท่าเดิม)",
        "default_conf": "ความมั่นใจขั้นต่ำเริ่มต้น (0-1)", "default_match_dist": "ระยะจับคู่กับจุดอ้างอิงเริ่มต้น (px)",
        "default_fail_on_extra": "ตัดสิน FAIL เมื่อเจอชิ้นเกินหรือไม่",
    },
    "กล้อง": {
        "camera_index": "หมายเลขกล้อง", "camera_device_name": "ชื่อกล้อง", "camera_backend": "ไดรเวอร์กล้อง",
        "camera_width": "ความกว้างที่ถ่ายจากเซนเซอร์ (px)", "camera_height": "ความสูงที่ถ่ายจากเซนเซอร์ (px)", "camera_fps": "FPS ที่ขอ",
        "camera_output_width": "ความกว้างภาพที่ใช้งาน (px)", "camera_output_height": "ความสูงภาพที่ใช้งาน (px)",
        "camera_output_mode": "วิธีได้ขนาดภาพใช้งาน: crop = ตัดกลางภาพ 1:1, fit = ตัดสัดส่วนแล้วย่อ",
        "camera_rotate_deg": "หมุนภาพกล้องให้ตรง (องศา + = ทวนเข็ม) ใช้กับทุกภาพรวมภาพสด",
    },
    "สเตจ XY": {
        "steps_per_mm": "สเต็ปต่อ mm ของมอเตอร์", "default_speed": "ความเร็วเคลื่อนที่เริ่มต้น (steps/s)",
        "default_settle_sec": "รอให้นิ่งหลังเคลื่อนที่ขั้นต่ำ (วินาที)", "soft_limit_x_mm": "ระยะเคลื่อนที่สูงสุดแกน X (mm)",
        "soft_limit_y_mm": "ระยะเคลื่อนที่สูงสุดแกน Y (mm)", "firmware_baud": "ความเร็ว serial ของ Nano", "serial_startup_delay": "รอ Nano บูตหลังเปิดพอร์ต (วินาที)",
        "stage_approach_mm": "ชดเชย backlash: ระยะเลยเป้าก่อนเข้าเป้าจากทิศ + (0 = ปิด)",
        "stage_monitor_enabled": "วัดความคลาดเคลื่อนของรางด้วยกล้องทุกครั้งที่เคลื่อนที่ (realtime)",
        "stage_sound_enabled": "ให้มอเตอร์ส่งเสียงเมื่อสแกน/HOME/calibrate เสร็จ",
    },
    "กันสั่นและชดเชยบอร์ด": {
        "stabilize_enabled": "รอภาพนิ่งก่อนถ่าย และถ่ายเฟรมที่สั่นใหม่", "stabilize_max_wait_sec": "รอภาพนิ่งนานสุด (วินาที)",
        "stabilize_threshold_px": "ถือว่านิ่งเมื่อภาพขยับไม่เกิน (px)",
        "board_align_enabled": "ชดเชยบอร์ดที่วางเอียง/เลื่อนจากตอนสอนจุด", "board_align_max_deg": "เอียงได้ไม่เกิน (องศา) เกินนี้หยุดสแกน",
        "board_align_max_mm": "เลื่อนได้ไม่เกิน (mm) เกินนี้หยุดสแกน",
    },
    "วัดความสูง 3D": {
        "depth_camera_distance_mm": "ระยะเลนส์ถึงผิวบอร์ด (mm) ใช้คำนวณความสูง", "depth_baseline_mm": "ระยะเลื่อนสเตจต่อภาพตอนวัด 3D (mm)",
        "depth_views": "จำนวนทิศที่เลื่อนไปถ่ายตอนวัด 3D",
    },
}


def get_settings() -> Dict[str, Any]:
    """Every setting with its value and meaning, grouped like the settings page."""
    from ..routers.system import get_settings as settings_dict

    raw = dict(settings_dict())
    raw["default_model"] = _parent_run_name(raw.get("default_model"))
    out: Dict[str, Any] = {}
    seen = set()
    for group, keys in SETTINGS_GLOSSARY.items():
        out[group] = {k: {"value": raw.get(k), "meaning": meaning} for k, meaning in keys.items() if k in raw}
        seen.update(keys)
    hidden = {"cors_origins", "host", "port", "model_search_dirs"}
    rest = {k: v for k, v in raw.items() if k not in seen and k not in hidden}
    if rest:
        out["อื่นๆ"] = rest
    return out


def _calibration_summary(cal: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not cal:
        return None
    um = lambda v: None if v is None else round(v * 1000, 1)  # noqa: E731
    rep = cal.get("repeatability") or {}
    axis = lambda a: {  # noqa: E731
        "backlash_um": um(a.get("backlash_mm")), "linearity_um": um(a.get("linearity_mm")),
        "straightness_um": um(a.get("straightness_mm")), "px_per_mm": a.get("px_per_mm"),
        "scale_error_pct": a.get("scale_error_pct"), "suggested_steps_per_mm": a.get("suggested_steps_per_mm"),
    }
    return {
        "measured": _time(cal.get("time")), "center_mm": cal.get("center_mm"), "range_mm": cal.get("range_mm"),
        "x": axis(cal.get("x") or {}), "y": axis(cal.get("y") or {}),
        "squareness_error_deg": cal.get("squareness_deg"), "camera_rotation_vs_stage_x_deg": cal.get("camera_rotation_deg"),
        "y_scale_vs_x": cal.get("xy_scale_ratio"),
        "repeat_same_direction_rms_um": um(max((rep.get(k) or {}).get("rms_mm", 0) for k in ("plus", "minus"))),
        "direction_gap_um": [um(v) for v in rep.get("direction_gap_mm", [])] or None,
        "with_compensation_worst_um": um((rep.get("compensated") or {}).get("worst_pair_mm")),
        "suggested_backlash_compensation_mm": cal.get("suggested_approach_mm"),
        "absolute_scale_measured": bool(cal.get("mm_per_px")),
        "frames_rotated_deg_while_measuring": cal.get("image_rotation_deg"),
    }


def get_stage_calibration() -> Dict[str, Any]:
    """Stage accuracy (camera calibration): backlash, linearity, squareness, repeatability."""
    from ..config import settings
    from .stage_calibration_service import stage_calibration_service

    st = stage_calibration_service.status()
    return {
        "job": {k: st.get(k) for k in ("state", "step", "total", "message")},
        "last_result": _calibration_summary(st.get("last")) or "ยังไม่เคย calibrate",
        "backlash_compensation_mm_now": settings.stage_approach_mm,
    }


def get_stage_errors() -> Dict[str, Any]:
    """Live positioning error of the latest moves (camera-measured)."""
    from .stage_monitor_service import stage_monitor_service

    snap = stage_monitor_service.snapshot()
    rows = [{"time": _time(x["time"]), "move_mm": x["move_mm"], "error_um": [round(v * 1000, 1) for v in x["error_mm"]],
             "total_um": x["error_um"]} for x in snap["samples"][-12:]]
    return {"enabled": snap["enabled"], "status": snap["status"], "summary": snap["summary"], "latest_moves": rows}


def _point_brief(p: Dict[str, Any]) -> Dict[str, Any]:
    mf = p.get("multiframe_info") or {}
    out = {"index": p.get("point_index"), "name": p.get("name"), "verdict": p.get("verdict"), "reason": p.get("reason")}
    if mf.get("stabilize"):
        out["waited_still_sec"] = mf["stabilize"].get("waited_sec")
        out["shaken_frames"] = mf["stabilize"].get("shaken_frames")
    if mf.get("alignment"):
        a = mf["alignment"]
        out["image_aligned"] = {k: a.get(k) for k in ("applied", "angle_deg", "shift_px", "reason") if a.get(k) is not None}
    if mf.get("max_offset_px") is not None:
        out["frame_offset_px"] = mf["max_offset_px"]
    return out


def get_scan_progress() -> Dict[str, Any]:
    """The scan running now (or the last one this session): progress, board alignment, points so far."""
    from .aoi_scan_service import aoi_scan_service

    r = aoi_scan_service.current_run
    if not r:
        return {"running": False, "note": "ยังไม่มีการสแกนตั้งแต่เปิดสถานี — ดูรอบเก่าด้วย list_scan_runs"}
    d = r.model_dump()
    return {
        "running": aoi_scan_service.is_running, "id": d["id"], "status": d["status"], "golden": d["is_golden_scan"],
        "started": _time(d["created_at"]), "finished": _time(d["completed_at"]),
        "point": f"{min(d['current_point_index'] + 1, d['total_points'])}/{d['total_points']}",
        "counts": {k: d[k] for k in ("pass_count", "fail_count", "review_count", "error_count")},
        "overall_verdict": d["overall_verdict"], "error": d.get("error_message"),
        "board_alignment": {k: v for k, v in (d.get("board_alignment") or {}).items() if k != "measured"} or None,
        "points": [_point_brief(p) for p in d["results"][-20:]],
    }


def get_camera() -> Dict[str, Any]:
    """Camera: device, capture/output size and mode, real FPS, straightening angle, viewers."""
    from ..config import settings
    from .camera_service import camera_service

    return {
        "active": camera_service.is_active, "simulated": camera_service.is_mock, "device": settings.camera_device_name,
        "index": camera_service.device_index, "capture_size": camera_service.capture_resolution if camera_service.is_active else None,
        "output_size": camera_service.resolution if camera_service.is_active else None, "output_mode": camera_service.output_mode,
        "fps_measured": round(camera_service.fps, 1), "rotate_deg": settings.camera_rotate_deg,
        "live_viewers": camera_service.stream_count,
    }


def get_motion() -> Dict[str, Any]:
    """Stage controller: connection, HOME, position, firmware abilities, compensation and recent wire log."""
    from ..config import settings
    from .machine_service import machine_service

    st = machine_service.get_state().model_dump()
    caps = sorted(getattr(machine_service._client, "capabilities", set()) or []) if machine_service._client else []
    return {
        **{k: st.get(k) for k in ("connected", "mode", "port", "ready", "homed", "position_mm", "position_steps",
                                   "is_moving", "soft_limits_mm", "last_error", "last_event")},
        "steps_per_mm": machine_service.steps_per_mm,
        "firmware_commands": caps or None,
        "can_play_sound": machine_service.can_play,
        "idle_coils_off_after_sec": 3 if "RELEASE" in caps else None,
        "backlash_compensation_mm": settings.stage_approach_mm,
        "wire_log_tail": (st.get("rx_log") or [])[-8:],
    }


def get_access() -> Dict[str, Any]:
    """Who controls the station now, passcode, connected browsers, remote access (Tailscale)."""
    from ..config import settings
    from ..core.security import lease_manager
    from ..routers import ws
    from . import tunnel_service

    lease = lease_manager.get_lease_info().model_dump()
    out = {
        "controlled": lease.get("is_controlled"), "operator": lease.get("operator_name"),
        "since": _time(lease.get("granted_at")), "expires": _time(lease.get("expires_at")),
        "passcode_set": bool(settings.operator_passcode), "open_browsers": len(ws.active_connections),
    }
    out["default_passcode_in_use"] = settings.operator_passcode == "rmutt-aoi"
    try:
        t = tunnel_service.status()
        serve = t.get("serve") or {}
        out["remote"] = {
            "tailscale_installed": t.get("installed"), "state": t.get("state"), "url": serve.get("url"),
            "public_internet_funnel": serve.get("funnel"), "lan": t.get("lan"), "direct_url_in_tailnet": t.get("direct_url"),
        }
    except Exception as exc:
        out["remote"] = {"error": str(exc)[:120]}
    return out


def get_recent_events(level: str = "INFO", limit: int = 30) -> Dict[str, Any]:
    """The station's latest log lines (errors, warnings, scan/alignment/calibration events)."""
    from ..core import log_buffer

    lvl = level.upper() if level.upper() in ("INFO", "WARNING", "ERROR") else "INFO"
    rows = log_buffer.recent(lvl, int(limit or 30))
    return {"level": lvl, "count": len(rows), "events": rows}


def get_full_snapshot() -> Dict[str, Any]:
    """Everything at once for an overall summary; each part fails on its own."""
    def safe(fn, *a, **k):
        try:
            return fn(*a, **k)
        except Exception as exc:
            return {"error": f"{exc.__class__.__name__}: {exc}"[:200]}

    hw = safe(get_hardware)
    hw_brief = hw if "error" in hw else {
        "cpu_usage_pct": (hw.get("cpu") or {}).get("usage"), "memory": hw.get("memory"),
        "temperatures": hw.get("temperatures"), **{k: hw[k] for k in ("gpu", "power", "fan", "power_mode") if k in hw},
    }
    return {
        "station": safe(get_station_status),
        "scan": safe(get_scan_progress),
        "motion": safe(get_motion),
        "camera": safe(get_camera),
        "access": safe(get_access),
        "stage_calibration": safe(get_stage_calibration),
        "stage_errors": safe(lambda: {k: v for k, v in get_stage_errors().items() if k != "latest_moves"}),
        "statistics": safe(get_statistics),
        "hardware": hw_brief,
        "settings": safe(get_settings),
        "recent_warnings": safe(lambda: get_recent_events("WARNING", 8)["events"]),
    }


def get_hardware() -> Dict[str, Any]:
    from .hardware_service import hardware_service

    d = hardware_service.snapshot()
    d.pop("time", None)
    d["cpu"]["cores"] = [{k: c[k] for k in ("id", "usage", "mhz")} for c in d["cpu"]["cores"]]
    return d


def navigate(page: str) -> Dict[str, Any]:
    if page not in PAGES:
        return {"ok": False, "error": f"unknown page; use one of {list(PAGES)}"}
    return {"ok": True, "page": page}


TOOLS: Dict[str, Callable[..., Any]] = {
    "get_station_status": get_station_status,
    "get_statistics": get_statistics,
    "list_scan_runs": list_scan_runs,
    "get_scan_run": get_scan_run,
    "read_part_markings": read_part_markings,
    "list_single_inspections": list_single_inspections,
    "list_reference_profiles": list_reference_profiles,
    "get_reference_profile": get_reference_profile,
    "list_boards": list_boards,
    "get_board": get_board,
    "list_datasets": list_datasets,
    "get_dataset": get_dataset,
    "list_models": list_models,
    "get_settings": get_settings,
    "get_hardware": get_hardware,
    "get_full_snapshot": get_full_snapshot,
    "get_stage_calibration": get_stage_calibration,
    "get_stage_errors": get_stage_errors,
    "get_scan_progress": get_scan_progress,
    "get_camera": get_camera,
    "get_motion": get_motion,
    "get_access": get_access,
    "get_recent_events": get_recent_events,
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
    {"name": "read_part_markings",
     "description": "อ่านตัวอักษรที่พิมพ์บนชิ้นส่วนด้วย OCR จากภาพถ่ายจริงของรอบสแกน เช่น เบอร์ IC (EPM570T144C5, MAX232CPE), ค่าตัวเก็บประจุ — ใช้เมื่อถามว่าชิปเบอร์อะไร/ยี่ห้ออะไร/มีชิปอะไรบ้าง (ช้ากว่าเครื่องมืออื่นเล็กน้อย)",
     "parameters": {"type": "object", "properties": {
         "run_id": _STR,
         "labels": {"type": "array", "items": {"type": "string"}, "description": "คลาสที่จะอ่าน เช่น [\"ic\"] (ค่าเริ่ม ic) หรือ [\"capacitor\",\"connector\"]"},
         "point_index": {"type": "integer", "description": "อ่านเฉพาะจุดนี้ (เริ่มที่ 0) ถ้าไม่ระบุอ่านทุกจุดของรอบ"}},
         "required": ["run_id"]}},
    {"name": "list_single_inspections", "description": "รายการตรวจภาพเดี่ยวล่าสุด (รวมถ่ายทดสอบ)",
     "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    {"name": "list_reference_profiles", "description": "รายการโปรไฟล์อ้างอิง (ต้นแบบ)"},
    {"name": "get_reference_profile", "description": "รายละเอียดโปรไฟล์อ้างอิงหนึ่งตัว: จำนวนจุด ชิ้นแต่ละคลาส",
     "parameters": {"type": "object", "properties": {"ref_id": _STR}, "required": ["ref_id"]}},
    {"name": "list_boards", "description": "รายการบอร์ดที่บันทึกไว้ (ชุดจุดตรวจที่ตั้งชื่อไว้ในหน้าสแกน AOI): ชื่อ จำนวนจุด จำนวนชิ้นต้นแบบ วันที่แก้ล่าสุด"},
    {"name": "get_board", "description": "รายละเอียดบอร์ดที่บันทึกไว้หนึ่งบอร์ด: ทุกจุดตรวจ พิกัด ซูม และชิ้นส่วนต้นแบบแยกคลาสต่อจุด ระบุ board_id หรือ name อย่างใดอย่างหนึ่ง",
     "parameters": {"type": "object", "properties": {"board_id": _STR, "name": {"type": "string", "description": "ชื่อบอร์ด (ตรงทั้งหมดหรือบางส่วน)"}}}},
    {"name": "list_datasets", "description": "รายการชุดข้อมูลเทรนที่ถ่ายจากสถานี"},
    {"name": "get_dataset", "description": "รายละเอียดชุดข้อมูลหนึ่งชุด: คลาส จำนวนภาพ/กรอบ ติด label อย่างไร",
     "parameters": {"type": "object", "properties": {"dataset_id": _STR}, "required": ["dataset_id"]}},
    {"name": "list_models", "description": "โมเดล YOLO ที่มีให้เลือก (จาก runs การเทรน) และตัวที่ใช้อยู่"},
    {"name": "get_settings", "description": "การตั้งค่าทั้งหมดของสถานี แยกหมวด พร้อมความหมายของแต่ละค่า: สถานี โมเดล/การตรวจ กล้อง (รวมมุมหมุนภาพ) สเตจ (ชดเชย backlash เสียง) กันสั่น ชดเชยบอร์ด 3D"},
    {"name": "get_full_snapshot", "description": "ภาพรวมทุกอย่างในครั้งเดียว: สถานะสด สแกนที่กำลังรัน/ล่าสุด สเตจและเฟิร์มแวร์ กล้อง สิทธิ์ควบคุม ผล calibrate ราง ความคลาดเคลื่อนราง สถิติ Yield ฮาร์ดแวร์ การตั้งค่าทั้งหมด และคำเตือนล่าสุด — ใช้เมื่อถูกขอให้สรุปภาพรวม/ทุกอย่าง/สถานะเครื่อง"},
    {"name": "get_stage_calibration", "description": "ผล calibrate ความแม่นยำราง XY: backlash, ความเป็นเชิงเส้น, ความตรงราง, มุมฉาก, กล้องเอียง, สเกล Y/X, การกลับจุดเดิม, ค่าชดเชยที่แนะนำ/ที่ใช้อยู่ และสถานะงาน calibrate"},
    {"name": "get_stage_errors", "description": "ความคลาดเคลื่อนของรางแบบ realtime (วัดด้วยกล้องทุกครั้งที่เคลื่อนที่): ค่าล่าสุด RMS สูงสุด และการเคลื่อนที่ล่าสุด"},
    {"name": "get_scan_progress", "description": "สแกนที่กำลังรันอยู่ (หรือรอบล่าสุดตั้งแต่เปิดเครื่อง): จุดที่เท่าไหร่ ผ่าน/ไม่ผ่าน การชดเชยการวางบอร์ด (เอียง/เลื่อน) การรอภาพนิ่ง การจัดภาพตามต้นแบบรายจุด"},
    {"name": "get_camera", "description": "กล้อง: รุ่น ขนาดภาพที่ถ่าย/ที่ใช้ โหมด crop/fit FPS จริง มุมหมุนภาพ จำนวนผู้ดูภาพสด"},
    {"name": "get_motion", "description": "ตัวควบคุมสเตจ: เชื่อมต่อ/HOME ตำแหน่ง ขอบเขต คำสั่งที่เฟิร์มแวร์รองรับ (เช่น TONE, RELEASE) เสียง การปิดคอยล์อัตโนมัติ การชดเชย backlash และ log การสื่อสารล่าสุด"},
    {"name": "get_access", "description": "ใครถือสิทธิ์ควบคุมสถานีตอนนี้ หมดอายุเมื่อไหร่ ตั้งรหัสผ่านไหม มีเบราว์เซอร์เปิดอยู่กี่เครื่อง และการเข้าถึงระยะไกล (Tailscale)"},
    {"name": "get_recent_events", "description": "log เหตุการณ์ล่าสุดของสถานี: ข้อผิดพลาด คำเตือน และเหตุการณ์สแกน/ชดเชยบอร์ด/calibrate/GPU — ใช้เมื่อถามว่าเกิดอะไรขึ้น ทำไมล้ม error อะไร",
     "parameters": {"type": "object", "properties": {"level": {"type": "string", "enum": ["INFO", "WARNING", "ERROR"]},
                                                     "limit": {"type": "integer", "description": "จำนวน (1-200, ค่าเริ่ม 30)"}}}},
    {"name": "get_hardware", "description": "ประสิทธิภาพเครื่องสด: การใช้งาน/ความถี่ CPU แต่ละคอร์, GPU, RAM, อุณหภูมิ, พลังงาน (W), พัดลม (%/rpm), โหมดพลังงาน Jetson, over-current — ใช้เมื่อถามว่าเครื่องร้อน/ช้า/กินไฟ/พัดลม"},
    {"name": "navigate", "description": "พาผู้ใช้ไปหน้าในเว็บแอป",
     "parameters": {"type": "object", "properties": {"page": {"type": "string", "enum": list(PAGES)}}, "required": ["page"]}},
]

TOOL_LABELS = {
    "get_station_status": "ดูสถานะสถานี", "get_statistics": "ดูสถิติ Yield", "list_scan_runs": "ดูรายการรอบสแกน",
    "get_scan_run": "ดูผลรอบสแกน", "read_part_markings": "อ่านตัวอักษรบนชิ้น (OCR)", "list_single_inspections": "ดูการตรวจภาพเดี่ยว", "list_reference_profiles": "ดูโปรไฟล์อ้างอิง",
    "get_reference_profile": "ดูรายละเอียดโปรไฟล์", "list_datasets": "ดูชุดข้อมูล", "get_dataset": "ดูรายละเอียดชุดข้อมูล",
    "list_models": "ดูรายการโมเดล", "list_boards": "ดูบอร์ดที่บันทึกไว้", "get_board": "ดูรายละเอียดบอร์ด", "get_settings": "ดูการตั้งค่า", "get_hardware": "ดูประสิทธิภาพเครื่อง", "navigate": "เปิดหน้า",
    "get_full_snapshot": "ดูภาพรวมทั้งระบบ", "get_stage_calibration": "ดูผล calibrate ราง", "get_stage_errors": "ดูความคลาดเคลื่อนราง",
    "get_scan_progress": "ดูความคืบหน้าสแกน", "get_camera": "ดูสถานะกล้อง", "get_motion": "ดูสถานะสเตจ/เฟิร์มแวร์",
    "get_access": "ดูสิทธิ์ควบคุม/การเข้าถึง", "get_recent_events": "ดู log ล่าสุด",
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


# One quick retry per model, then move on; if every model is busy, wait and go round again.
RETRY_DELAYS_SEC = (1,)
ROUND_PAUSE_SEC = 5.0
MODEL_ROUNDS = 2


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
        if res.status_code in chat_service.UNAVAILABLE:
            chat_service.mark_unavailable(model)
            raise _ModelBusy(last)  # same handling as a busy model: restart the turn on the next one
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
        yield _event("error", message="AI agent ใช้ Gemini — ใส่ Gemini API key และเลือกผู้ให้บริการ Gemini ที่ ตั้งค่าสถานี → ผู้ช่วย AI")
        return
    system = SYSTEM_PROMPT + (f"\nผู้ใช้กำลังอยู่ที่หน้า: {page} ({PAGES.get(page, '')})" if page else "")
    base = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
            for m in history[-20:] if m.get("content")]
    headers = {"x-goog-api-key": os.environ.get("GEMINI_API_KEY", ""), "Content-Type": "application/json"}
    navigated: set = set()
    last_error = ""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=15)) as client:
            for round_no in range(MODEL_ROUNDS):
                if round_no:
                    await asyncio.sleep(ROUND_PAUSE_SEC)
                    yield _event("tool", name="retry", label="ทุกรุ่นไม่ว่าง — รอสักครู่แล้วลองใหม่", args={})
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
                        yield _event("tool", name="retry", label=f"{model} ใช้ไม่ได้ตอนนี้ — เปลี่ยนรุ่น AI แล้วลองใหม่", args={})
                        continue
                    except RuntimeError as exc:
                        yield _event("error", message=f"AI ตอบไม่ได้ — {exc}")
                        return
            yield _event("error", message=f"Gemini ทุกรุ่นไม่ว่างตอนนี้ ลองใหม่ในอีกสักครู่ — {last_error}")
    except httpx.HTTPError as exc:
        logger.warning("Agent request failed: %s", exc)
        yield _event("error", message=f"เชื่อมต่อ AI ไม่ได้: {exc.__class__.__name__}")
