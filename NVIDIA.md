# NVIDIA GPU setup

The GUI, `test.py`, `camera.py`, and `train.py` prefer CUDA GPU 0 by default.
In **Station & model → Processor**, choose:

- **Auto (prefer NVIDIA)**: CUDA when available, otherwise CPU with a visible reason.
- **NVIDIA GPU (CUDA:0)**: require CUDA; report errors instead of retrying on CPU.
- **CPU**: explicitly use the CPU.

The GUI saves this choice. The device used appears under Processor and alongside
the inference timing. Image decoding, camera capture, and Qt drawing still run
on the CPU; the YOLO model runs on the selected device. FP32 is retained to avoid
changing precision and inspection thresholds.

For the root command-line scripts, set `PCB_DEVICE=auto`, `cpu`, or `cuda:0`
(other CUDA indices such as `cuda:1` are also accepted):

```bash
PCB_DEVICE=cuda:0 main_program/.venv/bin/python test.py
```

## Environment tested on 2026-09-11

- Jetson Orin Nano Super, aarch64, L4T 39.2.1 (JetPack 7.2.1).
- Python 3.12.3; PyTorch 2.13.0+cu130; torchvision 0.28.0+cu130.
- CUDA convolution, torchvision CUDA NMS, and the real `best.pt` passed.
- `test/pass.jpg`: 52 detections; approximately 167 ms on the measured warm
  inference. Timing varies with power mode, clocks, image size, and model.
- Model parameters and detection tensors were verified on `cuda:0`.
- The real GUI worker also passed Auto/CUDA → CPU → explicit CUDA switching
  in an offscreen Qt session, with 52 detections in each mode.

This validates the tested inference path, not every Orin model, training job,
camera driver, or JetPack release. CSI/Argus camera configuration and TensorRT
engine selection are not implemented by this change.

The current PyTorch build emits an SM 8.7 compatibility warning even though these
CUDA checks pass. NVIDIA explains upstream SM 8.0 kernel compatibility with Orin
in [this support response](https://forums.developer.nvidia.com/t/orin-agx-jp-7-2-pytorch-and-sm-87-support/378368/6).
The application does not suppress warnings. Re-run the checks below after
upgrading PyTorch, JetPack, or the model.

## Install for this CUDA 13 target

From the project root, in a Python 3.12 environment:

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-nvidia-cu130.txt
python main_program/check_nvidia.py --model best.pt --image test/pass.jpg
python main_program/gui_test.py
```

The second requirements file selects CUDA wheels explicitly. Do not apply it
unchanged to JetPack 5/6 or machines whose drivers do not support CUDA 13. For
other releases, install matching torch and torchvision using the
[NVIDIA compatibility table](https://docs.nvidia.com/deeplearning/frameworks/install-pytorch-jetson-platform-release-notes/pytorch-jetson-rel.html)
and [Ultralytics Jetson instructions](https://docs.ultralytics.com/guides/nvidia-jetson/).
The generic requirements file is not a universal Jetson dependency lock.

On Ubuntu, Qt's X11 backend also needs `libxcb-cursor0`:

```bash
sudo apt-get install libxcb-cursor0
```

## Diagnose CUDA and model loading

Use the same interpreter as the GUI, from a normal terminal with GPU access:

```bash
cd main_program
.venv/bin/python check_nvidia.py
.venv/bin/python check_nvidia.py --model ../best.pt --image ../test/pass.jpg
```

The first command checks actual CUDA computation and NMS, not only
`torch.cuda.is_available()`. The second also checks model inference, parameters,
and detection outputs. Both exit nonzero on failure and do not write inspection
history. A restricted sandbox/container may hide the GPU devices even when the
host terminal can use them.

If a `.pt` file is only around 130 bytes and begins with
`version https://git-lfs.github.com/spec/v1`, it is a Git LFS placeholder. From
the project root, download the actual weights:

```bash
sudo apt-get install git-lfs
git lfs install
git lfs pull
```

The GUI detects these placeholders before loading and shows the recovery steps.
The root `best.pt` was restored from this repository and verified against the
SHA-256 and size in its LFS pointer. Other LFS model files still require download.

## Automated checks

```bash
cd main_program
.venv/bin/python -m unittest discover -s qa -v
```

All 17 checks passed on the tested environment. These offscreen tests cover device selection, explicit GPU errors, CPU fallback,
worker routing, LFS validation, saved processor preferences, and GUI interactions.
They do not replace the physical GPU checks above.
