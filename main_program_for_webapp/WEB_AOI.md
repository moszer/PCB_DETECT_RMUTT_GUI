# รายงานและคู่มือระบบเว็บ PCB AOI & Defect Detection System (Web Edition)

เอกสารสรุปผลการพัฒนาระบบเว็บตรวจสอบชิ้นส่วน PCB (Automated Optical Inspection - AOI) ร่วมกับระบบขับเคลื่อนแกน XY (Arduino Nano Protocol v2) และโมเดลวิเคราะห์ภาพ YOLOv8

---

## 1. สถาปัตยกรรมระบบ (System Architecture)

ระบบถูกออกแบบแยกส่วน (Decoupled Architecture) ระหว่าง Backend และ Frontend อย่างสมบูรณ์:

```
┌─────────────────────────────────────────────────────────────┐
│                 Frontend: Next.js + TypeScript              │
│  - App Router, Tailwind CSS, SVG Overlay                    │
│  - 5 หน้าหลัก: Inspection, AOI Scan, References,            │
│               History & Yield, Settings                     │
│  - Interactive Viewport: Zoom, Pan, Fit, 1:1, Box Selection │
│  - Control Lease Management (Operator vs Viewer)            │
│  - Emergency STOP เข้าถึงได้ตลอดเวลาจาก Header               │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP REST & WebSocket (Telemetries)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 Backend: FastAPI + Python                   │
│  - Camera Service: Singleton Owner, Fresh Frame, MJPEG Stream│
│  - Inference Service: YOLOv8 on MPS (Apple GPU) / CUDA / CPU│
│  - Machine Service: Protocol v2 (Nano Serial / Simulation)  │
│  - AOI Scan Service: Serpentine Move → Settle → Capture     │
│                     → Infer → Evaluate → Persist Report     │
│  - Storage Service: SQLite Database + Filesystem Store      │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. สถานะความเข้ากันได้กับโปรแกรมเดิม (Desktop GUI Preservation)

| ข้อกำหนด | ผลการตรวจสอบจริง |
|---|---|
| ไม่แก้ไข ย้าย หรือลบไฟล์ใน `main_program/` | ✅ **100% ผ่าน**: ไม่มีการแก้ไขไฟล์ใดใน `main_program/` |
| Dependencies และ Virtual Environment เดิมไม่เปลี่ยน | ✅ **100% ผ่าน**: `main_program/venv` ไม่ถูกแตะต้อง |
| Desktop GUI เดิมยังทำงานได้ปกติ | ✅ **100% ผ่าน**: รันชุดทดสอบ `qa.test_aoi` 26 รายการ ผ่านทั้งหมด (Ran 26 tests in 13.4s - OK) |
| ข้อมูล `Refs.json` และการตั้งค่าเดิมไม่ถูกเขียนทับ | ✅ **100% ผ่าน**: ใช้วิธี Read-only Snapshot Import |

---

## 3. สรุปการแก้ไขปัญหาทางเทคนิคสำคัญระหว่างย้ายระบบ

1. **การแปลผลเมื่อไม่มี Reference Profile**:
   - ในระบบเดิม single-image แปลผลเป็น FAIL ขณะที่ AOI แปลผลเป็น REVIEW
   - ในเว็บกำหนดกติกามาตรฐานสากล: **เมื่อไม่มี Reference หรือไม่ได้เลือก Profile ให้ผลตรวจเป็น `REVIEW` เสมอ** (ไม่นับเป็นบอร์ดเสียหรือข้อผิดพลาดโดยอัตโนมัติ)
2. **การป้องกันภาพค้างระหว่างเคลื่อนที่ (Fresh Frame Guarantee)**:
   - ฟังก์ชัน `camera_service.get_fresh_frame(after_timestamp=move_done_time)` ตรวจสอบ timestamp ของภาพอย่างเคร่งครัด เพื่อป้องกันการนำภาพที่ถ่ายก่อนแกนเคลื่อนที่มาวิเคราะห์
3. **การทำงานของปุ่ม STOP**:
   - คำสั่ง STOP และการตัดการเชื่อมต่อ จะ Preempt ล้างคิวการเคลื่อนที่ทันท่วงที โดยไม่ต่อท้ายคิวประมวลผล YOLO
   - ผลตรวจที่ประมวลผลค้างหลังคำสั่ง STOP จะถูกละทิ้ง (Discard) และไม่บันทึกทับผลตรวจ
4. **ความปลอดภัยในการเข้าถึงผ่าน LAN (Control Lease)**:
   - ป้องกันการชนกันกรณีเปิดหน้าเว็บพร้อมกันหลายอุปกรณ์ (เช่น iPad หน้าเครื่องตรวจ + คอมพิวเตอร์ห้องควบคุม)
   - ผู้ควบคุม (Operator) ถือ Lease เพียงคนเดียว ผู้ใช้อื่นอยู่ในโหมด Viewer (อ่านสถานะเท่านั้น)
   - ข้อยกเว้นความปลอดภัย: ปุ่ม **STOP** สามารถกดได้จากทุกอุปกรณ์ทันทีโดยไม่ต้องถือสิทธิ์ Lease

---

## 4. ผลการรันชุดทดสอบ (Automated Test Results)

### Backend Tests (Pytest)
```
tests/test_api.py::ApiIntegrationTests::test_aoi_plan_and_simulation_scan PASSED
tests/test_api.py::ApiIntegrationTests::test_health_check PASSED
tests/test_api.py::ApiIntegrationTests::test_lease_acquire_and_release PASSED
tests/test_api.py::ApiIntegrationTests::test_system_status_and_devices PASSED
tests/test_api.py::ApiIntegrationTests::test_upload_inspection PASSED
tests/test_inspection.py::InspectionEvaluationTests::test_all_components_match_yields_pass PASSED
tests/test_inspection.py::InspectionEvaluationTests::test_extra_component_yields_fail_when_configured PASSED
tests/test_inspection.py::InspectionEvaluationTests::test_missing_component_yields_fail PASSED
tests/test_inspection.py::InspectionEvaluationTests::test_no_reference_yields_review PASSED
tests/test_inspection.py::InspectionEvaluationTests::test_wrong_component_yields_fail PASSED
tests/test_motion_protocol.py::MotionProtocolTests::test_move_enforces_limits PASSED
tests/test_motion_protocol.py::MotionProtocolTests::test_raster_planning PASSED
tests/test_motion_protocol.py::MotionProtocolTests::test_startup_handshake_and_homing PASSED
tests/test_motion_protocol.py::MotionProtocolTests::test_stop_preempts_motion PASSED

