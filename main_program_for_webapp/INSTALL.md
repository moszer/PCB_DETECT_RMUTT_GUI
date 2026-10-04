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

### อัปเดตเป็นเวอร์ชันล่าสุดจาก GitHub (คำสั่งเดียว)

```bash
./update.sh
```
ทำให้ครบ: เช็คว่าไม่มีการสแกนค้างและไม่มีไฟล์ที่แก้ไว้ในเครื่อง → `git pull` (ไม่โหลดไฟล์ LFS) → รัน `install.sh` เฉพาะเมื่อไลบรารีเปลี่ยน → หยุดสถานีตัวเก่าแล้วเปิดใหม่ด้วยตัวเลือกเดิม (เช่น `--prod`) ในหน้าต่างนี้ ข้อมูล `backend/data`, `backend/.env` และโมเดลไม่ถูกแตะ

| คำสั่ง | ใช้เมื่อ |
|---|---|
| `./update.sh --background` | เปิดสถานีใหม่เบื้องหลัง (เช่นสั่งผ่าน SSH) log อยู่ที่ `.cache/run_web.log` |
| `./update.sh --no-restart` | ดึงโค้ดและลงไลบรารีอย่างเดียว ไม่รีสตาร์ท |
| `./update.sh --force` | อัปเดตแม้มีการสแกนอยู่ (การสแกนจะหยุด) |

ตั้งชื่อย่อให้พิมพ์ได้จากทุกที่ (ครั้งเดียว):
```bash
echo "alias aoi-update='$(pwd)/update.sh'" >> ~/.bashrc && source ~/.bashrc
```
จากนั้นพิมพ์ `aoi-update` ได้เลย (macOS ที่ใช้ zsh เปลี่ยน `~/.bashrc` เป็น `~/.zshrc`)

### ตัวเลือก

| คำสั่ง | ใช้เมื่อ |
|---|---|
| `./install.sh --cpu` | Linux PC: ลง PyTorch แบบ CPU อย่างเดียว (ไฟล์เล็กกว่ามาก) |
| `./install.sh --test` | รันชุดทดสอบ backend ท้ายสุด |
| `./install.sh --no-system` | ข้ามการลงโปรแกรมระบบ (ไม่มีสิทธิ์ sudo หรือลงเองแล้ว) |
| `./install.sh --yes` | ไม่ถามยืนยัน (ติดตั้งอัตโนมัติ) |
| `./run_web.sh --prod` | build หน้าเว็บครั้งเดียวแล้วเสิร์ฟ เร็วและกินแรมน้อยกว่าโหมด dev **แนะนำบน Jetson และใช้งานประจำ** |
| `./run_web.sh --update` | อัปเกรดไลบรารี Python/JS ก่อนเริ่ม (ไม่แตะ PyTorch) |
| `./run_web.sh --no-check` | ข้ามการเช็คไลบรารีตอนเริ่ม |

### สิ่งที่ `./run_web.sh` แสดงตอนเริ่ม
ตราและชื่อมหาวิทยาลัย → เช็คสภาพแวดล้อม (Python/Node, โมเดล, `.env`, ไลบรารีตรงกับ requirements, พอร์ตว่าง) → สตาร์ท backend/frontend → **สรุปว่ากำลังรันอะไรอยู่** (บริการ+pid, โมเดล AI และฮาร์ดแวร์ที่ใช้, กล้อง, สเตจ, ผู้ช่วย AI, OCR, จำนวนข้อมูล, ลิงก์เปิดใช้งาน) และท้ายสุดแจ้งไลบรารีที่มีเวอร์ชันใหม่ (ตรวจวันละครั้ง ไม่อัปเดตให้เองเพราะเวอร์ชันใหม่อาจเปลี่ยนพฤติกรรม) สีและตราแสดงเฉพาะในเทอร์มินัล (`NO_COLOR=1` ปิดสี)

