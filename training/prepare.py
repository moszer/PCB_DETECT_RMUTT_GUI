import os
import sys

# Run from anywhere: all paths are resolved from this file, and the repo root is importable.
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, REPO_ROOT)

import random
import shutil

ROOT = os.path.join(HERE, "main_label")

images_dir = os.path.join(ROOT, "images")
labels_dir = os.path.join(ROOT, "labels")

train_img = os.path.join(images_dir, "train")
val_img = os.path.join(images_dir, "val")

train_lbl = os.path.join(labels_dir, "train")
val_lbl = os.path.join(labels_dir, "val")

os.makedirs(train_img, exist_ok=True)
os.makedirs(val_img, exist_ok=True)
os.makedirs(train_lbl, exist_ok=True)
os.makedirs(val_lbl, exist_ok=True)

images = [f for f in os.listdir(images_dir) if f.endswith((".jpg",".png",".jpeg"))]

random.shuffle(images)

split = int(len(images) * 0.8)

train = images[:split]
val = images[split:]

for img in train:
    shutil.move(f"{images_dir}/{img}", f"{train_img}/{img}")
    lbl = img.replace(".jpg",".txt").replace(".png",".txt")
    shutil.move(f"{labels_dir}/{lbl}", f"{train_lbl}/{lbl}")

for img in val:
    shutil.move(f"{images_dir}/{img}", f"{val_img}/{img}")
    lbl = img.replace(".jpg",".txt").replace(".png",".txt")
    shutil.move(f"{labels_dir}/{lbl}", f"{val_lbl}/{lbl}")

print("Dataset split complete!")
