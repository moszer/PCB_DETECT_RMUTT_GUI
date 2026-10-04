# PCB Defect Detection with YOLO — สรุปโค้ดทั้งหมด

## โครงสร้างโปรเจค

```
defect detection yolo/
├── prepare.py              # แบ่ง dataset เป็น train/val
├── train.py                # ฝึกโมเดล YOLO
├── test.py                 # ทดสอบ inference กับภาพเดี่ยว
├── camera.py               # ตรวจจับ real-time ผ่าน webcam
├── data.yaml               # config dataset (23 classes)
├── best.pt                 # โมเดลที่ฝึกแล้ว
├── Refs.json               # จุดอ้างอิงสำหรับตรวจสอบ (reference profile)
├── main_label/             # dataset ภาพ + label
├── trained/                # ผลลัพธ์การฝึก (weights, graphs, metrics)
├── image_dataset/          # ภาพตัวอย่าง
└── main_program/           # โปรแกรมหลัก
    ├── gui_test.py         # entry point — รัน app
    └── app/
        ├── window.py       # main window class (รวม mixins)
        ├── utils.py        # helper หาไฟล์ asset
        ├── inspection_logic.py  # อัลกอริทึมตัดสิน PASS/FAIL
        └── mixins/
            ├── inspection_mixin.py     # inference YOLO
            ├── model_reference_mixin.py # โหลดโมเดล + จัดการ reference
            └── history_mixin.py        # บันทึกประวัติ + export CSV
```

---

## 1. เตรียมข้อมูล — `prepare.py`

แบ่งภาพและ label จาก `main_label/` เป็น train 80% / val 20%

```
main_label/images/ → images/train/ + images/val/
main_label/labels/ → labels/train/ + labels/val/
```

**หลักการ**: สุ่มภาพ → แบ่ง 80/20 → ย้ายไฟล์ภาพและ `.txt` label ตาม

---

## 2. ฝึกโมเดล — `train.py`

```python
model = YOLO("yolo26x.pt")            # โหลด pretrained YOLO26x
results = model.train(
    data="data.yaml",                  # 23 classes ชิ้นส่วน PCB
    epochs=100, imgsz=640, batch=16,
    device="cpu"
)
```

**หลังฝึกเสร็จ**: คัดลอก best.pt, results.csv, confusion_matrix.png ฯลฯ ไปเก็บใน `trained/` + export เป็น ONNX

---

## 3. ทดสอบภาพเดี่ยว — `test.py`

โหลด `best.pt` → predict ภาพ → แสดง bounding box + พิมพ์ class, confidence, พิกัด

---

## 4. ตรวจจับ Real-time — `camera.py`

เปิด webcam → อ่านเฟรม → YOLO predict → วาด bounding box → แสดงผล loop จนกด `q`

---

## 5. Dataset Config — `data.yaml`

23 classes ชิ้นส่วน PCB:

```
ant, button, capacitor, capacitor_0, chip, connector, connector_0,
connector_1, connector_2, diode, hole, inductor, input, led,
resistor, resistor_8, sdcard, sot21, sot23, sot31, sot32, usb, xtal
```

---

---

# อธิบายโค้ด main_program/ อย่างละเอียด

---

## A. gui_test.py — จุดเริ่มต้นของโปรแกรม

```python
import sys
from PyQt6.QtWidgets import QApplication
from app.window import DefectDetectionGUI

def main():
    app = QApplication(sys.argv)     # สร้าง Qt Application
    window = DefectDetectionGUI()    # สร้างหน้าต่างหลัก
    window.show()                    # แสดงหน้าต่าง
    return app.exec()                # เริ่ม event loop รอ user input

if __name__ == "__main__":
    raise SystemExit(main())         # ส่ง exit code กลับให้ OS
```

**หลักการ**: สร้าง `QApplication` → สร้าง `DefectDetectionGUI` (หน้าต่างหลัก) → แสดงผล → เข้า event loop ของ Qt รอรับ event จากผู้ใช้จนกว่าจะปิดโปรแกรม

---

## B. app/window.py — หน้าต่างหลัก (รวม Mixin ทั้งหมด)

```python
class DefectDetectionGUI(UIMixin, ModelReferenceMixin, InspectionMixin, HistoryMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Factory Defect Inspection Station")
        self.setMinimumSize(1260, 760)
```

**สถาปัตยกรรม Mixin**: แบ่งโค้ดออกเป็น 4 คลาสย่อย แล้วรวมเข้ากับ `QMainWindow` ด้วย multiple inheritance ทำให้แต่ละไฟล์ดูแลเรื่องเดียว

**ค่าเริ่มต้นที่กำหนดใน `__init__`**:

| ตัวแปร | ค่าเริ่มต้น | หน้าที่ |
|---|---|---|
| `script_root` | `app/` folder | หา path ของไฟล์ต่างๆ |
| `project_root` | root ของโปรเจค | base path สำหรับ asset |
| `default_model_path` | `best.pt` | โมเดล YOLO ที่ใช้ |
| `default_refs_path` | `Refs.json` | จุดอ้างอิง default |
| `_current_theme` | `"light"` | theme ปัจจุบัน |
| `model` | `None` | object ของ YOLO model |
| `model_names` | `{}` | dict ชื่อ class จากโมเดล |
| `reference_points` | `[]` | รายการจุดอ้างอิง |
| `undo_stack` / `redo_stack` | `[]` | สำหรับ undo/redo reference |
| `zoom_factor` | `1.0` | ระดับ zoom (0.2–8.0) |
| `total_count` / `pass_count` / `fail_count` | `0` | นับผลการตรวจ |

**ลำดับการ init**: `init_ui()` → `apply_styles()` → `load_default_assets()`

---

## C. app/utils.py — ฟังก์ชันค้นหาไฟล์ Asset

```python
def resolve_asset_path(script_root, project_root, filename, create_in_project=False):
    candidates = [
        os.path.join(script_root, filename),   # หาใน app/ ก่อน
        os.path.join(project_root, filename),   # หาใน root โปรเจค
    ]
    for path in candidates:
        if os.path.exists(path):
            return path                         # คืน path แรกที่เจอ
    if create_in_project:
        return os.path.join(project_root, filename)  # ถ้าไม่เจอ ให้สร้างที่ root
    return candidates[0]
```

**หลักการ**: ค้นหาไฟล์ (เช่น `best.pt`, `Refs.json`) โดยลองหาใน `app/` ก่อน ถ้าไม่เจอก็หาใน root โปรเจค — ทำให้วางไฟล์ได้หลายที่โดยไม่ต้อง hardcode path

---

## D. app/inspection_logic.py — อัลกอริทึมตัดสิน PASS/FAIL

### ฟังก์ชัน `evaluate_inspection()` — หัวใจของระบบ

```python
def evaluate_inspection(reference_points, detections, match_dist, fail_on_extra):
```

**Input**:
- `reference_points` — จุดอ้างอิงที่คาดว่าต้องมี เช่น `[{"x":460, "y":379, "label":"button"}, ...]`
- `detections` — ผลที่ YOLO ตรวจเจอจริง เช่น `[{"x":462, "y":381, "label":"button", "conf":0.95}, ...]`
- `match_dist` — ระยะพิกเซลสูงสุดที่ถือว่าตรงกัน (default 50px)
- `fail_on_extra` — ถ้า `True` จะ FAIL เมื่อเจอชิ้นส่วนเกิน

**อัลกอริทึมการจับคู่ (Greedy Nearest-Neighbor Matching)**:

```python
for ref in reference_points:
    # 1. หา detection ที่ใกล้ ref ที่สุด (Euclidean distance)
    best_idx = None
    best_dist = float("inf")
    for idx in unmatched_det_indexes:
        det = detections[idx]
        dist = math.hypot(ref["x"] - det["x"], ref["y"] - det["y"])
        if dist < best_dist:
            best_dist = dist
            best_idx = idx

    # 2. ตัดสินผล
    if best_idx is not None and best_dist <= match_dist:
        det = detections[best_idx]
        unmatched_det_indexes.remove(best_idx)  # ใช้แล้วเอาออก
        if det["label"] == ref["label"]:
            ok_count += 1                       # class ตรง → OK
        else:
            wrong.append(...)                   # class ไม่ตรง → WRONG
    else:
        missing.append(ref)                     # หาไม่เจอ → MISSING

# 3. detection ที่เหลือคือ EXTRA
extra = [detections[idx] for idx in sorted(unmatched_det_indexes)]
```

**ตัดสินผล**:
- ไม่มี missing, wrong, extra → **PASS**
- มีอย่างใดอย่างหนึ่ง → **FAIL** พร้อมระบุเหตุผล เช่น `"Missing 2, Wrong class 1"`

**Output**: dict ที่มี `verdict`, `reason`, `ok`, `missing`, `wrong`, `extra`, `reference_eval`, `total_refs`

### ฟังก์ชัน `draw_reference_overlay()` — วาดผลลงบนภาพ

