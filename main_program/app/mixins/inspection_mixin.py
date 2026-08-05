import os

import cv2
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from ..inspection_logic import draw_reference_overlay, evaluate_inspection
from ..animations import fade_in, pulse_glow
from ..styles import tokens_for


class InferenceWorker(QThread):
    finished = pyqtSignal(list, object, dict)  # detections, annotated_frame, speed
    error = pyqtSignal(str)

    def __init__(self, model, image_path, conf_value, model_names, show_labels, show_coords):
        super().__init__()
        self.model = model
        self.image_path = image_path
        self.conf_value = conf_value
        self.model_names = model_names
        self.show_labels = show_labels
        self.show_coords = show_coords

    def run(self):
        try:
            results = self.model.predict(
                source=self.image_path, conf=self.conf_value, save=False, device="cpu"
            )
        except Exception as exc:
            self.error.emit(f"Could not run inference:\n{exc}")
            return

        annotated_frame = None
        detections = []
        speed = {"preprocess": 0.0, "inference": 0.0, "postprocess": 0.0}

        for result in results:
            annotated_frame = result.plot(labels=self.show_labels)
            for k in speed:
                speed[k] += result.speed.get(k, 0.0)
            for box in result.boxes:
                cls_idx = int(box.cls[0])
                cls_name = str(self.model_names.get(cls_idx, cls_idx))
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
                confidence = float(box.conf[0])
                detections.append(
                    {"x": cx, "y": cy, "label": cls_name, "conf": confidence, "box": (x1, y1, x2, y2)}
                )
                if self.show_coords:
                    cv2.circle(annotated_frame, (cx, cy), 3, (255, 80, 0), -1)
                    cv2.putText(
                        annotated_frame,
                        f"({cx},{cy})",
                        (cx + 5, cy - 5),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.4,
                        (255, 255, 255),
                        1,
                        cv2.LINE_AA,
                    )

        if annotated_frame is None:
            fallback = cv2.imread(self.image_path)
            if fallback is None:
                self.error.emit("Unable to open selected image file.")
                return
            annotated_frame = fallback

        self.finished.emit(detections, annotated_frame, speed)


