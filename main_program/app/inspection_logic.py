import math

import cv2

# ── Category colors (Clean Industrial Dashboard palette), BGR order for OpenCV ──
_HEX_COLORS = {
    "ic": "#3B82F6",        # blue-500   — chips, connectors, sockets
    "capacitor": "#F59E0B", # amber-500
    "resistor": "#10B981",  # emerald-500
    "default": "#94A3B8",   # slate-400  — everything else
}

_CLASS_KEYWORDS = {
    "capacitor": ("capacitor",),
    "resistor": ("resistor",),
    "ic": ("chip", "sot", "connector", "usb", "sdcard", "xtal", "input"),
}


def _hex_to_bgr(hex_color):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return (b, g, r)


CLASS_COLORS_BGR = {key: _hex_to_bgr(value) for key, value in _HEX_COLORS.items()}


def class_color(label):
    """Map a YOLO class label to a category color (BGR) for the detection overlay."""
    lowered = str(label).lower()
    for category, keywords in _CLASS_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return CLASS_COLORS_BGR[category]
    return CLASS_COLORS_BGR["default"]


def draw_detections_overlay(frame, detections, selected_index=None, thickness=2, alpha=0.30):
    """Layer 2 of the viewport: thin, semi-transparent, class-colored bounding boxes
    for every raw YOLO detection. No confidence/label text is baked in here — that
    detail lives in the contextual side panel once a box is clicked (see
    detection_status_map / the GUI's select_detection_at)."""
    if not detections:
        return
    overlay = frame.copy()
    for det in detections:
        x1, y1, x2, y2 = (int(v) for v in det["box"])
        cv2.rectangle(overlay, (x1, y1), (x2, y2), class_color(det["label"]), -1)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, dst=frame)

    for idx, det in enumerate(detections):
        x1, y1, x2, y2 = (int(v) for v in det["box"])
        color = class_color(det["label"])
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
        if idx == selected_index:
            cv2.rectangle(frame, (x1 - 3, y1 - 3), (x2 + 3, y2 + 3), (255, 255, 255), 2)


def detection_status_map(inspection_result):
    """id(detection) -> status ('OK'|'WRONG'|'EXTRA'), for labelling a raw detection
    in the contextual panel without re-deriving the match against references."""
    status_map = {}
    for entry in inspection_result.get("reference_eval", []):
        det = entry.get("det")
        if det is not None:
            status_map[id(det)] = entry["status"]
    for det in inspection_result.get("extra", []):
        status_map[id(det)] = "EXTRA"
    return status_map


def evaluate_inspection(reference_points, detections, match_dist, fail_on_extra):
    if not reference_points:
        return {
            "verdict": "FAIL",
            "reason": "No reference profile loaded.",
            "ok": 0,
            "missing": [],
            "wrong": [],
            "extra": detections,
            "reference_eval": [],
            "total_refs": 0,
        }

    unmatched_det_indexes = set(range(len(detections)))
    reference_eval = []
    missing = []
    wrong = []
    ok_count = 0

    for ref in reference_points:
        best_idx = None
        best_dist = float("inf")
        for idx in unmatched_det_indexes:
            det = detections[idx]
            dist = math.hypot(ref["x"] - det["x"], ref["y"] - det["y"])
            if dist < best_dist:
                best_dist = dist
                best_idx = idx

        if best_idx is not None and best_dist <= match_dist:
            det = detections[best_idx]
            unmatched_det_indexes.remove(best_idx)
            if det["label"] == ref["label"]:
                ok_count += 1
                reference_eval.append({"ref": ref, "det": det, "status": "OK", "distance": best_dist})
            else:
                wrong.append({"ref": ref, "det": det, "distance": best_dist})
                reference_eval.append({"ref": ref, "det": det, "status": "WRONG", "distance": best_dist})
        else:
            missing.append(ref)
            reference_eval.append({"ref": ref, "det": None, "status": "MISSING", "distance": None})

    extra = [detections[idx] for idx in sorted(unmatched_det_indexes)]

    fail_reasons = []
    if missing:
        fail_reasons.append(f"Missing {len(missing)}")
    if wrong:
        fail_reasons.append(f"Wrong class {len(wrong)}")
    if fail_on_extra and extra:
        fail_reasons.append(f"Extra {len(extra)}")

    verdict = "PASS" if not fail_reasons else "FAIL"
    reason = "All expected components matched." if verdict == "PASS" else ", ".join(fail_reasons)

    return {
        "verdict": verdict,
        "reason": reason,
        "ok": ok_count,
        "missing": missing,
        "wrong": wrong,
        "extra": extra,
        "reference_eval": reference_eval,
        "total_refs": len(reference_points),
    }


