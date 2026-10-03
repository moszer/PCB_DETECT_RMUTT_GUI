"""Named sets of test points ("จุดตรวจ") saved in the station SQLite DB so they can be reloaded later."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from .storage_service import storage_service

MAX_NAME = 80


def _ensure_table() -> None:
    with storage_service._get_connection() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS point_sets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                points_json TEXT NOT NULL,
                point_count INTEGER NOT NULL,
                component_count INTEGER NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )"""
        )


_ensure_table()


def _counts(points: List[Dict[str, Any]]) -> tuple:
    return len(points), sum(len(p.get("expected_components") or []) for p in points)


def _summary(row) -> Dict[str, Any]:
    return {
        "id": row["id"], "name": row["name"], "point_count": row["point_count"], "component_count": row["component_count"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def clean_name(name: str) -> str:
    name = " ".join((name or "").split())[:MAX_NAME]
    if not name:
        raise ValueError("ต้องตั้งชื่อชุดจุดตรวจ")
    return name


def list_sets() -> List[Dict[str, Any]]:
    with storage_service._get_connection() as conn:
        rows = conn.execute("SELECT * FROM point_sets ORDER BY updated_at DESC").fetchall()
    return [_summary(r) for r in rows]


def get_set(set_id: str) -> Optional[Dict[str, Any]]:
    with storage_service._get_connection() as conn:
        row = conn.execute("SELECT * FROM point_sets WHERE id = ?", (set_id,)).fetchone()
    return {**_summary(row), "points": json.loads(row["points_json"])} if row else None


def name_taken(name: str, except_id: Optional[str] = None) -> bool:
    with storage_service._get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM point_sets WHERE lower(name) = lower(?) AND id != ?", (name, except_id or "")
        ).fetchone()
    return row is not None


def create_set(name: str, points: List[Dict[str, Any]]) -> Dict[str, Any]:
    name = clean_name(name)
    if name_taken(name):
        raise ValueError(f"มีชุดชื่อ “{name}” อยู่แล้ว")
    set_id, now = f"ps_{uuid.uuid4().hex[:10]}", time.time()
    count, comps = _counts(points)
    with storage_service._get_connection() as conn:
        conn.execute(
            "INSERT INTO point_sets (id, name, points_json, point_count, component_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (set_id, name, json.dumps(points, ensure_ascii=False), count, comps, now, now),
        )
    return get_set(set_id)  # type: ignore[return-value]


def update_set(set_id: str, name: Optional[str] = None, points: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    current = get_set(set_id)
    if not current:
        return None
    new_name = clean_name(name) if name is not None else current["name"]
    if new_name != current["name"] and name_taken(new_name, set_id):
        raise ValueError(f"มีชุดชื่อ “{new_name}” อยู่แล้ว")
    new_points = points if points is not None else current["points"]
    count, comps = _counts(new_points)
    with storage_service._get_connection() as conn:
        conn.execute(
            "UPDATE point_sets SET name = ?, points_json = ?, point_count = ?, component_count = ?, updated_at = ? WHERE id = ?",
            (new_name, json.dumps(new_points, ensure_ascii=False), count, comps, time.time(), set_id),
        )
    return get_set(set_id)


def delete_set(set_id: str) -> bool:
    with storage_service._get_connection() as conn:
        return conn.execute("DELETE FROM point_sets WHERE id = ?", (set_id,)).rowcount > 0
