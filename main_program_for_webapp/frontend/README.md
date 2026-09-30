# PCB AOI & Defect Detection System - Next.js Frontend

Web interface for the PCB Inspection Station built with Next.js App Router, TypeScript, Tailwind CSS, and HTML5/SVG interactive overlays.

---

## 1. Views & Features

1. **Single Inspection (`/`)**:
   - Live camera MJPEG preview with interactive pan/zoom.
   - Upload PCB image drag-and-drop.
   - One-click "Capture & Inspect".
   - SVG interactive overlay with class-colored bounding boxes and golden reference target markers.
   - Click-to-inspect component side panel with OK, WRONG, MISSING, and EXTRA statuses.
2. **AOI Automated Scan**:
   - XY Stage connection toggle (Simulation vs Serial Nano).
   - Real-time coordinates display (mm and steps).
   - HOME, Jog keypad (0.1, 1, 5, 10 mm step size), and Motors OFF.
   - Raster scan planner with serpentine path calculation.
   - Teach mode ("Scan Golden Board") and Inspection mode.
   - Live progress monitor with thumbnail results grid and full-detail modal.
3. **Golden References**:
   - Profile management with single-image and AOI grid profiles.
   - One-click "Import Desktop Refs.json" without modifying original files.
   - Component expectation table.
4. **History & Yield**:
   - Board-level and point-level yield rate KPI cards.
   - Filterable runs table with PASS/FAIL/REVIEW/ERROR status.
   - CSV export download.
5. **System Settings**:
   - Hardware processor switcher (Apple MPS, NVIDIA CUDA, CPU).
   - Model weights path configuration.
   - Machine soft limit bounds (mm).
   - Station and operator metadata.

---

## 2. Running Locally

```bash
cd frontend

# Install dependencies
npm install

# Run development server (default port 3000 or 3001)
npm run dev -- -p 3001

# Or build and run production server
npm run build
npx next start -p 3001
```

---

## 3. Environment Configuration

If the FastAPI backend runs on a custom address:
```bash
# In frontend/.env.local:
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8000
```
Next.js automatically proxies `/api/*` requests to the backend.