### สิ่งที่ต้องมีก่อน
- **macOS:** ไม่ต้องมีอะไร (ถ้ายังไม่มี Homebrew สคริปต์จะถามว่าจะลงให้ไหม)
- **Ubuntu / Debian / Jetson:** สิทธิ์ `sudo` และอินเทอร์เน็ต
- **ไฟล์โมเดล:** ถ้าในโฟลเดอร์ยังไม่มี `best.pt` (หรือเป็นแค่ LFS pointer) `./install.sh` จะดาวน์โหลดจาก Hugging Face ให้เอง ดูหัวข้อ "โมเดลจาก Hugging Face" ด้านล่าง

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
- โหมดพลังงาน: หมายเลขโหมดต่างกันตามรุ่นบอร์ด ดูรายการด้วย `grep "POWER_MODEL ID" /etc/nvpmodel.conf` และโหมดปัจจุบันด้วย `sudo nvpmodel -q` (Orin Nano Super: `0`=15W, `1`=25W, `2`=MAXN_SUPER) โหมดสูงสุดต้องใช้อะแดปเตอร์ไฟที่จ่ายไฟพอ ถ้าขึ้นเตือน *over-current / System throttled* ให้ดูหัวข้อแก้ปัญหาด้านล่าง
- เช็คว่าใช้ GPU: หน้าเว็บมุมขวาบนต้องขึ้น **CUDA** (ไม่ใช่ CPU)
- **หน้า "ประสิทธิภาพเครื่อง"** แสดง CPU แต่ละคอร์ GPU RAM อุณหภูมิ พลังงาน (W) พัดลม และตัวนับ over-current แบบสด และตั้งค่าได้: โหมดพลังงาน (nvpmodel), ล็อกความถี่สูงสุด (jetson_clocks), พัดลมอัตโนมัติ (เงียบ/เย็น) หรือกำหนดเอง 20–100% การตั้งค่าต้องเปิดสิทธิ์ครั้งเดียว (`install.sh` ทำให้แล้ว หรือรันเอง):
  ```bash
  sudo ./scripts/jetson/install-power-control.sh          # ยกเลิก: ... --remove
  ```
  สคริปต์ติดตั้งตัวช่วย `/usr/local/sbin/aoi-jetson-power` ที่รับเฉพาะคำสั่งเหล่านี้ และกฎ sudoers ให้ผู้ใช้ของสถานีรันตัวช่วยนี้ได้โดยไม่ถามรหัส ถ้ากำหนดความเร็วพัดลมเองแล้วอุณหภูมิถึง 85°C ระบบสลับกลับเป็นอัตโนมัติให้ Jetson ไม่รองรับการโอเวอร์คล็อกเกินสเปก แรงสุดที่ทำได้คือ MAXN_SUPER + ล็อกความถี่สูงสุด

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

## 4. โมเดลจาก Hugging Face

