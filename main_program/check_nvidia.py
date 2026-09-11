"""Check real CUDA execution, optionally including the project's YOLO model.

Run with the same Python environment as gui_test.py, outside restricted sandboxes.
This command does not write inspection history or modify GUI settings.
"""
import argparse
import platform
from pathlib import Path

from app.inference_runtime import select_device, validate_model_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, help="Optional local .pt weights to test")
    parser.add_argument("--image", type=Path, help="Required with --model")
    args = parser.parse_args()
    if bool(args.model) != bool(args.image):
        parser.error("--model and --image must be supplied together")

    print(f"Python: {platform.python_version()} ({platform.machine()})")
    for path in (Path("/proc/device-tree/model"), Path("/etc/nv_tegra_release")):
        if path.exists():
            print(path.read_text().rstrip("\x00").strip())
    try:
        import torch
        import torchvision

        print(f"PyTorch: {torch.__version__}; torchvision: {torchvision.__version__}")
        print(f"CUDA build: {torch.version.cuda}")
        device = select_device("cuda:0")
        print(f"Device: {device.label}")
        print(f"Compute capability: {torch.cuda.get_device_capability(0)}")
        print(f"Compiled architectures: {torch.cuda.get_arch_list()}")
        with torch.inference_mode():
            frame = torch.ones((1, 3, 64, 64), device=device.device)
            conv = torch.nn.Conv2d(3, 8, 3).to(device.device)
            output = conv(frame).relu()
            if not torch.isfinite(output).all().item():
                raise RuntimeError("CUDA convolution produced non-finite results")
            boxes = torch.tensor([[0., 0., 10., 10.], [1., 1., 11., 11.]], device=device.device)
            scores = torch.tensor([0.9, 0.8], device=device.device)
            keep = torchvision.ops.nms(boxes, scores, 0.5)
            if keep.tolist() != [0]:
                raise RuntimeError("CUDA NMS returned an unexpected result")
            torch.cuda.synchronize()
        print("PASS: CUDA convolution and torchvision NMS")

        if args.model:
            validate_model_file(args.model)
            if not args.image.is_file():
                raise FileNotFoundError(f"Image not found: {args.image}")
            from ultralytics import YOLO

            model = YOLO(str(args.model))
            # Warm-up followed by a measured inference on the same source.
            for _ in range(2):
                results = model.predict(source=str(args.image), device=device.device, save=False, verbose=False)
            if next(model.model.parameters()).device.type != "cuda":
                raise RuntimeError("Model parameters are not on CUDA")
            print(f"PASS: YOLO parameters on {next(model.model.parameters()).device}")
            for result in results:
                if result.boxes is None or result.boxes.data.device.type != "cuda":
                    raise RuntimeError("Expected CUDA detection output")
                print(f"Detections: {len(result.boxes)}; inference: {result.speed['inference']:.1f} ms")
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}")
        print("Check NVIDIA driver/device access and the PyTorch/torchvision build for your JetPack.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
