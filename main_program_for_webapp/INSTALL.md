# ติดตั้ง RMUTT PCB AOI Station

ติดตั้งด้วยคำสั่งเดียว สคริปต์ตรวจเองว่าเครื่องเป็น macOS, Linux หรือ NVIDIA Jetson แล้วติดตั้ง PyTorch ให้ตรงรุ่น

| เครื่อง | ใช้ AI ประมวลผลด้วย | OCR อ่านเบอร์ชิป |
|---|---|---|
| Mac (Apple Silicon M1–M4) | Apple GPU (MPS) | Apple Vision |
| Linux PC มีการ์ดจอ NVIDIA | CUDA | tesseract |
| Linux PC ไม่มีการ์ดจอ / Raspberry Pi | CPU | tesseract |
| Jetson Orin Nano (JetPack 7) | CUDA (ทดสอบแล้ว) | tesseract |
| Jetson (JetPack 6) | CUDA (ดาวน์โหลดจาก Jetson AI Lab) | tesseract |

---

## 1. ติดตั้งแบบปกติ (แนะนำ)

```bash
git clone https://github.com/moszer/PCB_DETECT_RMUTT_GUI.git
cd PCB_DETECT_RMUTT_GUI/main_program_for_webapp
./install.sh
./run_web.sh
```

เปิดเบราว์เซอร์ที่ **http://localhost:3001** เครื่องอื่นในวงแลนเดียวกันเข้าได้ทาง IP ที่สคริปต์แสดงตอนเริ่ม

`install.sh` จัดการให้:
1. ลงโปรแกรมระบบ: macOS ใช้ Homebrew (Python, Node.js) / Ubuntu ใช้ apt (Python, build tools, libGL, tesseract, v4l-utils) และ Node.js 22 LTS
2. สร้าง Python venv ที่ `backend/venv` แล้วลง **PyTorch รุ่นที่ตรงกับเครื่อง** และไลบรารี backend
3. ลงแพ็กเกจหน้าเว็บ (`npm ci`)
4. สร้าง `backend/.env` จาก `.env.example`
5. Linux: เพิ่มผู้ใช้เข้ากลุ่ม `dialout` (สเตจ XY ผ่าน USB serial) และ `video` (กล้อง) **ต้อง logout/login ใหม่ 1 ครั้ง**
6. ตรวจผล: แสดงรุ่น Python/torch/OpenCV, ฮาร์ดแวร์ AI ที่ใช้ได้ และ OCR

รัน `./install.sh` ซ้ำได้ทุกเมื่อ (เช่นหลัง `git pull`) จะอัปเดตเฉพาะที่เปลี่ยน

### ตัวเลือก

| คำสั่ง | ใช้เมื่อ |
|---|---|
| `./install.sh --cpu` | Linux PC: ลง PyTorch แบบ CPU อย่างเดียว (ไฟล์เล็กกว่ามาก) |
| `./install.sh --test` | รันชุดทดสอบ backend ท้ายสุด |
| `./install.sh --no-system` | ข้ามการลงโปรแกรมระบบ (ไม่มีสิทธิ์ sudo หรือลงเองแล้ว) |
| `./install.sh --yes` | ไม่ถามยืนยัน (ติดตั้งอัตโนมัติ) |
| `./run_web.sh --prod` | build หน้าเว็บครั้งเดียวแล้วเสิร์ฟ เร็วและกินแรมน้อยกว่าโหมด dev **แนะนำบน Jetson และใช้งานประจำ** |

### สิ่งที่ต้องมีก่อน
- **macOS:** ไม่ต้องมีอะไร (ถ้ายังไม่มี Homebrew สคริปต์จะถามว่าจะลงให้ไหม)
- **Ubuntu / Debian / Jetson:** สิทธิ์ `sudo` และอินเทอร์เน็ต
- **ไฟล์โมเดล:** `best.pt` เก็บด้วย Git LFS ถ้าสคริปต์เตือนว่าเป็น LFS pointer ให้รัน `git lfs install && git lfs pull`

---

## 2. NVIDIA Jetson Orin Nano

```bash
sudo apt update && sudo apt install -y git git-lfs
git clone https://github.com/moszer/PCB_DETECT_RMUTT_GUI.git
cd PCB_DETECT_RMUTT_GUI/main_program_for_webapp
./install.sh
./run_web.sh --prod
```

