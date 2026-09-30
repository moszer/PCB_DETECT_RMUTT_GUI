# รายงานตรวจ Backend + Frontend ของ PCB AOI — 25 กันยายน 2026

**ผลประเมิน:** ยังไม่พร้อมใช้แทน Desktop GUI หรือควบคุม AOI จริง มีทั้งบั๊กที่ขัดขวางการทำงาน และฟังก์ชันที่ยังไม่ได้ย้ายมา รายการ P1 ควรแก้ก่อนทดสอบเครื่องจริง

## ขอบเขตและวิธีตรวจ

- อ่าน backend/app, frontend/src และเทียบ main_program/app ล่าสุดใน workspace
- ตรวจ API contracts, state machine, camera, inference, persistence, authentication และ UI wiring
- สำเนา source ไป temp ก่อนรัน backend tests และ production build เพื่อไม่ใช้ฐานข้อมูลจริงหรือรบกวน .next ของโปรแกรมที่กำลังเปิด
- ทดสอบเฉพาะ TestClient, fake capture/client และ Simulation ไม่เปิด Serial/กล้องจริง และไม่สั่งมอเตอร์จริง
- ไม่แก้ source/config/environment ของ backend/frontend/GUI; เพิ่มเฉพาะรายงานและหลักฐานในโฟลเดอร์ audit นี้
- ก่อนเริ่มพบ main_program มีการแก้ไขที่ยังไม่ commit อยู่แล้ว จึงไม่สามารถระบุว่าเว็บที่สร้างก่อนหน้านี้ไม่เคยกระทบ GUI ได้จาก git status เพียงอย่างเดียว ไม่มีการ reset หรือแก้ไฟล์เหล่านั้นในการตรวจครั้งนี้
- ยังไม่ได้ทดสอบ browser บน iPad, Jetson, YOLO detection accuracy กับ dataset จริง หรือ hardware end-to-end ข้อสรุปเกี่ยวกับ UI แยกระหว่างตรวจ source กับ render component ชัดเจน

## ผลตรวจที่รันจริง

| รายการ | ผล |
|---|---|
| Backend tests เดิม บนสำเนาแยก | 14 passed, 1 dependency deprecation warning |
| Frontend TypeScript | ผ่าน; production build ทำ TypeScript check อีกครั้ง |
| Production build บนสำเนาแยก | `npm run build -- --webpack` ผ่าน; ไม่ได้ทดสอบ default Turbopack build |
| ESLint เฉพาะ frontend/src | 61 errors, 25 warnings; ไม่ใช่จำนวน runtime bugs |
| Python probes เจาะจง | ทำซ้ำอาการที่ระบุได้ 14/14 กรณี (บางกรณีเป็นกลุ่มบั๊กเดียวกัน) |
| React ReferencesView render | ทำซ้ำ crash จาก shape ของ list API ได้ |
| Machine state broadcast | ทำซ้ำ stale state หลัง simulated Jog ได้ |

เทสต์เดิมชื่อ test_aoi_plan_and_simulation_scan เรียกเพียง /api/aoi/plan ไม่ได้ start/stop scan จึงไม่พบ deadlock ส่วน test_lease_acquire_and_release ส่งคำขอโดยไม่มี passcode แล้วคาดหวังสำเร็จ เทสต์จึงไม่ได้ยืนยันความถูกต้องของ authentication การ build ผ่านยืนยันการคอมไพล์ ไม่ได้ยืนยันว่า API และ UI ทำงานเข้ากันทุกเส้นทาง

## Findings เรียงตามผลกระทบ

### F01 — P1 — เริ่ม AOI แล้ว deadlock

**หลักฐาน:** ทำซ้ำได้: thread ค้างที่ start_scan → is_running → acquire lock

`start_scan()` ถือ `threading.Lock` แล้วเรียก property `is_running` ซึ่งขอล็อกตัวเดิมอีกครั้ง ล็อกชนิดนี้เข้าใช้งานซ้ำจาก thread เดียวกันไม่ได้ จึงค้างก่อนตรวจกล้อง/โมเดลด้วยซ้ำ หลังเรียก Start การอ่าน current_run, เปลี่ยนโมเดล และการตอบกลับ STOP ก็อาจค้างตาม เพราะใช้ล็อกเดียวกัน STOP ส่งคำสั่งไป machine ก่อนรอล็อก แต่ HTTP request ไม่จบ จึงห้ามสรุปว่าเครื่องไม่รับ STOP ทุกกรณี

