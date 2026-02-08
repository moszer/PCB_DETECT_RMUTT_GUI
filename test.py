from ultralytics import YOLO
import cv2
import os

# Load your trained model
model = YOLO("best.pt")

# Path to test image (change this to your image path)
image_path = "image_dataset/Raspberry-Pi-Pico-with-RP2040-768x630.webp"

# Run inference
results = model.predict(
    source=image_path,
    conf=0.25,        # Confidence threshold
    save=True,        # Save annotated image
    show=True,        # Display result (requires GUI)
    device="cpu"
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
