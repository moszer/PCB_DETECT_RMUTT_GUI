# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A YOLOv8-based PCB (Printed Circuit Board) defect inspection station. The system detects and validates electronic components on circuit boards using a trained YOLO model, comparing detections against a reference profile to produce PASS/FAIL verdicts.

## Running the Application

```bash
# Launch the main GUI inspection station (this is the app entry point,
# despite the "test" in the filename — there is no automated test suite)
python3 main_program/gui_test.py

# Split main_label/images+labels into train/val (80/20, random, moves files in place)
python3 prepare.py

# Train the model (edit the YOLO() weights arg / hyperparams directly in the script)
python3 train.py

# Test inference on a single image
python3 test.py

# Real-time webcam detection (standalone script; the GUI's Camera panel
# covers the capture-and-inspect workflow without leaving the app)
python3 camera.py
```

There is no automated test suite (no pytest config, no `test_*.py` files) — verification is manual, via `test.py` / the GUI against `test/pass.jpg` and `test/fail.png`.

## Installing Dependencies

```bash
pip install -r requirements.txt
```

Pinned for a Python 3.14 venv: `ultralytics`, `opencv-python` (imported as `cv2`), `PyQt6`, plus the `torch`/`torchvision`/`numpy`/`pillow` versions ultralytics resolves to. A pre-built venv also exists at `main_program/venv/`.

## Architecture

The GUI application uses **mixin-based composition**. The main window class `DefectDetectionGUI` inherits from multiple mixins:

```
DefectDetectionGUI (main_program/app/window.py)
    ├── InteractionMixin (mixins/interaction_mixin.py) — Keyboard shortcuts, drag & drop, Ctrl+scroll zoom, launch/theme fades
    ├── UIMixin (mixins/ui_mixin.py)         — Builds the top bar, 280px left accordion panel, center browse bar + viewport, 320px contextual right panel, toggleable history panel, status bar
    ├── ModelReferenceMixin (mixins/model_reference_mixin.py) — Lazy YOLO loading, Refs.json management, undo/redo, toasts
    ├── InspectionMixin (mixins/inspection_mixin.py)   — Debounced inference, overlay compositing, click-to-select detection detail, busy overlay, animated verdict reveal, zoom, image display
    ├── BrowseMixin (mixins/browse_mixin.py)           — Folder indexing (`load_image_folder`), Prev/Next stepping, `open_image_path()` (the single "show and inspect this file" entry point)
    ├── CameraMixin (mixins/camera_mixin.py)           — Live webcam preview on a QThread (`CameraWorker`), capture-then-inspect flow
    ├── HistoryMixin (mixins/history_mixin.py)         — CSV logging, animated counters/yield, history-row flash
    └── SettingsMixin (mixins/settings_mixin.py)       — Persist/restore settings.json on close
```