def draw_reference_overlay(frame, inspection_result, show_labels):
    for entry in inspection_result["reference_eval"]:
        ref = entry["ref"]
        rx, ry = int(ref["x"]), int(ref["y"])
        status = entry["status"]
        if status == "OK":
            color = _hex_to_bgr("#10B981")  # emerald-500
            label = f"{ref['label']} OK"
        elif status == "WRONG":
            color = _hex_to_bgr("#EF4444")  # red-500
            found = entry["det"]["label"] if entry["det"] else "none"
            label = f"{ref['label']}!= {found}"
        else:
            color = _hex_to_bgr("#EF4444")  # red-500
            label = f"{ref['label']} MISS"

        cv2.circle(frame, (rx, ry), 14, color, 2)
        cv2.circle(frame, (rx, ry), 3, color, -1)
        if show_labels:
            cv2.putText(
                frame,
                label,
                (rx + 10, ry - 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                color,
                1,
                cv2.LINE_AA,
            )


def box_iou(box_a, box_b):
    """Calculate Intersection over Union (IoU) between two bounding boxes (x1, y1, x2, y2)."""
    xa1, ya1, xa2, ya2 = [float(v) for v in box_a]
    xb1, yb1, xb2, yb2 = [float(v) for v in box_b]
    xi1 = max(xa1, xb1)
    yi1 = max(ya1, yb1)
    xi2 = min(xa2, xb2)
    yi2 = min(ya2, yb2)
    inter_w = max(0.0, xi2 - xi1)
    inter_h = max(0.0, yi2 - yi1)
    inter_area = inter_w * inter_h
    area_a = max(0.0, xa2 - xa1) * max(0.0, ya2 - ya1)
    area_b = max(0.0, xb2 - xb1) * max(0.0, yb2 - yb1)
    union_area = area_a + area_b - inter_area
    if union_area <= 0:
        return 0.0
    return inter_area / union_area


def match_frame_detections(expected_components, frame_detections, min_iou=0.3):
    """
    Match expected reference components with detected objects in a single frame.
    Uses greedy bipartite matching prioritizing highest IoU for identical class names.
    Also detects WRONG class (high overlap with different label) and unmatched extra boxes.
    """
    pairs = []
    for ei, exp in enumerate(expected_components):
        exp_label = exp["label"].strip().lower()
        for bi, det in enumerate(frame_detections):
            det_label = det["label"].strip().lower()
            if exp_label == det_label:
                iou = box_iou(exp["box"], det["box"])
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
        best_bi = None
        best_iou = 0.0
        for bi, det in enumerate(frame_detections):
            if bi in used_detections:
                continue
            iou = box_iou(exp["box"], det["box"])
            if iou >= min_iou and iou > best_iou:
                best_iou = iou
                best_bi = bi
        if best_bi is not None:
            used_detections.add(best_bi)
            wrong_matches.append({
                "expected_index": ei,
                "box_index": best_bi,
                "expected_label": exp["label"],
                "found_label": frame_detections[best_bi]["label"],
                "iou": best_iou,
            })

    unmatched_detections = [bi for bi in range(len(frame_detections)) if bi not in used_detections]
    return {
        "matched_expected": matched_expected,
        "matches": matches,
        "wrong_matches": wrong_matches,
        "unmatched_detections": unmatched_detections,
    }


def slot_status(hits, target_frames=10, pass_threshold=None):
    """
    Status of a component slot based on hit accumulation across N inspection frames.
    Consistent with web BoardInspection logic:
    - hits >= pass_threshold (default ceil(target * 0.8)) -> confirmed (OK)
    - hits >= uncertain_threshold (default floor(target * 0.4)) -> uncertain (WARN)
    - hits < uncertain_threshold -> suspect (MISSING)
    """
    target = max(1, target_frames)
    pass_th = pass_threshold if pass_threshold is not None else max(1, math.ceil(target * 0.8))
    uncertain_th = max(1, math.floor(target * 0.4))
    if hits >= pass_th:
        return "confirmed"
    elif hits >= uncertain_th:
        return "uncertain"
    else:
        return "suspect"


def evaluate_multiframe_round(expected_components, frame_results, target_frames=10, pass_threshold=None):
    """
    Evaluates multi-frame completeness across all N frames for a given PCB inspection position.
    Returns completeness metrics, component-by-component hits, and PASS/FAIL/REVIEW verdict.
    """
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
    has_extra = extra_count >= math.ceil(target * 0.5)

    if not expected_components:
        verdict = "REVIEW"
        reason = "No reference components defined for this position"
    elif has_wrong:
        verdict = "FAIL"
        reason = f"Wrong class detected ({sum(1 for c in component_eval if c['status'] == 'wrong')} components)"
    elif has_missing:
        verdict = "FAIL"
        reason = f"Missing components ({sum(1 for c in component_eval if c['status'] == 'missing')} components below {pass_th}/{target} frames)"
    elif has_uncertain:
        verdict = "REVIEW"
        reason = f"Uncertain detections ({sum(1 for c in component_eval if c['status'] == 'uncertain')} components in 4-{pass_th-1} frames)"
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
        "has_extra": has_extra,
    }