14 passed in 1.26s
```

### Frontend Build (Next.js)
```
▲ Next.js 16.3.6 (Turbopack)
✓ Compiled successfully in 2.7s
✓ Finished TypeScript in 803ms
✓ Generating static pages (4/4) in 180ms
```

### Desktop GUI Regression Suite
```
Ran 26 tests in 13.462s
OK
```

---

## 5. วิธีการติดตั้งและรันระบบ

### วิธีที่ 1: รันคำสั่งเดียวผ่านสคริปต์อัตโนมัติ (แนะนำ)
เปิด Terminal ที่โฟลเดอร์รากของโปรเจกต์ แล้วพิมพ์:
```bash
./run_web.sh
```
สคริปต์จะเริ่มทั้ง Backend (FastAPI พอร์ต 8000) และ Frontend (Next.js พอร์ต 3001) พร้อมแสดง IP ให้เชื่อมต่อจาก iPad ทันที (กด `Ctrl + C` เมื่อต้องการหยุดการทำงานทั้งหมด)

---

### วิธีที่ 2: รันแยก 2 หน้าต่าง Terminal (สำหรับ Development)

#### Terminal 1 — รัน Backend (FastAPI):
```bash
cd "/Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend"
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
- Swagger API Docs: `http://localhost:8000/docs`
- Health Status: `http://localhost:8000/api/system/status`

#### Terminal 2 — รัน Frontend (Next.js):
```bash
cd "/Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend"
npm run dev
```
- เปิดหน้าเว็บ: `http://localhost:3001`
- รหัสผ่านสิทธิ์ควบคุมเครื่อง: ดูจาก `backend/data/.operator-passcode` บนเครื่องสถานี หรือค่าที่ตั้งใน `backend/.env`



---

### สำหรับ NVIDIA Jetson (JetPack 5/6)

> [!IMPORTANT]
> บน Jetson ห้ามติดตั้ง `torch` ปกติผ่าน `pip` เพราะจะไม่มี CUDA Support ให้ใช้ Wheel ทางการของ NVIDIA

```bash
cd backend
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r requirements-jetson.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

---

## 6. การเข้าใช้งานผ่าน iPad หรือคอมพิวเตอร์ในเครือข่าย LAN

1. เชื่อมต่ออุปกรณ์กับ Wi-Fi เดียวกันกับเครื่องแม่ข่าย
2. ตรวจสอบ IP เครื่องแม่ข่าย (เช่น `192.168.1.42`)
3. เปิด Safari หรือ Chrome บน iPad เข้าที่:
   ```
   http://192.168.1.42:3001
   ```
4. ระบบรองรับ Touch Gestures: สัมผัสเพื่อเลือก Component, ลากเพื่อ Pan ภาพ, และปุ่มกดมีขนาดไม่ต่ำกว่า 44px ตามมาตรฐาน UI Touchscreen

---

## 7. ขั้นตอนตรวจรับกับเครื่องจริง (Hardware Commissioning Checklist)

1. ตรวจสอบให้แน่ใจว่าไม่มีโปรแกรมอื่น (เช่น Arduino IDE หรือ Desktop GUI) เปิดพอร์ต Serial ค้างไว้
2. เข้าหน้า **AOI Automated Scan** บนเว็บ เลือกโหมด **Serial (Nano)** และเลือกพอร์ต `/dev/cu.usbserial*`
3. กด **Connect Stage** และตรวจเช็กข้อความในหน้าต่างการเชื่อมต่อ ต้องได้รับ `[READY] 2 0 0 21167 20446 0`
4. กดปุ่ม **HOME** เพื่อให้เครื่องวิ่งหา Limit Switches จนเสร็จสมบูรณ์
5. ทดสอบการ Jog ทีละ 0.1 mm และ 1.0 mm เพื่อยืนยันว่าทิศทางการเคลื่อนที่ถูกต้อง
6. ทดสอบกดปุ่ม **STOP** ฉุกเฉินเพื่อยืนยันว่ามอเตอร์หยุดการทำงานทันที
