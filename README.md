# RMUTT PCB AOI Station — YOLO component inspection

An **automated optical inspection (AOI)** station for printed circuit boards, built as an
undergraduate project at **RMUTT** (Rajamangala University of Technology Thanyaburi,
มหาวิทยาลัยเทคโนโลยีราชมงคลธัญบุรี).

A camera on an **XY stage** visits every test point on a board, a **YOLO** model finds the
components in each image, and each result is compared with a taught **golden reference** to
give a **PASS / FAIL** verdict. Missing, wrong and extra parts are listed.

The repository holds two stations that share the model and the matching logic:

| | Web station (recommended) | Desktop station |
| --- | --- | --- |
| Folder | [`main_program_for_webapp/`](main_program_for_webapp/) | [`main_program/`](main_program/) |
| Stack | FastAPI + Next.js 16, any browser on the LAN | PyQt6 desktop app |
| XY stage scanning | ✅ boards, marked points, grids | ✅ grid scan ([docs/AOI.md](docs/AOI.md)) |
| Runs on | macOS, Linux, NVIDIA Jetson, Docker | macOS, Jetson |

---

## Quick start (web station)

```bash
git clone https://github.com/moszer/PCB_DETECT_RMUTT_GUI.git
cd PCB_DETECT_RMUTT_GUI/main_program_for_webapp
./install.sh        # detects macOS / Linux / Jetson and installs the matching PyTorch
./run_web.sh        # add --prod on Jetson or for daily use
```

Open **http://localhost:3001**. Other devices on the same network (e.g. an iPad at the
machine) use the LAN address that `run_web.sh` prints.

- Step-by-step installation, Jetson notes, Docker and troubleshooting (in Thai):
  [main_program_for_webapp/INSTALL.md](main_program_for_webapp/INSTALL.md)
- Try it without any hardware: `./docker-test.sh` builds the stack, runs the backend tests
  and smoke-tests a real inspection. Alternatively, click **จำลอง** (simulation) in the stage
  bar of a normal install.
