"""Storage service: SQLite database and filesystem storage for inspection runs and references."""
from __future__ import annotations

import csv
from contextlib import contextmanager
import io
import json
import logging
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np

from ..config import DB_PATH, REFERENCES_DIR, RUNS_DIR, UPLOADS_DIR
from ..core.schemas import (
    AOIPointResult,
    AOIRunReport,
    Detection,
    InspectionSummary,
    ReferenceProfile,
    ReferenceSummary,
    Verdict,
)

logger = logging.getLogger("storage_service")

SAFE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")


class StorageService:
    """Manages SQLite persistence and filesystem image assets."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Runs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    is_simulation INTEGER NOT NULL,
                    is_golden_scan INTEGER NOT NULL,
                    reference_id TEXT,
                    created_at REAL NOT NULL,
                    completed_at REAL,
                    overall_verdict TEXT NOT NULL,
                    total_points INTEGER NOT NULL,
                    pass_count INTEGER DEFAULT 0,
                    fail_count INTEGER DEFAULT 0,
                    review_count INTEGER DEFAULT 0,
                    error_count INTEGER DEFAULT 0,
                    plan_json TEXT NOT NULL,
                    error_message TEXT
                )
            """)
            # Point results table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS point_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    point_index INTEGER NOT NULL,
                    col INTEGER NOT NULL,
                    row INTEGER NOT NULL,
                    x_mm REAL NOT NULL,
                    y_mm REAL NOT NULL,
                    verdict TEXT NOT NULL,
                    reason TEXT,
                    image_path TEXT NOT NULL,
                    annotated_path TEXT NOT NULL,
                    image_url TEXT NOT NULL,
                    annotated_url TEXT NOT NULL,
                    detections_json TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    speed_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES runs (id) ON DELETE CASCADE
                )
            """)
            # References table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS references_profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    profile_type TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            # Single-image inspection history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS single_inspections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    verdict TEXT NOT NULL,
                    reason TEXT,
                    model_used TEXT,
                    device_used TEXT,
                    image_path TEXT NOT NULL,
                    annotated_path TEXT,
                    detections_json TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    speed_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
            """)
            columns = {r[1] for r in cursor.execute("PRAGMA table_info(point_results)")}
            if "details_json" not in columns:
                cursor.execute("ALTER TABLE point_results ADD COLUMN details_json TEXT")
            # Which machine/model scanned the board, and its real condition (for accuracy / F1).
            run_cols = {r[1] for r in cursor.execute("PRAGMA table_info(runs)")}
            for col in ("host", "device", "model", "ground_truth"):
                if col not in run_cols:
                    cursor.execute(f"ALTER TABLE runs ADD COLUMN {col} TEXT")
            # Startup recovery for F18: mark interrupted runs as aborted
            cursor.execute("""
                UPDATE runs
                SET status = 'aborted', overall_verdict = 'REVIEW',
                    error_message = 'Interrupted: Server restarted during scan.',
                    completed_at = ?
                WHERE status = 'running'
            """, (time.time(),))
            conn.commit()
            logger.info("Storage database initialized at %s", self.db_path)


    # ── Image File Helpers ──

    def save_upload_image(self, file_bytes: bytes, filename: str) -> Tuple[Path, str]:
        """Save an uploaded raw image file."""
        stem = re.sub(r"[^a-zA-Z0-9_-]", "_", Path(filename).stem)[:80] or "image"
        ext = Path(filename).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
            ext = ".png"
        unique_name = f"{uuid.uuid4().hex}_{stem}{ext}"
        target_path = UPLOADS_DIR / unique_name
        target_path.write_bytes(file_bytes)
        url = f"/api/storage/uploads/{unique_name}"
        return (target_path, url)

    def save_image_array(self, image: np.ndarray, folder: Path, filename: str) -> Tuple[Path, str]:
        """Save a BGR numpy image to disk."""
        folder.mkdir(parents=True, exist_ok=True)
        file_path = folder / filename
        success = cv2.imwrite(str(file_path), image)
        if not success:
            raise IOError(f"Failed to write image file to {file_path}")
        from ..core.thumbs import warm

        warm(file_path)  # placeholder + preview ready before anyone opens the result
        # Build relative url
        rel_path = file_path.relative_to(RUNS_DIR.parent)
        url = f"/api/storage/{rel_path.as_posix()}"
        return (file_path, url)

    # ── Single Inspection Persistence ──

    def save_single_inspection(
        self,
        verdict: Verdict,
        reason: Optional[str],
        model_used: str,
        device_used: str,
        image_path: str,
        annotated_path: Optional[str],
        detections: List[Detection],
        summary: InspectionSummary,
        speed_ms: Dict[str, float]
    ) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO single_inspections (
                    verdict, reason, model_used, device_used,
                    image_path, annotated_path, detections_json,
                    summary_json, speed_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                verdict, reason, model_used, device_used,
                image_path, annotated_path,
                json.dumps([d.model_dump() for d in detections]),
                json.dumps(summary.model_dump()),
                json.dumps(speed_ms),
                time.time()
            ))
            conn.commit()
            return cursor.lastrowid

    # ── AOI Run Persistence ──

    def create_run(self, report: AOIRunReport):
        import socket
        from .inference_service import inference_service

        run_folder = RUNS_DIR / report.id
        run_folder.mkdir(parents=True, exist_ok=True)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO runs (
                    id, status, is_simulation, is_golden_scan, reference_id,
                    created_at, completed_at, overall_verdict, total_points,
                    pass_count, fail_count, review_count, error_count,
                    plan_json, error_message, host, device, model
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                report.id, report.status, int(report.is_simulation), int(report.is_golden_scan),
                report.reference_id, report.created_at, report.completed_at, report.overall_verdict,
                len(report.points), report.pass_count, report.fail_count, report.review_count,
                report.error_count, json.dumps(report.plan.model_dump()), report.error_message,
                socket.gethostname(),
                inference_service.device_info.label if inference_service.device_info else None,
                Path(inference_service.model_path or "").name or None,
            ))
            conn.commit()
        self.atomic_save_report_json(report)

    def update_run_point(self, run_id: str, point_result: AOIPointResult):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO point_results (
                    run_id, point_index, col, row, x_mm, y_mm,
                    verdict, reason, image_path, annotated_path,
                    image_url, annotated_url, detections_json,
                    summary_json, speed_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id, point_result.point_index, point_result.col, point_result.row,
                point_result.x_mm, point_result.y_mm, point_result.verdict, point_result.reason,
                point_result.image_path, point_result.annotated_path, point_result.image_url,
                point_result.annotated_url, json.dumps([d.model_dump() for d in point_result.detections]),
                json.dumps(point_result.summary.model_dump()), json.dumps(point_result.speed_ms),
                time.time()
            ))
            cursor.execute("UPDATE point_results SET details_json = ? WHERE id = ?", (point_result.model_dump_json(),cursor.lastrowid))
            conn.commit()

    def finalize_run(self, report: AOIRunReport):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE runs SET
                    status = ?, completed_at = ?, overall_verdict = ?,
                    pass_count = ?, fail_count = ?, review_count = ?, error_count = ?,
                    error_message = ?, reference_id = ?
                WHERE id = ?
            """, (
                report.status, report.completed_at or time.time(), report.overall_verdict,
                report.pass_count, report.fail_count, report.review_count, report.error_count,
                report.error_message, report.reference_id, report.id
            ))
            conn.commit()
        self.atomic_save_report_json(report)

    def atomic_save_report_json(self, report: AOIRunReport):
        """Write report.json atomically to run folder."""
        run_folder = RUNS_DIR / report.id
        run_folder.mkdir(parents=True, exist_ok=True)
        temp_file = run_folder / "report.json.tmp"
        target_file = run_folder / "report.json"
        temp_file.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        temp_file.replace(target_file)

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
            run_row = cursor.fetchone()
            if not run_row:
                return None

            run_dict = dict(run_row)
            run_dict["plan"] = json.loads(run_dict["plan_json"])

            cursor.execute("SELECT * FROM point_results WHERE run_id = ? ORDER BY point_index ASC", (run_id,))
            points = []
            for p_row in cursor.fetchall():
                p = dict(p_row)
                if p.get("details_json"):
                    p.update(json.loads(p["details_json"]))
                p["detections"] = json.loads(p["detections_json"])
                p["summary"] = json.loads(p["summary_json"])
                p["speed_ms"] = json.loads(p["speed_json"])
                points.append(p)

            run_dict["results"] = points
            return run_dict

    def set_ground_truth(self, run_id: str, truth: Optional[str]) -> bool:
        """The board's real condition: 'good', 'defective', or None to clear."""
        with self._get_connection() as conn:
            cur = conn.execute("UPDATE runs SET ground_truth = ? WHERE id = ?", (truth, run_id))
            conn.commit()
            return cur.rowcount > 0

    def performance_rows(self, since: float = 0.0, include_simulation: bool = False) -> Dict[str, Any]:
        """Raw rows for the performance report: finished production scans + their point timings."""
        with self._get_connection() as conn:
            sim = "" if include_simulation else " AND is_simulation = 0"
            runs = [dict(r) for r in conn.execute(
                "SELECT id, status, is_simulation, created_at, completed_at, overall_verdict, total_points, "
                "host, device, model, ground_truth FROM runs WHERE is_golden_scan = 0 AND created_at >= ?" + sim,
                (since,),
            )]
            ids = [r["id"] for r in runs]
            points = []
            if ids:
                marks = ",".join("?" * len(ids))
                points = [dict(r) for r in conn.execute(f"SELECT run_id, speed_json FROM point_results WHERE run_id IN ({marks})", ids)]
            singles = [dict(r) for r in conn.execute(
                "SELECT device_used, model_used, speed_json, created_at FROM single_inspections WHERE created_at >= ?", (since,)
            )]
        return {"runs": runs, "points": points, "singles": singles}

    def list_runs(
        self,
        verdict: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[Dict[str, Any]], int]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM runs"
            params = []
            if verdict:
                query += " WHERE overall_verdict = ?"
                params.append(verdict)
            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            runs = [dict(r) for r in cursor.fetchall()]

            count_query = "SELECT COUNT(*) FROM runs"
            count_params = []
            if verdict:
                count_query += " WHERE overall_verdict = ?"
                count_params.append(verdict)
            cursor.execute(count_query, count_params)
            total = cursor.fetchone()[0]

            return (runs, total)

    # ── Single Inspection Querying ──

    def list_single_inspections(self, limit: int = 50, offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM single_inspections ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))
            rows = [self._single_row(r) for r in cursor.fetchall()]

            cursor.execute("SELECT COUNT(*) FROM single_inspections")
            total = cursor.fetchone()[0]
            return (rows, total)

    def get_single_inspection(self, inspection_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM single_inspections WHERE id = ?", (inspection_id,))
            r = cursor.fetchone()
            return self._single_row(r) if r else None

    @staticmethod
    def _single_row(r: sqlite3.Row) -> Dict[str, Any]:
        row = dict(r)
        row["detections"] = json.loads(row["detections_json"])
        row["summary"] = json.loads(row["summary_json"])
        row["speed_ms"] = json.loads(row["speed_json"])
        if row.get("image_path"):
            row["image_url"] = f"/api/storage/uploads/{Path(row['image_path']).name}"
        if row.get("annotated_path"):
            row["annotated_url"] = f"/api/storage/uploads/{Path(row['annotated_path']).name}"
        return row

    def export_single_csv(self) -> str:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM single_inspections ORDER BY created_at DESC")
            rows = cursor.fetchall()

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["ID", "Verdict", "Reason", "Model", "Device", "Created At"])
            for r in rows:
                writer.writerow([
                    r["id"], r["verdict"], r["reason"] or "",
                    r["model_used"] or "", r["device_used"] or "",
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["created_at"]))
                ])
            return output.getvalue()

    def get_statistics(self) -> Dict[str, Any]:
        """Compute production board-level and point-level yield rate statistics.
        
        Strictly excludes Simulation and Golden Scan runs from production KPIs.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Production completed runs only
            cursor.execute("""
                SELECT
                    COUNT(*) as total_prod_runs,
                    SUM(CASE WHEN overall_verdict = 'PASS' THEN 1 ELSE 0 END) as pass_runs,
                    SUM(CASE WHEN overall_verdict = 'FAIL' THEN 1 ELSE 0 END) as fail_runs,
                    SUM(CASE WHEN overall_verdict = 'REVIEW' THEN 1 ELSE 0 END) as review_runs,
                    SUM(CASE WHEN overall_verdict = 'ERROR' THEN 1 ELSE 0 END) as error_runs,
                    SUM(pass_count) as total_pass_points,
                    SUM(fail_count) as total_fail_points,
                    SUM(review_count) as total_review_points,
                    SUM(error_count) as total_error_points
                FROM runs
                WHERE status = 'complete'
                  AND is_simulation = 0
                  AND is_golden_scan = 0
            """)
            stats = dict(cursor.fetchone() or {})
            total_prod_runs = stats.get("total_prod_runs") or 0
            pass_runs = stats.get("pass_runs") or 0
            fail_runs = stats.get("fail_runs") or 0

            # Board yield rate: PASS / (PASS + FAIL) or 0.0
            decided_boards = pass_runs + fail_runs
            board_yield = round((pass_runs / decided_boards * 100), 1) if decided_boards > 0 else 0.0

            total_pts = (stats.get("total_pass_points") or 0) + (stats.get("total_fail_points") or 0)
            pass_pts = stats.get("total_pass_points") or 0
            point_yield = round((pass_pts / total_pts * 100), 1) if total_pts > 0 else 0.0

            # Count simulation and golden scans separately for transparency
            cursor.execute("SELECT COUNT(*) FROM runs WHERE is_simulation = 1")
            sim_runs = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM runs WHERE is_golden_scan = 1")
            golden_runs = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM single_inspections")
            total_single = cursor.fetchone()[0]

            return {
                "total_runs": total_prod_runs,
                "pass_runs": pass_runs,
                "fail_runs": fail_runs,
                "review_runs": stats.get("review_runs") or 0,
                "error_runs": stats.get("error_runs") or 0,
                "board_yield_rate": board_yield,
                "point_yield_rate": point_yield,
                "total_pass_points": pass_pts,
                "total_fail_points": stats.get("total_fail_points") or 0,
                "simulation_runs": sim_runs,
                "golden_runs": golden_runs,
                "single_inspections_count": total_single
            }

    def export_runs_csv(self) -> str:
        """Export inspection history to CSV string."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM runs ORDER BY created_at DESC")
            rows = cursor.fetchall()

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "Run ID", "Status", "Verdict", "Simulation", "Golden Scan",
                "Total Points", "Pass", "Fail", "Review", "Error", "Created At"
            ])
            for r in rows:
                writer.writerow([
                    r["id"], r["status"], r["overall_verdict"],
                    "Yes" if r["is_simulation"] else "No",
                    "Yes" if r["is_golden_scan"] else "No",
                    r["total_points"], r["pass_count"], r["fail_count"],
                    r["review_count"], r["error_count"],
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["created_at"]))
                ])
            return output.getvalue()

    # ── Reference Profile Persistence (Protected from Path Traversal) ──

    def save_reference(self, profile: ReferenceProfile):
        if not profile.id or not SAFE_ID_REGEX.match(profile.id):
            raise ValueError(f"Invalid reference profile ID '{profile.id}'. Must contain only alphanumeric characters, dashes, and underscores.")

        target_file = (REFERENCES_DIR / f"{profile.id}.json").resolve()
        if target_file.parent != REFERENCES_DIR.resolve():
            raise ValueError("Path containment violation: profile ID escapes reference directory.")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO references_profiles (
                    id, name, description, profile_type, data_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                profile.id, profile.name, profile.description, profile.profile_type,
                profile.model_dump_json(), profile.created_at, time.time()
            ))
            conn.commit()

        # Save copy as JSON in REFERENCES_DIR
        temporary = target_file.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(profile.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(target_file)

    def get_reference(self, ref_id: str) -> Optional[ReferenceProfile]:
        if not ref_id or not SAFE_ID_REGEX.match(ref_id):
            return None

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT data_json FROM references_profiles WHERE id = ?", (ref_id,))
            row = cursor.fetchone()
            if row:
                return ReferenceProfile.model_validate_json(row["data_json"])

        # Fallback to file in REFERENCES_DIR with strict containment check
        ref_path = (REFERENCES_DIR / f"{ref_id}.json").resolve()
        if ref_path.parent == REFERENCES_DIR.resolve() and ref_path.is_file():
            return ReferenceProfile.model_validate_json(ref_path.read_text(encoding="utf-8"))
        return None

    def list_references(self) -> List[ReferenceSummary]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, description, profile_type, data_json, created_at, updated_at FROM references_profiles ORDER BY updated_at DESC")
            summaries: List[ReferenceSummary] = []
            for r in cursor.fetchall():
                data = json.loads(r["data_json"])
                p_type = r["profile_type"]
                if p_type == "single":
                    cnt = len(data.get("points", []))
                else:
                    grid = data.get("grid_points", {})
                    cnt = sum(len(pts) for pts in grid.values())

                summaries.append(ReferenceSummary(
                    id=r["id"],
                    name=r["name"],
                    description=r["description"] or "",
                    profile_type=p_type,
                    points_count=cnt,
                    created_at=float(r["created_at"]),
                    updated_at=float(r["updated_at"])
                ))
            return summaries

    def delete_reference(self, ref_id: str) -> bool:
        if not ref_id or not SAFE_ID_REGEX.match(ref_id):
            return False

        existed = self.get_reference(ref_id) is not None
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM references_profiles WHERE id = ?", (ref_id,))
            conn.commit()

        ref_path = (REFERENCES_DIR / f"{ref_id}.json").resolve()
        if ref_path.parent == REFERENCES_DIR.resolve() and ref_path.is_file():
            ref_path.unlink()
        return existed


# Global singleton
storage_service = StorageService()