**จุดอ้างอิง:** [backend/app/services/aoi_scan_service.py:38](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/aoi_scan_service.py:38>), [backend/app/services/aoi_scan_service.py:108](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/aoi_scan_service.py:108>), [backend/app/services/aoi_scan_service.py:157](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/aoi_scan_service.py:157>)

**แนวทางแก้/ตรวจรับ:** ตรวจสถานะภายใน critical section โดยไม่ล็อกซ้อน ออกแบบ Start/Stop ให้ atomic และรอ worker เดิมหยุดก่อนเริ่มใหม่ ทดสอบ Start ครั้งแรก/ซ้ำพร้อมกันและ STOP ให้คืนค่าภายในเวลาที่กำหนด ไม่ใช้เพียงการเพิ่ม timeout

### F02 — P1 — ตรวจรูป upload ขวาง event loop ของ API รวมถึงคำสั่ง STOP

**หลักฐาน:** ทำซ้ำได้ด้วย inference stub 250 ms; heartbeat ใน asyncio หายไป 262 ms

Endpoint upload เป็น async แต่เรียกโหลดโมเดลและ predict แบบ synchronous รวมทั้ง decode/annotate/เขียนไฟล์ใน event loop ระหว่างนี้ HTTP และ WebSocket ใน process เดียวกันถูกหน่วง คำสั่ง STOP ผ่าน HTTP ต้องรอให้ loop กลับมารับงาน แม้ serial pump จะอยู่คนละ thread

**จุดอ้างอิง:** [backend/app/routers/inspection.py:19](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/routers/inspection.py:19>), [backend/app/routers/inspection.py:50](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/routers/inspection.py:50>)

**แนวทางแก้/ตรวจรับ:** ย้ายงานหนักไป worker ที่มีคิวจำกัด ให้ event loop รับ STOP ได้ระหว่าง inference และทดสอบการส่งคำสั่งพร้อมตรวจรูปช้า

### F03 — P1 — สิทธิ์ควบคุมถูกข้ามและข้อมูลยืนยันตัวตนถูกเปิดเผย

**หลักฐาน:** ทำซ้ำผ่าน TestClient: ไม่ส่ง passcode ก็ acquire ได้, force takeover ได้, อ่าน operator token และ passcode ได้โดยไม่ยืนยันตัวตน

auth ตรวจ passcode เฉพาะเมื่อผู้เรียกส่งมา; lease endpoint และ system/status เปิดเผย active_operator_id ซึ่งถูกใช้เป็น credential; settings คืน operator_passcode ทั้งก้อน; ถ้าไม่มี lease จะอนุญาตคำสั่งเครื่องทันที Frontend ส่ง force=true ทุกครั้งที่ขอสิทธิ์ อีกทั้ง endpoint กล้อง โมเดล Settings และ Reference ไม่มีการตรวจสิทธิ์

**จุดอ้างอิง:** [backend/app/routers/auth.py:37](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/routers/auth.py:37>), [backend/app/routers/aoi.py:41](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/routers/aoi.py:41>), [backend/app/routers/system.py:72](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/routers/system.py:72>), [frontend/src/components/Header.tsx:46](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend/src/components/Header.tsx:46>)

**แนวทางแก้/ตรวจรับ:** แยก session secret จากข้อมูล operator ที่เปิดให้ดู บังคับ authentication/authorization ฝั่ง backend ไม่รับ force จากผู้ใช้ทั่วไป ไม่คืน secrets ใน response และทดสอบสองผู้ใช้พร้อมกัน

### F04 — P1 — Reference ID สามารถพาไฟล์ JSON ออกนอกโฟลเดอร์ที่กำหนด

**หลักฐาน:** ทำซ้ำเฉพาะไฟล์ทดสอบใน temp: POST Reference ด้วย ID ../audit_escape สร้าง JSON ที่ parent ของ references ได้

นำ profile.id ต่อเป็นเส้นทางไฟล์โดยตรงและไม่ตรวจ containment จึงมีโอกาสเขียนทับ JSON อื่นตามสิทธิ์ของ backend รวมถึงพื้นที่นอกข้อมูลเว็บ ข้อนี้เกี่ยวข้องกับข้อกำหนดไม่กระทบข้อมูล GUI เดิม การทดสอบไม่ได้แตะไฟล์จริงนอก sandbox ชั่วคราว

