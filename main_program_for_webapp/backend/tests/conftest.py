"""Run all tests against isolated storage and simulated hardware, never the station DB."""
import os
import tempfile
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

_test_storage = tempfile.TemporaryDirectory(prefix="pcb-aoi-tests-")
os.environ["PCB_STORAGE_DIR"] = _test_storage.name
os.environ["PCB_OPERATOR_PASSCODE"] = "rmutt-aoi"

import pytest


@contextmanager
def operator_headers():
    """Use a real lease for API tests that mutate station state."""
    from app.core.security import lease_manager

    ok, token, _ = lease_manager.acquire_lease("API test", "local", force=True)
    assert ok
    try:
        yield {"X-Operator-Token": token}
    finally:
        lease_manager.release_lease(token)

@pytest.fixture(scope="session", autouse=True)
def simulated_station():
    from app.services.inference_service import inference_service
    from app.services.camera_service import camera_service
    from app.services.machine_service import machine_service
    from app.services.aoi_scan_service import aoi_scan_service
    fake_capture = MagicMock()
    fake_capture.isOpened.return_value = False
    with patch("cv2.VideoCapture", return_value=fake_capture), \
         patch.object(inference_service, "_model", MagicMock()), \
         patch.object(inference_service, "_model_path", "test-model.pt"), \
         patch.object(inference_service, "predict", return_value=([], {"inference": 1.0})):
        yield
        aoi_scan_service.stop_scan()
        camera_service.stop()
        machine_service.disconnect()
