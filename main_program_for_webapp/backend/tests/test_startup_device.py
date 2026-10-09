"""The startup display must not advertise an unsupported CUDA build as clean."""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.core.device import InferenceDevice, select_device
from app.services.inference_service import InferenceService


class StartupDeviceTests(unittest.TestCase):
    def _torch(self, arches):
        cuda = types.SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 1,
            get_device_name=lambda _: "Orin",
            get_device_capability=lambda _: (8, 7),
            get_arch_list=lambda: arches,
        )
        return types.SimpleNamespace(cuda=cuda, __version__="2.13.0+cu130")

    def test_unlisted_cuda_architecture_is_visible(self):
        with patch.dict(sys.modules, {"torch": self._torch(["sm_80", "sm_90"])}):
            selected = select_device("cuda:0")
        self.assertEqual(selected.device, "cuda:0")
        self.assertIn("Warning:", selected.detail)
        self.assertIn("sm_87", selected.detail)

    def test_listed_cuda_architecture_has_no_warning(self):
        with patch.dict(sys.modules, {"torch": self._torch(["sm_80", "sm_87"])}):
            selected = select_device("cuda:0")
        self.assertNotIn("Warning:", selected.detail)

    def test_cuda_warmup_waits_for_kernel_completion(self):
        model = Mock()
        model.names = {0: "defect"}
        synchronize = Mock()
        fake_torch = types.SimpleNamespace(cuda=types.SimpleNamespace(synchronize=synchronize))
        fake_ultralytics = types.SimpleNamespace(YOLO=lambda _: model)
        device = InferenceDevice("cuda:0", "NVIDIA Orin (cuda:0)")
        with patch.dict(sys.modules, {"torch": fake_torch, "ultralytics": fake_ultralytics}), \
                patch("app.services.inference_service.select_device", return_value=device), \
                patch("app.services.inference_service.validate_model_file", return_value=Path("model.pt")):
            service = InferenceService()
            service.load_model("model.pt")
        synchronize.assert_called_once_with("cuda:0")
        self.assertTrue(service.is_loaded)

    def test_cuda_kernel_failure_does_not_mark_model_loaded(self):
        model = Mock()
        model.names = {0: "defect"}
        fake_torch = types.SimpleNamespace(cuda=types.SimpleNamespace(synchronize=Mock(side_effect=RuntimeError("no kernel image"))))
        fake_ultralytics = types.SimpleNamespace(YOLO=lambda _: model)
        device = InferenceDevice("cuda:0", "NVIDIA Orin (cuda:0)")
        with patch.dict(sys.modules, {"torch": fake_torch, "ultralytics": fake_ultralytics}), \
                patch("app.services.inference_service.select_device", return_value=device), \
                patch("app.services.inference_service.validate_model_file", return_value=Path("model.pt")):
            service = InferenceService()
            with self.assertRaisesRegex(RuntimeError, "no kernel image"):
                service.load_model("model.pt")
        self.assertFalse(service.is_loaded)


if __name__ == "__main__":
    unittest.main()
