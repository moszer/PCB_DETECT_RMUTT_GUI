# PCB Inspect workspace QA

AOI tests in `test_aoi.py` cover bounded serpentine plans, v2 handshakes, duplicate
boot replies, Home requirements, stale/mismatched completion IDs, STOP/OFF,
link/operation timeouts, controller reset, stale frames, write/inference failures,
golden-reference comparison and complete/aborted run reports. These use simulation
and synthetic images; they never open a hardware serial port or camera.

The native PyQt6 workspace now separates application actions, session metrics,
inspection setup, the image canvas, and the inspection verdict. History uses the
full center workspace. Component details appear when a detection is selected.
Light and dark themes use the same layout and teal action color.

## Run

From `main_program`:

```sh
.venv/bin/python gui_test.py
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s qa -v
```

The tests use temporary images, skip saved settings and model startup, and never
write production inspection logs. They cover empty-state actions, image loading
without a model, zoom, result updates, component selection, history, compact
layouts in both themes, busy/camera action availability, and rapid card toggles.

The NVIDIA update adds device-routing checks, CPU fallback and explicit CUDA
failure checks, LFS-pointer validation, processor preference persistence, and
processor/model controls during inference. All 17 tests passed on 2026-09-11.
Closing a window now stops its animations before widget teardown, fixing the
stale animation callback crash exposed by the suite on the Jetson environment.

Real CUDA convolution, torchvision NMS, and `best.pt` inference were also tested
on Orin Nano Super / L4T 39.2.1 / Python 3.12.3 / PyTorch 2.13.0+cu130.
`test/pass.jpg` produced 52 detections in about 167 ms in the measured warm run.
An offscreen GUI smoke check exercised Auto/CUDA → CPU → explicit CUDA with the
actual model, verifying the device and 52 detections in each mode. It wrote no
production history or settings. See [NVIDIA.md](../../NVIDIA.md) for reproduction
commands and the remaining PyTorch SM 8.7 warning.

## Visual and inference checks

Apple MPS support was checked on macOS 27.0 / arm64 / PyTorch 2.13.0 on
2026-09-16. All 35 automated tests passed, including CUDA/MPS/CPU selection,
unavailable MPS errors, explicit device requests without silent CPU retry, and
MPS preference persistence. The actual GUI inference worker ran `best.pt` on
`test/pass.jpg` through CPU → MPS → Auto → CPU; model parameters were verified
on the selected device and each pass produced 52 detections. The initial MPS
pass took about 281 ms, the next MPS pass 37 ms, and the final CPU pass 166 ms.
These are individual inference timings, not sustained FPS or accuracy benchmarks.
No production logs or settings were written by this smoke check.

The update feature adds real temporary Git repository tests for fast-forward
installation, local file preservation, model/reference backups, dirty checkouts,
untracked and ignored collisions, detached/diverged branches, stale update
targets, remote validation, and timeout errors. Qt tests cover background checks,
retry after failure, camera activity, closing during work, and restart-required
completion. All 29 tests passed on macOS on 2026-09-16. A read-only check against
the actual GitHub remote also succeeded; installation was exercised in temporary
repositories. The Updates button was visually checked at 1100 × 760.

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
