import os
import sys

# Run from anywhere: all paths are resolved from this file, and the repo root is importable.
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, REPO_ROOT)

from ultralytics import YOLO
from main_program.app.inference_runtime import select_device, validate_model_file
import cv2

# Load your trained model
device = select_device()
print(f"Inference device: {device.label} {device.detail}")
MODEL_PATH = os.path.join(REPO_ROOT, "best.pt")  # same model the desktop app uses
validate_model_file(MODEL_PATH)
model = YOLO(MODEL_PATH)

# Path to test image (change this to your image path)
image_path = os.path.join(REPO_ROOT, "training", "image_dataset", "Raspberry-Pi-Pico-with-RP2040-768x630.webp")

# Run inference
results = model.predict(
    source=image_path,
    conf=0.25,        # Confidence threshold
    save=True,        # Save annotated image
    show=True,        # Display result (requires GUI)
    device=device.device
)

# Print detection results
for result in results:
    boxes = result.boxes
    print(f"\nDetected {len(boxes)} objects:")
    for box in boxes:
        cls_id = int(box.cls[0])
        cls_name = result.names[cls_id]
        conf = float(box.conf[0])
        xyxy = box.xyxy[0].tolist()
        print(f"  - {cls_name}: {conf:.2%} at {xyxy}")

print(f"\nResults saved to: {results[0].save_dir}")
