# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A YOLOv8-based PCB (Printed Circuit Board) defect inspection station. The system detects and validates electronic components on circuit boards using a trained YOLO model, comparing detections against a reference profile to produce PASS/FAIL verdicts.

## Running the Application

```bash
# Launch the main GUI inspection station
python3 main_program/gui_test.py

# Train the model
python3 train.py

# Test inference on a single image
python3 test.py

# Real-time webcam detection
python3 camera.py
```

## Installing Dependencies

No `requirements.txt` exists. Install manually:

```bash
pip install ultralytics opencv-python PyQt6
```

## Architecture

The GUI application uses **mixin-based composition**. The main window class `DefectDetectionGUI` inherits from multiple mixins:

```
DefectDetectionGUI (main_program/app/window.py)
    ├── InteractionMixin (mixins/interaction_mixin.py) — Keyboard shortcuts, drag & drop, Ctrl+scroll zoom, launch/theme fades
    ├── UIMixin (mixins/ui_mixin.py)         — Builds the top bar, verdict/KPI HUD, sidebar cards, image view, history table
    ├── ModelReferenceMixin (mixins/model_reference_mixin.py) — Lazy YOLO loading, Refs.json management, undo/redo, toasts
    ├── InspectionMixin (mixins/inspection_mixin.py)   — Debounced inference, busy overlay, animated verdict reveal, zoom, image display
    ├── HistoryMixin (mixins/history_mixin.py)         — CSV logging, animated counters/yield, history-row flash
    └── SettingsMixin (mixins/settings_mixin.py)       — Persist/restore settings.json on close
```

**Presentation / animation modules** (Qt stylesheets can't animate, so motion lives in Python):
- `styles.py` — token-based light/dark design system (`get_stylesheet`, `tokens_for`, `reference_label_style`)
- `animations.py` — reusable `fade_in`, `pulse_glow`, `animate_number`, `animate_bar`
- `components.py` — custom-painted `YieldBar` and `BusyOverlay` (rotating spinner)
- `toast.py` — `ToastManager` slide-in notifications
- `splash.py` — branded animated splash with an indeterminate progress stripe

The YOLO backend is imported lazily; if `ultralytics` is unavailable the UI still launches in a degraded, view-only state instead of crashing.

**Inspection data flow:**
1. User loads image → `run_inference()` calls `model.predict()` → detections
2. `evaluate_inspection()` in `inspection_logic.py` matches detections to reference points (nearest-neighbor within `match_dist` pixels)
3. Result: `{verdict, ok, missing, wrong, extra}` dict
4. `draw_reference_overlay()` annotates the image (green=OK, blue=WRONG, red=MISSING)
5. Result logged to `inspection_log.csv` if auto-log is enabled

## Key Data Files

- **`Refs.json`** — Reference profile: array of `{"x": int, "y": int, "label": str}` points defining expected components
- **`inspection_log.csv`** — Auto-generated inspection history (time, station, operator, verdict, counts)
- **`data.yaml`** — Dataset config: 23 component classes (button, capacitor, chip, connector, diode, led, resistor, usb, xtal, etc.)
- **`best.pt`** / **`trained/best.pt`** — Trained YOLOv8 weights loaded at runtime

## Core Logic: `inspection_logic.py`

`evaluate_inspection(reference_points, detections, match_dist=50, fail_on_extra=True)` — The central algorithm:
- Matches each reference point to the nearest detection of the same class within `match_dist` pixels
- Returns verdict (`PASS`/`FAIL`) and lists of ok/missing/wrong/extra components

`draw_reference_overlay(frame, inspection_result, show_labels)` — Draws colored bounding boxes on the image based on match status.

## Custom Widget: `ReferenceLabel` (`widgets.py`)

A custom `QLabel` that translates mouse click coordinates from displayed-image space back to original-image space (accounting for zoom level). Used in edit mode to mark reference points by clicking.

## Inspection Parameters (configurable in GUI)

- Confidence threshold: 1–100% (default 25%)
- Match distance: 5–250 px (default 50 px)
- Fail on extra detections: toggle
- Zoom: 20%–800%
