# PCB Defect Inspection Station (YOLO + PyQt6)

**AOI Scan:** connect the Nano XY stage (protocol v2, 9600 baud), home/jog,
scan a serpentine grid, and capture/inspect each position. Simulation, per-point
golden-board references, STOP and saved run reports are included. See [AOI setup](AOI.md).

A desktop **inspection station** for printed circuit boards. It runs a YOLO detector over a
board image, matches what it found against a **reference profile** of expected components,
and returns a **PASS / FAIL** verdict with the missing, wrong and extra parts listed.

Companion desktop app to [PCB_DETECT_RMUTT](https://github.com/moszer/PCB_DETECT_RMUTT).
Undergraduate project at **RMUTT** (Rajamangala University of Technology Thanyaburi).

---

## What it does

Detection alone doesn't tell you whether a board is good. This app adds the comparison step:

1. **Detect** — YOLO inference over the loaded image → raw detections (`x, y, label, conf, box`)
2. **Match** — each reference point is greedily matched to its nearest unclaimed detection.
   If that detection is within `match_dist` pixels **and** carries the right label, it's `OK`.
   Right place but wrong class is reported as **`WRONG`**, not `MISSING` — a distinction that
   matters when a board is populated but populated incorrectly.
3. **Verdict** — `PASS` / `FAIL` plus `ok` / `missing` / `wrong` / `extra` lists
4. **Log** — appended to `inspection_log.csv` (time, station, operator, verdict, counts)

The reference profile lives in `Refs.json` as `{"x", "y", "label"}` points and is edited in
the app by clicking on the board in edit mode.

## Updating the desktop app

Open **Updates** in the top bar. The dialog fetches GitHub `main`, shows the
installed Git tag/commit and the latest revision, and lists up to 20 new commits.
Click **Install update**, then **Close application** and launch the app again.
Checks and installation run in the background. Stop camera capture and finish
the current inspection before installing.

Automatic updates require Git, a clone of this repository, the `main` branch,
and no edits to tracked files. Local commits, unfinished merges/rebases, and
diverged history require resolving the checkout manually. Untracked models,
captures, settings, and logs are retained; if a new upstream file would collide
with an untracked or ignored file, installation stops. The updater never runs
`reset`, `clean`, or an automatic stash. If upstream replaces a tracked model,
JSON, or CSV file, its previous contents are backed up under
`.git/pcb-update-backups/`; the dialog reports that location.

An update installs exactly the revision shown in the dialog. If the checkout
or fetched target changes after review, check again. GitHub `main` can contain
commits newer than the latest release tag. ZIP downloads must be updated manually
or replaced by a Git clone. Python dependencies are not installed automatically:
if requirements changed, follow the platform instructions below, especially for
Jetson/CUDA. Keep Git LFS installed for model downloads.

For older copies that do not yet have the Updates button, first pull the version
that includes this feature with `git pull --ff-only origin main`, then reopen the
application.

## Installation

Use **Python 3.12** and create a separate virtual environment for this project.
The repository uses Git LFS for `.pt` model weights, so Git LFS must be installed
before downloading the model files.

> `gui_test.py` is the application entry point despite its name. Automated GUI
> and device-routing tests live in `main_program/qa/`.

### macOS (Apple Silicon or Intel)

On Apple Silicon (M-series), the application supports **Apple GPU inference
through PyTorch MPS / Metal**. Auto selects CUDA when available, otherwise MPS,
then CPU. Use native arm64 Python on Apple Silicon. MPS availability depends on
the installed macOS and PyTorch versions; CPU remains available on all platforms.
NVIDIA CUDA is not available on current macOS systems. If your Mac is only being
used to prepare a Jetson, install the application on the Jetson using the next section.

Install Apple's command-line tools, Python 3.12 and Git LFS. If Homebrew is not
installed, follow the [official Homebrew installation guide](https://docs.brew.sh/Installation).

```bash
xcode-select --install
brew install python@3.12 git git-lfs
git lfs install
```

Clone the project and download the real model weights:

```bash
git clone https://github.com/moszer/PCB_DETECT_RMUTT_GUI.git
cd PCB_DETECT_RMUTT_GUI
git lfs pull
```

Create the environment and install the Python libraries:

```bash
python3.12 -m venv main_program/.venv
source main_program/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main_program/gui_test.py
```

In **Station & model → Processor**, select **Auto (prefer GPU)** or
**Apple Silicon GPU (MPS)**. A previously saved CPU preference is kept until you
change it. The selected device appears under Processor and beside inference
timing. Explicit MPS mode reports unavailable devices or runtime errors; it does
not silently retry on CPU. If a model operation is unsupported or GPU memory is
full, select CPU. Camera capture and UI drawing are unaffected by this setting.

Check MPS support using the same Python environment that launches the GUI:

```bash
python -c "import platform, torch; print(platform.machine()); print('MPS built:', torch.backends.mps.is_built()); print('MPS available:', torch.backends.mps.is_available())"
```

Both MPS checks should be `True`. The command-line tools also accept
`PCB_DEVICE=mps`. See [PyTorch's MPS documentation](https://docs.pytorch.org/docs/stable/notes/mps.html)
for platform requirements. On first camera use, macOS may ask for permission;
allow it for Terminal or the application used to launch the project.

### NVIDIA Jetson Orin Nano / Orin Nano Super

The tested target is **Jetson Orin Nano Super, JetPack 7.2.1 / L4T 39.2.1,
Python 3.12 and CUDA 13**. JetPack provides the NVIDIA driver, CUDA, cuDNN and
TensorRT. Install JetPack before creating the Python environment. For a fresh
board, follow NVIDIA's [Orin Nano quick-start guide](https://docs.nvidia.com/jetson/orin-nano-devkit/user-guide/quick_start.html).

Check the installed L4T release:

```bash
cat /etc/nv_tegra_release
```

For the tested JetPack 7.2.1 setup, install the system libraries required by
Python, Qt/X11, OpenCV and Git LFS:

```bash
sudo apt update
sudo apt install -y nvidia-jetpack python3-venv python3-pip git git-lfs \
  libxcb-cursor0 libxkbcommon-x11-0 libxcb-xinerama0 libgl1 libglib2.0-0
sudo reboot
```

After reboot, clone the project and retrieve the model weights:

```bash
git clone https://github.com/moszer/PCB_DETECT_RMUTT_GUI.git
cd PCB_DETECT_RMUTT_GUI
git lfs install
git lfs pull
```

Create the environment and install the common libraries first, then install the
CUDA 13 PyTorch wheels explicitly. The second command is required because a
generic PyTorch installation can leave Jetson running on the CPU.

```bash
python3 -m venv main_program/.venv
source main_program/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install --upgrade -r requirements-nvidia-cu130.txt
```

Verify real GPU operations and then verify this project's model:

```bash
python main_program/check_nvidia.py
python main_program/check_nvidia.py --model best.pt --image test/pass.jpg
```

Both commands must report `PASS`, and the model check must report
`YOLO parameters on cuda:0`. Start the GUI with:

```bash
python main_program/gui_test.py
```

In **Station & model → Processor**, use **Auto (prefer GPU)** or
**NVIDIA GPU (CUDA:0)**. The selected device also appears beside the inference
time in the status bar.

JetPack 5.x and 6.x use different Python, CUDA, PyTorch and torchvision builds.
Do not install `requirements-nvidia-cu130.txt` on those releases. Select the
matching packages from the [NVIDIA PyTorch compatibility table](https://docs.nvidia.com/deeplearning/frameworks/install-pytorch-jetson-platform-release-notes/pytorch-jetson-rel.html)
and the [Ultralytics Jetson guide](https://docs.ultralytics.com/guides/nvidia-jetson/).
Detailed notes for the tested CUDA 13 environment are in [NVIDIA.md](NVIDIA.md).

### Installation troubleshooting

- `Could not load the Qt platform plugin "xcb"` or a message mentioning
  `xcb-cursor0`: install the Jetson system packages shown above, then restart
  the GUI. Do not install these Ubuntu packages on macOS.
- `Unable to load model`, `invalid load`, or a `.pt` file of roughly 130 bytes:
  the file is a Git LFS pointer. Run `git lfs install` and `git lfs pull` from
  the repository root.
- `CUDA available: False`: confirm that JetPack is installed, reboot, activate
  the same virtual environment used by the GUI, reinstall
  `requirements-nvidia-cu130.txt`, and run `main_program/check_nvidia.py` again.
- An SM 8.7 warning can appear with the tested upstream PyTorch wheel on Orin.
  The project's CUDA convolution, torchvision NMS and actual YOLO model checks
  passed on this setup; the diagnostic command remains the source of truth after
  any JetPack or PyTorch upgrade.

Other scripts:

```bash
python3 prepare.py    # split main_label/ into train/val (80/20, moves files in place)
python3 train.py      # train (edit weights + hyperparams inside the script)
python3 test.py       # single-image inference
python3 camera.py     # standalone webcam detection
```

## Requirements

The root [requirements.txt](requirements.txt) contains the common Python
dependencies. [requirements-nvidia-cu130.txt](requirements-nvidia-cu130.txt)
selects the CUDA wheels for the tested JetPack 7.2.1 target.

Common dependency pins (exercised with Python 3.12 on the local Jetson):

`ultralytics==8.4.92` · `opencv-python==5.0.0.93` · `PyQt6==6.11.0` ·
`torch==2.13.0` · `torchvision==0.28.0` · `numpy==2.5.1` · `pillow==12.3.0`

The YOLO backend is imported **lazily** — if `ultralytics` is missing the UI still launches
in a degraded view-only state instead of crashing.

---

## The GUI

A "Clean Industrial Dashboard" layout: a top bar carrying branding and a global
**TOTAL / PASS / FAIL / YIELD** KPI strip, above a three-column body —

- **left, 280px** — collapsible accordion: Inspection, Camera, Display, Reference Profile,
  Station & Model
- **center** — the image viewport, dominant, with a browse bar above it
  (Open Folder · folder name · ◀ *n / total* ▶ stepper), a floating PASS/FAIL verdict badge,
  and an on-demand history panel below
- **right, 320px** — contextual detection panel, hidden until you click a box

Images arrive by file picker, folder picker, drag & drop (file *or* folder), or a webcam
capture — every route funnels through `open_image_path()`, which indexes the containing
folder so the stepper can walk the rest of it, each step a full inspection.

**Overlays** are recomposited on every redraw without re-running inference: thin,
semi-transparent class-colored detection boxes (IC/connector blue, capacitor amber,
resistor emerald, everything else slate) plus small OK / WRONG / MISSING markers at each
reference point.

**Tunable in the GUI:** confidence 1–100% (default 25%), match distance 5–250 px
(default 50 px), fail-on-extra toggle, zoom 20–800%.

### Architecture

The main window is composed from mixins rather than one monolithic class:

```
DefectDetectionGUI              main_program/app/window.py
├── InteractionMixin            shortcuts, drag & drop, Ctrl+scroll zoom, fades
├── UIMixin                     builds top bar, panels, viewport, status bar
├── ModelReferenceMixin         lazy YOLO load, Refs.json, undo/redo, toasts
├── InspectionMixin             debounced inference, overlay compositing, verdict reveal
├── BrowseMixin                 folder indexing, Prev/Next, open_image_path()
├── CameraMixin                 threaded webcam preview, capture-then-inspect
├── HistoryMixin                CSV logging, animated counters, yield
└── SettingsMixin               persist/restore settings.json
```

Qt stylesheets can't animate, so motion lives in Python:
`styles.py` (token-based light/dark design system) ·
`animations.py` (`fade_in`, `pulse_glow`, `animate_number`, `animate_bar`) ·
`components.py` (custom-painted `YieldBar`, `BusyOverlay`, `CollapsibleCard`, `ToggleSwitch`) ·
`toast.py` · `splash.py`

`widgets.py` holds `ReferenceLabel`, a `QLabel` that maps click coordinates from displayed
space back to original-image space across zoom levels — click-to-place reference points in
edit mode, click-to-inspect a detection otherwise.

The matching algorithm itself is isolated in `main_program/app/inspection_logic.py`:
`evaluate_inspection()`, `draw_detections_overlay()`, `draw_reference_overlay()`,
`detection_status_map()`.

---

## Dataset — 23 classes

```
ant  button  capacitor  capacitor_0  chip  connector  connector_0  connector_1
connector_2  diode  hole  inductor  input  led  resistor  resistor_8  sdcard
sot21  sot23  sot31  sot32  usb  xtal
```

Labelled in Label Studio; `main_label/` holds the images and YOLO-format labels,
`prepare.py` produces the 80/20 split.

## Training

```python
from ultralytics import YOLO

model = YOLO("yolo26x.pt")
model.train(
    data="data.yaml", epochs=300, imgsz=640, batch=16, device=0,
    optimizer="AdamW", lr0=0.001, lrf=0.01, cos_lr=True, patience=50,
    hsv_h=0.015, hsv_s=0.7, hsv_v=0.4, degrees=10, translate=0.1,
    scale=0.5, shear=2.0, flipud=0.5, fliplr=0.5, mosaic=1.0, mixup=0.1,
    cache=True, amp=True, workers=8, plots=True,
)
```

On Colab, mount Drive, `os.chdir` into the project, `pip install ultralytics`, and rewrite
`data.yaml` with an absolute `path:` before training.

> **The run committed in `trained/` is a smoke test, not the real model** — `args.yaml`
> shows 10 epochs on `device: cpu` with `yolo26n.pt`, and `results.csv` reports mAP 0.0
> throughout. Retrain before trusting any numbers from it. `trained/best.pt` and
> `trained/last.pt` are Git LFS pointers; `trained/best.onnx` is the real exported graph.

| Weights | Size | Speed | Accuracy |
| --- | --- | --- | --- |
| `yolo26n.pt` | Nano | Fastest | Lowest |
| `yolo26s.pt` | Small | Fast | Low |
| `yolo26m.pt` | Medium | Medium | Medium |
| `yolo26l.pt` | Large | Slow | High |
| `yolo26x.pt` | XLarge | Slowest | Highest |

## Key files

| File | Role |
| --- | --- |
| `Refs.json` | Reference profile — expected components as `{x, y, label}` |
| `data.yaml` | Dataset config, 23 classes |
| `inspection_log.csv` | Generated inspection history |
| `trained/best.onnx` | Exported model graph |