**จุดอ้างอิง:** [backend/app/services/storage_service.py:374](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/storage_service.py:374>), [backend/app/routers/references.py:27](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/routers/references.py:27>)

**แนวทางแก้/ตรวจรับ:** ให้ server สร้าง ID หรือจำกัดเป็น UUID/slug แล้วตรวจ resolved path ให้อยู่ใต้ references เสมอ ทดสอบทั้ง relative/absolute path และบังคับสิทธิ์เขียน

### F05 — P1 — Soft limit ที่แสดงกับที่เครื่องใช้ไม่ตรงกัน

**หลักฐาน:** ทำซ้ำใน Simulation: เปลี่ยนเป็น 1×1 mm แต่ MotionClient ยังใช้ 19456×19456 steps หรือ 38×38 mm; planner ยอมรับจุด X=39 mm

update_settings เปลี่ยนเพียง MachineService._soft_limits_mm แต่ไม่เปลี่ยน client.soft_limits ที่ใช้ตรวจ MOVE/Jog และ planner ตรวจแค่ firmware limits จึงแสดงแผนที่สั่งจริงไม่ได้หรือยอมให้เคลื่อนที่เกินขอบเขตใหม่ที่ผู้ใช้ตั้งไว้

**จุดอ้างอิง:** [backend/app/routers/system.py:89](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/routers/system.py:89>), [backend/app/services/machine_service.py:145](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/machine_service.py:145>), [backend/app/services/aoi_scan_service.py:66](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/aoi_scan_service.py:66>)

**แนวทางแก้/ตรวจรับ:** อัปเดตค่าที่ใช้บังคับจริงผ่าน method ที่ล็อกอย่างถูกต้อง ตรวจช่วงค่าก่อนรับ ใช้ effective limits เดียวกันใน planner/command/UI และห้ามเปลี่ยนขอบเขตระหว่างงาน

### F06 — P1 — ตัดการเชื่อมต่อระหว่าง MOVE แต่ระบบแจ้งว่าสำเร็จ

**หลักฐาน:** ทำซ้ำด้วย fake transport/client: move_to_steps คืน True หลัง disconnect ขณะรอ completion

disconnect ปลุก Event ของคำสั่งที่รอ แล้วตั้ง client=None; move_to_steps ตรวจตำแหน่งเฉพาะเมื่อยังมี client จึงผ่านไปคืน True การยกเลิกถูกตีความเป็นสำเร็จ งาน AOI มีโอกาสไปจับภาพต่อทั้งที่ไม่ถึงจุดที่ต้องการ

**จุดอ้างอิง:** [backend/app/services/machine_service.py:165](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/machine_service.py:165>), [backend/app/services/machine_service.py:240](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/machine_service.py:240>)

**แนวทางแก้/ตรวจรับ:** เก็บผล command ตาม ID เป็น success/cancelled/error ตรวจ DONE ID, connected, homed และตำแหน่งปลายทางให้ครบ ทุกการ disconnect/STOP ต้องยกเลิก waiter อย่างมีเหตุผล

### F07 — P1 — หน้า Reference พังเมื่อเลือกโปรไฟล์ที่โหลดจากรายการ

**หลักฐาน:** ยืนยัน API shape และ render React component จริง: Cannot read properties of undefined (reading map)

list_references คืนแค่ metadata ไม่มี points/grid_points แต่ frontend เก็บรายการเป็น ReferenceProfile เต็ม และเรียก selectedRef.points.map โดยไม่โหลด detail ตอนเลือก Single profile จึง crash; AOI profile แสดงรายการจุดว่าง และจำนวนจุดในตัวเลือกผิด การ import ใหม่อาจดูเหมือนทำงานเพราะ endpoint import คืน detail ครบ แต่กลับเข้าหน้าใหม่ก็เจอปัญหาเดิม

**จุดอ้างอิง:** [backend/app/services/storage_service.py:391](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/storage_service.py:391>), [frontend/src/components/ReferencesView.tsx:17](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend/src/components/ReferencesView.tsx:17>), [frontend/src/components/ReferencesView.tsx:158](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend/src/components/ReferencesView.tsx:158>), [frontend/src/lib/api.ts:186](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend/src/lib/api.ts:186>)