```python
def draw_reference_overlay(frame, inspection_result, show_labels):
    for entry in inspection_result["reference_eval"]:
        ref = entry["ref"]
        rx, ry = int(ref["x"]), int(ref["y"])
        status = entry["status"]

        if status == "OK":
            color = (50, 205, 50)      # เขียว — ตรง
        elif status == "WRONG":
            color = (0, 165, 255)      # ส้ม — class ผิด
        else:
            color = (0, 0, 255)        # แดง — หายไป

        cv2.circle(frame, (rx, ry), 14, color, 2)   # วงกลมใหญ่
        cv2.circle(frame, (rx, ry), 3, color, -1)    # จุดตรงกลาง
        if show_labels:
            cv2.putText(frame, label, ...)            # เขียนข้อความ
```

**หลักการ**: วาดวงกลม 2 ชั้นที่ตำแหน่ง reference แต่ละจุด สีบ่งบอกสถานะ (เขียว=OK, ส้ม=WRONG, แดง=MISSING)

---

## E. app/mixins/inspection_mixin.py — Inference (การรัน YOLO)

### ขั้นตอนหลักของ `run_inference()`

```python
def run_inference(self, image_path, record_history=False):
    # 1. อ่าน confidence threshold
    conf_value = self.conf_slider.value() / 100.0

    # 2. รัน YOLO predict
    results = self.model.predict(source=image_path, conf=conf_value, save=False, device="cpu")

    # 3. ดึงข้อมูล detection จาก result
    for result in results:
        annotated_frame = result.plot(labels=...)     # ภาพที่ YOLO วาด bounding box แล้ว
        for box in result.boxes:
            cls_idx = int(box.cls[0])                 # index ของ class
            cls_name = self.model_names.get(cls_idx)  # ชื่อ class เช่น "capacitor"
            x1, y1, x2, y2 = box.xyxy[0].tolist()    # พิกัดกรอบ
            cx, cy = int((x1+x2)/2), int((y1+y2)/2)  # จุดกึ่งกลาง
            confidence = float(box.conf[0])           # ค่าความมั่นใจ
            detections.append({"x": cx, "y": cy, "label": cls_name, "conf": confidence, ...})

    # 4. เทียบกับ reference → ตัดสิน PASS/FAIL
    inspection_result = evaluate_inspection(
        reference_points=self.reference_points,
        detections=detections,
        match_dist=float(self.match_dist_spin.value()),
        fail_on_extra=self.check_fail_extra.isChecked(),
    )

    # 5. วาด overlay ลงบนภาพ (วงกลม OK/WRONG/MISSING + EXTRA)
    draw_reference_overlay(annotated_frame, inspection_result, ...)

    # 6. บันทึกประวัติ (ถ้าเป็นการตรวจครั้งใหม่)
    if record_history:
        self.update_production_counters(inspection_result)
        self.append_history(image_path, inspection_result)
```

**หลักการ**: รับ path ภาพ → YOLO predict → ดึง bounding box ทั้งหมด → คำนวณจุดกึ่งกลางแต่ละ box → ส่งเข้า `evaluate_inspection()` เทียบกับ reference → วาด overlay ลงภาพ → บันทึกผล

---

## F. app/mixins/model_reference_mixin.py — โหลดโมเดล + จัดการ Reference

### โหลดโมเดล YOLO

```python
def load_model(self, model_path):
    candidate_model = YOLO(model_path)        # โหลดโมเดลจากไฟล์ .pt
    names = candidate_model.names              # ดึง dict ชื่อ class เช่น {0: "ant", 1: "button", ...}
    self.model = candidate_model
    self.model_names = names
    self.populate_class_combo()                # เอาชื่อ class ใส่ dropdown
    self.refresh_image()                       # ถ้ามีภาพอยู่ ให้ตรวจใหม่
```

### โหลด Asset เริ่มต้น

```python
def load_default_assets(self):
    # ถ้ามี best.pt → โหลดโมเดลอัตโนมัติ
    if os.path.exists(self.default_model_path):
        self.load_model(self.default_model_path)
    # ถ้ามี Refs.json → โหลด reference อัตโนมัติ
    if os.path.exists(self.default_refs_path):
        self.load_reference_file(self.default_refs_path, ...)
```

### ระบบ Undo/Redo

```python
def save_state(self):
    # เก็บ snapshot ปัจจุบันก่อนแก้ไข
    self.undo_stack.append(copy.deepcopy(self.reference_points))
    self.redo_stack.clear()  # ล้าง redo เมื่อมีการแก้ใหม่

def undo(self):
    self.redo_stack.append(copy.deepcopy(self.reference_points))  # เก็บสถานะปัจจุบัน
    self.reference_points = self.undo_stack.pop()                  # ย้อนกลับ

def redo(self):
    self.undo_stack.append(copy.deepcopy(self.reference_points))  # เก็บสถานะปัจจุบัน
    self.reference_points = self.redo_stack.pop()                  # คืนกลับ
```

