import math

import cv2


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
            color = (50, 205, 50)
            label = f"{ref['label']} OK"
        elif status == "WRONG":
            color = (0, 165, 255)
            found = entry["det"]["label"] if entry["det"] else "none"
            label = f"{ref['label']}!= {found}"
        else:
            color = (0, 0, 255)
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