**แนวทางแก้/ตรวจรับ:** แยกชนิด ReferenceSummary กับ ReferenceProfile เรียก getReference(id) เมื่อเลือกและมี loading/error state ทดสอบทั้ง refresh และ import แล้วกลับเข้าใหม่ หลีกเลี่ยง any ที่กลบ contract mismatch

### F08 — P1 — System status คืน HTTP 500 เมื่อมี AOI run

**หลักฐาน:** ทำซ้ำโดยใส่ AOIRunReport ใน service แล้ว GET /api/system/status ได้ 500

Endpoint อ่าน r.total_points แต่ AOIRunReport ไม่มี field นี้ แม้ start_scan ส่ง total_points เข้า constructor ก็ถูก Pydantic ละทิ้งตามค่าเริ่มต้น บั๊กนี้จะปรากฏต่อเมื่อแก้ deadlock หรือมี current_run อยู่แล้ว

**จุดอ้างอิง:** [backend/app/routers/system.py:44](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/routers/system.py:44>), [backend/app/core/schemas.py:156](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/core/schemas.py:156>), [backend/app/services/aoi_scan_service.py:140](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/aoi_scan_service.py:140>)

**แนวทางแก้/ตรวจรับ:** ใช้ len(points) หรือ computed field และกำหนด schema ของ status ให้ตรง frontend ทดสอบ status ระหว่าง running, complete, aborted และ error

### F09 — P1 — Golden Reference ไม่ตรวจว่าตรงกับตำแหน่ง/กล้อง/โมเดลของงาน

**หลักฐาน:** พบจากการเทียบโค้ด เป็นเส้นทางที่จะทำงานหลังแก้ F01

เว็บจับคู่ Golden ด้วย col_row หรือ point index เท่านั้น ไม่เก็บหรือเทียบ origin/pitch/จุดเครื่อง/ROI/ขนาดภาพ/โมเดลและค่าตรวจในโปรไฟล์ จึงเลือก baseline จากแผนอื่นที่ใช้ index เดียวกันได้ GUI เดิมตรวจ signature ของแผนก่อนเริ่ม งานเว็บจึงอาจให้ผลผ่านหรือไม่ผ่านจากบริเวณอ้างอิงคนละจุด

**จุดอ้างอิง:** [backend/app/services/aoi_scan_service.py:255](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/aoi_scan_service.py:255>), [backend/app/services/aoi_scan_service.py:319](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/aoi_scan_service.py:319>), [backend/app/core/schemas.py:51](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/core/schemas.py:51>), [main_program/app/aoi_dialog.py:1340](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/main_program/app/aoi_dialog.py:1340>)

**แนวทางแก้/ตรวจรับ:** บันทึก provenance และ scan signature ตอน teach ตรวจ compatibility ก่อนเริ่มหรือ reject อย่างชัดเจน พร้อมทดสอบเปลี่ยน origin/pitch/resolution/model แล้วต้องไม่เทียบข้าม baseline

### F10 — P1 — เปิดกล้องไม่ได้แต่รายงานว่า Active และยอมใช้ภาพจำลองตรวจ

**หลักฐาน:** ทำซ้ำด้วย VideoCapture ที่เปิดไม่สำเร็จ: start คืนสำเร็จและ is_active=True

CameraService fallback เป็นภาพ generator โดยอัตโนมัติ ภาพมีข้อความ SIMULATED แต่ SystemStatus ไม่ส่ง flag ว่าเป็นกล้องจำลอง และ AOI ระบุ simulation จากโหมดเครื่องเท่านั้น ถ้าเครื่องเป็น Serial แต่กล้องเสีย ระบบสามารถใช้ภาพจำลองในงานที่ถูกระบุว่าเป็นงานจริงได้

**จุดอ้างอิง:** [backend/app/services/camera_service.py:72](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/camera_service.py:72>), [backend/app/services/camera_service.py:34](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/camera_service.py:34>), [backend/app/services/aoi_scan_service.py:134](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/aoi_scan_service.py:134>)

**แนวทางแก้/ตรวจรับ:** ให้ mock เป็นโหมดที่เลือกอย่างชัดเจน เปิดกล้องจริงไม่สำเร็จต้อง ERROR และห้าม production scan รับ mock/stale frame ตรวจทั้ง camera source และ stage mode ในข้อมูลผลตรวจ

### F11 — P2 — เปลี่ยนกล้องเดิมจาก 1080p เป็น 4K แล้วไม่มีผล