def draw_multiframe_overlay(frame, multiframe_result):
    """
    Renders high-visibility bounding boxes with component label, hit stats [hits/target],
    and status badge, along with a top summary banner.
    """
    status_colors = {
        "confirmed": _hex_to_bgr("#10B981"),  # emerald-500
        "uncertain": _hex_to_bgr("#F59E0B"),  # amber-500
        "missing": _hex_to_bgr("#EF4444"),    # rose-500
        "wrong": _hex_to_bgr("#EF4444"),      # rose-500
        "extra": _hex_to_bgr("#F97316"),      # orange-500
    }

    h, w = frame.shape[:2]

    # Draw component boxes and hit tags
    for comp in multiframe_result.get("components", []):
        exp = comp["expected"]
        status = comp.get("status", "confirmed")
        hits = comp.get("hits", 0)
        target = comp.get("target_frames", 10)
        color = status_colors.get(status, (200, 200, 200))

        box = [int(v) for v in exp["box"]]
        x1, y1, x2, y2 = box

        # Bounding box
        thickness = 2
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)

        # Text label
        label = exp.get("label", "comp")
        if status == "confirmed":
            tag = f"{label} [{hits}/{target}] OK"
        elif status == "missing":
            tag = f"{label} [{hits}/{target}] MISSING"
        elif status == "wrong":
            tag = f"{label}!={comp.get('wrong_label', '?')} [{hits}/{target}]"
        elif status == "uncertain":
            tag = f"{label} [{hits}/{target}] WARN"
        else:
            tag = f"{label} [{hits}/{target}]"

        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.45
        (tw, th), baseline = cv2.getTextSize(tag, font, font_scale, 1)

        # Draw background pill for tag (avoid going off image boundary)
        if y1 - th - 8 < 0:
            tag_y1 = y1
            tag_y2 = min(h, y1 + th + 8)
            text_y = y1 + th + 4
        else:
            tag_y1 = max(0, y1 - th - 8)
            tag_y2 = y1
            text_y = y1 - 4

        tag_x1 = max(0, x1)
        tag_x2 = min(w, x1 + tw + 8)

        cv2.rectangle(frame, (tag_x1, tag_y1), (tag_x2, tag_y2), (18, 20, 24), -1)
        cv2.rectangle(frame, (tag_x1, tag_y1), (tag_x2, tag_y2), color, 1)
        cv2.putText(frame, tag, (tag_x1 + 4, text_y), font, font_scale, color, 1, cv2.LINE_AA)

    # Top summary banner
    verdict = multiframe_result.get("verdict", "PASS")
    banner_color = status_colors.get(
        "confirmed" if verdict == "PASS" else "missing" if verdict == "FAIL" else "uncertain"
    )
    target = multiframe_result.get("target_frames", 10)
    confirmed = multiframe_result.get("confirmed_count", 0)
    total = multiframe_result.get("total_expected", 0)

    if verdict == "PASS":
        banner_text = f"PASS [{target}F] · {confirmed}/{total} COMPONENTS CONFIRMED"
    elif verdict == "FAIL":
        missing = multiframe_result.get("missing_count", 0)
        wrong = multiframe_result.get("wrong_count", 0)
        reasons = []
        if missing:
            reasons.append(f"{missing} MISSING")
        if wrong:
            reasons.append(f"{wrong} WRONG")
        banner_text = f"FAIL [{target}F] · {', '.join(reasons)} · {confirmed}/{total} OK"
    else:
        banner_text = f"REVIEW [{target}F] · {multiframe_result.get('reason', 'Review required')}"

    # Draw semi-transparent header bar
    font = cv2.FONT_HERSHEY_SIMPLEX
    (bw, bh), _ = cv2.getTextSize(banner_text, font, 0.55, 1)
    bx1, by1 = 12, 12
    bx2, by2 = min(w - 12, bx1 + bw + 20), min(h - 12, by1 + bh + 14)

    overlay = frame.copy()
    cv2.rectangle(overlay, (bx1, by1), (bx2, by2), (15, 17, 23), -1)
    cv2.addWeighted(overlay, 0.85, frame, 0.15, 0, frame)
    cv2.rectangle(frame, (bx1, by1), (bx2, by2), banner_color, 2)
    cv2.putText(frame, banner_text, (bx1 + 10, by2 - 8), font, 0.55, banner_color, 1, cv2.LINE_AA)

