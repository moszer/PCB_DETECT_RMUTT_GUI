"""Training-data capture: raster-photograph a whole board marked by 4 corners, keep
YOLO-format labels (optionally pre-labelled by the current model), edit and export them."""
from __future__ import annotations

import json
import logging
import math
import re
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2

from ..config import DATASETS_DIR
from ..core.motion_protocol import raster_points
from .camera_service import camera_service
from .inference_service import inference_service
from .machine_service import machine_service

logger = logging.getLogger("dataset_service")

SAFE_ID = re.compile(r"^ds_[A-Za-z0-9_]+$")
SAFE_FILE = re.compile(r"^img_\d{4}\.jpg$")
MAX_IMAGES = 400


def _atomic_write(path: Path, text: str):
    tmp = path.with_suffix(path.suffix + f".{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def plan_board_points(
    corners: List[Tuple[float, float]], pitch_x: float, pitch_y: float, steps_per_mm: float, limits: Tuple[int, int]
) -> Tuple[List[Tuple[int, int]], Dict[str, Any]]:
    """Serpentine raster covering the bounding box of the 4 marked corners.

    The pitch is shrunk so the first and last frames land exactly on the board edges.
    """
    if len(corners) != 4:
        raise ValueError("Mark exactly 4 board corners")
    if pitch_x <= 0 or pitch_y <= 0:
        raise ValueError("Pitch must be positive")
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    cols = max(1, math.ceil((max_x - min_x) / pitch_x) + 1)
    rows = max(1, math.ceil((max_y - min_y) / pitch_y) + 1)
    if cols * rows > MAX_IMAGES:
        raise ValueError(f"{cols}×{rows} = {cols * rows} images exceeds {MAX_IMAGES}; increase the pitch")
    step_x = (max_x - min_x) / (cols - 1) if cols > 1 else 0.0
    step_y = (max_y - min_y) / (rows - 1) if rows > 1 else 0.0
    points = raster_points(min_x, min_y, cols, rows, step_x, step_y, steps_per_mm, limits)
    return points, {"origin": [min_x, min_y], "columns": cols, "rows": rows, "pitch": [step_x, step_y]}