**หลักฐาน:** ทำซ้ำกับ fake capture: ขอ 3840×2160 หลังเริ่ม 1920×1080 แต่ resolution คงเดิม

start คืน True ทันทีหาก device_index เดิม โดยไม่เทียบ width/height/fps นอกจากนี้ frontend ไม่เรียก startCamera/stopCamera เลย และ stream endpoint เปิด camera index 0 ที่ค่า default 1080p อัตโนมัติ จึงยังไม่มีทางเลือกกล้อง/4K ผ่าน UI จริง

**จุดอ้างอิง:** [backend/app/services/camera_service.py:49](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/camera_service.py:49>), [backend/app/routers/camera.py:19](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/routers/camera.py:19>), [frontend/src/components/InspectionView.tsx:41](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend/src/components/InspectionView.tsx:41>), [frontend/src/lib/api.ts:92](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend/src/lib/api.ts:92>)

**แนวทางแก้/ตรวจรับ:** เพิ่ม UI เลือกกล้องและ mode ต่อ API ให้ครบ เปลี่ยน capture settings อย่างปลอดภัย หยุด/join thread เดิมก่อนเปิดใหม่ ตรวจขนาดจากเฟรมจริงและแสดง requested เทียบ actual

### F12 — P2 — ตำแหน่งเครื่องบนเว็บค้างหลัง Jog

**หลักฐาน:** ทำซ้ำใน Simulation: machine อยู่ [512,0] และหยุดแล้ว แต่ broadcast ล่าสุดยัง [0,0] และ moving=True

MachineService notify ตอนออกคำสั่ง แต่ on_event DONE/POS/ERROR และ pump ไม่ broadcast สถานะล่าสุด หน้า page เลือก machineState จาก WebSocket ทับผล polling เสมอ จึงยังแสดงค่าเก่าแม้ GET status จะมีค่าใหม่

**จุดอ้างอิง:** [backend/app/services/machine_service.py:127](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/machine_service.py:127>), [backend/app/services/machine_service.py:177](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/machine_service.py:177>), [frontend/src/app/page.tsx:52](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend/src/app/page.tsx:52>)

**แนวทางแก้/ตรวจรับ:** ส่ง state snapshot หลังเปลี่ยนสถานะพร้อม sequence/time และเลือกข้อมูลใหม่ที่สุดใน frontend ทดสอบ Jog จบ, serial fault และ WS disconnect/reconnect

### F13 — P2 — ผล AOI แต่ละจุดไม่ถูกสะสมในหน้าเว็บระหว่างสแกน

**หลักฐาน:** ตรวจ contract จาก source; ยังไม่ทดสอบสแกนจริงเพราะติด F01

point_complete ส่ง point_result แต่ useStationSocket เพียงแทน scanProgress ด้วย event ล่าสุด จากนั้น page ใช้เฉพาะ scanProgress.report ซึ่งมีใน complete/active_run ส่วน fallback status ส่งแค่ summary ไม่มี results ตารางจุดจึงไม่รับภาพทีละจุด และ abort/error ไม่ได้อัปเดต full report อย่างสม่ำเสมอ

**จุดอ้างอิง:** [backend/app/services/aoi_scan_service.py:303](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/aoi_scan_service.py:303>), [frontend/src/hooks/useStationSocket.ts:58](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend/src/hooks/useStationSocket.ts:58>), [frontend/src/app/page.tsx:76](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend/src/app/page.tsx:76>), [frontend/src/components/AOIScanView.tsx:179](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend/src/components/AOIScanView.tsx:179>)

**แนวทางแก้/ตรวจรับ:** ใช้ reducer สำหรับ run snapshot และ event ที่มี run_id/sequence หรือดึง full run เมื่อ event มา รองรับ duplicate/out-of-order/reconnect แล้วไม่ทำผลจุดหาย

### F14 — P2 — ช่องเปลี่ยนโมเดลไม่ได้ใช้งานจริง และ Save Configuration ไม่ถาวร

**หลักฐาน:** ตรวจ source: modelPath มีเพียง state/input; ไม่มี caller ของ api.setModel ใน component; backend เก็บ settings ในหน่วยความจำ

กด Save ส่งเฉพาะ station/operator/soft limits ไม่ส่ง model_path จึงแสดง Saved แต่โมเดลไม่เปลี่ยน ค่า settings อื่นหายเมื่อ backend restart; Inspection ใช้ conf/match_dist ที่ hardcode ใน component ไม่ดึง defaults ที่บันทึก

