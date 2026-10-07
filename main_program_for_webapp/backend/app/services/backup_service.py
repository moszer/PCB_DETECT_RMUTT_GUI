"""Verified station-data archives and a small daily backup scheduler.

Restore always creates a new data directory; an active station is never overwritten.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import sqlite3
import tempfile
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath

from ..config import STORAGE_DIR

BACKUP_DIR = STORAGE_DIR / "backups"
MANIFEST = "manifest.json"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def create_backup(storage_dir: Path = STORAGE_DIR, backup_dir: Path | None = None) -> Path:
    """Snapshot SQLite online and archive all station files except older backups."""
    storage_dir = Path(storage_dir).resolve()
    backup_dir = Path(backup_dir or storage_dir / "backups").resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    if not storage_dir.is_dir():
        raise FileNotFoundError(storage_dir)
    destination = backup_dir / f"station-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.zip"
    temporary = destination.with_suffix(".tmp")
    entries: dict[str, str] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="aoi-backup-") as tmp:
            snapshot = Path(tmp) / "inspection.db"
            db = storage_dir / "inspection.db"
            if db.is_file():
                with sqlite3.connect(db) as source, sqlite3.connect(snapshot) as target:
                    source.backup(target)
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for path in sorted(storage_dir.rglob("*")):
                    if not path.is_file() or path.is_symlink() or path == db:
                        continue
                    if path.is_relative_to(backup_dir) or path.suffix in {".tmp", ".db-wal", ".db-shm", ".db-journal"}:
                        continue
                    name = path.relative_to(storage_dir).as_posix()
                    data = path.read_bytes()
                    archive.writestr(name, data)
                    entries[name] = _digest(data)
                if snapshot.is_file():
                    data = snapshot.read_bytes()
                    archive.writestr("inspection.db", data)
                    entries["inspection.db"] = _digest(data)
                archive.writestr(MANIFEST, json.dumps({"format": 1, "created_at": time.time(), "files": entries}, sort_keys=True))
        temporary.chmod(0o600)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def verify_backup(archive_path: Path) -> dict[str, str]:
    """Reject unsafe paths, missing entries and changed bytes before any restore."""
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read(MANIFEST))
        if manifest.get("format") != 1 or not isinstance(manifest.get("files"), dict):
            raise ValueError("Unsupported backup manifest")
        files: dict[str, str] = manifest["files"]
        if set(archive.namelist()) != set(files) | {MANIFEST}:
            raise ValueError("Backup entries do not match manifest")
        for name, expected in files.items():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or name == MANIFEST or not path.parts:
                raise ValueError(f"Unsafe backup path: {name}")
            if _digest(archive.read(name)) != expected:
                raise ValueError(f"Backup checksum mismatch: {name}")
        return files


def restore_backup(archive_path: Path, target_dir: Path) -> Path:
    """Restore into a new directory so the running station remains untouched."""
    archive_path = Path(archive_path)
    target_dir = Path(target_dir).resolve()
    if target_dir.exists():
        raise FileExistsError(f"Restore target already exists: {target_dir}")
    files = verify_backup(archive_path)
    with tempfile.TemporaryDirectory(prefix="aoi-restore-", dir=target_dir.parent) as tmp:
        staging = Path(tmp) / "data"
        staging.mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            for name in files:
                output = staging / name
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(archive.read(name))
        staging.rename(target_dir)
    return target_dir


class BackupScheduler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        try:
            hours = float(os.environ.get("PCB_BACKUP_INTERVAL_HOURS", "24"))
        except ValueError:
            logging.getLogger(__name__).warning("Invalid PCB_BACKUP_INTERVAL_HOURS; automatic backups disabled")
            return
        if not math.isfinite(hours) or hours <= 0 or self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(hours * 3600,), name="station-backup", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self, interval: float) -> None:
        import logging

        logger = logging.getLogger(__name__)
        archives = sorted(BACKUP_DIR.glob("station-*.zip"), key=lambda path: path.stat().st_mtime)
        delay = max(60.0, interval - (time.time() - archives[-1].stat().st_mtime)) if archives else 60.0
        while not self._stop.wait(delay):
            try:
                from .aoi_scan_service import aoi_scan_service
                from .dataset_service import dataset_service
                from .stage_calibration_service import stage_calibration_service

                if aoi_scan_service.is_running or dataset_service.is_running or stage_calibration_service.is_running:
                    delay = min(interval, 600.0)
                    continue
                archive = create_backup()
                keep = max(1, int(os.environ.get("PCB_BACKUP_KEEP", "7")))
                for old in sorted(BACKUP_DIR.glob("station-*.zip"), reverse=True)[keep:]:
                    old.unlink()
                logger.info("Station backup saved: %s", archive)
                delay = interval
            except Exception:
                logger.exception("Station backup failed")
                delay = min(interval, 600.0)


backup_scheduler = BackupScheduler()
