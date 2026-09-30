# PCB AOI & Defect Detection System - Web Backend (FastAPI)

FastAPI-based Computer Vision and Motion Controller backend for PCB component inspection using YOLOv8 and Arduino Nano XY stage (Protocol v2).

---

## 1. System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                  Next.js Frontend (Browser)                  │
│   (Inspection Viewport, AOI Grid Planner, Golden References) │
└──────────────┬───────────────────────────────┬───────────────┘
               │ HTTP REST API                 │ WebSocket
               ▼                               ▼
┌──────────────────────────────────────────────────────────────┐
│                      FastAPI Backend                         │
│  - routers/auth.py         : Operator Control Lease (LAN)    │
│  - routers/camera.py       : Frame Acquisition & MJPEG Stream│
│  - routers/inspection.py   : YOLO Detection & Match Verdict  │
│  - routers/aoi.py          : Motion Sequence & Stage Control │
│  - routers/references.py   : Golden Reference Profile Store  │
│  - routers/history.py      : Inspection Runs & Yield Stats   │
│  - routers/ws.py           : Real-time Telemetry & Events    │
└──────────────┬───────────────┬───────────────┬───────────────┘
               │               │               │
               ▼               ▼               ▼
      ┌────────────────┐┌──────────────┐┌──────────────┐
      │  Ultralytics   ││  Nano XY     ││ SQLite & Disk│
      │  YOLOv8 Weights││  Stage (v2)  ││ Storage Store│
      │  (MPS/CUDA/CPU)││ (pyserial/sim)││              │
      └────────────────┘└──────────────┘└──────────────┘
```

---

## 2. Hardware Acceleration Support

The backend queries and verifies the actual runtime environment dynamically:
- **Apple Silicon (Mac M1/M2/M3/M4)**: Uses PyTorch Metal Performance Shaders (`mps`). Detections execute in ~120-160ms on Apple GPU.
- **NVIDIA GPU / Jetson (CUDA)**: Uses CUDA runtime with automatic GPU device indexing (`cuda:0`).
- **CPU Fallback**: Graceful fallback to multi-threaded CPU execution if no GPU is available.

---

## 3. Motion Control & Serial Protocol v2

Compatible with `Desktop/cnc/cnc.ino` firmware:
- **Baud Rate**: 9600 baud, 8N1.
- **Kinematics**: 512 steps/mm mechanism.
- **Travel Limits**: EEPROM defaults (21167 × 20446 steps).
- **Soft Limits**: Configurable (default 38.00 × 38.00 mm) to prevent hard endstop collisions.
- **Startup Delay**: 2.5s Nano boot wait before transmitting commands.
- **Heartbeat**: 1.0s `POS` query serves as both state query and host heartbeat.
- **Timeouts**: Host disconnects after 6.0s silent link; firmware stops active job after 3.0s without messages.
- **Emergency STOP**: Preempts active movement immediately and clears queues without queuing behind inference.

---

## 4. Control Lease Model (Multi-Client & LAN Safety)

When accessed via local Wi-Fi / LAN by multiple devices (e.g., operator iPad and supervisor PC):
- **Single Operator Lease**: Only one client can hold the active lease at a time to issue motion (`HOME`, `JOG`, `MOVE`, `START_SCAN`).
- **Heartbeat Renewal**: The active operator client automatically renews its lease every 5 seconds (20s TTL). If the tab is closed, the lease safely expires.
- **Viewers**: Other clients can observe live video, stage position, yield rate, and inspection history in read-only mode.
- **Safety Exception**: The emergency **STOP** button can be triggered by ANY connected client at any time.

---

## 5. Running on macOS (Apple Silicon)

```bash
cd backend

# 1. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run automated tests
pytest

# 4. Start the backend server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

---

## 6. Running on NVIDIA Jetson (JetPack 5 / 6)

On Jetson, do **not** install generic PyTorch from PyPI (which lacks Tegra CUDA support). Use NVIDIA's pre-built wheels:

```bash
cd backend

# 1. Create virtual environment with access to JetPack system packages
python3 -m venv --system-site-packages venv
source venv/bin/activate

# 2. Install Jetson requirements
pip install -r requirements-jetson.txt

# 3. Verify CUDA is active
python3 -c "import torch; print('CUDA Available:', torch.cuda.is_available(), torch.cuda.get_device_name(0))"

# 4. Start backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

---

## 7. Connecting from iPad / Tablet via Local LAN

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
4. Touch targets are sized for touchscreens (>= 44px) and support pinch/drag on the PCB viewport.

---

## 8. Physical Machine Checklist (Before Real CNC Operation)

> [!CAUTION]
> Always verify with Simulation mode before operating the physical stage.

- [ ] Confirm no other application (e.g. Arduino IDE Serial Monitor or Desktop GUI) has `/dev/cu.usbserial*` open.
- [ ] Ensure stage limit switches are unobstructed and travel area is completely clear.
- [ ] Connect stage in **Serial** mode via web interface.
- [ ] Check firmware v2 handshake logs: `[READY] 2 0 0 21167 20446 0`.
- [ ] Press **HOME** and verify mechanical limit switch homing.
- [ ] Test small Jog movements (0.1 mm, then 1.0 mm) and verify physical direction.
- [ ] Verify that pressing **STOP** immediately halts motor movement.
