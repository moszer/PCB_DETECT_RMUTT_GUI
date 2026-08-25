import os
from datetime import datetime

import cv2
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QMessageBox


class CameraWorker(QThread):
    """Continuously pulls frames from a webcam on its own thread and hands
    them to the GUI thread via a signal, so the live preview never blocks
    the event loop the way a blocking cv2.imshow() loop would."""

    frame_ready = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, camera_index):
        super().__init__()
        self.camera_index = camera_index
        self._running = False

    def run(self):
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            self.error.emit(f"Could not open camera index {self.camera_index}.")
            return
        self._running = True
        while self._running:
            ret, frame = cap.read()
            if not ret:
                self.error.emit("Lost connection to the camera.")
                break
            self.frame_ready.emit(frame)
            self.msleep(40)  # ~25 fps preview cap
        cap.release()

    def stop(self):
        self._running = False


class CameraMixin:
    def toggle_camera(self):
        if getattr(self, "_camera_worker", None) is not None:
            self.stop_camera()
        else:
            self.start_camera()

    def start_camera(self):
        index = self.camera_index_spin.value()
        worker = CameraWorker(index)
        worker.frame_ready.connect(self._on_camera_frame)
        worker.error.connect(self._on_camera_error)
        self._camera_worker = worker
        self._camera_latest_frame = None
        worker.start()

        self.btn_camera_toggle.setChecked(True)
        self.btn_camera_toggle.setText("⏹  Stop Camera")
        self.btn_camera_capture.setEnabled(True)
        self.btn_select.setEnabled(False)
        self.camera_index_spin.setEnabled(False)
        self.update_nav_controls()
        self.camera_status.setText(f"Camera: live (index {index})")
        self.stats_label.setText("Camera live — click Capture & Inspect to run inspection.")

    def stop_camera(self):
        worker = getattr(self, "_camera_worker", None)
        if worker is not None:
            worker.stop()
            worker.wait(1000)
            worker.frame_ready.disconnect(self._on_camera_frame)
            worker.error.disconnect(self._on_camera_error)
        self._camera_worker = None
        self._camera_latest_frame = None

        self.btn_camera_toggle.setChecked(False)
        self.btn_camera_toggle.setText("▶  Start Camera")
        self.btn_camera_capture.setEnabled(False)
        self.btn_select.setEnabled(True)
        self.camera_index_spin.setEnabled(True)
        self.update_nav_controls()
        self.camera_status.setText("Camera: idle")

    def _on_camera_frame(self, frame):
        self._camera_latest_frame = frame
        self.display_cv_image(frame)

    def _on_camera_error(self, message):
        was_live = getattr(self, "_camera_worker", None) is not None
        self.stop_camera()
        if was_live:
            if hasattr(self, "toasts"):
                self.toasts.show("Camera error", "error")
            QMessageBox.critical(self, "Camera Error", message)

    def capture_and_inspect(self):
        frame = getattr(self, "_camera_latest_frame", None)
        if frame is None:
            QMessageBox.warning(self, "Capture", "No camera frame available yet.")
            return

        # Stop the live preview before inspecting: otherwise the camera thread
        # keeps pushing raw frames to display_cv_image() every ~40ms and the
        # inspection overlay drawn below gets overwritten almost immediately.
        # This also re-enables the Select (file) button, which start_camera()
        # disabled for the duration of the live preview.
        self.stop_camera()

        captures_dir = os.path.join(self.main_program_root, "captures")
        os.makedirs(captures_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = os.path.join(captures_dir, f"capture_{timestamp}.png")
        cv2.imwrite(path, frame)

        # Tracks the captures folder, so Prev/Next steps back through captures.
        self.open_image_path(path)
