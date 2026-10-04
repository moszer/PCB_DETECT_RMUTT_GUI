# AOI scanning with the Nano XY stage

Open `main_program/gui_test.py`, load a detection model, stop the main camera
preview, then select **AOI Scan** in the top bar. The AOI workspace uses the main
window's model, confidence and Processor selection. It has its own camera preview
and per-position references; the normal single-image reference is not reused.

## Setup

Install `pyserial==3.5` in the Python environment running the GUI (included in both
requirements files). Use the matching **protocol v2** firmware from the supplied
`Desktop/cnc/cnc.ino` project. This integration neither flashes firmware nor starts
motors automatically. Serial uses 9600 baud; only one application can own the port.
Close/disconnect CNC Motion Studio before connecting from PCB Inspect.

USB ports are listed before system/Bluetooth ports; when a USB controller is
present at startup the dialog selects Serial mode and its port without opening
it. Click Connect explicitly. **Show connection log** displays the actual TX/RX
lines, including startup replies and controller errors. A missing `pyserial`
message refers to the Python interpreter running this GUI, not another venv.

1. Select **Simulation** to test stage sequencing without opening a serial port,
   or select **Serial**, refresh ports and choose the Nano.
2. Wait for the v2 handshake, then press **HOME**. The machine uses its physical
   limit switches. There is no software "set zero" operation.
3. The supplied mechanism uses **512 steps/mm**. Change this before connecting if
   the mechanism changes. Actual travel limits come from the controller EEPROM.
   The supplied defaults are 21167 × 20446 steps (about 41.34 × 39.93 mm).
   **Soft limit X/Y** fields in Scan setup default to **38.00 × 38.00 mm** to ensure
   safe clearance within physical travel; Jog and scan planning enforce these limits without triggering full-stop faults.
4. Start the camera in this dialog. 4K/Full HD are requested modes; the label under
   the preview shows the actual resolution delivered by the driver.
5. Set absolute machine origin X/Y, columns/rows, and pitch. **Preview points**
   lists the serpentine order; it does not move anything. Keep the board fixed
   and choose pitch based on the camera's actual field of view. Jog uses the
   same machine coordinates and travel checks.
6. **Start AOI scan** moves to each point, waits for the matching DONE and the
   settle interval, captures a fresh frame, then runs YOLO before moving again.
   Simulation simulates only stage motion; it still needs camera frames and a
   loaded model. It cannot validate physical alignment or motion accuracy.

## References and results

Without a reference, each point is **REVIEW**, with detections and images saved.
To compare repeated boards, use **Scan golden board**, inspect its saved images
and detections, then scan subsequent boards at the same fixture position. A
completed golden scan becomes the reference in the current dialog. For another
session, use **Load reference…** and select that run's `report.json`; manually
restore the same grid/settings before scanning. Reference settings, per-point
coordinates and actual image dimensions are checked before comparison.

Golden-board labels are model predictions, not ground truth. Missing detections
in the golden scan become missing expectations, so review them before relying on
PASS/FAIL. A reference with zero detections yields REVIEW. The per-point check
uses class and pixel-center distance, and fails on extra detections. It does not
perform board registration, stitching, measurement, solder inspection, or infer
electrical faults. The board/camera need repeatable positioning, focus and light.

Every run is stored in `main_program/aoi_runs/<timestamp>/`:

- Original and annotated PNG for every completed point.
- `report.json`: settings, steps/mm, simulation flag, requested camera mode,
  actual image size, positions in steps, detections, per-point verdict/reason and
  inference timings. Updated atomically after each point; status is `complete`,
  `running`, or `aborted`. Overlapping views are separate inspections and must
  not be summed as unique board component counts.

These reports are separate from the single-image production counters/history.

## Stops and connection failures

**STOP** cancels the scan and preempts motion. Any late inference result is
discarded. **Motors OFF** clears Home; Home is required again. Disconnect and
closing the workspace send STOP, and shutdown waits for camera/inference threads
without destroying a running QThread. Incomplete scans cannot be loaded as a
golden reference. Unexpected controller reset, mismatched MOVE completion,
controller errors, loss of fresh camera frames, and failed image writes abort
the scan rather than advancing to the next point.

The host waits 2.5 seconds for Nano startup before transmitting, then sends one
POS query every second (also a heartbeat) and stops/disconnects after a six-second
reply timeout. The v2 firmware independently stops an active job after three
seconds without host messages. Software STOP is not a hardware emergency stop;
the reported coordinates count commanded motor steps, not encoder measurements.
No real motor motion or USB camera capture was exercised by automated tests.

Live connection verification on 2026-09-25: the CH340 device at
`/dev/cu.usbserial-210` returned protocol v2 and 21167 × 20446 step limits. The
previous immediate / paired heartbeat sequence produced `BAD_COMMAND` and a
disconnect. With the startup delay and single POS heartbeat, both the protocol
client and the actual AOI dialog sustained repeated position replies without
disconnecting. These checks sent no HOME or MOVE commands and did not flash the
controller. Reopen an already-running GUI to load the changed connection code.

## Tests

From `main_program`:

```sh
QT_QPA_PLATFORM=offscreen venv/bin/python -m unittest qa.test_aoi -v
```

Tests use a simulated transport, synthetic camera frames and a fake inference
model. Hardware commissioning still needs travel, homing, focus, settle time,
USB buffering, repeatability and STOP checks with the actual mechanism.