- **Model weights are on Hugging Face:** [Moszer777/pcb-aoi-yolo-rmutt](https://huggingface.co/Moszer777/pcb-aoi-yolo-rmutt)
  holds every training run. `./install.sh` downloads `best.pt` from there when the checkout
  has none, and **Settings → YOLO model → Hugging Face** lists, downloads and switches to any
  other run. CLI: `cd backend && venv/bin/python -m app.core.hub --list`.
  The desktop station's `best.pt`/`exp.pt` at the repo root use **Git LFS**
  (`git lfs install && git lfs pull` if a `.pt` file is only ~130 bytes).

`run_web.sh` prints the RMUTT banner. It then checks Python/Node, the model, `.env`,
library versions against the requirements and free ports, and starts both services. Finally
it summarizes what is running: model and AI hardware, camera, stage, AI assistant, OCR,
data counts and URLs. Options:

| Option | Effect |
| --- | --- |
| `--prod` | Build the frontend once and serve it (faster, less RAM) |
| `--update` | Upgrade Python/JS libraries before starting (PyTorch is left alone) |
| `--no-check` | Skip the library check |

**Update to the latest version:** `./update.sh` pulls from GitHub, runs `install.sh` only when
libraries changed, and restarts the station with the same options (`--background` over SSH,
`--no-restart` to only pull). It refuses while a scan is running or when tracked files were
edited locally; your data, `.env` and models are untouched.

---

## Web station features

The UI is in Thai. The sidebar has seven pages.

| Page | What it does |
| --- | --- |
| **สแกน AOI** (AOI scan) | Main workflow. Create or open a board, home the stage, jog to each test point and mark it (a reference photo is captured automatically), teach the expected parts, then scan the whole board |
| **ตรวจภาพเดี่ยว** (single inspection) | Inspect a live camera frame or an uploaded image against a reference profile, with click-to-inspect boxes |
| **ชุดข้อมูลเทรน** (training data) | Mark the four corners of a board and the stage photographs the whole board automatically. Edit labels in the browser (marquee select, bulk delete), then download a YOLO dataset with a train/val split |
| **โปรไฟล์อ้างอิง** (references) | Golden reference profiles (single image and AOI grid); import the desktop `Refs.json` |
| **ประวัติ & Yield** (history) | Every scan and single inspection with board/point yield, filters and CSV export |
| **ประสิทธิภาพเครื่อง** (performance) | Live CPU usage/clock per core, GPU, RAM/swap, temperatures, power rails, fan and over-current events. On Jetson it also sets the power mode (nvpmodel), max clocks (jetson_clocks) and fan (auto quiet/cool or fixed 20–100 %) after a one-time `sudo ./scripts/jetson/install-power-control.sh` |
| **ตั้งค่าสถานี** (settings) | Choose the model (also finds Ultralytics `runs/*/weights`), choose the compute device (MPS / CUDA / CPU), set stage soft limits and station info |

### AOI scan page

- **Workflow stepper:** ① board → ② stage ready → ③ mark points → ④ scan. A hint under it
  says what to do next.
- **Boards:** named sets of test points stored on the station. They autosave, and a board must
  be opened before marking.
- **Jog on the live view:** a jog pad over the camera image works with press-and-hold on touch
  screens. Keyboard shortcuts: arrows (Shift = ×10), `M` mark, `Space` test snap, `H` HOME,
  `1`–`5` zoom, `?` help.
- **Scan dock under the camera:** start/stop, progress, and one thumbnail per point. The
  thumbnails show the plan before a scan and turn into PASS/FAIL as the results arrive.
- **Multi-frame inspection:** each point is confirmed over N frames, and you can watch every
  frame as it is analyzed.
- **Point detail:** per-component status, **OCR of part markings** (Apple Vision on macOS,
  tesseract on Linux), and a rough **3D height map** from camera motion stereo.
- **Grid scan:** serpentine raster with a golden-board teach run.
- **Operator / engineer modes:**
  - Operator mode shows only *pick board → start → big PASS/FAIL*.
  - Engineer mode keeps marking, references and parameters.
- **Guided tour** on the first visit, replayable from `?`.
- Unavailable buttons turn grey with a lock and the reason, e.g. "กด HOME สเตจก่อน".

### Station-wide

- **AI assistant:** a chat button on every page. It answers questions about the station's
  live data (status, runs, boards, references, datasets, models, settings), can read part
  markings, and can navigate between pages. It also has per-board chat ("what is this board
  for?"), saved chat history and sound effects. It uses Google Gemini, with automatic model
  fallback, or OpenRouter.
- **Open on a phone / from anywhere:** a QR button on every page lists the station's LAN and
  Tailscale links with QR codes. Settings → *เข้าใช้งานจากที่อื่น* logs in to Tailscale (login
  link as QR), and turns on HTTPS inside your tailnet (`tailscale serve`) or on the public internet
  (`tailscale funnel`, refused while the default passcode is in use). Only the station's own entry is
  touched; other serve/funnel entries on the machine are left alone.
- **Image zoom:** result images (point detail, board inspection, history) zoom with the wheel,
  pinch, double-click or the +/− buttons, and pan by dragging.
- **Operator control lease:** only one browser controls the stage at a time; others see a
  *view-only* banner. **STOP** always works from any device.
- **Camera:** MJPEG live stream with a snapshot fallback. Format and crop are configurable
  (default 4K → 2160×2160 square crop, remembered).
- Light/dark theme, splash screen with the RMUTT logo, sound effects, and touch-sized controls
  for tablets.

### Configuration — `main_program_for_webapp/backend/.env`

The AI key can also be set in the browser under **Settings → ผู้ช่วย AI** (test, save,
remove). It applies at once, is written to `backend/.env`, and is never sent back to the
browser (only a masked hint). It requires the operator lease (station passcode).


Created from `.env.example` by `install.sh`. The file is git-ignored; never commit keys.

```bash
PCB_OPERATOR_PASSCODE=change-me     # passcode to take control (default rmutt-aoi)
AI_PROVIDER=gemini                  # or openrouter
GEMINI_API_KEY=...                  # https://aistudio.google.com/apikey
PCB_DEVICE=auto                     # auto | cuda:0 | mps | cpu
PCB_CAMERA_SIMULATION=1             # software test camera (Docker, no webcam)
PCB_MODEL_REPO=Moszer777/pcb-aoi-yolo-rmutt   # Hugging Face repo with the weights
PCB_MODEL_FILE=best.pt              # file install.sh downloads when best.pt is missing
HF_TOKEN=...                        # only for a private repo (read access)
```

Ports can be changed with `PCB_FRONTEND_PORT` / `PCB_BACKEND_PORT` (defaults 3001 / 8000).

### Architecture

```
Browser (Next.js 16 · React 19 · Tailwind 4)          :3001
   │   /api/* proxied by Next  ·  WebSocket /ws/status (stage, scan progress, frames)
   ▼
FastAPI backend                                        :8000
   routers/  system · auth · camera · inspection · aoi · references · history · datasets · chat · ws
   services/ inference (YOLO) · camera · machine (serial / simulation) · aoi_scan · dataset
             depth · chat (Gemini/OpenRouter) · agent (tool calling) · storage · point_set_store
   core/     inspection matching · motion protocol v2 · device selection · OCR · depth
   │
   ├── Ultralytics YOLO on Apple MPS / CUDA / CPU
   ├── Arduino Nano XY stage, protocol v2 @ 9600 baud (or the built-in simulator)
   └── SQLite + files in backend/data/ (runs, references, boards, datasets, chat history)
```

Details:
[backend/README.md](main_program_for_webapp/backend/README.md) (API, motion protocol, lease, tests) ·
[frontend/README.md](main_program_for_webapp/frontend/README.md) (UI structure) ·
[docs/WEB_AOI.md](docs/WEB_AOI.md) (Thai project report for the web edition).

---

## How inspection works

Detection alone doesn't tell you whether a board is good, so both stations add a comparison step:

1. **Detect:** YOLO inference produces raw detections (`x, y, label, conf, box`).
2. **Match:** each reference component is greedily matched to its nearest unclaimed detection.
   - Within the match distance **and** the right label → `OK`.
   - Right place but wrong class → **`WRONG`**, not `MISSING`. This matters when a board is
     populated, but populated incorrectly.
3. **Verdict:** `PASS` / `FAIL` with `ok` / `missing` / `wrong` / `extra` lists.
   - In the web station, a point with no taught reference gives `REVIEW` (detection only).
   - Multi-frame mode confirms a part only when it is seen in at least a set share of frames.
4. **Log:** results go to SQLite and the History page (web), or to `inspection_log.csv` (desktop).

---

## Repository layout

```
main_program_for_webapp/   Web station
  install.sh  run_web.sh   one-command install / start (macOS, Linux, Jetson)
  docker-compose*.yml      Docker (+ hardware passthrough, + Jetson GPU), docker-test.sh
  backend/                 FastAPI app, tests/ (pytest), requirements*.txt, .env.example
  frontend/                Next.js app (src/app, src/components, src/lib, src/hooks)
  scripts/console.py       run_web.sh banner, library check, status summary
  INSTALL.md               installation guide (Thai)
main_program/              Desktop station (PyQt6): gui_test.py, app/, qa/ tests
best.pt  exp.pt  Refs.json Model weights (Git LFS) and the desktop reference profile
training/                  train.py, prepare.py, data.yaml, main_label/ (labelled images),
                           image_dataset/, base weights yolo26*.pt, trained/, runs/
tools/                     predict_image.py (one image) · webcam_detect.py (live webcam)
assets/                    logo-rmutt.png · ascii-art.txt · test_images/ (pass.jpg, fail.png)
                           samples/ · board_photos/
docs/                      AOI.md · NVIDIA.md · WEB_AOI.md · web-audit/ · thesis/
scripts/archive/           one-off helper scripts kept for reference
```

Companion to [PCB_DETECT_RMUTT](https://github.com/moszer/PCB_DETECT_RMUTT).

---

## Desktop station (PyQt6)

The original single-image station. It loads a board image (file, folder, drag & drop or
webcam), runs YOLO, and compares the result with `Refs.json`. In edit mode you click on the
board to edit the reference.

```bash
python main_program/gui_test.py    # entry point, despite the name
```

### Installation

Use **Python 3.12** and create a separate virtual environment for this project.
The repository uses Git LFS for `.pt` model weights, so Git LFS must be installed
before downloading the model files.

> `gui_test.py` is the application entry point despite its name. Automated GUI
> and device-routing tests live in `main_program/qa/`.

#### macOS (Apple Silicon or Intel)

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

#### NVIDIA Jetson Orin Nano / Orin Nano Super

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
python main_program/check_nvidia.py --model best.pt --image assets/test_images/pass.jpg
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
Detailed notes for the tested CUDA 13 environment are in [docs/NVIDIA.md](docs/NVIDIA.md).

#### Installation troubleshooting

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
python3 training/prepare.py    # split training/main_label/ into train/val (80/20, moves files in place)
python3 training/train.py      # train (edit weights + hyperparams inside the script)
python3 tools/predict_image.py   # single-image inference (best.pt)
python3 tools/webcam_detect.py   # standalone webcam detection (best.pt)
```

### Requirements

The root [requirements.txt](requirements.txt) contains the common Python
dependencies. [requirements-nvidia-cu130.txt](requirements-nvidia-cu130.txt)
selects the CUDA wheels for the tested JetPack 7.2.1 target.

Common dependency pins (exercised with Python 3.12 on the local Jetson):

`ultralytics==8.4.92` · `opencv-python==5.0.0.93` · `PyQt6==6.11.0` ·
`torch==2.13.0` · `torchvision==0.28.0` · `numpy==2.5.1` · `pillow==12.3.0`

The YOLO backend is imported **lazily** — if `ultralytics` is missing the UI still launches
in a degraded view-only state instead of crashing.

---

### The GUI

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

#### Architecture

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

### Updating the desktop app

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
if requirements changed, follow the platform instructions above, especially for
Jetson/CUDA. Keep Git LFS installed for model downloads.

For older copies that do not yet have the Updates button, first pull the version
that includes this feature with `git pull --ff-only origin main`, then reopen the
application.

---

## Dataset — 23 classes

```
ant  button  capacitor  capacitor_0  chip  connector  connector_0  connector_1
connector_2  diode  hole  inductor  input  led  resistor  resistor_8  sdcard
sot21  sot23  sot31  sot32  usb  xtal
```

Labelled in Label Studio; `training/main_label/` holds the images and YOLO-format labels,
`prepare.py` produces the 80/20 split. The web station's **ชุดข้อมูลเทรน** page can also capture and label new boards and export them in the same YOLO format.

## Training

```python
from ultralytics import YOLO

model = YOLO("training/yolo26x.pt")
model.train(
    data="training/data.yaml", epochs=300, imgsz=640, batch=16, device=0,
    optimizer="AdamW", lr0=0.001, lrf=0.01, cos_lr=True, patience=50,
    hsv_h=0.015, hsv_s=0.7, hsv_v=0.4, degrees=10, translate=0.1,
    scale=0.5, shear=2.0, flipud=0.5, fliplr=0.5, mosaic=1.0, mixup=0.1,
    cache=True, amp=True, workers=8, plots=True,
)
```

On Colab, mount Drive, `os.chdir` into the project, `pip install ultralytics`, and rewrite
`training/data.yaml` with an absolute `path:` before training.

> **The run committed in `training/trained/` is a smoke test, not the real model** — `args.yaml`
> shows 10 epochs on `device: cpu` with `yolo26n.pt`, and `results.csv` reports mAP 0.0
> throughout. Retrain before trusting any numbers from it. `training/trained/best.pt` and
> `training/trained/last.pt` are Git LFS pointers; `training/trained/best.onnx` is the real exported graph.

| Weights | Size | Speed | Accuracy |
| --- | --- | --- | --- |
| `training/yolo26n.pt` | Nano | Fastest | Lowest |
| `yolo26s.pt` | Small | Fast | Low |
| `yolo26m.pt` | Medium | Medium | Medium |
| `yolo26l.pt` | Large | Slow | High |
| `training/yolo26x.pt` | XLarge | Slowest | Highest |

## Key files

| File | Role |
| --- | --- |
| `Refs.json` | Reference profile — expected components as `{x, y, label}` |
| `training/data.yaml` | Dataset config, 23 classes |
| `inspection_log.csv` | Generated inspection history |
| `training/trained/best.onnx` | Exported model graph |
| `main_program_for_webapp/backend/data/` | Web station data: `inspection.db`, run images, references, boards, datasets (git-ignored) |
| `main_program_for_webapp/backend/.env` | Web station secrets and options (git-ignored, from `.env.example`) |