**จุดอ้างอิง:** [frontend/src/components/SettingsView.tsx:61](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend/src/components/SettingsView.tsx:61>), [frontend/src/components/SettingsView.tsx:164](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend/src/components/SettingsView.tsx:164>), [backend/app/routers/system.py:78](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/routers/system.py:78>), [frontend/src/components/InspectionView.tsx:30](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend/src/components/InspectionView.tsx:30>)

**แนวทางแก้/ตรวจรับ:** ต่อคำสั่งโหลดโมเดลพร้อม loading/error ให้แสดงโมเดลที่ backend ยืนยัน บันทึก settings แยกจาก GUI ลง disk/DB และ reload เมื่อเริ่มใหม่ ทดสอบเปลี่ยนโมเดลและ restart

### F15 — P2 — History ไม่แสดงผลตรวจภาพเดี่ยว และเปิดรายละเอียดรอบเก่าไม่ได้จาก UI

**หลักฐาน:** ทำซ้ำ: บันทึก single inspection 1 รายการ แต่ /history/runs คืน total=0; ตรวจ UI ไม่มีคำสั่ง getRun

ผลภาพ upload/live เก็บใน single_inspections ขณะที่ list/history/statistics/CSV อ่าน runs เท่านั้น หน้า History แสดงแค่ตาราง AOI ไม่มีการคลิกไปดูภาพและผลแต่ละจุด รวมถึงไม่มี pagination แม้ API จำกัด 50 รายการ

**จุดอ้างอิง:** [backend/app/services/storage_service.py:143](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/storage_service.py:143>), [backend/app/services/storage_service.py:267](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/storage_service.py:267>), [frontend/src/components/HistoryView.tsx:171](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend/src/components/HistoryView.tsx:171>)

**แนวทางแก้/ตรวจรับ:** แยกประวัติ single/AOI ให้ผู้ใช้เห็นชัดหรือรวมผ่าน contract เดียว เพิ่ม run detail และ pagination ทดสอบตรวจภาพแล้วเปิดดูย้อนหลังและ export พบรายการนั้น

### F16 — P2 — สถิติ production นับ Simulation และ Golden scan รวมด้วย

**หลักฐาน:** ทำซ้ำ: สร้าง completed simulation PASS 1 งานแล้ว production yield เป็น 100%

Query กรองเฉพาะ status=complete ไม่แยก is_simulation/is_golden_scan และ board yield ใช้ REVIEW เป็นตัวหาร ทำให้สถิติไม่ได้สะท้อนผลผลิตที่ตัดสินผ่าน/ไม่ผ่านตามปกติ

**จุดอ้างอิง:** [backend/app/services/storage_service.py:296](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/storage_service.py:296>)

**แนวทางแก้/ตรวจรับ:** กำหนดนิยาม KPI กรอง simulation/teach ออกจาก production และแสดง REVIEW/ERROR แยก ทดสอบข้อมูลผสมทั้งโหมดและ verdict

### F17 — P2 — สิทธิ์ผู้ควบคุมหมดอายุเองและไม่มีนโยบายหยุดงานเมื่อหลุด

**หลักฐาน:** ตรวจ source ทั้ง frontend/backend: renewLease มีเพียง declaration ไม่มี caller; WS ping ไม่ต่อ lease

Lease TTL เป็น 20 วินาที แต่ frontend ไม่ต่ออายุ README ระบุว่าต่อทุก 5 วินาทีซึ่งไม่ตรง implementation เมื่อหมดอายุ manager ลบ lease เฉย ๆ ไม่มี callback ไปหยุดงานและ F03 จะเปิดทางให้คำสั่งไม่มีสิทธิ์ผ่านได้

**จุดอ้างอิง:** [frontend/src/lib/api.ts:88](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend/src/lib/api.ts:88>), [frontend/src/hooks/useStationSocket.ts:39](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend/src/hooks/useStationSocket.ts:39>), [backend/app/core/security.py:26](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/core/security.py:26>), [backend/app/routers/ws.py:73](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/routers/ws.py:73>)

**แนวทางแก้/ตรวจรับ:** เพิ่ม renewal ตาม session และนโยบาย lease expiry ฝั่ง backend โดยไม่ผูกความปลอดภัยกับการเปิด tab ทดสอบแท็บ background, ปิด browser, เครือข่ายหลุด และผู้ใช้คนใหม่