**Layout** ("Clean Industrial Dashboard"): a top bar (branding, global TOTAL/PASS/FAIL/YIELD KPI strip, and file/zoom/theme actions) sits above a 3-column body — a collapsible 280px control panel (accordion sections: Inspection, Camera, Display, Reference Profile, Station & Model) on the left, the image viewport centered and dominant (with a slim browse bar above it — Open Folder, the open folder's name, and the ◀ *n / total* ▶ stepper — a floating PASS/FAIL verdict badge over its top-left corner, and an on-demand history panel below it), and a 320px contextual panel on the right that's hidden until a detection is clicked. The native `QMainWindow` status bar carries short status text and per-run timing. `Display` toggles use the custom `ToggleSwitch` widget rather than checkboxes.

**Presentation / animation modules** (Qt stylesheets can't animate, so motion lives in Python):
- `styles.py` — token-based light/dark design system (`get_stylesheet`, `tokens_for`, `reference_label_style`); dark theme is the slate-900/800/700 + blue-500 accent palette
- `animations.py` — reusable `fade_in`, `pulse_glow`, `animate_number`, `animate_bar`
- `components.py` — custom-painted `YieldBar`, `BusyOverlay` (rotating spinner), `CollapsibleCard`, and `ToggleSwitch`
- `toast.py` — `ToastManager` slide-in notifications
- `splash.py` — branded animated splash with an indeterminate progress stripe

The YOLO backend is imported lazily; if `ultralytics` is unavailable the UI still launches in a degraded, view-only state instead of crashing.

**Inspection data flow:**
1. User loads an image (file picker, 📁 folder picker, drag & drop of a file *or* a folder) or captures one from the Camera panel — `capture_and_inspect()` in `camera_mixin.py` grabs the live preview's latest frame, writes it to `main_program/captures/`, then feeds that path through the same path as a file selection. Every route funnels into `open_image_path()` in `browse_mixin.py`, which indexes the containing folder (natural filename order, non-recursive) so the browse bar's ◀ *n / total* ▶ stepper can walk the rest of it — each step is a full inspection that logs to history → `run_inference()` calls `model.predict()` → a clean base frame (`result.orig_img`, no baked-in ultralytics boxes/labels) plus a raw `detections` list (`x, y, label, conf, box`)
2. `evaluate_inspection()` in `inspection_logic.py` matches detections to reference points (nearest-neighbor within `match_dist` pixels) → `{verdict, ok, missing, wrong, extra, reference_eval}`
3. `_recompose_and_display()` in `inspection_mixin.py` layers the viewport image on every redraw (including selection changes, without re-running inference): `draw_detections_overlay()` — thin, semi-transparent, class-colored boxes (IC/connector-like classes blue, capacitor amber, resistor emerald, others slate) — then `draw_reference_overlay()` — small OK (emerald) / WRONG or MISSING (red) markers at reference points
4. Clicking a detection box (`ReferenceLabel` → `select_detection_at()`, disabled while in edit mode) populates the right contextual panel (class, confidence, coordinates, status) via `detection_status_map()`
5. Result logged to `inspection_log.csv` if auto-log is enabled

## Key Data Files

- **`Refs.json`** — Reference profile: array of `{"x": int, "y": int, "label": str}` points defining expected components
- **`inspection_log.csv`** — Auto-generated inspection history (time, station, operator, verdict, counts)
- **`data.yaml`** — Dataset config: 23 component classes (button, capacitor, chip, connector, diode, led, resistor, usb, xtal, etc.)
- **`best.pt`** / **`trained/best.pt`** — Trained YOLOv8 weights loaded at runtime

## Core Logic: `inspection_logic.py`

`evaluate_inspection(reference_points, detections, match_dist, fail_on_extra)` — The central algorithm (both params required, no defaults — the GUI supplies its slider values):
- Greedily matches each reference point to its nearest not-yet-claimed detection, regardless of class, then checks if that nearest detection is within `match_dist` px *and* has the matching label — same-position/wrong-class detections become `WRONG`, not `MISSING`
- Returns verdict (`PASS`/`FAIL`) and lists of ok/missing/wrong/extra components

`draw_detections_overlay(frame, detections, selected_index)` — thin, semi-transparent, class-colored boxes for every raw detection (`class_color()` maps a label to its category color); the box at `selected_index` gets a white highlight outline.

`draw_reference_overlay(frame, inspection_result, show_labels)` — small OK/WRONG/MISSING circle markers at each reference point.

`detection_status_map(inspection_result)` — `id(detection) -> "OK"/"WRONG"/"EXTRA"`, used to label a clicked detection in the right panel.

## Custom Widget: `ReferenceLabel` (`widgets.py`)

A custom `QLabel` that translates mouse click coordinates from displayed-image space back to original-image space (accounting for zoom level). In edit mode, clicks mark new reference points; otherwise clicks hit-test the last inference's detections and populate the right contextual panel (`select_detection_at()`).

## Inspection Parameters (configurable in GUI)

- Confidence threshold: 1–100% (default 25%)
- Match distance: 5–250 px (default 50 px)
- Fail on extra detections: toggle
- Zoom: 20%–800%
