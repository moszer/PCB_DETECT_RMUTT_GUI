"""The camera opens with the station's saved format and remembers the last one applied."""
import unittest
from unittest.mock import PropertyMock, patch

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services.camera_service import CameraService, camera_service


class CameraDefaultTests(unittest.TestCase):
    def test_new_service_uses_saved_format(self):
        with patch.multiple(settings, camera_width=3840, camera_height=2160, camera_output_width=2160,
                            camera_output_height=2160, camera_output_mode="crop"):
            cam = CameraService()
        self.assertEqual((cam._requested_width, cam._requested_height), (3840, 2160))
        self.assertEqual(cam._output_size, (2160, 2160))
        self.assertEqual(cam._output_mode, "crop")

    def test_preferred_camera_is_found_by_name(self):
        cam = CameraService()
        devices = [{"index": 0, "name": "MacBook Pro Camera (Index 0)"}, {"index": 1, "name": "OBSBOT Meet 2 StreamCamera (Index 1)"}]
        with patch.object(cam, "list_devices", return_value=devices), patch.object(settings, "camera_device_name", "OBSBOT"):
            self.assertEqual(cam.preferred_device_index(), 1)

    def test_applied_format_is_saved_for_a_real_camera_only(self):
        client = TestClient(app)
        body = {"device_index": 1, "width": 3840, "height": 2160, "fps": 30, "output_width": 2160, "output_height": 2160, "output_mode": "crop"}
        devices = [{"index": 1, "name": "OBSBOT Meet 2 StreamCamera (Index 1)", "active": True}]
        with patch.object(camera_service, "start", return_value=True), \
                patch.object(camera_service, "list_devices", return_value=devices), \
                patch("app.routers.camera.save_settings_to_disk") as save, \
                patch.multiple(settings, camera_index=0, camera_device_name="x", camera_output_mode="fit"):
            with patch.object(type(camera_service), "is_mock", new_callable=PropertyMock, return_value=True):
                client.post("/api/camera/start", json=body)
                save.assert_not_called()
            with patch.object(type(camera_service), "is_mock", new_callable=PropertyMock, return_value=False):
                client.post("/api/camera/start", json=body)
                saved = save.call_args[0][0]
                self.assertEqual((saved.camera_index, saved.camera_output_mode, saved.camera_device_name), (1, "crop", "OBSBOT Meet 2 StreamCamera"))
                self.assertEqual(settings.camera_output_mode, "crop")


if __name__ == "__main__":
    unittest.main()


class OpenCaptureTests(unittest.TestCase):
    """Linux must ask for V4L2 + MJPG, otherwise USB webcams answer 640x480."""

    def test_linux_requests_mjpg_before_size(self):
        import cv2
        from unittest.mock import MagicMock, patch
        from app.services.camera_service import camera_service

        cap = MagicMock()
        cap.isOpened.return_value = True
        with patch("sys.platform", "linux"), patch("cv2.VideoCapture", return_value=cap) as vc:
            camera_service._open_capture(0)
        vc.assert_called_once_with(0, cv2.CAP_V4L2)
        cap.set.assert_called_once_with(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

    def test_other_platforms_open_plainly(self):
        from unittest.mock import MagicMock, patch
        from app.services.camera_service import camera_service

        with patch("sys.platform", "darwin"), patch("cv2.VideoCapture", return_value=MagicMock()) as vc:
            camera_service._open_capture(1)
        vc.assert_called_once_with(1)
