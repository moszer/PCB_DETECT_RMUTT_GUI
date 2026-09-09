"""Folder browsing: open a whole directory of images and step through them.

Any single image that gets opened (file picker, drag & drop, camera capture)
also indexes its own folder, so Prev/Next works without a second dialog.
"""
import os

import cv2
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from ..utils import list_images_in_folder


class BrowseMixin:
    # ── Opening ──
    def select_folder(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            "Open Image Folder",
            self.folder_path or self.project_root,
        )
        if not directory:
            return
        self.load_image_folder(directory)

    def load_image_folder(self, directory, start_path=None):
        """Index every image in `directory` and open one of them (the first, or
        `start_path` when it belongs to the folder)."""
        images = list_images_in_folder(directory)
        if not images:
            QMessageBox.warning(
                self,
                "Open Folder",
                f"No supported images found in:\n{directory}",
            )
            return False

        self.folder_path = directory
        self.folder_images = images
        index = 0
        if start_path:
            target = os.path.abspath(start_path)
            if target in images:
                index = images.index(target)

        if hasattr(self, "toasts"):
            self.toasts.show(f"{len(images)} images · {os.path.basename(directory)}", "info")
        self.open_folder_index(index)
        return True

    def open_image_path(self, path, track_folder=True):
        """Single entry point for 'show and inspect this image file'."""
        if getattr(self, "_inference_running", False) or getattr(self, "_camera_worker", None) is not None:
            self.stats_label.setText("Finish the current inspection or stop the camera before opening an image.")
            return
        if self.history_panel.isVisible():
            self.toggle_history_panel()
        frame = cv2.imread(path)
        if frame is None:
            QMessageBox.warning(self, "Open image", "This image could not be read. Choose another image.")
            return
        self.current_image_path = path
        self._reset_result_summary(
            "PENDING" if self.model else "VIEW ONLY",
            os.path.basename(path),
            "Analyzing the selected image…" if self.model else "Load a model in Station & model to inspect this image.",
        )
        self._base_frame = frame
        self.zoom_factor = 1.0
        self.update_zoom_display()
        self.display_cv_image(frame)
        if track_folder:
            self.track_image_folder(path)
        self.run_inference(path, record_history=True)

    def track_image_folder(self, image_path):
        """Index the folder a standalone image came from so the Prev/Next
        controls line up with it, without opening any other image."""
        target = os.path.abspath(image_path)
        folder = os.path.dirname(target)
        images = list_images_in_folder(folder)
        self.folder_path = folder if images else ""
        self.folder_images = images
        self.folder_index = images.index(target) if target in images else -1
        self.update_nav_controls()

    # ── Stepping ──
    def open_folder_index(self, index):
        if not self.folder_images:
            return
        if not 0 <= index < len(self.folder_images):
            return

        path = self.folder_images[index]
        if not os.path.exists(path):
            # The folder changed under us — re-index and keep the current image.
            self.folder_images = list_images_in_folder(self.folder_path)
            current = os.path.abspath(self.current_image_path) if self.current_image_path else None
            self.folder_index = (
                self.folder_images.index(current)
                if current in self.folder_images
                else -1
            )
            self.update_nav_controls()
            if hasattr(self, "toasts"):
                self.toasts.show("Image no longer on disk", "error")
            return

        self.folder_index = index
        self.update_nav_controls()
        self.open_image_path(path, track_folder=False)

    def show_next_image(self):
        self._step_image(1)

    def show_prev_image(self):
        self._step_image(-1)

    def _step_image(self, delta):
        total = len(self.folder_images)
        if total == 0:
            if hasattr(self, "toasts"):
                self.toasts.show("Open a folder first", "info")
            return
        if getattr(self, "_inference_running", False):
            return

        target = 0 if self.folder_index < 0 else self.folder_index + delta
        if not 0 <= target < total:
            if hasattr(self, "toasts"):
                self.toasts.show(
                    "Already at the last image" if delta > 0 else "Already at the first image",
                    "info",
                )
            return
        self.open_folder_index(target)

    # ── Controls ──
    def update_nav_controls(self):
        if not hasattr(self, "nav_value_label"):
            return

        total = len(self.folder_images)
        if total == 0:
            self.nav_value_label.setText("—")
            self.nav_value_label.setToolTip("No image folder open")
        elif self.folder_index < 0:
            self.nav_value_label.setText(f"– / {total}")
            self.nav_value_label.setToolTip(f"{total} images in {self.folder_path}")
        else:
            self.nav_value_label.setText(f"{self.folder_index + 1} / {total}")
            self.nav_value_label.setToolTip(
                f"{os.path.basename(self.folder_images[self.folder_index])}\n{self.folder_path}"
            )

        if total == 0:
            self.folder_name_label.setText("No folder open")
            self.folder_name_label.setToolTip("")
        else:
            self.folder_name_label.setText(
                f"{os.path.basename(self.folder_path.rstrip(os.sep)) or self.folder_path}"
                f"  ·  {total} images"
            )
            self.folder_name_label.setToolTip(self.folder_path)

        busy = getattr(self, "_inference_running", False)
        camera_live = getattr(self, "_camera_worker", None) is not None
        blocked = busy or camera_live
        self.btn_prev_image.setEnabled(not blocked and self.folder_index > 0)
        self.btn_next_image.setEnabled(not blocked and 0 <= self.folder_index < total - 1)
        self.btn_select_folder.setEnabled(not blocked)
