"""Benchmark and performance report for comparing machines (thesis table 4.13).

Benchmark: the same images, N rounds after a warm-up, timing every inference; optionally mAP50
on a dataset split (same data.yaml on every machine). Runs with the station's loaded model
from the web page, or standalone:

    cd backend && venv/bin/python -m app.services.benchmark --data /path/data.yaml --rounds 3

Report: this machine's column of the table, from the benchmark and from real scans (scan
time per board; accuracy / F1 from boards whose real condition was marked in History).
"""
from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import cv2
import yaml

from ..config import REPO_ROOT
from .perf_log import BENCH_DIR, system_info

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
MAX_IMAGES = 200


class BenchmarkError(RuntimeError):
    pass


def _stats(values: List[float]) -> Optional[Dict[str, float]]:
    if not values:
        return None
    vs = sorted(values)
    return {
        "mean": round(statistics.fmean(vs), 2),
        "std": round(statistics.pstdev(vs), 2),
        "median": round(statistics.median(vs), 2),
        "p95": round(vs[min(len(vs) - 1, int(round(0.95 * (len(vs) - 1))))], 2),
        "min": round(vs[0], 2),
        "max": round(vs[-1], 2),
        "n": len(vs),
    }


def dataset_images(data_yaml: str, split: str) -> List[Path]:
    """Image files of a YOLO dataset split (as data.yaml defines it)."""
    path = Path(data_yaml).expanduser()
    if not path.is_file():
        raise BenchmarkError(f"ไม่พบไฟล์ {data_yaml}")
    cfg = yaml.safe_load(path.read_text()) or {}
    entry = cfg.get(split) or (cfg.get("val") if split == "test" else None)
    if not entry:
        raise BenchmarkError(f"data.yaml ไม่มีชุด '{split}'")
    base = Path(cfg.get("path") or path.parent)
    if not base.is_absolute():
        base = (path.parent / base).resolve()
    images: List[Path] = []
    for item in entry if isinstance(entry, list) else [entry]:
        p = Path(item)
        if not p.is_absolute():
            raw = str(item)
            p = (base / raw).resolve()
            if not p.exists() and raw.startswith("../"):  # Roboflow exports; Ultralytics resolves them like this
                p = (base / raw[3:]).resolve()
        if p.is_dir():
            images += sorted(f for f in p.rglob("*") if f.suffix.lower() in IMAGE_EXT)
        elif p.suffix == ".txt" and p.is_file():
            images += [Path(line.strip()) for line in p.read_text().splitlines() if line.strip()]
    if not images:
        raise BenchmarkError(f"ไม่พบภาพในชุด '{split}' ของ {data_yaml}")
    return images


def default_images() -> List[Path]:
    folder = REPO_ROOT.parent / "assets" / "test_images"
    return sorted(f for f in folder.glob("*") if f.suffix.lower() in IMAGE_EXT)


def run(
    infer,  # InferenceService
    data_yaml: Optional[str] = None,
    split: str = "test",
    rounds: int = 3,
    warmup: int = 5,
    imgsz: Optional[int] = None,
    conf: float = 0.25,
    max_images: int = 50,
    label: str = "",
    progress: Optional[Callable[[str, int, int], None]] = None,
) -> Dict[str, Any]:
    if infer.model_path is None:
        raise BenchmarkError("ยังไม่ได้โหลดโมเดล")
    paths = dataset_images(data_yaml, split) if data_yaml else default_images()
    paths = paths[: max(1, min(max_images, MAX_IMAGES))]
    frames = [(p.name, img) for p in paths if (img := cv2.imread(str(p))) is not None]
    if not frames:
        raise BenchmarkError("อ่านภาพสำหรับทดสอบไม่ได้")
    total_steps = warmup + rounds * len(frames)
    step = 0
    report = lambda stage: progress and progress(stage, step, total_steps)  # noqa: E731

    for i in range(warmup):  # first calls include CUDA/MPS setup; not counted
        infer.predict(frames[i % len(frames)][1], conf=conf, imgsz=imgsz, tag="benchmark-warmup")
        step += 1
        report("warmup")
    timings: Dict[str, List[float]] = {"preprocess": [], "inference": [], "postprocess": [], "total": []}
    started = time.perf_counter()
    for _ in range(rounds):
        for _name, img in frames:
            _dets, speed = infer.predict(img, conf=conf, imgsz=imgsz, tag="benchmark")
            for k in timings:
                timings[k].append(float(speed.get(k, 0.0)))
            step += 1
            report("timing")
    wall = time.perf_counter() - started
    total = _stats(timings["total"])

    result: Dict[str, Any] = {
        "time": time.time(),
        "label": label,
        "system": system_info(infer),
        "settings": {"data": data_yaml, "split": split if data_yaml else None, "images": len(frames), "rounds": rounds, "warmup": warmup, "imgsz": imgsz, "conf": conf},
        "timing_ms": {k: _stats(v) for k, v in timings.items()},
        "throughput_fps": round(1000 / total["mean"], 2) if total and total["mean"] else None,
        "wall_fps": round(len(timings["total"]) / wall, 2) if wall else None,
        "map": None,
    }
    if data_yaml:
        report("map")
        result["map"] = validate(infer, data_yaml, split, imgsz)
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    out = BENCH_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{result['system']['hostname']}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    result["file"] = out.name
    return result


