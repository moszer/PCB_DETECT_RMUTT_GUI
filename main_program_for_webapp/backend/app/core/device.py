"""Hardware device selection (MPS, CUDA, CPU) and model validation."""
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class InferenceDevice:
    device: str
    label: str
    detail: str = ""


def select_device(preference: Optional[str] = None) -> InferenceDevice:
    """Select inference device (CUDA, MPS, or CPU).
    
    Prefers CUDA, then Apple MPS, then CPU fallback.
    Explicit requests (e.g. 'cuda:0', 'mps', 'cpu') do not fall back silently.
    """
    preference = (preference or os.environ.get("PCB_DEVICE", "auto")).strip().lower()
    if preference == "cpu":
        return InferenceDevice("cpu", "CPU", "CPU selected explicitly.")
    if preference in ("cuda", "0"):
        preference = "cuda:0"
    if preference not in ("auto", "mps") and not re.fullmatch(r"cuda:\d+", preference):
        raise ValueError("Choose auto, cpu, mps, or cuda:<index> (e.g. cuda:0).")

    import torch

    def apple_device() -> InferenceDevice:
        mps = getattr(getattr(torch, "backends", None), "mps", None)
        if mps is not None and mps.is_available():
            return InferenceDevice("mps", "Apple GPU (MPS)", "Metal Performance Shaders active.")
        reason = (
            "This PyTorch installation has no MPS support."
            if mps is None or not mps.is_built() else
            "PyTorch cannot access Metal GPU on this system."
        )
        raise RuntimeError(
            f"{reason} On Apple Silicon, use native arm64 Python with compatible macOS / PyTorch."
        )

    if preference == "mps":
        return apple_device()

    if not torch.cuda.is_available():
        reason = (
            "PyTorch has no CUDA support."
            if torch.version.cuda is None else
            "PyTorch cannot access an NVIDIA CUDA GPU."
        )
        if preference == "auto":
            try:
                return apple_device()
            except RuntimeError as exc:
                return InferenceDevice("cpu", "CPU (GPU unavailable)", f"{reason}\n{exc}")
        raise RuntimeError(
            f"{reason} Check NVIDIA driver or Jetson JetPack compatibility."
        )

    index = 0 if preference == "auto" else int(preference.split(":")[1])
    count = torch.cuda.device_count()
    if index >= count:
        raise RuntimeError(f"Requested cuda:{index}, but only {count} CUDA GPU(s) visible.")
    name = torch.cuda.get_device_name(index)
    return InferenceDevice(f"cuda:{index}", f"NVIDIA {name} (cuda:{index})", f"VRAM: {count} GPU(s)")


def validate_model_file(model_path: str) -> Path:
    """Validate that the YOLO model exists and is not a Git LFS pointer."""
    path = Path(model_path)
    if not path.is_file():
        raise FileNotFoundError(f"Model file not found: {path}")
    with path.open("rb") as stream:
        header = stream.read(256)
    if header.startswith(b"version https://git-lfs.github.com/spec/v1"):
        raise ValueError(
            f"{path.name} is a Git LFS pointer, not actual weights. Run 'git lfs pull'."
        )
    return path