class InspectionMixin:
    def select_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Inspection Image",
            self.project_root,
            "Image Files (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not file_path:
            return
        self.current_image_path = file_path
        self.zoom_factor = 1.0
        self.update_zoom_display()
        self.run_inference(file_path, record_history=True)

    def inspect_current_image(self):
        if not self.current_image_path:
            QMessageBox.warning(self, "Inspection", "Please select an image first.")
            return
        self.run_inference(self.current_image_path, record_history=True)

    def zoom_in(self):
        self.set_zoom(self.zoom_factor * 1.25)

    def zoom_out(self):
        self.set_zoom(self.zoom_factor / 1.25)

    def zoom_fit(self):
        self.set_zoom(1.0, force=True)

    def set_zoom(self, factor, force=False):
        clamped = max(self.min_zoom_factor, min(self.max_zoom_factor, float(factor)))
        if (not force) and abs(clamped - self.zoom_factor) < 1e-6:
            return
        self.zoom_factor = clamped
        self.update_zoom_display()
        self.scale_image_to_label()

    def update_zoom_display(self):
        zoom_percent = int(round(self.zoom_factor * 100))
        self.zoom_value_label.setText(f"{zoom_percent}%")

    def refresh_image(self):
        if self.current_image_path:
            self.run_inference(self.current_image_path, record_history=False)

    def request_live_refresh(self):
        """Coalesce rapid parameter changes (slider drag, checkbox toggles) into
        a single inference so live tuning stays smooth instead of firing on every tick."""
        if not self.current_image_path or not self.model:
            return
        timer = getattr(self, "_refresh_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self.refresh_image)
            self._refresh_timer = timer
        timer.start(200)

    def run_inference(self, image_path, record_history=False):
        if not self.model:
            self.stats_label.setText("Model not loaded. Select and load a model file.")
            return

        # If inference is already running, remember the latest request and run it
        # as soon as the current one finishes (keeps the view in sync with controls).
        if getattr(self, "_inference_running", False):
            self._pending_inference = (image_path, record_history)
            return

        conf_value = self.conf_slider.value() / 100.0
        self._inference_running = True
        self._set_inference_busy(True)
        self.stats_label.setText("Running inference…")
        if hasattr(self, "busy_overlay"):
            self.busy_overlay.start("Analyzing")

        worker = InferenceWorker(
            self.model,
            image_path,
            conf_value,
            self.model_names,
            self.check_labels.isChecked(),
            self.check_coords.isChecked(),
        )
        self._inference_worker = worker  # keep reference to prevent GC
        worker.finished.connect(
            lambda dets, frame, spd: self._on_inference_done(dets, frame, spd, image_path, record_history)
        )
        worker.error.connect(self._on_inference_error)
        worker.start()

    def _on_inference_done(self, detections, annotated_frame, speed, image_path, record_history):
        self._inference_running = False
        self._set_inference_busy(False)
        if hasattr(self, "busy_overlay"):
            self.busy_overlay.stop()

        inspection_result = evaluate_inspection(
            reference_points=self.reference_points,
            detections=detections,
            match_dist=float(self.match_dist_spin.value()),
            fail_on_extra=self.check_fail_extra.isChecked(),
        )
        self.last_inspection_result = inspection_result
        draw_reference_overlay(annotated_frame, inspection_result, self.check_labels.isChecked())

        if self.check_show_extra.isChecked():
            for det in inspection_result["extra"]:
                cv2.circle(annotated_frame, (det["x"], det["y"]), 12, (0, 255, 255), 2)
                cv2.putText(
                    annotated_frame,
                    f"EXTRA:{det['label']}",
                    (det["x"] + 8, det["y"] - 8),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (0, 255, 255),
                    1,
                    cv2.LINE_AA,
                )

        self.current_annotated_frame = annotated_frame.copy()
        self.update_result_panel(inspection_result, image_path)
        self.display_cv_image(annotated_frame)

        total_ms = sum(speed.values())
        self.perf_label.setText(
            f"Pre: {speed['preprocess']:.1f} ms  |  "
            f"Infer: {speed['inference']:.1f} ms  |  "
            f"Post: {speed['postprocess']:.1f} ms  |  "
            f"Total: {total_ms:.1f} ms"
        )

        # Override status if any reference points fall outside image bounds
        img_h, img_w = annotated_frame.shape[:2]
        out_of_bounds = [
            pt for pt in self.reference_points
            if pt["x"] >= img_w or pt["y"] >= img_h
        ]
        if out_of_bounds:
            self.stats_label.setText(
                f"Warning: {len(out_of_bounds)} reference point(s) outside image bounds "
                f"({img_w}x{img_h}) — references may be from a different image size."
            )

        if record_history:
            self.update_production_counters(inspection_result)
            self.append_history(image_path, inspection_result)

        # Run any request that arrived while this inference was in flight.
        pending = getattr(self, "_pending_inference", None)
        if pending is not None:
            self._pending_inference = None
            path, record = pending
            QTimer.singleShot(0, lambda: self.run_inference(path, record))

    def _on_inference_error(self, message):
        self._inference_running = False
        self._set_inference_busy(False)
        if hasattr(self, "busy_overlay"):
            self.busy_overlay.stop()
        self._pending_inference = None
        if hasattr(self, "toasts"):
            self.toasts.show("Inference failed", "error")
        QMessageBox.critical(self, "Inference Error", message)

    def _set_inference_busy(self, busy):
        self.btn_select.setEnabled(not busy)
        self.btn_reinspect.setEnabled(not busy and self.model is not None)

    def _repolish(self, widget, object_name):
        widget.setObjectName(object_name)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def update_result_panel(self, inspection_result, image_path):
        verdict = inspection_result["verdict"]
        if verdict == "PASS":
            self._repolish(self.verdict_card, "verdictCardPass")
            self._repolish(self.verdict_label, "verdictBigPass")
        elif verdict == "FAIL":
            self._repolish(self.verdict_card, "verdictCardFail")
            self._repolish(self.verdict_label, "verdictBigFail")
        else:
            self._repolish(self.verdict_card, "verdictCard")
            self._repolish(self.verdict_label, "verdictBig")
        self.verdict_label.setText(verdict)

        missing_count = len(inspection_result["missing"])
        wrong_count = len(inspection_result["wrong"])
        extra_count = len(inspection_result["extra"])
        ok_count = inspection_result["ok"]

        image_name = os.path.basename(image_path) if image_path else "—"
        self.verdict_image_name.setText(image_name)
        self.verdict_reason.setText(inspection_result["reason"])
        self._set_pill(self.pill_expect, inspection_result["total_refs"])
        self._set_pill(self.pill_ok, ok_count)
        self._set_pill(self.pill_miss, missing_count)
        self._set_pill(self.pill_wrong, wrong_count)
        self._set_pill(self.pill_extra, extra_count)

        self.stats_label.setText(
            f"Inspection complete  ·  {verdict}  ·  "
            f"Expected {inspection_result['total_refs']} / OK {ok_count} / "
            f"Missing {missing_count} / Wrong {wrong_count} / Extra {extra_count}"
        )
        self._animate_verdict(verdict)

    def _animate_verdict(self, verdict):
        tokens = tokens_for(getattr(self, "_current_theme", "light"))
        if verdict == "FAIL":
            fade_in(self.verdict_card, duration=220,
                    on_finished=lambda: pulse_glow(self.verdict_label, tokens["fail_strong"],
                                                   blur=40, cycles=2))
        elif verdict == "PASS":
            fade_in(self.verdict_card, duration=220,
                    on_finished=lambda: pulse_glow(self.verdict_label, tokens["pass_strong"],
                                                   blur=30, cycles=1, duration=900))
        else:
            fade_in(self.verdict_card, duration=220)

    def display_cv_image(self, frame):
        # Normalise to 3-channel BGR before converting
        if frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif frame.ndim == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, channels = rgb_frame.shape
        self.original_image_size = (w, h)
        bytes_per_line = channels * w
        image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        self.current_image_pixmap = QPixmap.fromImage(image)
        # Drop the dashed empty-state border now that we have a real image.
        self.image_display.setText("")
        self.image_display.setStyleSheet("QLabel#imageDisplay { border: none; background: transparent; }")
        self.scale_image_to_label()

    def scale_image_to_label(self):
        if not self.current_image_pixmap:
            return
        pixmap_w = self.current_image_pixmap.width()
        pixmap_h = self.current_image_pixmap.height()
        if pixmap_w <= 0 or pixmap_h <= 0:
            return

        viewport_size = self.image_scroll.viewport().size()
        if viewport_size.width() <= 0 or viewport_size.height() <= 0:
            return

        fit_scale = min(viewport_size.width() / pixmap_w, viewport_size.height() / pixmap_h)
        target_scale = fit_scale * self.zoom_factor
        target_w = max(1, int(pixmap_w * target_scale))
        target_h = max(1, int(pixmap_h * target_scale))

        scaled = self.current_image_pixmap.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_display.setPixmap(scaled)
        self.image_display.resize(scaled.size())
        self.image_display.setMinimumSize(scaled.size())

    def save_annotated_image(self):
        if self.current_annotated_frame is None:
            QMessageBox.warning(self, "Save Image", "No annotated result available.")
            return
        if self.current_image_path:
            base_name = os.path.splitext(os.path.basename(self.current_image_path))[0]
        else:
            base_name = "inspection"
        default_path = os.path.join(self.project_root, f"{base_name}_annotated.png")
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Annotated Image", default_path, "PNG Files (*.png);;JPEG Files (*.jpg *.jpeg)"
        )
        if not out_path:
            return
        try:
            cv2.imwrite(out_path, self.current_annotated_frame)
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", f"Could not save image:\n{exc}")
            if hasattr(self, "toasts"):
                self.toasts.show("Could not save image", "error")
            return
        self.stats_label.setText(f"Annotated image saved: {os.path.basename(out_path)}")
        if hasattr(self, "toasts"):
            self.toasts.show(f"Saved · {os.path.basename(out_path)}", "success")

    def _sync_placeholder_size(self):
        """Keep the empty-state placeholder filling the whole viewer area."""
        if self.current_image_pixmap or not hasattr(self, "image_scroll"):
            return
        viewport = self.image_scroll.viewport().size()
        if viewport.width() > 0 and viewport.height() > 0:
            self.image_display.resize(viewport)

    def resizeEvent(self, event):
        if self.current_image_pixmap:
            self.scale_image_to_label()
        else:
            self._sync_placeholder_size()
        if hasattr(self, "toasts"):
            self.toasts.reflow()
        super().resizeEvent(event)
