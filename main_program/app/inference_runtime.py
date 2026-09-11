"""Shared, lazy NVIDIA device selection for the GUI and command-line tools."""
import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InferenceDevice:
    device: str
    label: str
    detail: str = ""


def select_device(preference=None):
    """Prefer CUDA in auto mode; explicit CUDA requests never fall back to CPU.

    Torch stays lazy so the GUI can open without the inference dependencies.
    CUDA execution errors are left to the caller, never retried silently on CPU.
    """
    preference = (preference or os.environ.get("PCB_DEVICE", "auto")).strip().lower()
    if preference == "cpu":
        return InferenceDevice("cpu", "CPU", "CPU selected explicitly.")
    if preference in ("cuda", "0"):
        preference = "cuda:0"
    if preference != "auto" and not re.fullmatch(r"cuda:\d+", preference):
        raise ValueError("Choose auto, cpu, or cuda:<index> (for example cuda:0).")

    import torch

    if not torch.cuda.is_available():
        reason = (
            "This PyTorch installation has no CUDA support."
            if torch.version.cuda is None else
            "PyTorch cannot access an NVIDIA CUDA GPU."
        )
        if preference == "auto":
            return InferenceDevice("cpu", "CPU (CUDA unavailable)", reason)
        raise RuntimeError(
            f"{reason} Install PyTorch/torchvision compatible with your NVIDIA "
            "driver or Jetson JetPack, and check GPU device access. "
            "Run check_nvidia.py for diagnostics."
        )

    index = 0 if preference == "auto" else int(preference.split(":")[1])
    count = torch.cuda.device_count()
    if index >= count:
        raise RuntimeError(f"Requested cuda:{index}, but only {count} CUDA GPU(s) are visible.")
    name = torch.cuda.get_device_name(index)
    return InferenceDevice(f"cuda:{index}", f"NVIDIA {name} (cuda:{index})")


def validate_model_file(model_path):
    """Reject missing weights and Git LFS placeholders before invoking YOLO."""
    path = Path(model_path)
    if not path.is_file():
        raise FileNotFoundError(f"Model file not found: {path}")
    with path.open("rb") as stream:
        header = stream.read(256)
    if header.startswith(b"version https://git-lfs.github.com/spec/v1"):
        raise ValueError(
            f"{path.name} is a Git LFS pointer, not the model weights. "
            "Install Git LFS, then run 'git lfs install' and 'git lfs pull' "
            "in the project folder to download the real model."
        )
