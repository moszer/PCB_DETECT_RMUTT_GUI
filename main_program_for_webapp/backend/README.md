# RMUTT PCB AOI Station — Backend (FastAPI)

The computer-vision and motion-control service of the web station. It does four things:
- runs YOLO inspection and drives the Arduino Nano XY stage (protocol v2)
- stores runs, references, boards and training datasets
- serves the AI assistant
- streams live state to the Next.js frontend

Install and start everything from the parent folder with `./install.sh && ./run_web.sh` (see
[../INSTALL.md](../INSTALL.md)). This file covers the backend itself.

---

## 1. Layout

```
app/
  main.py               FastAPI app, CORS, router registration
  config.py             paths, .env loading, persisted station settings (data/settings.json)
  routers/
    system.py           status, settings, compute device, model list/upload/select,
                        Hugging Face model list/download (/models/hub),
                        live hardware readings and Jetson power/clock/fan control (/hardware),
                        LAN/Tailscale remote access (/remote-access) and QR codes (/qr)
    auth.py             operator control lease (acquire / renew / release)
    camera.py           MJPEG stream, snapshot, camera devices and format
    inspection.py       inspect upload / live / multi-frame, OCR of part markings
    aoi.py              stage connect/home/jog/move/stop, scan plan/start/stop/status,
                        boards (point-sets CRUD), depth measurement, XY rail calibration
                        and the printable speckle target (/calibration/speckle.{pdf,png})
    boards.py           boards page: pictures, readiness, per-board history, export
    media.py            small previews (LQIP + JPEG thumbs) of stored images
    references.py       golden reference profiles, import desktop Refs.json
    history.py          runs (search by serial ?q=), single inspections, statistics, CSV export,
                        performance comparison and benchmark
    datasets.py         4-corner board capture, label editing, YOLO dataset download
    chat.py             board chat, station-wide AI agent, chat history
    ws.py               WebSocket /ws/status: machine state, scan progress, frames
  services/
    inference_service   YOLO loading and prediction (MPS / CUDA / CPU)
    camera_service      capture thread, stream fan-out (max 2 streams per client)
    machine_service     serial stage + built-in simulator
    aoi_scan_service    scan sequencing, multi-frame confirmation, point_frame events
    dataset_service     automatic whole-board photography and auto-labelling
    depth_service       motion-stereo height map of a part: shots in up to 8 stage directions, fused (phase correlation + SGBM)
    stage_calibration_service  XY stage accuracy from the camera (backlash, linearity, squareness, repeatability)
    chat_service        Gemini (streamGenerateContent, model fallback) / OpenRouter
    agent_service       tool-calling agent over read-only station data + page navigation
    storage_service     SQLite (data/inspection.db) and run images
    point_set_store     saved boards
    hardware_service    CPU/GPU/RAM/thermal/power/fan readings; Jetson control through the
                        root helper scripts/jetson/aoi-jetson-power (sudo -n, fixed commands only)
    chat_store          saved chat history
    notify_service      Telegram / webhook alerts (fail, error, fails in a row, yield drop),
                        history CSV to Telegram
    library_service     installed library versions + update check (PyPI / npm), cached
    tunnel_service      Tailscale login / serve / funnel for the station's own entry
    board_alignment     board-placement compensation from two taught points
    backup_service, benchmark, perf_log, stage_monitor_service, ai_settings
  core/                 inspection matching, motion protocol v2, device detection, OCR, depth, schemas,
                        hub.py (Hugging Face weight downloads: resume + SHA-256 check, stdlib only),
                        access.py (internet guard), shutdown.py (end live streams on stop),
                        stage_calibration.py (rail map), model_catalog.py, log_buffer.py (secret redaction)
tests/                  pytest suite (API, motion protocol, inspection, datasets, OCR, depth, chat, agent…)
data/                   runtime data (git-ignored)
```

---

## 2. Running

```bash
# from main_program_for_webapp/: installs the matching PyTorch for this machine
./install.sh

# backend only (run_web.sh does this for you)
cd backend
venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# YOLO weights from Hugging Face (install.sh does this when best.pt is missing)
venv/bin/python -m app.core.hub --list
venv/bin/python -m app.core.hub --file best.pt --out ../best.pt

# tests
venv/bin/python -m pytest -q
```

Interactive API docs: **http://localhost:8000/docs**.

Settings come from `backend/.env`, which `install.sh` copies from `.env.example`. The file is git-ignored.