class DatasetService:
    def __init__(self, root: Path = DATASETS_DIR):
        self.root = root
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._current: Optional[str] = None
        self._subscribers: List[Callable[[Dict[str, Any]], None]] = []

    # ── Progress ──

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]):
        self._subscribers.append(callback)

    def _broadcast(self, payload: Dict[str, Any]):
        for sub in list(self._subscribers):
            try:
                sub(payload)
            except Exception:
                pass

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def current_id(self) -> Optional[str]:
        return self._current if self.is_running else None

    # ── Storage helpers ──

    def _dir(self, dataset_id: str) -> Path:
        if not SAFE_ID.match(dataset_id or ""):
            raise ValueError("Invalid dataset id")
        path = (self.root / dataset_id).resolve()
        if path.parent != self.root.resolve():
            raise ValueError("Invalid dataset id")
        return path

    def _meta_path(self, dataset_id: str) -> Path:
        return self._dir(dataset_id) / "dataset.json"

    def get(self, dataset_id: str) -> Optional[Dict[str, Any]]:
        try:
            path = self._meta_path(dataset_id)
        except ValueError:
            return None
        if not path.is_file():
            return None
        with self._lock:
            return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, meta: Dict[str, Any]):
        meta["updated_at"] = time.time()
        _atomic_write(self._meta_path(meta["id"]), json.dumps(meta, ensure_ascii=False, indent=2))

    def list(self) -> List[Dict[str, Any]]:
        out = []
        for meta_file in sorted(self.root.glob("ds_*/dataset.json"), reverse=True):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            images = meta.get("images", [])
            out.append({
                "id": meta["id"],
                "name": meta["name"],
                "status": meta["status"],
                "created_at": meta["created_at"],
                "updated_at": meta.get("updated_at", meta["created_at"]),
                "image_count": len(images),
                "planned": meta.get("planned", len(images)),
                "box_count": sum(i.get("boxes", 0) for i in images),
                "cover": f"/api/storage/datasets/{meta['id']}/images/{images[0]['file']}" if images else None,
            })
        return out

    def delete(self, dataset_id: str) -> bool:
        if self.current_id == dataset_id:
            raise RuntimeError("Stop the capture before deleting this dataset")
        path = self._dir(dataset_id)
        if not path.is_dir():
            return False
        for child in sorted(path.rglob("*"), reverse=True):
            child.unlink() if child.is_file() else child.rmdir()
        path.rmdir()
        return True

    # ── Labels ──

    def get_labels(self, dataset_id: str, file: str) -> Dict[str, Any]:
        meta = self.get(dataset_id)
        if not meta or not SAFE_FILE.match(file):
            raise FileNotFoundError("Image not found")
        label_path = self._dir(dataset_id) / "labels" / (Path(file).stem + ".txt")
        classes = meta["classes"]
        boxes = []
        if label_path.is_file():
            for line in label_path.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) != 5:
                    continue
                cls, cx, cy, w, h = int(parts[0]), *map(float, parts[1:])
                boxes.append({
                    "label": classes[cls] if 0 <= cls < len(classes) else f"class_{cls}",
                    "bbox": [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2],
                })
        return {"file": file, "boxes": boxes, "classes": classes}

    def _write_labels(self, meta: Dict[str, Any], file: str, boxes: List[Dict[str, Any]]) -> int:
        classes: List[str] = meta["classes"]
        lines = []
        for box in boxes:
            label = str(box["label"]).strip()
            x1, y1, x2, y2 = (min(1.0, max(0.0, float(v))) for v in box["bbox"])
            if not label or x2 - x1 <= 1e-4 or y2 - y1 <= 1e-4:
                continue
            if label not in classes:
                classes.append(label)
            lines.append(f"{classes.index(label)} {(x1 + x2) / 2:.6f} {(y1 + y2) / 2:.6f} {x2 - x1:.6f} {y2 - y1:.6f}")
        label_path = self._dir(meta["id"]) / "labels" / (Path(file).stem + ".txt")
        _atomic_write(label_path, "\n".join(lines) + ("\n" if lines else ""))
        return len(lines)

    def save_labels(self, dataset_id: str, file: str, boxes: List[Dict[str, Any]]) -> Dict[str, Any]:
        with self._lock:
            meta = self.get(dataset_id)
            if not meta or not SAFE_FILE.match(file):
                raise FileNotFoundError("Image not found")
            entry = next((i for i in meta["images"] if i["file"] == file), None)
            if entry is None:
                raise FileNotFoundError("Image not found")
            entry["boxes"] = self._write_labels(meta, file, boxes)
            entry["labeled_by"] = "manual"
            self._save(meta)
            return entry

    def delete_image(self, dataset_id: str, file: str):
        with self._lock:
            meta = self.get(dataset_id)
            if not meta or not SAFE_FILE.match(file):
                raise FileNotFoundError("Image not found")
            meta["images"] = [i for i in meta["images"] if i["file"] != file]
            base = self._dir(dataset_id)
            (base / "images" / file).unlink(missing_ok=True)
            (base / "labels" / (Path(file).stem + ".txt")).unlink(missing_ok=True)
            self._save(meta)

    # ── Export ──

    def export_zip(self, dataset_id: str, val_ratio: float = 0.2) -> Path:
        """YOLO-ready archive in the Roboflow layout used by train_lab and the training dashboard:
        {train,valid}/{images,labels}, data.yaml, classes.txt."""
        meta = self.get(dataset_id)
        if not meta:
            raise FileNotFoundError("Dataset not found")
        base = self._dir(dataset_id)
        total = len(meta["images"])
        # Evenly spread exactly k validation images (at least one once there are 2+ images).
        k = min(total - 1, max(1, round(total * val_ratio))) if val_ratio > 0 and total >= 2 else 0
        tmp = tempfile.NamedTemporaryFile(prefix=f"{dataset_id}_", suffix=".zip", delete=False, dir=self.root)
        tmp.close()
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
            for n, image in enumerate(meta["images"]):
                split = "valid" if k and (n * k) // total != ((n + 1) * k) // total else "train"
                stem = Path(image["file"]).stem
                zf.write(base / "images" / image["file"], f"{split}/images/{image['file']}")
                label = base / "labels" / f"{stem}.txt"
                zf.writestr(f"{split}/labels/{stem}.txt", label.read_text(encoding="utf-8") if label.is_file() else "")
            names = json.dumps(meta["classes"], ensure_ascii=False)
            zf.writestr(
                "data.yaml",
                f"# {meta['name']} — exported from RMUTT AOI web station\n"
                f"path: .\ntrain: train/images\nval: valid/images\nnc: {len(meta['classes'])}\nnames: {names}\n",
            )
            zf.writestr("classes.txt", "\n".join(meta["classes"]) + "\n")
        return Path(tmp.name)

    # ── Capture ──

    def start_capture(
        self,
        name: str,
        corners: List[Tuple[float, float]],
        pitch_x_mm: float,
        pitch_y_mm: float,
        speed: int,
        settle_sec: float,
        auto_label: bool,
        conf: float,
        imgsz: Optional[int],
    ) -> Dict[str, Any]:
        from .aoi_scan_service import aoi_scan_service

        with self._lock:
            if self.is_running:
                raise RuntimeError("A dataset capture is already running")
            if aoi_scan_service.is_running:
                raise RuntimeError("Stop the AOI scan before capturing a dataset")
            from .stage_calibration_service import stage_calibration_service
            if stage_calibration_service.is_running:
                raise RuntimeError("รอให้ calibrate ราง XY เสร็จก่อน")
            state = machine_service.get_state()
            if not state.connected or not state.homed:
                raise RuntimeError("Connect and HOME the stage first")
            if not camera_service.is_active:
                raise RuntimeError("Camera is not active")
            if auto_label and not inference_service.is_loaded:
                raise RuntimeError("Load a model to pre-label images (or turn auto-label off)")

            spm = machine_service.steps_per_mm
            limits = (
                min(state.limits_steps[0], round(state.soft_limits_mm[0] * spm)),
                min(state.limits_steps[1], round(state.soft_limits_mm[1] * spm)),
            )
            points, layout = plan_board_points(corners, pitch_x_mm, pitch_y_mm, spm, limits)

            dataset_id = f"ds_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
            base = self.root / dataset_id
            (base / "images").mkdir(parents=True)
            (base / "labels").mkdir()
            meta = {
                "id": dataset_id,
                "name": name.strip() or f"Board {time.strftime('%Y-%m-%d %H:%M')}",
                "status": "capturing",
                "created_at": time.time(),
                "corners": [list(c) for c in corners],
                "layout": layout,
                "planned": len(points),
                "resolution": list(camera_service.resolution),
                "model": inference_service.model_path if auto_label else None,
                "classes": list(inference_service.class_names) if inference_service.is_loaded else [],
                "images": [],
                "error": None,
            }
            self._save(meta)
            self._stop.clear()
            self._current = dataset_id
            self._thread = threading.Thread(
                target=self._capture,
                args=(meta, points, spm, speed, settle_sec, auto_label, conf, imgsz),
                daemon=True,
                name="DatasetCapture",
            )
            self._thread.start()
            return meta

    def stop_capture(self):
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            machine_service.stop()
            thread.join(timeout=3)

    def _finish(self, meta: Dict[str, Any], status: str, error: Optional[str] = None):
        with self._lock:
            meta["status"] = status
            meta["error"] = error
            self._save(meta)
        self._broadcast({"event": status, "dataset": self._summary(meta)})

    @staticmethod
    def _summary(meta: Dict[str, Any]) -> Dict[str, Any]:
        return {k: meta[k] for k in ("id", "name", "status", "planned", "error")} | {"captured": len(meta["images"])}

    def _capture(self, meta, points, spm, speed, settle_sec, auto_label, conf, imgsz):
        from ..core.security import lease_manager

        was_controlled = lease_manager.get_lease_info().is_controlled
        base = self._dir(meta["id"])
        try:
            self._broadcast({"event": "start", "dataset": self._summary(meta)})
            for index, (xs, ys) in enumerate(points):
                if self._stop.is_set():
                    break
                if was_controlled and not lease_manager.get_lease_info().is_controlled:
                    return self._finish(meta, "aborted", "Operator control lease expired during capture.")
                self._broadcast({"event": "moving", "dataset": self._summary(meta), "index": index, "target_mm": [xs / spm, ys / spm]})
                machine_service.move_to_steps(xs, ys, speed=speed)
                if self._stop.wait(settle_sec):
                    break
                stab = camera_service.wait_until_still(time.monotonic(), should_stop=self._stop.is_set)
                _, frame = camera_service.get_fresh_frame(after_timestamp=stab["timestamp"], timeout_sec=3.0)
                file = f"img_{index + 1:04d}.jpg"
                if not cv2.imwrite(str(base / "images" / file), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95]):
                    raise IOError(f"Could not write {file}")
                h, w = frame.shape[:2]
                boxes = []
                if auto_label:
                    detections, _ = inference_service.predict(frame, conf=conf, imgsz=imgsz, tag="dataset")
                    boxes = [{"label": d.label, "bbox": [d.box[0] / w, d.box[1] / h, d.box[2] / w, d.box[3] / h]} for d in detections]
                with self._lock:
                    count = self._write_labels(meta, file, boxes)
                    entry = {
                        "file": file,
                        "x_mm": round(xs / spm, 2),
                        "y_mm": round(ys / spm, 2),
                        "width": w,
                        "height": h,
                        "boxes": count,
                        "labeled_by": "model" if auto_label else None,
                    }
                    meta["images"].append(entry)
                    self._save(meta)
                self._broadcast({"event": "captured", "dataset": self._summary(meta), "index": index, "image": entry})

            if self._stop.is_set():
                self._finish(meta, "aborted", "Capture stopped by operator.")
            else:
                self._finish(meta, "complete")
        except Exception as exc:
            if self._stop.is_set():
                return self._finish(meta, "aborted", "Capture stopped by operator.")
            if was_controlled and not lease_manager.get_lease_info().is_controlled:
                return self._finish(meta, "aborted", "Operator control lease expired during capture.")
            logger.error("Dataset capture %s failed: %s", meta["id"], exc, exc_info=True)
            self._finish(meta, "error", str(exc))


dataset_service = DatasetService()
