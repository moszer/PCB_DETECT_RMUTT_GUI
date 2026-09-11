"""Device routing checks that do not require an NVIDIA GPU on the test host."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.inference_runtime import InferenceDevice, select_device, validate_model_file
from app.mixins.inspection_mixin import InferenceWorker


def fake_torch(available=True, cuda_version="13.0", count=1):
    return SimpleNamespace(
        version=SimpleNamespace(cuda=cuda_version),
        cuda=SimpleNamespace(
            is_available=Mock(return_value=available),
            device_count=Mock(return_value=count),
            get_device_name=Mock(return_value="Orin"),
        ),
    )


class DeviceTests(unittest.TestCase):
    def test_auto_prefers_nvidia(self):
        with patch.dict(sys.modules, {"torch": fake_torch()}):
            device = select_device("auto")
        self.assertEqual(device.device, "cuda:0")
        self.assertIn("Orin", device.label)

    def test_auto_reports_cpu_fallback_for_missing_cuda(self):
        with patch.dict(sys.modules, {"torch": fake_torch(False, None)}):
            device = select_device("auto")
        self.assertEqual(device.device, "cpu")
        self.assertIn("no CUDA support", device.detail)

    def test_forced_gpu_never_silently_falls_back(self):
        with patch.dict(sys.modules, {"torch": fake_torch(False)}):
            with self.assertRaisesRegex(RuntimeError, "cannot access"):
                select_device("cuda:0")

    def test_explicit_cpu_does_not_initialize_cuda(self):
        torch = fake_torch()
        with patch.dict(sys.modules, {"torch": torch}):
            self.assertEqual(select_device("cpu").device, "cpu")
        torch.cuda.is_available.assert_not_called()

    def test_gpu_index_and_environment_override(self):
        with patch.dict(sys.modules, {"torch": fake_torch(count=2)}):
            with patch.dict(os.environ, {"PCB_DEVICE": "cuda:1"}):
                self.assertEqual(select_device().device, "cuda:1")
            with self.assertRaisesRegex(RuntimeError, "only 2"):
                select_device("cuda:2")
        with self.assertRaises(ValueError):
            select_device("invalid")

    def test_lfs_pointer_is_rejected_before_deserialization(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "best.pt"
            path.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:123\nsize 100\n")
            with self.assertRaisesRegex(ValueError, "git lfs pull"):
                validate_model_file(path)
            with self.assertRaises(FileNotFoundError):
                validate_model_file(path.with_name("missing.pt"))

    def test_worker_routes_to_selected_device_and_preserves_results(self):
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        result = SimpleNamespace(orig_img=frame, boxes=[], speed={"inference": 2.0})
        model = Mock()
        model.predict.return_value = [result]
        worker = InferenceWorker(model, "board.png", 0.25, {}, "cuda:0")
        finished, errors, devices = [], [], []
        worker.finished.connect(lambda *args: finished.append(args))
        worker.error.connect(errors.append)
        worker.device_selected.connect(lambda *args: devices.append(args))
        with patch("app.mixins.inspection_mixin.select_device", return_value=InferenceDevice("cuda:0", "NVIDIA Orin")):
            worker.run()
        self.assertEqual(errors, [])
        self.assertEqual(devices, [("NVIDIA Orin", "")])
        model.predict.assert_called_once_with(source="board.png", conf=0.25, save=False, device="cuda:0")
        self.assertEqual(len(finished), 1)
        np.testing.assert_array_equal(finished[0][1], frame)

    def test_gpu_failure_is_reported_without_cpu_retry(self):
        model = Mock()
        model.predict.side_effect = RuntimeError("CUDA out of memory")
        worker = InferenceWorker(model, "board.png", 0.25, {}, "auto")
        errors = []
        worker.error.connect(errors.append)
        with patch("app.mixins.inspection_mixin.select_device", return_value=InferenceDevice("cuda:0", "NVIDIA Orin")):
            worker.run()
        self.assertEqual(model.predict.call_count, 1)
        self.assertIn("CUDA out of memory", errors[0])


if __name__ == "__main__":
    unittest.main()
