"""Certify benchmarked models against a fixed defect test set before serial AOI scans.

Run: python -m app.quality_gate certify data/benchmarks/<report>.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from .config import STORAGE_DIR

APPROVAL_FILE = STORAGE_DIR / "model_approvals.json"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def evaluate(report: dict[str, Any], min_map50: float, min_recall: float, min_class_recall: float) -> list[str]:
    """Return reasons the benchmark fails the station acceptance criteria."""
    metric = report.get("map") or {}
    settings = report.get("settings") or {}
    errors = []
    if settings.get("split") != "test" or not settings.get("data"):
        errors.append("A labeled, frozen test split is required")
    if not metric.get("per_class"):
        errors.append("Per-class validation results are required")
    expected = set(metric.get("expected_classes") or [])
    if not expected:
        errors.append("Expected dataset classes are required")
    for name in sorted(expected - set(metric.get("per_class") or {})):
        errors.append(f"No test results for class {name}")
    if float(metric.get("map50") or 0) < min_map50:
        errors.append(f"mAP50 below {min_map50}%")
    if float(metric.get("recall") or 0) < min_recall:
        errors.append(f"Overall recall below {min_recall}%")
    for name, values in metric.get("per_class", {}).items():
        if float(values.get("recall") or 0) < min_class_recall:
            errors.append(f"Recall for {name} below {min_class_recall}%")
    return errors


def certify(report_path: Path, min_map50: float, min_recall: float, min_class_recall: float) -> dict[str, Any]:
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    errors = evaluate(report, min_map50, min_recall, min_class_recall)
    if errors:
        raise ValueError("Model failed acceptance: " + "; ".join(errors))
    path = Path(report["system"]["model"]["path"])
    if not path.is_file():
        raise FileNotFoundError(f"Model weights not found: {path}")
    digest = file_sha256(path)
    recorded_hash = report["system"]["model"].get("sha256") or ""
    if len(recorded_hash) < 16 or not digest.startswith(recorded_hash):
        raise ValueError("Model weights changed since benchmark")
    record = {
        "sha256": digest, "model": str(path.resolve()), "approved_at": time.time(),
        "benchmark": str(Path(report_path).resolve()), "dataset": report["settings"]["data"],
        "criteria": {"min_map50": min_map50, "min_recall": min_recall, "min_class_recall": min_class_recall},
        "metrics": report["map"],
    }
    approvals = json.loads(APPROVAL_FILE.read_text()) if APPROVAL_FILE.is_file() else {}
    approvals[digest] = record
    temporary = APPROVAL_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(approvals, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(APPROVAL_FILE)
    return record


def require_approved(model_path: str | None) -> None:
    """Raise if the loaded model is not certified for a serial hardware scan."""
    if os.environ.get("PCB_REQUIRE_MODEL_APPROVAL", "1") != "1":
        return
    if not model_path or not Path(model_path).is_file():
        raise ValueError("No loaded model weights to approve")
    digest = file_sha256(Path(model_path))
    approvals = json.loads(APPROVAL_FILE.read_text()) if APPROVAL_FILE.is_file() else {}
    if digest not in approvals:
        raise ValueError("Model is not approved for hardware scans. Run a test-set benchmark and certify it first.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["certify"])
    parser.add_argument("report", type=Path)
    parser.add_argument("--min-map50", type=float, required=True)
    parser.add_argument("--min-recall", type=float, required=True)
    parser.add_argument("--min-class-recall", type=float, required=True)
    args = parser.parse_args()
    if any(not 0 <= value <= 100 for value in (args.min_map50, args.min_recall, args.min_class_recall)):
        parser.error("Thresholds must be between 0 and 100")
    print(json.dumps(certify(args.report, args.min_map50, args.min_recall, args.min_class_recall), indent=2))


if __name__ == "__main__":
    main()
