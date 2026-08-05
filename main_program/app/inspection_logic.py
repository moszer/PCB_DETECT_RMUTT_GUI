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
