"""AOI scan orchestration: Move -> Settle -> Fresh Frame -> Infer -> Evaluate -> Save."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import math

from ..config import RUNS_DIR
from ..core.inspection import (
    digital_zoom,
    draw_annotated_image,
    draw_multiframe_annotated_image,
    evaluate_inspection,
    evaluate_multiframe_round,
    normalized_detections,
    reference_components,
)
from ..core.motion_protocol import raster_points
from ..core.schemas import (
    AOIPointResult,
    AOIRunReport,
    Detection,
    InspectionSummary,
    ReferencePoint,
    ReferenceProfile,
    ScanPlanRequest,
    ScanPoint,
    Verdict,
)
from .camera_service import camera_service
from .inference_service import inference_service
from .machine_service import machine_service
from .storage_service import storage_service

logger = logging.getLogger("aoi_scan_service")


class AOIScanService:
    """Coordinates automated XY stage raster scanning and visual inspection."""

    def __init__(self):
        self._lock = threading.RLock()
        self._current_run: Optional[AOIRunReport] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._progress_subscribers: List[Callable[[Dict[str, Any]], None]] = []

    @property
    def is_running(self) -> bool:
        with self._lock:
            return bool((self._current_run is not None and self._current_run.status == "running") or (self._worker_thread and self._worker_thread.is_alive()))

    @property
    def current_run(self) -> Optional[AOIRunReport]:
        with self._lock:
            return self._current_run

    def subscribe_progress(self, callback: Callable[[Dict[str, Any]], None]):
        self._progress_subscribers.append(callback)

    def _broadcast_progress(self, payload: Dict[str, Any]):
        for sub in list(self._progress_subscribers):
            try:
                sub(payload)
            except Exception:
                pass

    def plan_scan(self, plan: ScanPlanRequest) -> List[ScanPoint]:
        """Validate and calculate raster scan points in mm and steps enforcing effective soft limits."""
        state = machine_service.get_state()
        steps_per_mm = machine_service.steps_per_mm

        # Enforce effective soft limits
        effective_limit_x = min(state.limits_steps[0], round(state.soft_limits_mm[0] * steps_per_mm))
        effective_limit_y = min(state.limits_steps[1], round(state.soft_limits_mm[1] * steps_per_mm))

        # 1. Custom points mode
        if getattr(plan, "plan_mode", "grid") == "custom" and plan.custom_points:
            scan_points: List[ScanPoint] = []
            for idx, cp in enumerate(plan.custom_points):
                x_steps = round(cp.x_mm * steps_per_mm)
                y_steps = round(cp.y_mm * steps_per_mm)
                if not (0 <= x_steps <= effective_limit_x and 0 <= y_steps <= effective_limit_y):
                    raise ValueError(f"Point {idx+1} exceeds travel limits")
                scan_points.append(ScanPoint(
                    index=idx,
                    name=cp.name or f"Point {idx + 1}",
                    col=idx,
                    row=0,
                    x_steps=x_steps,
                    y_steps=y_steps,
                    x_mm=round(x_steps / steps_per_mm, 2),
                    y_mm=round(y_steps / steps_per_mm, 2),
                    zoom=float(max(1.0, min(cp.zoom or 1.0, 5.0))),
                    expected_components=cp.expected_components
                ))
            return scan_points

        # 2. Raster matrix grid mode
        raw_step_points = raster_points(
            x=plan.origin_x_mm,
            y=plan.origin_y_mm,
            columns=plan.columns,
            rows=plan.rows,
            pitch_x=plan.pitch_x_mm,
            pitch_y=plan.pitch_y_mm,
            steps_per_mm=steps_per_mm,
            limits=(effective_limit_x, effective_limit_y)
        )

        scan_points: List[ScanPoint] = []
        idx = 0
        for r in range(plan.rows):
            col_range = range(plan.columns) if r % 2 == 0 else reversed(range(plan.columns))
            for c in col_range:
                pt_step = raw_step_points[idx]
                scan_points.append(ScanPoint(
                    index=idx,
                    name=f"R{r+1}C{c+1}",
                    col=c,
                    row=r,
                    x_steps=pt_step[0],
                    y_steps=pt_step[1],
                    x_mm=round(pt_step[0] / steps_per_mm, 2),
                    y_mm=round(pt_step[1] / steps_per_mm, 2),
                    zoom=1.0
                ))
                idx += 1
        return scan_points

    def start_scan(
        self,
        plan: ScanPlanRequest,
        is_golden_scan: bool = False,
        reference_id: Optional[str] = None,
        conf_thresh: float = 0.25,
        match_dist: float = 50.0,
        fail_on_extra: bool = True,
        imgsz: Optional[int] = None,
        multiframe_enabled: bool = True,
        target_frames: int = 10,
        pass_ratio: float = 0.8
    ) -> AOIRunReport:
        with self._lock:
            # Check without re-locking / deadlock (F01)
            if self.is_running:
                raise RuntimeError("An AOI scan is already in progress.")

            state = machine_service.get_state()
            if not state.connected:
                raise RuntimeError("Machine stage is not connected.")
            if not state.homed:
                raise RuntimeError("Machine stage must be HOMED before starting AOI scan.")
            if not inference_service.is_loaded:
                raise RuntimeError("Inference model is not loaded.")
            if not camera_service.is_active:
                raise RuntimeError("Camera is not active.")
            if state.mode == "serial" and camera_service.is_mock:
                raise RuntimeError("Cannot start production scan: real machine is connected but camera is in simulation/mock mode.")

            points = self.plan_scan(plan)
            if plan.custom_points:
                plan = plan.model_copy(update={
                    "custom_points": [cp.model_copy(update={"reference_image": None}) for cp in plan.custom_points]
                })

            ref_profile: Optional[ReferenceProfile] = None
            if not is_golden_scan and reference_id:
                ref_profile = storage_service.get_reference(reference_id)
                if not ref_profile:
                    raise ValueError(f"Reference profile '{reference_id}' not found.")
                # Verify reference signature compatibility (F09) for grid plans
                if ref_profile.profile_type != "aoi_grid":
                    raise ValueError("Select an AOI grid reference for a scan")
                sig = ref_profile.scan_signature or {}
                if sig.get("resolution") and tuple(sig["resolution"]) != camera_service.resolution:
                    raise ValueError("Reference camera resolution differs from the current camera")
                if sig.get("steps_per_mm") and sig["steps_per_mm"] != machine_service.steps_per_mm:
                    raise ValueError("Reference stage calibration differs from the current machine")
                if plan.plan_mode == "custom" and sig.get("custom_points") != [(p.x_mm,p.y_mm,p.zoom) for p in points] and sig.get("custom_points") != [[p.x_mm,p.y_mm,p.zoom] for p in points]:
                    raise ValueError("Reference custom point positions/zoom differ from this scan")
                if getattr(plan, "plan_mode", "grid") == "grid" and ref_profile.scan_signature:
                    sig = ref_profile.scan_signature
                    if any(abs(float(sig.get(k,getattr(plan,k)))-getattr(plan,k)) > .001 for k in ("origin_x_mm","origin_y_mm")):
                        raise ValueError("Reference origin differs from the scan origin")
                    sig_cols = sig.get("columns")
                    sig_rows = sig.get("rows")
                    sig_pitch_x = sig.get("pitch_x_mm")
                    sig_pitch_y = sig.get("pitch_y_mm")
                    if (sig_cols is not None and sig_cols != plan.columns) or \
                       (sig_rows is not None and sig_rows != plan.rows) or \
                       (sig_pitch_x is not None and abs(sig_pitch_x - plan.pitch_x_mm) > 0.01) or \
                       (sig_pitch_y is not None and abs(sig_pitch_y - plan.pitch_y_mm) > 0.01):
                        raise ValueError(
                            f"Reference grid geometry ({sig_cols}x{sig_rows}, pitch {sig_pitch_x}x{sig_pitch_y}mm) "
                            f"differs from current scan plan ({plan.columns}x{plan.rows}, pitch {plan.pitch_x_mm}x{plan.pitch_y_mm}mm)."
                        )

            run_id = f"aoi_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
            run_folder = RUNS_DIR / run_id
            run_folder.mkdir(parents=True, exist_ok=True)

            report = AOIRunReport(
                id=run_id,
                status="running",
                is_simulation=state.mode == "simulation",
                is_golden_scan=is_golden_scan,
                reference_id=reference_id,
                plan=plan,
                points=points,
                total_points=len(points),
                results=[],
                current_point_index=0
            )

            self._current_run = report
            self._stop_event.clear()
            storage_service.create_run(report)

            self._worker_thread = threading.Thread(
                target=self._scan_worker,
                args=(report, points, run_folder, ref_profile, conf_thresh, match_dist, fail_on_extra, imgsz, multiframe_enabled, target_frames, pass_ratio),
                daemon=True,
                name="AOIScanWorker"
            )
            self._worker_thread.start()
            return report

    def stop_scan(self):
        """Preempt motion, cancel scan sequence, and abort."""
        # Set the stop flag before preempting motion so the worker treats the
        # cancelled MOVE as an abort, not as a scan error.
        self._stop_event.set()
        machine_service.stop()
        with self._lock:
            if self._current_run:
                self._abort_run(self._current_run, "Scan stopped by operator.")
        worker = self._worker_thread
        if worker and worker.is_alive() and threading.current_thread() != worker:
            worker.join(timeout=1.0)

    def _abort_run(self, report: AOIRunReport, message: str):
        """Mark a running scan aborted, persist it and notify clients (idempotent)."""
        self._stop_event.set()
        with self._lock:
            if report.status != "running":
                return
            report.status = "aborted"
            report.completed_at = time.time()
            report.overall_verdict = "REVIEW"
            report.error_message = message
            storage_service.finalize_run(report)
        self._broadcast_progress({
            "event": "aborted",
            "run_id": report.id,
            "message": message,
            "report": report.model_dump()
        })

    def _broadcast_point_event(self, event: str, report: AOIRunReport, pt: ScanPoint, **extra: Any):
        self._broadcast_progress({
            "event": event,
            "run_id": report.id,
            "status": "running",
            "point_index": pt.index,
            "total_points": report.total_points,
            "target_mm": (pt.x_mm, pt.y_mm),
            "zoom": pt.zoom,
            "name": pt.name or f"Point {pt.index + 1}",
            **extra,
            "report": report.model_dump()
        })

    def _scan_worker(
        self,
        report: AOIRunReport,
        points: List[ScanPoint],
        run_folder: Path,
        ref_profile: Optional[ReferenceProfile],
        conf_thresh: float,
        match_dist: float,
        fail_on_extra: bool,
        imgsz: Optional[int] = None,
        multiframe_enabled: bool = True,
        target_frames: int = 10,
        pass_ratio: float = 0.8
    ):
        try:
            self._do_scan(report, points, run_folder, ref_profile, conf_thresh, match_dist, fail_on_extra, imgsz, multiframe_enabled, target_frames, pass_ratio)
        finally:
            with self._lock:
                if self._worker_thread is threading.current_thread():
                    self._worker_thread = None

    def _do_scan(
        self,
        report: AOIRunReport,
        points: List[ScanPoint],
        run_folder: Path,
        ref_profile: Optional[ReferenceProfile],
        conf_thresh: float,
        match_dist: float,
        fail_on_extra: bool,
        imgsz: Optional[int] = None,
        multiframe_enabled: bool = True,
        target_frames: int = 10,
        pass_ratio: float = 0.8
    ):

        logger.info("AOI scan worker started for run %s (%d points)...", report.id, len(points))
        golden_grid_points: Dict[str, List[ReferencePoint]] = {}
        from ..core.security import lease_manager
        was_controlled = lease_manager.get_lease_info().is_controlled

        try:

            for pt in points:
                if self._stop_event.is_set():
                    logger.info("Scan cancelled before point %d.", pt.index)
                    break
                    
                is_controlled = lease_manager.get_lease_info().is_controlled
                if was_controlled and not is_controlled:
                    logger.warning("Operator lease expired during scan. Aborting.")
                    self._abort_run(report, "Operator control lease expired during scan.")
                    break
                was_controlled = is_controlled

                with self._lock:
                    report.current_point_index = pt.index

                self._broadcast_point_event("point_start", report, pt)

                # 1. Move stage to point
                machine_service.move_to_steps(pt.x_steps, pt.y_steps, speed=report.plan.speed)
                move_done_time = time.monotonic()

                if self._stop_event.is_set():
                    break

                self._broadcast_point_event("point_capturing", report, pt)

                # 2. Wait settle interval so stage vibration settles and target is clearly framed and zoomed before shot
                if self._stop_event.wait(report.plan.settle_sec):
                    break
                capture_after = time.monotonic()

                # 3. Check if this point has golden reference components for multi-frame completeness inspection
                exp_comps = getattr(pt, "expected_components", None)
                if not exp_comps and ref_profile:
                    refs = ref_profile.grid_points.get(f"{pt.col}_{pt.row}") or ref_profile.grid_points.get(str(pt.index))
                    if refs:
                        rw,rh = camera_service.resolution
                        exp_comps = reference_components(refs,rw,rh,match_dist)
                use_multiframe = (not report.is_golden_scan) and bool(exp_comps)

                if use_multiframe:
                    actual_frames = max(1, target_frames) if multiframe_enabled else 1
                    pass_th = max(1, math.ceil(actual_frames * pass_ratio))
                    frame_results: List[List[Dict[str, Any]]] = []
                    latest_frame = None
                    last_detections: List[Detection] = []
                    last_speed = {}

                    last_frame_time = capture_after
                    for f_idx in range(actual_frames):
                        if self._stop_event.is_set():
                            break

                        frame_after = last_frame_time
                        try:
                            last_frame_time, cur_f = camera_service.get_fresh_frame(after_timestamp=frame_after, timeout_sec=3.0)
                        except Exception as exc:
                            raise RuntimeError(f"Point {pt.index} Frame {f_idx + 1}: Failed to capture camera frame: {exc}")

                        cur_f = digital_zoom(cur_f, pt.zoom)

                        latest_frame = cur_f
                        h_f, w_f = cur_f.shape[:2]

                        cur_dets, cur_speed = inference_service.predict(cur_f, conf=conf_thresh, imgsz=imgsz)
                        last_detections = cur_dets
                        last_speed = cur_speed

                        frame_dets = normalized_detections(cur_dets,w_f,h_f)
                        frame_results.append(frame_dets)

                        self._broadcast_point_event(
                            "point_frame", report, pt, frame_index=f_idx + 1, target_frames=actual_frames
                        )

                        if f_idx < actual_frames - 1:
                            time.sleep(0.06)

                    if self._stop_event.is_set():
                        break

                    eval_res = evaluate_multiframe_round(
                        expected_components=exp_comps,
                        frame_results=frame_results,
                        target_frames=actual_frames,
                        pass_threshold=pass_th,
                        fail_on_extra=fail_on_extra
                    )

                    verdict: Verdict = eval_res["verdict"]
                    reason = eval_res["reason"]
                    component_eval = eval_res["components"]
                    summary = InspectionSummary(
                        total_refs=len(exp_comps),
                        ok=eval_res["confirmed_count"],
                        missing=eval_res["missing_count"],
                        wrong=eval_res["wrong_count"],
                        extra=eval_res["extra_count"],
                        total_detections=len(last_detections)
                    )

                    raw_filename = f"point_{pt.index:03d}_raw.png"
                    raw_path, raw_url = storage_service.save_image_array(latest_frame, run_folder, raw_filename)

                    annotated = draw_multiframe_annotated_image(latest_frame, component_eval)
                    annotated_filename = f"point_{pt.index:03d}_annotated.png"
                    annotated_path, annotated_url = storage_service.save_image_array(
                        annotated, run_folder, annotated_filename
                    )

                    multiframe_info = {
                        "target_frames": actual_frames,
                        "pass_threshold": pass_th,
                        "pass_ratio": pass_ratio,
                        "total_frames": len(frame_results),
                        "confirmed_count": eval_res["confirmed_count"],
                        "missing_count": eval_res["missing_count"],
                        "wrong_count": eval_res["wrong_count"],
                    }

                    pt_result = AOIPointResult(
                        point_index=pt.index,
                        name=getattr(pt, "name", None) or f"Point {pt.index + 1}",
                        col=pt.col,
                        row=pt.row,
                        x_mm=pt.x_mm,
                        y_mm=pt.y_mm,
                        zoom=getattr(pt, "zoom", 1.0),
                        verdict=verdict,
                        reason=reason,
                        image_path=str(raw_path),
                        annotated_path=str(annotated_path),
                        image_url=raw_url,
                        annotated_url=annotated_url,
                        summary=summary,
                        detections=last_detections,
                        speed_ms=last_speed,
                        component_eval=component_eval,
                        multiframe_info=multiframe_info
                    )
                else:
                    # Single-frame fallback (Golden scan or Grid without template)
                    try:
                        _, frame = camera_service.get_fresh_frame(after_timestamp=capture_after, timeout_sec=3.0)
                    except Exception as exc:
                        raise RuntimeError(f"Point {pt.index}: Failed to capture fresh camera frame: {exc}")

                    frame = digital_zoom(frame, pt.zoom)

                    if self._stop_event.is_set():
                        break

                    # 4. Save raw image
                    raw_filename = f"point_{pt.index:03d}_raw.png"
                    raw_path, raw_url = storage_service.save_image_array(frame, run_folder, raw_filename)

                    # 5. Run inference
                    detections, speed = inference_service.predict(frame, conf=conf_thresh, imgsz=imgsz)

                    if self._stop_event.is_set():
                        break

                    # 6. Evaluate against reference or record golden points
                    pt_key = f"{pt.col}_{pt.row}"
                    if report.is_golden_scan:
                        verdict: Verdict = "REVIEW"
                        reason = "Golden scan baseline point recorded."
                        ref_eval = []
                        recorded_refs = [
                            ReferencePoint(x=d.cx, y=d.cy, label=d.label, tolerance_px=match_dist)
                            for d in detections
                        ]
                        golden_grid_points[pt_key] = recorded_refs
                        summary = InspectionSummary(
                            total_refs=len(recorded_refs),
                            ok=len(recorded_refs),
                            total_detections=len(detections)
                        )
                    else:
                        expected_refs = None
                        if ref_profile:
                            expected_refs = ref_profile.grid_points.get(pt_key) or ref_profile.grid_points.get(str(pt.index))

                        verdict, reason, summary, ref_eval, detections = evaluate_inspection(
                            reference_points=expected_refs,
                            detections=detections,
                            match_dist=match_dist,
                            fail_on_extra=fail_on_extra
                        )

                    # 7. Draw annotated image and save
                    annotated = draw_annotated_image(frame, detections, ref_eval)
                    annotated_filename = f"point_{pt.index:03d}_annotated.png"
                    annotated_path, annotated_url = storage_service.save_image_array(
                        annotated, run_folder, annotated_filename
                    )

                    # 8. Create Point Result
                    pt_result = AOIPointResult(
                        point_index=pt.index,
                        name=getattr(pt, "name", None) or f"Point {pt.index + 1}",
                        col=pt.col,
                        row=pt.row,
                        x_mm=pt.x_mm,
                        y_mm=pt.y_mm,
                        zoom=getattr(pt, "zoom", 1.0),
                        verdict=verdict,
                        reason=reason,
                        image_path=str(raw_path),
                        annotated_path=str(annotated_path),
                        image_url=raw_url,
                        annotated_url=annotated_url,
                        summary=summary,
                        detections=detections,
                        speed_ms=speed
                    )

                with self._lock:
                    if self._stop_event.is_set() or report.status != "running":
                        break
                    report.results.append(pt_result)
                    if verdict == "PASS":
                        report.pass_count += 1
                    elif verdict == "FAIL":
                        report.fail_count += 1
                    elif verdict == "REVIEW":
                        report.review_count += 1
                    else:
                        report.error_count += 1

                    storage_service.update_run_point(report.id, pt_result)
                    storage_service.atomic_save_report_json(report)

                self._broadcast_progress({
                    "event": "point_complete",
                    "run_id": report.id,
                    "point_index": pt.index,
                    "total_points": len(points),
                    "point_result": pt_result.model_dump(),
                    "report": report.model_dump()
                })

            # Check if all completed or aborted
            with self._lock:
                if not self._stop_event.is_set() and len(report.results) == len(points):
                    report.status = "complete"
                    report.completed_at = time.time()
                    if report.is_golden_scan:
                        report.overall_verdict = "REVIEW"
                        # Save new golden profile with scan signature
                        scan_sig = {
                            "origin_x_mm": report.plan.origin_x_mm,
                            "origin_y_mm": report.plan.origin_y_mm,
                            "columns": report.plan.columns,
                            "rows": report.plan.rows,
                            "pitch_x_mm": report.plan.pitch_x_mm,
                            "pitch_y_mm": report.plan.pitch_y_mm,
                            "steps_per_mm": machine_service.steps_per_mm,
                            "model": inference_service.model_path,
                            "resolution": camera_service.resolution,
                            "custom_points": [(p.x_mm,p.y_mm,p.zoom) for p in points] if report.plan.plan_mode == "custom" else None,
                        }
                        new_profile = ReferenceProfile(
                            id=f"ref_golden_{report.id}",
                            name=f"Golden Scan ({time.strftime('%Y-%m-%d %H:%M')})",
                            description=f"Generated from golden scan {report.id} ({len(points)} points)",
                            profile_type="aoi_grid",
                            grid_points=golden_grid_points,
                            scan_signature=scan_sig,
                            image_width=camera_service.resolution[0],
                            image_height=camera_service.resolution[1]
                        )
                        storage_service.save_reference(new_profile)
                        report.reference_id = new_profile.id
                        logger.info("Saved new golden reference profile: %s", new_profile.id)
                    else:
                        if report.fail_count > 0:
                            report.overall_verdict = "FAIL"
                        elif report.review_count > 0:
                            report.overall_verdict = "REVIEW"
                        elif report.error_count > 0:
                            report.overall_verdict = "ERROR"
                        else:
                            report.overall_verdict = "PASS"

                    storage_service.finalize_run(report)
                    self._broadcast_progress({
                        "event": "complete",
                        "run_id": report.id,
                        "overall_verdict": report.overall_verdict,
                        "report": report.model_dump()
                    })

        except Exception as exc:
            if self._stop_event.is_set():
                return
            if was_controlled and not lease_manager.get_lease_info().is_controlled:
                # The motion pump preempts moves when the lease lapses; report that
                # as the abort cause rather than the resulting motion error.
                self._abort_run(report, "Operator control lease expired during scan.")
                return
            logger.error("Scan error on run %s: %s", report.id, exc, exc_info=True)
            with self._lock:
                report.status = "error"
                report.completed_at = time.time()
                report.overall_verdict = "ERROR"
                report.error_message = str(exc)
                storage_service.finalize_run(report)

            self._broadcast_progress({
                "event": "error",
                "run_id": report.id,
                "error": str(exc),
                "report": report.model_dump()
            })


# Global singleton
aoi_scan_service = AOIScanService()