| Variable | Purpose |
| --- | --- |
| `PCB_OPERATOR_PASSCODE` | Optional explicit passcode; otherwise one is generated in the station data directory |
| `AI_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_MODELS` | AI assistant via Google Gemini (models tried in order) |
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` | AI assistant via OpenRouter instead |
| `PCB_DEVICE` | `auto` / `cuda:0` / `mps` / `cpu` |
| `PCB_CORS_ORIGINS` | Comma-separated browser origins allowed to call the backend directly (the Next.js LAN proxy is same-origin) |
| `PCB_BACKUP_INTERVAL_HOURS`, `PCB_BACKUP_KEEP` | Automatic station-data backup frequency (default 24h) and number of archives kept (default 7); set interval to `0` to disable |
| `PCB_REQUIRE_MODEL_APPROVAL` | `1` (default) blocks serial hardware scans until the loaded model passes the quality gate; `0` is for supervised commissioning only |
| `PCB_CAMERA_SIMULATION=1` | Software test camera (Docker, no webcam) |
| `PCB_STORAGE_DIR` | Data folder (default `backend/data`) |
| `PCB_MODEL_REPO`, `PCB_MODEL_FILE`, `HF_TOKEN` | Hugging Face repo with the YOLO weights, the file `install.sh` fetches (default `best.pt`), and a read token for private repos |
| `TELEGRAM_BOT_TOKEN`, `NOTIFY_WEBHOOK_URL` | Alert channels; set from **Settings → แจ้งเตือนผลสแกน** (rules are kept in `data/notify.json`) |
| `PCB_FRONTEND_PORT`, `PCB_BACKEND_PORT` | Ports used by `run_web.sh` (defaults 3001 / 8000) |

AI keys stay on the server and are never sent to the browser. They can be edited from
**Settings → ผู้ช่วย AI** (`GET/PUT /api/chat/config`, `POST /api/chat/config/test`).
Writing requires the operator lease even when nobody else holds the station; values are
validated so they cannot inject other lines into `.env`.

The operator passcode is generated separately for each station on first start when
`PCB_OPERATOR_PASSCODE` is unset. Read it locally from `backend/data/.operator-passcode` and
keep that file private. Previously saved `rmutt-aoi` defaults are replaced automatically.
An active operator token is required for stage motion, camera changes, station settings,
references, datasets and benchmark writes, even when the station is otherwise idle.
Emergency STOP and scan/capture abort remain available without a token.
GitHub Actions runs frontend lint, typecheck and build plus the backend test suite on
every push and pull request (`.github/workflows/aoi.yml`).

---

## 3. Hardware Acceleration

The backend checks at runtime which device actually works:
- **Apple Silicon (M1–M4):** PyTorch Metal (`mps`), about 120–160 ms per inference.
- **NVIDIA GPU / Jetson:** CUDA (`cuda:0`). `install.sh` installs:
  - `torch 2.13.0+cu130` on JetPack 7 (`requirements-jetson-cu130.txt`, tested on Orin Nano Super)
  - NVIDIA Jetson AI Lab wheels on JetPack 6 (`pypi.jetson-ai-lab.io/jp6/cu126`, not yet tested on a real board)
- **CPU** when no GPU is available.

The device can be changed at runtime from the Settings page.

---

## 4. Motion Control & Serial Protocol v2

Compatible with the firmware in [`../firmware/cnc/cnc.ino`](../firmware/):
- **Baud Rate**: 9600 baud, 8N1.
- **Kinematics**: 512 steps/mm mechanism.
- **Travel Limits**: EEPROM defaults (21167 × 20446 steps).
- **Soft Limits**: Configurable (default 38.00 × 38.00 mm) to prevent hard endstop collisions.
- **Startup Delay**: 2.5s Nano boot wait before transmitting commands.
- **Heartbeat**: a `POS` query serves as both state query and host heartbeat: every 0.25 s while a move is pending, 1.0 s when idle.
- **Timeouts**: Host disconnects after 6.0s silent link; firmware stops active job after 3.0s without messages.
- **Emergency STOP**: Preempts active movement immediately and clears queues without queuing behind inference.

---

## 5. Control Lease Model (Multi-Client & LAN Safety)

When accessed via local Wi-Fi / LAN by multiple devices (e.g., operator iPad and supervisor PC):
- **Single Operator Lease**: Only one client can hold the active lease at a time to issue motion (`HOME`, `JOG`, `MOVE`, `START_SCAN`).
- **Heartbeat Renewal**: The active operator client automatically renews its lease every 5 seconds (20s TTL). If the tab is closed, the lease safely expires.
- **Viewers**: Other clients can observe live video, stage position, yield rate, and inspection history in read-only mode; the UI shows a *view-only* banner and locks the controls.
- **Safety Exception**: The emergency **STOP** button can be triggered by ANY connected client at any time.

---

## 6. Data & Storage

- `data/inspection.db`: SQLite database of runs, point results, single inspections and boards.
- `data/runs/`, `data/uploads/`: captured and annotated images.
- `data/references/`, `data/datasets/`, `data/models/`: reference profiles, training datasets, uploaded weights.
- `data/settings.json`: station settings saved from the UI.

### Back up and restore

The server creates a verified archive shortly after its first start and then every 24 hours
by default. Archives are in `backend/data/backups/` and include the SQLite database,
captured images, references, datasets, uploaded models, station settings and generated
operator passcode. To create or verify one manually:

```bash
cd backend
venv/bin/python -m app.backup_cli backup
venv/bin/python -m app.backup_cli verify data/backups/station-YYYYMMDD-HHMMSS-PID.zip
```

To restore, stop the station first and restore into a **new** data directory. The command
refuses to overwrite an existing directory. Point `PCB_STORAGE_DIR` to the restored path
when starting the station, then verify the boards and images in the UI:

```bash
venv/bin/python -m app.backup_cli restore data/backups/station-YYYYMMDD-HHMMSS-PID.zip /path/to/new-station-data
PCB_STORAGE_DIR=/path/to/new-station-data ../run_web.sh
```

The backups live on the station's data volume, so copy selected archives to a separate
drive or server to survive disk failure. Back up `backend/.env` and any model weights
outside `backend/data/` separately; they are intentionally excluded from station-data archives.

### Accept a model for hardware scans

Use a labeled, fixed `test` split that represents the camera, boards, defects and lighting
used by this station. Run the benchmark from **Performance** with its `data.yaml` and
`test` split. The report contains overall mAP50/recall, per-class recall and model hash.
Inspect missed defects, then certify the report:

```bash
cd backend
venv/bin/python -m app.quality_gate certify data/benchmarks/<report>.json \
  --min-map50 85 --min-recall 90 --min-class-recall 90