- **JetPack 7 (L4T R39):** ลง `torch 2.13.0+cu130` ตาม `backend/requirements-jetson-cu130.txt` ซึ่งทดสอบแล้วบน Orin Nano Super (best.pt ~167 ms/ภาพ)
- **JetPack 6 (L4T R36):** ลงจาก index ของ NVIDIA Jetson AI Lab (`https://pypi.jetson-ai-lab.io/jp6/cu126`) **ยังไม่ได้ทดสอบบนเครื่องจริง**
- **รุ่นอื่น / ลงไม่ผ่าน:** หา wheel ของ JetPack ตัวเองที่ [PyTorch for Jetson](https://forums.developer.nvidia.com/t/pytorch-for-jetson/72048) แล้วระบุ index เอง:
  ```bash
  PCB_TORCH_INDEX=<index-url> ./install.sh
  ```
- ตั้งโหมดพลังงานสูงสุดให้ AI เร็วขึ้น: `sudo nvpmodel -m 0 && sudo jetson_clocks`
- เช็คว่าใช้ GPU: หน้าเว็บมุมขวาบนต้องขึ้น **CUDA** (ไม่ใช่ CPU)

---

## 3. Docker

ใช้ทดสอบระบบโดยไม่ต้องลงอะไรในเครื่องนอกจาก Docker หรือใช้รันบนเซิร์ฟเวอร์

```bash
cd main_program_for_webapp
./docker-test.sh            # build + รัน test 91 ตัว + เปิดระบบ + ตรวจการทำงาน แล้วปิด
docker compose up --build   # เปิดใช้งาน → http://localhost:3001
```

`docker-test.sh` ตรวจ: backend ทำงาน, หน้าเว็บโหลดได้, หน้าเว็บคุยกับ backend ได้, YOLO ตรวจภาพจริงได้ และภาพสดจากกล้องทดสอบ ใช้พอร์ต 3101/8101 จึงไม่ชนกับสถานีที่รันอยู่ ใส่ `--keep` ถ้าอยากให้เปิดค้างไว้ดู

- ข้อมูล (ฐานข้อมูล ภาพสแกน การตั้งค่า ชุดข้อมูล) เก็บใน Docker volume `aoi-data` ไม่หายเมื่อปิด/อัปเดต
- ถ้ามี `backend/.env` (AI key, รหัสผ่าน) จะถูกใช้อัตโนมัติ
- **ใน Docker ไม่มีกล้องและสเตจจริง** ระบบใช้กล้องทดสอบ และสั่งสเตจในโหมด "จำลอง" ได้

### ต่อกล้องและสเตจจริง (Linux / Jetson เท่านั้น)
Docker Desktop บน macOS ส่งอุปกรณ์ USB เข้า container ไม่ได้ บน Mac ให้ใช้การติดตั้งแบบปกติ

```bash
ls /dev/video* /dev/ttyUSB* /dev/ttyACM*     # ดูชื่ออุปกรณ์
PCB_CAMERA_DEVICE=/dev/video0 PCB_SERIAL_DEVICE=/dev/ttyUSB0 \
  docker compose -f docker-compose.yml -f docker-compose.hardware.yml up --build
```

### Jetson + GPU ใน Docker
```bash
docker compose -f docker-compose.yml -f docker-compose.hardware.yml -f docker-compose.jetson.yml up --build
```
ใช้ NVIDIA container runtime ที่มากับ JetPack และ PyTorch CUDA 13 (JetPack 7) **ยังไม่ได้ทดสอบบน Jetson จริง** ถ้า GPU ไม่ทำงานให้ใช้การติดตั้งแบบปกติ (หัวข้อ 2) ซึ่งทดสอบแล้ว

---

## 4. ตั้งค่าหลังติดตั้ง (`backend/.env`)

```bash
PCB_OPERATOR_PASSCODE=รหัสของคุณ     # รหัสขอสิทธิ์ควบคุม (ค่าเริ่มต้น rmutt-aoi — ควรเปลี่ยน)
AI_PROVIDER=gemini
GEMINI_API_KEY=...                   # https://aistudio.google.com/apikey (ผู้ช่วย AI / ถามเรื่องบอร์ด)
```
แก้แล้วรีสตาร์ท `./run_web.sh` ไฟล์นี้ไม่ขึ้น git ห้ามส่ง key ให้ใคร

---

## 5. แก้ปัญหาที่พบบ่อย

| อาการ | วิธีแก้ |
|---|---|
| `Missing backend virtual environment` | ยังไม่ได้รัน `./install.sh` |
| `Address already in use` | มีสถานีรันอยู่แล้ว ปิดตัวเก่า หรือเปลี่ยนพอร์ต `PCB_FRONTEND_PORT=3002 PCB_BACKEND_PORT=8002 ./run_web.sh` |
| Linux: เปิดกล้อง/สเตจไม่ได้ (Permission denied) | logout แล้ว login ใหม่หลังติดตั้ง (สิทธิ์กลุ่ม `video`, `dialout`) |
| Jetson: หน้าเว็บขึ้น CPU แทน CUDA | `backend/venv/bin/python -c "import torch; print(torch.cuda.is_available())"` ถ้าได้ False ให้ลง PyTorch ของ JetPack ตัวเองด้วย `PCB_TORCH_INDEX` |
| `best.pt` เป็น LFS pointer | `git lfs install && git lfs pull` |
| ผู้ช่วย AI ตอบ "ไม่ว่าง" บ่อย | Gemini รุ่นฟรีคิวเต็ม ระบบสลับรุ่นเอง หรือเปิด billing ใน Google AI Studio |