### F18 — P2 — Restart ไม่เปลี่ยนงานที่ค้างให้เป็น interrupted/error

**หลักฐาน:** ตรวจ lifecycle และ storage initialization: ไม่มี recovery ของ rows ที่ status=running

รายงานถูกเขียนเป็น running ระหว่างงาน แต่เมื่อ backend เปิดใหม่ current_run กลับ None ขณะที่ DB/JSON งานเดิมยัง running และไม่เชื่อมกลับเข้าหน้า active scan การปิดโปรแกรมก็ไม่ได้ให้ scan worker จบและ finalize อย่างชัดเจน

**จุดอ้างอิง:** [backend/app/main.py:25](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/main.py:25>), [backend/app/services/storage_service.py:40](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/storage_service.py:40>), [backend/app/services/aoi_scan_service.py:37](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/backend/app/services/aoi_scan_service.py:37>)

**แนวทางแก้/ตรวจรับ:** ทำ graceful shutdown และ startup recovery เปลี่ยนงานไม่สมบูรณ์เป็น interrupted/aborted พร้อมเหตุผลและคงภาพที่บันทึกแล้ว ห้าม resume มอเตอร์เอง

### F19 — P2 — Fit/1:1 ของภาพไม่อิงขนาดแสดงจริง และยังไม่มี touch pan/pinch

**หลักฐาน:** ตรวจ source; ยังไม่ได้วัด layout บน iPad/กล้องจริง

Fit ตั้ง scale=1 แต่ img ใช้ max-w-none และจำกัดสูงด้วย 75vh จึงไม่รับประกันว่าจะพอดีพื้นที่ด้านกว้าง ส่วน 1:1 ใช้ naturalWidth/containerWidth แทนอัตราส่วนกับขนาด img ที่แสดงจริง ซึ่งอาจถูกจำกัดด้วยความสูง มีเพียง mouse/wheel handlers ไม่มี pointer/touch gestures ตามที่ README อ้าง

**จุดอ้างอิง:** [frontend/src/components/Viewport.tsx:72](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend/src/components/Viewport.tsx:72>), [frontend/src/components/Viewport.tsx:110](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend/src/components/Viewport.tsx:110>), [frontend/src/components/Viewport.tsx:173](</Users/pattaraponprakodchue/Desktop/PCB Detect Defect RMUTT/defect detection yolo/frontend/src/components/Viewport.tsx:173>)

**แนวทางแก้/ตรวจรับ:** คำนวณ fit จากทั้ง width/height ของ viewport และ image; 1:1 ให้หนึ่ง image pixel เท่าหนึ่ง CSS pixel ตามนิยามที่แสดง รองรับ Pointer Events/pinch และทดสอบหลาย aspect ratio กับ iPad

## ฟังก์ชันที่หายไปหรือยังไม่เทียบเท่า GUI เดิม

