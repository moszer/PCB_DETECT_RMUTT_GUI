from ultralytics import YOLO
import shutil
import os
import glob

# Load a pretrained YOLO26 nano model
model = YOLO("yolo26x.pt")

# Train the model
results = model.train(
    data="data.yaml",
    epochs=100,
    imgsz=640,
    batch=16,
    device="cpu"
)

# Copy trained weights and data to 'trained' folder
trained_dir = "trained"
os.makedirs(trained_dir, exist_ok=True)

# Get the save directory from training results
save_dir = results.save_dir
print(f"\n📁 Training results saved at: {save_dir}")

# Copy model weights
best_pt = os.path.join(save_dir, "weights", "best.pt")
last_pt = os.path.join(save_dir, "weights", "last.pt")

if os.path.exists(best_pt):
    shutil.copy(best_pt, os.path.join(trained_dir, "best.pt"))
    print(f"✅ Saved best.pt")

if os.path.exists(last_pt):
    shutil.copy(last_pt, os.path.join(trained_dir, "last.pt"))
    print(f"✅ Saved last.pt")

# Copy training data files (results, graphs, etc.)
training_files = [
    "results.csv",           # Training metrics per epoch
    "results.png",           # Training graphs
    "confusion_matrix.png",  # Confusion matrix
    "confusion_matrix_normalized.png",
    "F1_curve.png",          # F1 score curve
    "P_curve.png",           # Precision curve
    "R_curve.png",           # Recall curve
    "PR_curve.png",          # Precision-Recall curve
    "labels.jpg",            # Label distribution
    "labels_correlogram.jpg",
    "args.yaml",             # Training arguments
]

for filename in training_files:
    src = os.path.join(save_dir, filename)
    if os.path.exists(src):
        shutil.copy(src, os.path.join(trained_dir, filename))
        print(f"✅ Saved {filename}")

# Copy validation batch images
for val_img in glob.glob(os.path.join(save_dir, "val_batch*.jpg")):
    shutil.copy(val_img, os.path.join(trained_dir, os.path.basename(val_img)))
    print(f"✅ Saved {os.path.basename(val_img)}")

# Export to ONNX format
model.export(format="onnx")

# Copy ONNX file to trained folder
onnx_file = os.path.join(save_dir, "weights", "best.onnx")
if os.path.exists(onnx_file):
    shutil.copy(onnx_file, os.path.join(trained_dir, "best.onnx"))
    print(f"✅ Saved best.onnx")

print(f"\n🎉 All trained models and data saved to '{trained_dir}' folder!")

