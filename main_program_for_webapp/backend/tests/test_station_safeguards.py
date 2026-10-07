"""Regression checks for the station's access, backups and model acceptance gate."""
import hashlib
import json
import stat
import sqlite3
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.security import lease_manager
from app.services.backup_service import create_backup, restore_backup, verify_backup
from app import quality_gate
from app import config


def test_motion_requires_operator_even_when_no_one_holds_lease():
    client = TestClient(app)
    lease = lease_manager.get_lease_info()
    assert not lease.is_controlled
    assert client.post("/api/aoi/connect", json={"mode": "simulation"}).status_code == 403
    assert client.post("/api/aoi/jog", json={"dx_mm": 1, "dy_mm": 0}).status_code == 403
    assert client.post("/api/camera/start", json={}).status_code == 403
    assert client.post("/api/system/settings", json={}).status_code == 403
    assert client.post("/api/aoi/stop").status_code == 200

    ok, token, _ = lease_manager.acquire_lease("test", "local")
    assert ok
    try:
        assert client.post("/api/aoi/connect", json={"mode": "simulation"}, headers={"X-Operator-Token": "wrong"}).status_code == 403
        assert client.post("/api/aoi/connect", json={"mode": "simulation"}, headers={"X-Operator-Token": token}).status_code == 200
    finally:
        client.post("/api/aoi/stop")
        lease_manager.release_lease(token)


def test_cors_only_allows_configured_origin():
    client = TestClient(app)
    allowed = client.options("/api/aoi/connect", headers={"Origin": "http://localhost:3001", "Access-Control-Request-Method": "POST"})
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3001"
    blocked = client.options("/api/aoi/connect", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert blocked.status_code == 400


def test_unique_operator_passcode_replaces_legacy_default(tmp_path, monkeypatch):
    monkeypatch.delenv("PCB_OPERATOR_PASSCODE", raising=False)
    monkeypatch.setattr(config, "PASSCODE_FILE", tmp_path / ".operator-passcode")
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    generated = config._operator_passcode()
    assert len(generated) >= 20
    assert config._operator_passcode() == generated
    assert stat.S_IMODE(config.PASSCODE_FILE.stat().st_mode) == 0o600
    config.SETTINGS_FILE.write_text(json.dumps({"operator_passcode": "rmutt-aoi", "cors_origins": ["*"]}))
    fresh = config.Settings()
    config.load_saved_settings(fresh)
    assert fresh.operator_passcode == generated
    assert "*" not in fresh.cors_origins


def test_backup_verifies_and_restores_station_files(tmp_path):
    storage = tmp_path / "station"
    storage.mkdir()
    (storage / "runs").mkdir()
    (storage / "runs" / "image.jpg").write_bytes(b"image")
    with sqlite3.connect(storage / "inspection.db") as db:
        db.execute("CREATE TABLE scans (id INTEGER)")
        db.execute("INSERT INTO scans VALUES (42)")
    archive = create_backup(storage)
    assert set(verify_backup(archive)) == {"inspection.db", "runs/image.jpg"}
    restored = restore_backup(archive, tmp_path / "restored")
    assert (restored / "runs" / "image.jpg").read_bytes() == b"image"
    with sqlite3.connect(restored / "inspection.db") as db:
        assert db.execute("SELECT id FROM scans").fetchone() == (42,)
    with pytest.raises(FileExistsError):
        restore_backup(archive, restored)

    broken = tmp_path / "broken.zip"
    with zipfile.ZipFile(broken, "w") as out:
        out.writestr("runs/image.jpg", b"changed")
        out.writestr("manifest.json", json.dumps({"format": 1, "files": {"runs/image.jpg": "bad"}}))
    with pytest.raises(ValueError, match="checksum"):
        verify_backup(broken)


def test_model_requires_per_class_recall_and_unchanged_weights(tmp_path, monkeypatch):
    model = tmp_path / "model.pt"
    model.write_bytes(b"weights")
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    report = {
        "system": {"model": {"path": str(model), "sha256": digest[:16]}},
        "settings": {"data": "fixed-test/data.yaml", "split": "test"},
        "map": {"map50": 91, "recall": 92, "per_class": {"missing_part": {"recall": 95}, "wrong_part": {"recall": 91}},
                "expected_classes": ["missing_part", "wrong_part"], "split": "test"},
    }
    report_path = tmp_path / "benchmark.json"
    report_path.write_text(json.dumps(report))
    monkeypatch.setattr(quality_gate, "APPROVAL_FILE", tmp_path / "approvals.json")
    monkeypatch.setenv("PCB_REQUIRE_MODEL_APPROVAL", "1")
    assert quality_gate.certify(report_path, 85, 90, 90)["sha256"] == digest
    quality_gate.require_approved(str(model))
    model.write_bytes(b"changed weights")
    with pytest.raises(ValueError, match="not approved"):
        quality_gate.require_approved(str(model))
    report["map"]["per_class"]["wrong_part"]["recall"] = 70
    assert "Recall for wrong_part below 90%" in quality_gate.evaluate(report, 85, 90, 90)