| ฟังก์ชัน | หลักฐาน GUI เดิม | สถานะเว็บที่พบ |
|---|---|---|
| Mark ตำแหน่งเอง / ลบ / Replay / ไปจุดที่เลือก | aoi_dialog.py:1171,1213,1236 | มีเฉพาะ raster grid; schema ไม่มีรายการ marked points |
| Zoom ต่อจุด / แก้ Zoom ของจุดที่เลือก | aoi_dialog.py:1135,1151 | ไม่มี field หรือ UI; zoom ภาพใน Inspection เป็นแค่ display |
| AOI live view / crosshair / ตั้ง origin จากตำแหน่งปัจจุบัน | aoi_dialog.py:1492,1497,1516 | หน้า AOI มี connection/grid/results แต่ไม่มี live camera workspace เหล่านี้ |
| ดูภาพ AOI แบบเต็ม 4K / 1:1 พร้อมเลื่อนภาพ | aoi_dialog.py:1788 | Modal ใช้ภาพสูงสูงสุด 380px ไม่มีตัวควบคุม full-resolution |
| สร้างและแก้ Reference บนภาพ / เลือก class / Undo / Redo | model_reference_mixin.py:110,134,153 | หน้า References มี import/list/delete แต่ไม่มี editor |
| เพิ่ม Extra detections เข้า Reference | model_reference_mixin.py:180 | ไม่มี UI flow |
| เปิด Reference JSON ที่เลือกเอง / export | model_reference_mixin.py:165,249 | import ได้เฉพาะ Refs.json path ตายตัวฝั่ง server |
| โหลด Golden AOI report เดิมและตรวจ signature | aoi_dialog.py:1321,1340 | ไม่รองรับรูปแบบ report เดิมและไม่มี compatibility check เทียบเท่า |
| เปิดโฟลเดอร์ภาพ / ก่อนหน้า / ถัดไป | browse_mixin.py:16,113,116 | Upload ได้ไฟล์เดียว ไม่มี folder/batch navigation |
| เลือก camera index / Start-Stop / ความละเอียด | camera_mixin.py:48; aoi_dialog.py:1124 | API บางส่วนมี แต่ไม่มี component เรียก startCamera/stopCamera |
| ปรับ speed / settle / threshold ของ AOI | aoi_dialog.py UI + scan config | speed=800 และ settle=0.5 ใน state; ไม่มีตัวปรับ settle และ AOI เรียก API ด้วย detection defaults |
| บันทึก annotated image จากหน้าตรวจ | inspection_mixin.py:441 | backend มีไฟล์ แต่หน้า Inspection ไม่มีปุ่ม Save/Download |
| ประวัติตรวจภาพเดี่ยวและส่งออก | history_mixin.py:48,169 | บันทึก DB แล้วแต่ไม่มีเส้นทางแสดง/export ให้ผู้ใช้ |
| เปิดผลรอบ AOI เก่าและดูภาพแต่ละจุด | aoi_dialog.py:1732,1837 | History เป็นตารางสรุป; getRun API ไม่ถูกใช้ |
| Theme / overlay toggles / keyboard shortcuts | ui_mixin.py:281,778; interaction_mixin.py:19 | ยังไม่มีความสามารถเทียบเท่าในเว็บ |
| Software updates | main_program/app/update_dialog.py | ยังไม่มีเว็บ updater; ควรออกแบบ idle-only update แยกจากการควบคุมเครื่อง |

การเปิดโฟลเดอร์ฝั่ง server, การดาวน์โหลดไฟล์ และ software update ควรปรับ UX ให้เข้ากับเว็บ ไม่จำเป็นต้องคัดลอก desktop behavior ตรง ๆ แต่ต้องกำหนด workflow ทดแทนให้ครบ

## ลำดับแก้ที่เสนอ

1. **ทำให้ Start/Stop และ ownership เชื่อถือได้:** F01–F06, F10, F17; เพิ่ม tests ที่ล้มเหลวจากอาการจริงก่อนแก้ ทดสอบ simulation เท่านั้น
2. **ทำ API contracts และสถานะให้ครบ:** F07–F09, F12–F13; schema เดียว, typed frontend, full snapshot + events, reference compatibility
3. **ต่อ UI เข้ากับบริการจริง:** F11, F14–F16, F18–F19; โมเดล/กล้อง/การบันทึก/ประวัติ/การคืนสถานะหลัง restart
4. **เติม feature parity:** เริ่ม marked points/replay, Reference editor, AOI live/full-image viewer, camera controls แล้ว folder browsing/export
5. **ตรวจรับ:** backend regression + frontend component/integration tests, browser end-to-end, Simulation end-to-end จากนั้นจึงขอทดสอบเครื่องจริงตามขอบเขตที่เจ้าของเครื่องอนุญาต

ทุกขั้นต้องรักษา main_program เป็น read-only และใช้ข้อมูล/virtual environment ของเว็บแยก หากต้องแก้ Desktop ให้แยกขอบเขตงานและขออนุมัติก่อน

## หลักฐานที่ส่งมอบ

- [Python probes](./reproduce_backend_findings.py): ทดสอบอาการ 14 กรณี เก็บข้อมูลใน temp และปิดกั้น real Serial/VideoCapture ระหว่าง probes; ควรรันบนสำเนา backend ที่แยกจาก production
- [ผล Python probes](./backend-probes.json)
- [ผล React render](./reference-render-probe.json)
- [ผล state broadcast](./machine-state-probe.json)
- [ESLint summary](./eslint-summary.json)

การยืนยันว่าบั๊กเกิดขึ้นได้ใน probe ไม่เท่ากับทดสอบระบบทั้งหมดผ่าน รายงานนี้เป็น audit ไม่ได้ติดตั้ง patch หรือแก้บั๊กให้แล้ว
