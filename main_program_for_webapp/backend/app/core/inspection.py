"""Core inspection evaluation and annotation utilities."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np

from .schemas import (
    Detection,
    DetectionStatus,
    InspectionResult,
    InspectionSummary,
    ReferenceEvaluation,
    ReferencePoint,
    ReferenceStatus,
    Verdict,
)

# Visual color palette (Hex and BGR for OpenCV)
CATEGORY_COLORS_HEX = {
    "ic": "#3B82F6",         # blue-500
    "capacitor": "#F59E0B",  # amber-500
    "resistor": "#10B981",   # emerald-500
    "diode": "#8B5CF6",      # purple-500
    "led": "#EC4899",        # pink-500
    "default": "#94A3B8",    # slate-400
}

CLASS_KEYWORDS = {
    "capacitor": ("capacitor", "cap"),
    "resistor": ("resistor", "res"),
    "diode": ("diode",),
    "led": ("led",),
    "ic": ("chip", "sot", "connector", "usb", "sdcard", "xtal", "input", "ic"),
}


def _hex_to_bgr(hex_color: str) -> Tuple[int, int, int]:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return (b, g, r)


CLASS_COLORS_BGR = {k: _hex_to_bgr(v) for k, v in CATEGORY_COLORS_HEX.items()}
STATUS_COLORS_BGR = {
    "ok": _hex_to_bgr("#22C55E"),      # green-500
    "fail": _hex_to_bgr("#EF4444"),    # red-500
    "warn": _hex_to_bgr("#F59E0B"),    # amber-500
}


def _slot_color(status: str) -> Tuple[int, int, int]:
    if status == "confirmed":
        return STATUS_COLORS_BGR["ok"]
    if status == "uncertain":
        return STATUS_COLORS_BGR["warn"]
    return STATUS_COLORS_BGR["fail"]


def digital_zoom(frame: np.ndarray, zoom: float) -> np.ndarray:
    """Center-crop by `zoom` and upscale back to the original size (no-op for zoom <= 1)."""
    if not zoom or zoom <= 1.01:
        return frame
    h, w = frame.shape[:2]
    crop_w, crop_h = max(1, int(w / zoom)), max(1, int(h / zoom))
    x1, y1 = (w - crop_w) // 2, (h - crop_h) // 2
    return cv2.resize(frame[y1:y1 + crop_h, x1:x1 + crop_w], (w, h), interpolation=cv2.INTER_LANCZOS4)


def get_class_color_bgr(label: str) -> Tuple[int, int, int]:
    lowered = str(label).lower()
    for cat, keywords in CLASS_KEYWORDS.items():
        if any(k in lowered for k in keywords):
            return CLASS_COLORS_BGR[cat]
    return CLASS_COLORS_BGR["default"]


def evaluate_inspection(
    reference_points: Optional[List[ReferencePoint | Dict[str, Any]]],
    detections: List[Detection],
    match_dist: float = 50.0,
    fail_on_extra: bool = True
) -> Tuple[Verdict, str, InspectionSummary, List[ReferenceEvaluation], List[Detection]]:
    """Evaluate detected PCB components against a golden reference.
    
    Verdicts:
    - REVIEW: No reference provided (or 0 reference points). Not counted as a defect.
    - PASS: All reference components matched within tolerance and no unexpected extra.
    - FAIL: Missing expected components, wrong component installed, or unexpected extra.
    """
    # Normalized references list
    refs: List[ReferencePoint] = []
    if reference_points:
        for r in reference_points:
            if isinstance(r, ReferencePoint):
                refs.append(r)
            elif isinstance(r, dict):
                refs.append(ReferencePoint(
                    id=r.get("id"),
                    x=float(r["x"]),
                    y=float(r["y"]),
                    label=str(r["label"]),
                    tolerance_px=float(r["tolerance_px"]) if r.get("tolerance_px") is not None else None
                ))

    # Case 1: No Reference provided -> REVIEW
    if not refs:
        summary = InspectionSummary(
            total_refs=0,
            ok=0,
            missing=0,
            wrong=0,
            extra=len(detections),
            total_detections=len(detections)
        )
        for det in detections:
            det.status = "EXTRA"
        return (
            "REVIEW",
            "No reference profile loaded (inspection requires manual or visual review).",
            summary,
            [],
            detections
        )

    # Case 2: Matching against reference points
    unmatched_det_indices = set(range(len(detections)))
    reference_eval: List[ReferenceEvaluation] = []
    ok_count = 0
    missing_count = 0
    wrong_count = 0

    for idx, ref in enumerate(refs):
        tol = ref.tolerance_px if ref.tolerance_px is not None else match_dist
        best_det_idx = None
        best_dist = float("inf")

        for det_idx in unmatched_det_indices:
            det = detections[det_idx]
            dist = math.hypot(ref.x - det.cx, ref.y - det.cy)
            if dist < best_dist:
                best_dist = dist
                best_det_idx = det_idx

        if best_det_idx is not None and best_dist <= tol:
            det = detections[best_det_idx]
            unmatched_det_indices.remove(best_det_idx)
            is_label_match = det.label.strip().lower() == ref.label.strip().lower()

            if is_label_match:
                status: ReferenceStatus = "OK"
                det.status = "OK"
                det.matched_ref_index = idx
                ok_count += 1
            else:
                status = "WRONG"
                det.status = "WRONG"
                det.matched_ref_index = idx
                wrong_count += 1

            reference_eval.append(ReferenceEvaluation(
                ref_index=idx,
                ref=ref,
                status=status,
                distance=round(best_dist, 1),
                det=det
            ))
        else:
            missing_count += 1
            reference_eval.append(ReferenceEvaluation(
                ref_index=idx,
                ref=ref,
                status="MISSING",
                distance=None,
                det=None
            ))

    # Mark remaining detections as EXTRA
    extra_count = len(unmatched_det_indices)
    for det_idx in unmatched_det_indices:
        detections[det_idx].status = "EXTRA"

    # Verdict derivation
    if missing_count > 0 or wrong_count > 0:
        verdict: Verdict = "FAIL"
        reasons = []
        if missing_count > 0:
            reasons.append(f"{missing_count} missing component(s)")
        if wrong_count > 0:
            reasons.append(f"{wrong_count} wrong component(s)")
        reason = "Defect detected: " + ", ".join(reasons)
    elif extra_count > 0 and fail_on_extra:
        verdict = "FAIL"
        reason = f"Defect detected: {extra_count} unexpected extra component(s)"
    else:
        verdict = "PASS"
        reason = "All reference components verified successfully."

    summary = InspectionSummary(
        total_refs=len(refs),
        ok=ok_count,
        missing=missing_count,
        wrong=wrong_count,
        extra=extra_count,
        total_detections=len(detections)
    )

    return (verdict, reason, summary, reference_eval, detections)


def draw_annotated_image(
    image: np.ndarray,
    detections: List[Detection],
    reference_eval: List[ReferenceEvaluation],
    show_labels: bool = True
) -> np.ndarray:
    """Draw bounding boxes and reference markers onto an image (BGR)."""
    annotated = image.copy()
    overlay = annotated.copy()

    # Draw semi-transparent fills for detections
    for det in detections:
        x1, y1, x2, y2 = (int(v) for v in det.box)
        color = get_class_color_bgr(det.label)
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)

    cv2.addWeighted(overlay, 0.25, annotated, 0.75, 0, dst=annotated)

    # Draw box borders and labels
    for det in detections:
        x1, y1, x2, y2 = (int(v) for v in det.box)
        color = get_class_color_bgr(det.label)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        if show_labels:
            label_text = f"{det.label} {int(det.conf * 100)}%"
            t_size = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)[0]
            cv2.rectangle(annotated, (x1, max(0, y1 - 18)), (x1 + t_size[0] + 4, max(0, y1)), color, -1)
            cv2.putText(
                annotated,
                label_text,
                (x1 + 2, max(12, y1 - 4)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 255, 255),
                1,
                cv2.LINE_AA
            )

    # Draw reference target points (OK=Green, WRONG/MISSING=Red)
    for entry in reference_eval:
        rx, ry = int(entry.ref.x), int(entry.ref.y)
        color = STATUS_COLORS_BGR["ok"] if entry.status == "OK" else STATUS_COLORS_BGR["fail"]

        cv2.circle(annotated, (rx, ry), 8, color, 2, cv2.LINE_AA)
        cv2.circle(annotated, (rx, ry), 2, color, -1, cv2.LINE_AA)

        if entry.status == "MISSING":
            # Draw cross for missing
            cv2.line(annotated, (rx - 6, ry - 6), (rx + 6, ry + 6), color, 2)
            cv2.line(annotated, (rx - 6, ry + 6), (rx + 6, ry - 6), color, 2)

    return annotated


def draw_multiframe_annotated_image(
    image: np.ndarray,
    component_eval: List[Dict[str, Any]],
    show_labels: bool = True
) -> np.ndarray:
    """Draw component completeness boxes (Confirmed=green, MISSING=red, WRONG=red/purple) on image."""
    annotated = image.copy()
    h, w = annotated.shape[:2]
    overlay = annotated.copy()

    # Semi-transparent box fills
    for item in component_eval:
        exp = item.get("expected", {})
        bbox = exp.get("box", exp.get("bbox", [0, 0, 0, 0]))
        x1 = int(round(max(0.0, min(1.0, bbox[0])) * w))
        y1 = int(round(max(0.0, min(1.0, bbox[1])) * h))
        x2 = int(round(max(0.0, min(1.0, bbox[2])) * w))
        y2 = int(round(max(0.0, min(1.0, bbox[3])) * h))

        color = _slot_color(item.get("status", "missing"))
        cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)

    cv2.addWeighted(overlay, 0.22, annotated, 0.78, 0, dst=annotated)

    # Box borders and text badges
    for item in component_eval:
        exp = item.get("expected", {})
        cid = exp.get("id", "P")
        cname = exp.get("name", "component")
        hits = item.get("hits", 0)
        target = item.get("target_frames", 10)
        bbox = exp.get("box", exp.get("bbox", [0, 0, 0, 0]))
        x1 = int(round(max(0.0, min(1.0, bbox[0])) * w))
        y1 = int(round(max(0.0, min(1.0, bbox[1])) * h))
        x2 = int(round(max(0.0, min(1.0, bbox[2])) * w))
        y2 = int(round(max(0.0, min(1.0, bbox[3])) * h))

        status = item.get("status", "missing")
        color = _slot_color(status)
        if status == "confirmed":
            label = f"{cid} {cname} ({hits}/{target}F)"
        elif status == "wrong":
            label = f"{cid} WRONG ({item.get('wrong_label', 'err')})"
        elif status == "uncertain":
            label = f"{cid} ? ({hits}/{target}F)"
        else:
            label = f"{cid} MISSING ({hits}/{target}F)"

        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

        if show_labels:
            t_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)[0]
            bg_y1 = max(0, y1 - 20)
            bg_y2 = max(20, y1)
            cv2.rectangle(annotated, (x1, bg_y1), (x1 + t_size[0] + 6, bg_y2), color, -1)
            cv2.putText(
                annotated,
                label,
                (x1 + 3, max(14, y1 - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 0, 0) if status in ("confirmed", "uncertain") else (255, 255, 255),
                1,
                cv2.LINE_AA
            )

    return annotated


def box_iou(box1: List[float] | Tuple[float, ...], box2: List[float] | Tuple[float, ...]) -> float:
    """Compute Intersection over Union between two bounding boxes [x1, y1, x2, y2]."""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area1 = max(0.0, box1[2] - box1[0]) * max(0.0, box1[3] - box1[1])
    area2 = max(0.0, box2[2] - box2[0]) * max(0.0, box2[3] - box2[1])
    union = area1 + area2 - intersection

    return intersection / union if union > 0 else 0.0


def normalized_detections(detections, width, height):
    return [{"label": d.label, "conf": d.conf, "box": [d.box[0]/width, d.box[1]/height, d.box[2]/width, d.box[3]/height]} for d in detections]


def reference_components(points, width, height, match_dist=50.0):
    return [{"id": p.id or f"P{i+1}", "name": p.label,
             "point": [p.x/width, p.y/height],
             "tolerance": [(p.tolerance_px or match_dist)/width, (p.tolerance_px or match_dist)/height],
             "box": [(p.x-(p.tolerance_px or match_dist))/width, (p.y-(p.tolerance_px or match_dist))/height,
                     (p.x+(p.tolerance_px or match_dist))/width, (p.y+(p.tolerance_px or match_dist))/height]}
            for i,p in enumerate(points)]


def component_overlap(expected, box):
    if "point" in expected:
        x,y = expected["point"]
        tx,ty = expected["tolerance"]
        distance = math.hypot(((box[0]+box[2])/2-x)/tx, ((box[1]+box[3])/2-y)/ty)
        return 1/(1+distance) if distance <= 1 else 0.0
    return box_iou(expected.get("box", expected.get("bbox", [0,0,0,0])), box)


def match_frame_detections(
    expected_components: List[Dict[str, Any]],
    frame_detections: List[Dict[str, Any]],
    min_iou: float = 0.3
) -> Dict[str, Any]:
    """Greedy bipartite matching of detected boxes in a frame to expected reference components."""
    pairs = []
    for ei, exp in enumerate(expected_components):
        exp_label = str(exp.get("label", exp.get("name", ""))).strip().lower()
        exp_box = exp.get("box", exp.get("bbox", [0, 0, 0, 0]))
        for bi, det in enumerate(frame_detections):
            det_label = str(det.get("label", det.get("name", ""))).strip().lower()
            det_box = det.get("box", det.get("bbox", [0, 0, 0, 0]))
            if exp_label and exp_label == det_label:
                iou = component_overlap(exp, det_box)
                if iou >= min_iou:
                    pairs.append((iou, ei, bi))
    pairs.sort(key=lambda x: x[0], reverse=True)

    matched_expected = set()
    used_detections = set()
    matches = []
    for iou, ei, bi in pairs:
        if ei not in matched_expected and bi not in used_detections:
            matched_expected.add(ei)
            used_detections.add(bi)
            matches.append({"expected_index": ei, "box_index": bi, "iou": iou})

    # Detect wrong class substitutions
    wrong_matches = []
    for ei, exp in enumerate(expected_components):
        if ei in matched_expected:
            continue
        exp_box = exp.get("box", exp.get("bbox", [0, 0, 0, 0]))
        best_bi = None
        best_iou = 0.0
        for bi, det in enumerate(frame_detections):
            if bi in used_detections:
                continue
            det_box = det.get("box", det.get("bbox", [0, 0, 0, 0]))
            iou = component_overlap(exp, det_box)
            if iou >= min_iou and iou > best_iou:
                best_iou = iou
                best_bi = bi
        if best_bi is not None:
            used_detections.add(best_bi)
            wrong_matches.append({
                "expected_index": ei,
                "box_index": best_bi,
                "expected_label": exp.get("label", exp.get("name", "")),
                "found_label": frame_detections[best_bi].get("label", frame_detections[best_bi].get("name", "")),
                "iou": best_iou,
            })

    unmatched_detections = [bi for bi in range(len(frame_detections)) if bi not in used_detections]
    return {
        "matched_expected": matched_expected,
        "matches": matches,
        "wrong_matches": wrong_matches,
        "unmatched_detections": unmatched_detections,
    }


def slot_status(hits: int, target_frames: int = 10, pass_threshold: Optional[int] = None) -> str:
    """Status of a component slot based on hit accumulation across N inspection frames."""
    target = max(1, target_frames)
    pass_th = pass_threshold if pass_threshold is not None else max(1, math.ceil(target * 0.8))
    uncertain_th = max(1, math.floor(target * 0.4))
    if hits >= pass_th:
        return "confirmed"
    elif hits >= uncertain_th:
        return "uncertain"
    else:
        return "suspect"


def evaluate_multiframe_round(
    expected_components: List[Dict[str, Any]],
    frame_results: List[List[Dict[str, Any]]],
    target_frames: int = 10,
    pass_threshold: Optional[int] = None,
    fail_on_extra: bool = False
) -> Dict[str, Any]:
    """Evaluates multi-frame completeness across all N frames."""
    total_frames = len(frame_results)
    target = max(1, target_frames)
    pass_th = pass_threshold if pass_threshold is not None else max(1, math.ceil(target * 0.8))

    hits = [0] * len(expected_components)
    wrong_counts = [0] * len(expected_components)
    wrong_found_labels = [{} for _ in expected_components]
    extra_detections_all = []

    for f_idx, detections in enumerate(frame_results):
        m = match_frame_detections(expected_components, detections)
        for ei in m["matched_expected"]:
            hits[ei] += 1
        for w in m["wrong_matches"]:
            ei = w["expected_index"]
            wrong_counts[ei] += 1
            fl = w["found_label"]
            wrong_found_labels[ei][fl] = wrong_found_labels[ei].get(fl, 0) + 1
        for bi in m["unmatched_detections"]:
            extra_detections_all.append(detections[bi])

    component_eval = []
    has_missing = False
    has_wrong = False
    has_uncertain = False

    for i, exp in enumerate(expected_components):
        h = hits[i]
        status = slot_status(h, target_frames, pass_th)
        wrong_label = None
        if wrong_counts[i] >= math.ceil(target * 0.5):
            most_freq_wrong = max(wrong_found_labels[i].items(), key=lambda x: x[1])[0]
            status = "wrong"
            wrong_label = most_freq_wrong
            has_wrong = True
        elif status == "suspect":
            status = "missing"
            has_missing = True
        elif status == "uncertain":
            status = "uncertain"
            has_uncertain = True

        component_eval.append({
            "expected": exp,
            "hits": h,
            "total_frames": total_frames,
            "target_frames": target,
            "pass_threshold": pass_th,
            "status": status,
            "wrong_label": wrong_label,
        })

    extra_count = len(extra_detections_all)

    if total_frames != target:
        verdict = "REVIEW"
        reason = f"Incomplete round: {total_frames}/{target} fresh frames captured"
    elif not expected_components:
        verdict = "REVIEW"
        reason = "No reference components defined"
    elif has_wrong:
        verdict = "FAIL"
        reason = f"Wrong class detected ({sum(1 for c in component_eval if c['status'] == 'wrong')} components)"
    elif has_missing:
        verdict = "FAIL"
        reason = f"Missing components ({sum(1 for c in component_eval if c['status'] == 'missing')} components below {pass_th}/{target} frames)"
    elif has_uncertain:
        verdict = "REVIEW"
        uncertain_th = max(1, math.floor(target * 0.4))
        reason = f"Uncertain detections ({sum(1 for c in component_eval if c['status'] == 'uncertain')} components in {uncertain_th}-{pass_th-1}/{target} frames)"
    elif fail_on_extra and extra_count > 0:
        verdict = "FAIL"
        reason = f"Unexpected components in inspection frames ({extra_count} observations)"
    else:
        verdict = "PASS"
        reason = f"All {len(expected_components)} expected components confirmed (>= {pass_th}/{target} frames)"

    return {
        "verdict": verdict,
        "reason": reason,
        "target_frames": target,
        "pass_threshold": pass_th,
        "frames_inspected": total_frames,
        "components": component_eval,
        "total_expected": len(expected_components),
        "confirmed_count": sum(1 for c in component_eval if c["status"] == "confirmed"),
        "missing_count": sum(1 for c in component_eval if c["status"] == "missing"),
        "wrong_count": sum(1 for c in component_eval if c["status"] == "wrong"),
        "uncertain_count": sum(1 for c in component_eval if c["status"] == "uncertain"),
        "extra_count": extra_count,
    }
