# PCB Defect Inspection Station (YOLO + PyQt6)

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

## Running

```bash
pip install -r requirements.txt
python3 main_program/gui_test.py
```

> `gui_test.py` is the **application entry point** despite the name — there is no automated
> test suite in this repo; verification is manual against `test/pass.jpg` and `test/fail.png`.

Other scripts:

```bash
python3 prepare.py    # split main_label/ into train/val (80/20, moves files in place)
python3 train.py      # train (edit weights + hyperparams inside the script)
python3 test.py       # single-image inference
python3 camera.py     # standalone webcam detection
```

## Requirements

Pinned to the tested Python 3.14 venv:

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