def validate(infer, data_yaml: str, split: str, imgsz: Optional[int]) -> Dict[str, Any]:
    """mAP on the dataset split with the loaded model (same weights, same device)."""
    with infer._lock:  # noqa: SLF001 - keep predict() calls out while the model validates
        model = infer._model  # noqa: SLF001
        device = infer.device_info.device if infer.device_info else "cpu"
        kwargs: Dict[str, Any] = {"data": data_yaml, "split": split, "device": device, "verbose": False, "plots": False}
        if imgsz:
            kwargs["imgsz"] = int(imgsz)
        try:
            metrics = model.val(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise BenchmarkError(f"คำนวณ mAP ไม่สำเร็จ: {exc}") from exc
    box = metrics.box
    return {"map50": round(float(box.map50) * 100, 2), "map50_95": round(float(box.map) * 100, 2),
            "precision": round(float(box.mp) * 100, 2), "recall": round(float(box.mr) * 100, 2), "split": split}


def latest() -> Optional[Dict[str, Any]]:
    files = sorted(BENCH_DIR.glob("*.json")) if BENCH_DIR.is_dir() else []
    if not files:
        return None
    data = json.loads(files[-1].read_text())
    data["file"] = files[-1].name
    return data


# ── background job for the web page ─────────────────────────────────────────

class BenchmarkJob:
    def __init__(self) -> None:
        self.state: Dict[str, Any] = {"status": "idle"}
        self._thread: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, infer, **kwargs) -> Dict[str, Any]:
        if self.running:
            raise BenchmarkError("กำลังทดสอบอยู่แล้ว")
        self.state = {"status": "running", "stage": "start", "done": 0, "total": 0, "started": time.time()}

        def progress(stage: str, done: int, total: int) -> None:
            self.state.update(stage=stage, done=done, total=total)

        def work() -> None:
            try:
                self.state = {"status": "done", "result": run(infer, progress=progress, **kwargs)}
            except Exception as exc:  # noqa: BLE001
                self.state = {"status": "error", "error": str(exc)}

        self._thread = threading.Thread(target=work, daemon=True, name="Benchmark")
        self._thread.start()
        return self.state


benchmark_job = BenchmarkJob()


# ── report (this machine's column of the comparison table) ─────────────────

def performance_report(rows: Dict[str, Any]) -> Dict[str, Any]:
    runs = rows["runs"]
    done = [r for r in runs if r["status"] == "complete" and r["completed_at"]]
    scan_s = _stats([r["completed_at"] - r["created_at"] for r in done])
    images: Dict[str, List[float]] = {"inference": [], "total": []}
    for p in rows["points"] + rows["singles"]:
        try:
            speed = json.loads(p["speed_json"] or "{}")
        except ValueError:
            continue
        for k in images:
            if k in speed:
                images[k].append(float(speed[k]))
    total = _stats(images["total"])

    labeled = [r for r in done if r.get("ground_truth") in ("good", "defective")]
    decided = [r for r in labeled if r["overall_verdict"] in ("PASS", "FAIL")]
    tp = sum(r["ground_truth"] == "defective" and r["overall_verdict"] == "FAIL" for r in decided)
    tn = sum(r["ground_truth"] == "good" and r["overall_verdict"] == "PASS" for r in decided)
    fp = sum(r["ground_truth"] == "good" and r["overall_verdict"] == "FAIL" for r in decided)
    fn = sum(r["ground_truth"] == "defective" and r["overall_verdict"] == "PASS" for r in decided)
    pct = lambda a, b: round(100 * a / b, 2) if b else None  # noqa: E731
    board = {
        "labeled": len(labeled), "decided": len(decided), "review": len(labeled) - len(decided),
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "accuracy": pct(tp + tn, len(decided)),
        "precision": pct(tp, tp + fp), "recall": pct(tp, tp + fn),
        "f1": pct(2 * tp, 2 * tp + fp + fn),
    }
    return {
        "system": system_info(),
        "benchmark": latest(),
        "scans": {"finished": len(done), "all": len(runs), "scan_time_s": scan_s, "hosts": sorted({r["host"] for r in runs if r.get("host")})},
        "images": {"count": len(images["total"]) or len(images["inference"]), "inference_ms": _stats(images["inference"]), "total_ms": total,
                   "throughput_fps": round(1000 / total["mean"], 2) if total and total["mean"] else None},
        "board": board,
    }