โมเดลและผลการเทรนทั้งหมดอยู่ที่ [Moszer777/pcb-aoi-yolo-rmutt](https://huggingface.co/Moszer777/pcb-aoi-yolo-rmutt) (repo public ไม่ต้องมีบัญชีก็โหลดได้)

| ทำอะไร | วิธี |
|---|---|
| ติดตั้งแล้วได้โมเดลเลย | `./install.sh` โหลด `best.pt` ให้อัตโนมัติถ้ายังไม่มี (ข้ามด้วย `PCB_SKIP_MODEL_DOWNLOAD=1`) |
| เลือกโหลดรุ่นอื่นจากหน้าเว็บ | ตั้งค่าสถานี → โมเดล YOLO → **ดาวน์โหลดจาก Hugging Face** → ดูรายการโมเดล → ดาวน์โหลด → ใช้ (ต้องมีสิทธิ์ควบคุม) |
| โหลดด้วยคำสั่ง | `cd backend && venv/bin/python -m app.core.hub --list` แล้ว `... --file m_new_final_l/weights/best.pt --out ../best.pt` |

ไฟล์ที่ดาวน์โหลดผ่านหน้าเว็บเก็บที่ `backend/data/models/hub/` ระบบตรวจ SHA-256 ทุกครั้ง และต่อจากที่ค้างได้ถ้าเน็ตหลุด

ตั้งค่าใน `backend/.env`: `PCB_MODEL_REPO` (repo อื่น), `PCB_MODEL_FILE` (ไฟล์ที่ install โหลด ค่าเริ่มต้น `best.pt`), `HF_TOKEN` (เฉพาะ repo แบบ private ใช้สิทธิ์อ่าน) หน้าเว็บโหลดได้เฉพาะ repo ที่ตั้งไว้ใน `PCB_MODEL_REPO` เท่านั้น เพราะไฟล์ `.pt` รันโค้ดได้ตอนโหลด จึงไม่ควรโหลดจาก repo ที่ไม่รู้ที่มา

---

## 5. ตั้งค่าหลังติดตั้ง (`backend/.env`)

```bash
PCB_OPERATOR_PASSCODE=รหัสของคุณ     # รหัสขอสิทธิ์ควบคุม (ค่าเริ่มต้น rmutt-aoi — ควรเปลี่ยน)
AI_PROVIDER=gemini
GEMINI_API_KEY=...                   # https://aistudio.google.com/apikey (ผู้ช่วย AI / ถามเรื่องบอร์ด)
```
แก้แล้วรีสตาร์ท `./run_web.sh` ไฟล์นี้ไม่ขึ้น git ห้ามส่ง key ให้ใคร

**ใส่ AI key จากหน้าเว็บก็ได้:** ตั้งค่าสถานี → **ผู้ช่วย AI** → เลือก Gemini หรือ OpenRouter → วาง key → "ทดสอบ key" → "บันทึก" มีผลทันทีไม่ต้องรีสตาร์ท ระบบเขียน key ลง `backend/.env` ให้ (สิทธิ์ไฟล์ 600) และหน้าเว็บจะแสดงแค่ตัวย่อ เช่น `AIza…x9Qk` ไม่ส่ง key กลับมาที่เบราว์เซอร์ ต้องกด "ขอสิทธิ์ควบคุม" ด้วยรหัสผ่านสถานีก่อนจึงแก้ได้

---

## 6. แก้ปัญหาที่พบบ่อย

| อาการ | วิธีแก้ |
|---|---|
| `Missing backend virtual environment` | ยังไม่ได้รัน `./install.sh` |
| `Address already in use` | มีสถานีรันอยู่แล้ว ปิดตัวเก่า หรือเปลี่ยนพอร์ต `PCB_FRONTEND_PORT=3002 PCB_BACKEND_PORT=8002 ./run_web.sh` |
| Linux: เปิดกล้อง/สเตจไม่ได้ (Permission denied) | logout แล้ว login ใหม่หลังติดตั้ง (สิทธิ์กลุ่ม `video`, `dialout`) |
| Jetson: หน้าเว็บขึ้น CPU แทน CUDA | `backend/venv/bin/python -c "import torch; print(torch.cuda.is_available())"` ถ้าได้ False ให้ลง PyTorch ของ JetPack ตัวเองด้วย `PCB_TORCH_INDEX` |
| `best.pt` เป็น LFS pointer | รัน `./install.sh` ใหม่ (โหลดจาก Hugging Face แทน) หรือ `git lfs install && git lfs pull` |
| Jetson ขึ้น *System throttled due to over-current* | ไฟเข้าบอร์ดไม่พอตอนโหลดหนัก: ใช้อะแดปเตอร์ 19V ที่แถมมากับบอร์ด (ไม่ใช่ที่ชาร์จมือถือ) และสายหนา ลดเป็น `sudo nvpmodel -m 1` (25W) ลดความละเอียดกล้องเป็น 1080p ตรวจจำนวนครั้งด้วย `cat /sys/class/hwmon/hwmon*/oc*_event_cnt` |
| Jetson โปรแกรมหยุดเอง / `Killed` | RAM 8GB เต็ม (ไม่มี swap) เพิ่ม swap: `sudo fallocate -l 8G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile` และอย่าเปิด Firefox บนบอร์ด ใช้เบราว์เซอร์จากเครื่องอื่นผ่านลิงก์ LAN |
| Jetson เห็น USB ในเทอร์มินัลแต่ไม่มี `/dev/ttyUSB0` (ชิป CH340) | เคอร์เนล JetPack 7 ไม่มีไดรเวอร์ CH340 ต้องคอมไพล์โมดูล `ch341` เอง หรือใช้บอร์ดชิป FTDI/CP2102 |
| ขึ้น Permission denied ตอนเชื่อมต่อสเตจ | ผู้ใช้ต้องอยู่ในกลุ่ม `dialout` และต้อง logout/login ใหม่ก่อน หรือรัน `sg dialout -c "./run_web.sh --prod"` |
| โหลดโมเดลจาก Hugging Face ไม่ได้ | เช็คอินเทอร์เน็ต, ชื่อ `PCB_MODEL_REPO`/`PCB_MODEL_FILE` ถ้า repo เป็น private ต้องใส่ `HF_TOKEN` ใน `backend/.env` |
| ผู้ช่วย AI ตอบ "ไม่ว่าง" บ่อย | Gemini รุ่นฟรีคิวเต็ม ระบบสลับรุ่นเอง หรือเปิด billing ใน Google AI Studio |