**หลักการ**: ใช้ `copy.deepcopy()` เก็บ snapshot ของ `reference_points` ลง stack ก่อนทำการแก้ไขทุกครั้ง

### Add EXTRA → REF

```python
def add_extra_to_references(self, save_default=False):
    extras = self.last_inspection_result.get("extra", [])
    dedupe_distance = max(8, int(self.match_dist_spin.value() * 0.2))  # ระยะกัน duplicate

    for det in extras:
        candidate = {"x": int(det["x"]), "y": int(det["y"]), "label": str(det["label"])}
        if self.is_reference_duplicate(candidate, dedupe_distance):
            skipped += 1     # ข้ามถ้าซ้ำ
            continue
        self.reference_points.append(candidate)   # เพิ่มเป็น reference ใหม่
        added += 1
```

**หลักการ**: เอา detection ที่ YOLO เจอแต่ไม่มีใน reference (EXTRA) มาเพิ่มเป็น reference อัตโนมัติ โดยตรวจ duplicate ด้วย Euclidean distance (20% ของ match_dist)

### โหลด/บันทึก Reference File

```python
# บันทึก — เขียน JSON array ลงไฟล์
def save_reference_file(self, file_path):
    with open(file_path, "w") as handle:
        json.dump(self.reference_points, handle, indent=2)

# โหลด — อ่าน JSON แล้ว validate แต่ละจุด
def load_reference_file(self, file_path, push_state=True, ...):
    payload = json.load(handle)
    validated = []
    for item in payload:
        validated.append({"x": int(item["x"]), "y": int(item["y"]), "label": str(item["label"])})
    if push_state:
        self.save_state()           # เก็บ undo ก่อนเปลี่ยน
    self.reference_points = validated
```

**รูปแบบไฟล์ Refs.json**:
```json
[
  {"x": 460, "y": 379, "label": "button"},
  {"x": 177, "y": 378, "label": "button"},
  {"x": 111, "y": 468, "label": "capacitor"}
]
```

---

## I. app/mixins/history_mixin.py — บันทึกประวัติ + Export CSV

### นับสถิติการผลิต

```python
def update_production_counters(self, inspection_result):
    self.total_count += 1
    if inspection_result["verdict"] == "PASS":
        self.pass_count += 1
    else:
        self.fail_count += 1
    # อัปเดต label บน UI
```

### บันทึกประวัติลงตาราง

```python
def append_history(self, image_path, inspection_result):
    row = {
        "time": timestamp,                    # เวลาตรวจ
        "image": os.path.basename(image_path), # ชื่อไฟล์ภาพ
        "verdict": "PASS" / "FAIL",
        "ok": N, "missing": N, "wrong": N, "extra": N,
        "station_id": ..., "operator": ..., "model": ...
    }
    self.history_rows.insert(0, row)          # เก็บใน memory
    self.insert_history_row(row)              # เพิ่มแถวในตาราง

    if self.history_table.rowCount() > 300:   # จำกัด 300 แถว
        self.history_table.removeRow(...)

    if self.check_auto_log.isChecked():       # ถ้าเปิด auto-log
        self.append_to_log_file(row)          # เขียนลง CSV ทันที
```

### Auto-log CSV

```python
def append_to_log_file(self, row):
    write_header = not os.path.exists(self.default_log_path)  # ถ้าไฟล์ยังไม่มี → เขียน header
    with open(self.default_log_path, "a") as handle:          # เปิดแบบ append
        writer = csv.writer(handle)
        if write_header:
            writer.writerow(["time", "station_id", "operator", "image", "verdict", ...])
        writer.writerow([row["time"], row["station_id"], ...])
```

### Export History

```python
def export_history_csv(self):
    # เปิด Save dialog → เขียนทุกแถวใน history_rows ลง CSV ใหม่
    export_path = QFileDialog.getSaveFileName(...)
    with open(export_path, "w") as handle:
        writer = csv.writer(handle)
        writer.writerow([...header...])
        for row in self.history_rows:
            writer.writerow([...])
```

---

## เทคโนโลยีที่ใช้

| เครื่องมือ | หน้าที่ |
|---|---|
| **Python** | ภาษาหลัก |
| **Ultralytics YOLO** | ฝึก + inference โมเดลตรวจจับวัตถุ |
| **OpenCV (cv2)** | ประมวลผลภาพ, วาด overlay, แปลง BGR↔RGB |
| **PyQt6** | GUI desktop application (widgets, layout, event) |
| **YOLO26x** | pretrained base model สำหรับ transfer learning |

## วิธีรันโปรแกรม

```bash
pip install PyQt6 ultralytics opencv-python
cd main_program
python gui_test.py
```
