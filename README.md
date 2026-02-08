# Defect Detection YOLO

A YOLO-based object detection project for PCB component and defect detection.

## 📁 Project Structure

```
defect detection yolo/
├── train.py          # Training script
├── test.py           # Inference/testing script
├── prepare.py        # Data preparation script
├── data.yaml         # Dataset configuration
├── main_label/       # Dataset folder
│   └── images/
│       ├── train/
│       └── val/
└── trained/          # Output folder for trained models
    ├── best.pt
    ├── last.pt
    ├── best.onnx
    └── results.csv
```

---

## 🖥️ Local Setup

```bash
# Install dependencies
pip install ultralytics

# Train model
python3 train.py

# Test on image
python3 test.py

# Real-time detection (Webcam)
python3 camera.py

# GUI Application (Select and Preview)
python3 gui_test.py
```

---

## ☁️ Google Colab Setup

### 1. Mount Google Drive
```python
from google.colab import drive
drive.mount('/content/drive')
```

### 2. Change to project directory
```python
import os
os.chdir('/content/drive/MyDrive/defect detection yolo')
```

### 3. Install dependencies
```python
!pip install ultralytics
```

### 4. Update data.yaml path (if needed)
```python
# Edit data.yaml to use absolute path
data_yaml = """
path: /content/drive/MyDrive/defect detection yolo/main_label

train: images/train
val: images/val

nc: 23
names:
  - ant
  - button
  - capacitor
  - capacitor_0
  - chip
  - connector
  - connector_0
  - connector_1
  - connector_2
  - diode
  - hole
  - inductor
  - input
  - led
  - resistor
  - resistor_8
  - sdcard
  - sot21
  - sot23
  - sot31
  - sot32
  - usb
  - xtal
"""

with open('data.yaml', 'w') as f:
    f.write(data_yaml)
```

### 5. Train with GPU (Best Settings)
```python
from ultralytics import YOLO

model = YOLO("yolo26x.pt")

results = model.train(
    data="data.yaml",
    epochs=300,           # More epochs for better learning
    imgsz=640,            # Image size
    batch=16,             # Batch size (adjust based on GPU memory)
    device=0,             # Use GPU
    
    # Optimizer settings
    optimizer="AdamW",    # Best optimizer
    lr0=0.001,            # Initial learning rate
    lrf=0.01,             # Final learning rate factor
    momentum=0.937,       # SGD momentum
    weight_decay=0.0005,  # Weight decay
    warmup_epochs=3,      # Warmup epochs
    
    # Data augmentation
    hsv_h=0.015,          # Hue augmentation
    hsv_s=0.7,            # Saturation augmentation
    hsv_v=0.4,            # Value augmentation
    degrees=10,           # Rotation degrees
    translate=0.1,        # Translation
    scale=0.5,            # Scale augmentation
    shear=2.0,            # Shear augmentation
    flipud=0.5,           # Flip up-down probability
    fliplr=0.5,           # Flip left-right probability
    mosaic=1.0,           # Mosaic augmentation
    mixup=0.1,            # Mixup augmentation
    
    # Training options
    cos_lr=True,          # Cosine learning rate scheduler
    patience=50,          # Early stopping patience
    save=True,            # Save checkpoints
    save_period=10,       # Save every N epochs
    val=True,             # Validate during training
    plots=True,           # Generate plots
    
    # Performance
    workers=8,            # Data loader workers
    cache=True,           # Cache images in RAM for faster training
    amp=True,             # Mixed precision training
)

### 6. Test inference
```python
model = YOLO("trained/best.pt")
results = model.predict(source="test_image.jpg", conf=0.25, save=True)
```

---

## 📊 Classes (23 total)

| ID | Class | ID | Class |
|----|-------|----|----|
| 0 | ant | 12 | input |
| 1 | button | 13 | led |
| 2 | capacitor | 14 | resistor |
| 3 | capacitor_0 | 15 | resistor_8 |
| 4 | chip | 16 | sdcard |
| 5 | connector | 17 | sot21 |
| 6 | connector_0 | 18 | sot23 |
| 7 | connector_1 | 19 | sot31 |
| 8 | connector_2 | 20 | sot32 |
| 9 | diode | 21 | usb |
| 10 | hole | 22 | xtal |
| 11 | inductor | | |

---

## 🚀 Model Variants

| Model | Size | Speed | Accuracy |
|-------|------|-------|----------|
| yolo26n.pt | Nano | Fastest | Lowest |
| yolo26s.pt | Small | Fast | Low |
| yolo26m.pt | Medium | Medium | Medium |
| yolo26l.pt | Large | Slow | High |
| yolo26x.pt | XLarge | Slowest | Highest |
