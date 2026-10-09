# RMUTT PCB AOI Station — Frontend (Next.js)

The browser UI of the web station: Next.js 16 (App Router), React 19, TypeScript and
Tailwind CSS 4. The UI is in Thai, works in light and dark themes, and fits desktop, tablet
(iPad at the machine) and phone screens.

Start the whole station from the parent folder with `./run_web.sh` (see
[../INSTALL.md](../INSTALL.md)). This file covers the frontend itself.

---

## 1. Pages

The page lives in a single route (`src/app/page.tsx`). The sidebar switches between eight
views, and the bottom bar does the same on small screens.

| View | Component | What it does |
| --- | --- | --- |
| สแกน AOI | `components/aoi/AOIScanView.tsx` | Boards, stage control, marking and teaching points, point/grid scans |
| ตรวจภาพเดี่ยว | `InspectionView.tsx`, `BoardInspection.tsx` | Inspect a live frame or an uploaded image against a reference |
| ชุดข้อมูลเทรน | `dataset/DatasetView.tsx`, `dataset/LabelEditor.tsx` | Whole-board capture, label editing (marquee select, bulk delete), dataset download |
| บอร์ด | `BoardsView.tsx`, `ReferencesView.tsx` | Taught boards (pictures, readiness, per-board history/yield), golden reference profiles, import the desktop `Refs.json` |
| ประวัติ & Yield | `HistoryView.tsx`, `RunReport.tsx`, `PerformanceView.tsx` | Runs and single inspections, yield, serial search, printable report, CSV export, send to Telegram, performance comparison |
| ประสิทธิภาพเครื่อง | `HardwareView.tsx` | Live CPU cores, GPU, RAM, temperatures, power, fan; Jetson power mode / max clocks / fan controls |
| ไลบรารี | `LibrariesView.tsx` | Python / JS / system libraries with versions and an update check |
| ตั้งค่าสถานี | `SettingsView.tsx`, `ModelPicker.tsx`, `AIKeyPanel.tsx`, `StageCalibrationCard.tsx`, `NotifyCard.tsx`, `RemoteAccess.tsx` | Model, compute device, stage limits, XY rail calibration, alerts, remote access, 3D view, station info |

Shared across all pages:
- `AppShell.tsx`: sidebar / phone bottom bar, header status chips, operator control, view-only and internet banners, STOP button.
- `AgentWidget.tsx`: the station-wide AI assistant.
- `SplashScreen.tsx`
- `Toast.tsx`

---

## 2. AOI scan page (`components/aoi/`)

| File | Role |
| --- | --- |
| `AOIScanView.tsx` | Page state and wiring: workflow steps, keyboard shortcuts, operator/engineer mode, guided tour, camera/result layout sized to the camera aspect ratio |
| `WorkflowSteps.tsx` | ① board → ② stage ready → ③ mark points → ④ scan, with the next action |
| `PointSets.tsx` | Create / open / rename / delete boards; autosaves the points (operator variant: open only) |
| `PointsPanel.tsx` | Mark button and the point list (go to, edit position, teach reference, zoom, delete) with the travel indicator |
| `StageBar.tsx` | Serial / simulation connect, HOME, position, motors off |
| `JogOverlay.tsx` | Jog pad over the live camera (press-and-hold, step cycling) |
| `ScanDock.tsx` | Start/stop, progress, and one thumbnail per point under the camera |
| `SerialInput.tsx` | Board serial number (keyboard or USB barcode / QR scanner) |
| `ScanCompleteModal.tsx` | Pop-up when a scan ends: verdict, counts, failing parts, print / results / next board |
| `ScanResults.tsx` | Result pane; when empty, shows the last scan and today's tally |
| `ResultOverlay.tsx` | Box-by-box result reveal and the per-frame capture progress |
| `OperatorPanel.tsx` | Operator mode: one big start button and a big PASS/FAIL |
| `ShortcutHelp.tsx` | Shortcut sheet (`?`) |
| `panels.tsx` | Grid scan, jog, and inspection-parameter tabs |

Keyboard shortcuts on this page:

| Key | Action |
| --- | --- |
| Arrows | Jog the stage |
| Shift + arrows | Jog ×10 |
| `M` | Mark the current position |
| `Space` | Test snap |
| `H` | HOME |
| `1`–`5` | Zoom |
| `?` | Help |

Shortcuts use `KeyboardEvent.code`, so they also work with the Thai keyboard layout.

Other components:
- `LiveCameraFeed.tsx`: MJPEG with a snapshot fallback; it closes leaked streams.
- `PointResultModal.tsx` (point detail), `DepthModal.tsx`, `Depth3DView.tsx`, `DepthMap2D.tsx` (3D height map).
- `ChatPanel.tsx`: board chat.
- `three/`: lazy-loaded three.js views — `StageTwin3D.tsx` (gantry twin from `public/models/machine.glb`), `Board3D.tsx`, `RailMap3D.tsx`, `DecorPcb.tsx`; helpers in `lib/three/`.
- `Tour.tsx`: guided tour.

---

## 3. Shared code

- `components/ui.tsx`: design primitives.
  - `Button`: when disabled it turns grey and can show a `reason` with a lock.
  - Also `Segmented`, `Modal`, `Badge`, `Field`, inputs, and more.
  - Touch screens get larger targets through `pointer-coarse:` variants.
- `app/globals.css`: color tokens for light and dark themes (`bg-surface`, `text-muted`, `text-pass`, …) and animations.
- `lib/api.ts`: typed client for every backend endpoint. It sends the operator token with each request.
- `lib/sound.ts`: sound effects synthesized with Web Audio (no audio files).
- `hooks/`:
  - `useStationSocket`: WebSocket `/ws/status` for live stage state, scan progress and frames.
  - `useOperatorLease`
  - `usePersistentState`: localStorage-backed state.
  - `useHoldRepeat`
  - `useElementSize`
  - `useSound`

The React Compiler lint rules are on. Don't call `setState` synchronously inside an effect
body; do it in async callbacks or event handlers.

---

## 4. Development

```bash
npm ci
npm run dev        # http://localhost:3001 (next dev -p 3001)
npm run lint
npx tsc --noEmit
npm run build && npm start    # production (run_web.sh --prod does this)
```

`/api/*` and `/ws/*` are proxied to the backend by `next.config.ts`. The proxy targets
`http://127.0.0.1:8000` by default; override it with `BACKEND_URL`:

```bash
BACKEND_URL=http://127.0.0.1:8001 npm run dev
```

In Docker, `BACKEND_URL` is baked in at build time (see `Dockerfile`).

> This Next.js version has breaking changes from older releases. Check
> `node_modules/next/dist/docs/` before using unfamiliar APIs (see `AGENTS.md`).