def table_rows(rep: Dict[str, Any]) -> List[List[str]]:
    """Rows of table 4.13 (item, value) for this machine."""
    s, b, bench = rep["system"], rep["board"], rep.get("benchmark")
    v = s.get("versions", {})
    model = s.get("model", {})
    power = s.get("power") or {}
    fmt = lambda st: f"{st['mean']:.1f} ± {st['std']:.1f} (n={st['n']})" if st else "–"  # noqa: E731
    bt = (bench or {}).get("timing_ms") or {}
    bset = (bench or {}).get("settings") or {}
    sw = f"{s.get('os')} · Python {s.get('python')} · torch {v.get('torch')} · ultralytics {v.get('ultralytics')} · OpenCV {v.get('cv2')}"
    if v.get("cuda"):
        sw += f" · CUDA {v.get('cuda')}"
    if s.get("l4t"):
        sw += f" · L4T {s['l4t']}" + (f" · JetPack {s['jetpack']}" if s.get("jetpack") else "")
    mode = f"{power.get('mode')}" + (" + jetson_clocks" if power.get("clocks_max") else "") if power else "ค่าเริ่มต้นของระบบ"
    if power.get("fan"):
        f = power["fan"]
        mode += f" · พัดลม {('กำหนดเอง ' + str(f.get('manual_percent')) + '%') if f.get('mode') == 'manual' else ('อัตโนมัติ ' + str(f.get('profile')))}"
    img = rep["images"]
    m = (bench or {}).get("map") or {}
    return [
        ["รุ่นอุปกรณ์และ RAM", f"{s.get('board') or s.get('hostname')} · RAM {s.get('ram_gb')} GB"],
        ["อุปกรณ์ประมวลผล", f"{model.get('device')} · CPU {s.get('cpu')} ({s.get('cpu_cores')} threads)" + (f" · GPU {s.get('gpu')}" if s.get("gpu") else "")],
        ["ระบบปฏิบัติการและเวอร์ชันซอฟต์แวร์", sw],
        ["รูปแบบโมเดลและ precision", f"{model.get('file')} ({model.get('format')}, {model.get('precision')}, {model.get('size_mb')} MB, sha256 {model.get('sha256')})"],
        ["โหมดพลังงานและการตั้งค่านาฬิกา", mode],
        ["จำนวนภาพและจำนวนรอบวัด", f"benchmark {bset.get('images', '–')} ภาพ × {bset.get('rounds', '–')} รอบ (warm-up {bset.get('warmup', '–')}) · ใช้งานจริง {img['count']} ภาพ · {rep['scans']['finished']} บอร์ด"],
        ["เวลาอนุมานเฉลี่ย (ms/ภาพ)", fmt(bt.get("inference")) + f" · ใช้งานจริง {fmt(img['inference_ms'])}"],
        ["เวลารวมประมวลผลภาพเฉลี่ย (ms/ภาพ)", fmt(bt.get("total")) + f" · ใช้งานจริง {fmt(img['total_ms'])}"],
        ["อัตราประมวลผลภาพ (ภาพ/วินาที)", f"{(bench or {}).get('throughput_fps') or '–'} · ใช้งานจริง {img['throughput_fps'] or '–'}"],
        ["เวลาสแกนเฉลี่ยต่อบอร์ด (s/บอร์ด)", fmt(rep["scans"]["scan_time_s"])],
        ["mAP50 บนภาพทดสอบชุดเดียวกัน (%)", f"{m.get('map50')} (mAP50-95 {m.get('map50_95')}, ชุด {m.get('split')})" if m else "–"],
        ["Accuracy ระดับบอร์ด (%)", f"{b['accuracy']} ({b['tp'] + b['tn']}/{b['decided']} บอร์ด, ตรวจซ้ำ {b['review']})" if b["decided"] else "–"],
        ["F1 ระดับบอร์ด (%)", f"{b['f1']} (TP {b['tp']} FP {b['fp']} FN {b['fn']} TN {b['tn']})" if b["decided"] else "–"],
    ]


def _cli() -> None:
    from ..config import settings
    from .inference_service import InferenceService

    ap = argparse.ArgumentParser(description="Benchmark this machine for the computer-vs-Jetson table")
    ap.add_argument("--data", help="data.yaml of the shared test dataset (also computes mAP50)")
    ap.add_argument("--split", default="test")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--images", type=int, default=50, help="max images from the split")
    ap.add_argument("--imgsz", type=int, default=None)
    ap.add_argument("--model", default=settings.default_model)
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    infer = InferenceService()
    infer.load_model(args.model, settings.device_preference)
    res = run(infer, args.data, args.split, args.rounds, args.warmup, args.imgsz, max_images=args.images, label=args.label,
              progress=lambda st, d, t: print(f"\r  {st}: {d}/{t}", end="", flush=True))
    print()
    rep = {"system": res["system"], "benchmark": res, "scans": {"finished": 0, "scan_time_s": None}, "images": {"count": 0, "inference_ms": None, "total_ms": None, "throughput_fps": None},
           "board": {"decided": 0}}
    for item, value in table_rows(rep):
        print(f"  {item}: {value}")
    print(f"\n  saved {BENCH_DIR / res['file']}")


if __name__ == "__main__":
    _cli()