```

The acceptance record is saved in `backend/data/model_approvals.json`. A serial scan
checks the loaded model's full SHA-256 against it; changing weights requires a new
benchmark and approval. Simulation scans still work without approval. Set thresholds
based on the project's tolerated missed-defect rate before certifying a production model.

---

## 7. Docker

`../docker-compose.yml` builds this backend into a `python:3.12-slim` image with CPU PyTorch.
Data persists in the `aoi-data` volume.
- `../docker-test.sh` builds the stack, runs this test suite in the container, and smoke-tests a real inspection.
- `docker-compose.hardware.yml` passes the camera and serial port through (Linux only).
- `docker-compose.jetson.yml` enables the GPU on Jetson.

---

## 8. Connecting from iPad / Tablet via Local LAN

1. Ensure the host computer and the iPad are on the same Wi-Fi network.
2. Find the host IP address on macOS:
   ```bash
   ipconfig getifaddr en0
   # Example: 192.168.1.42
   ```
3. Open Safari on the iPad and navigate to:
   ```
   http://192.168.1.42:3001
   ```
4. Touch screens get larger controls automatically, and the jog pads support press-and-hold. `run_web.sh` prints the LAN URL at startup.

---

## 9. Physical Machine Checklist (Before Real CNC Operation)

> [!CAUTION]
> Always verify with Simulation mode before operating the physical stage.

- [ ] Confirm no other application (e.g. Arduino IDE Serial Monitor or Desktop GUI) has `/dev/cu.usbserial*` open.
- [ ] Ensure stage limit switches are unobstructed and travel area is completely clear.
- [ ] Connect stage in **Serial** mode via web interface.
- [ ] Check firmware v2 handshake logs: `[READY] 2 0 0 21167 20446 0`.
- [ ] Press **HOME** and verify mechanical limit switch homing.
- [ ] Test small Jog movements (0.1 mm, then 1.0 mm) and verify physical direction.
- [ ] Verify that pressing **STOP** immediately halts motor movement.
