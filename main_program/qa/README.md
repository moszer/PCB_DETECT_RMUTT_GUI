# PCB Inspect workspace QA

The native PyQt6 workspace now separates application actions, session metrics,
inspection setup, the image canvas, and the inspection verdict. History uses the
full center workspace. Component details appear when a detection is selected.
Light and dark themes use the same layout and teal action color.

## Run

From `main_program`:

```sh
venv/bin/python gui_test.py
QT_QPA_PLATFORM=offscreen venv/bin/python -m unittest discover -s qa -v
```

The tests use temporary images, skip saved settings and model startup, and never
write production inspection logs. They cover empty-state actions, image loading
without a model, zoom, result updates, component selection, history, compact
layouts in both themes, busy/camera action availability, and rapid card toggles.

## Visual and inference checks

Reviewed the native Qt output at 1440 × 900 and 1100 × 760, including expanded
setup cards and selected-component details. Preview images are in `previews/`.

Ran the real bundled `best.pt` on `test/pass.jpg`: 52 detections, approximately
178 ms inference on CPU. The existing nine reference points are outside this
sample image's bounds, so its recorded verdict is FAIL (9 missing, 52 extra).
This confirms the inference/UI integration, not detection accuracy or a valid
pass/fail calibration. Use a reference profile for the intended board and image
size. Preview generation disabled auto-logging and settings persistence.

Physical camera capture was not exercised; camera button availability was tested
with simulated connection/frame states.
