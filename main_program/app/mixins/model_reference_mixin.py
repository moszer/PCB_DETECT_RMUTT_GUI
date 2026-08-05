import copy
import json
import math
import os

from PyQt6.QtWidgets import QFileDialog, QMessageBox


def _load_yolo_class():
    """Import ultralytics lazily so the UI still launches (in a degraded, view-only
    state) when the heavy YOLO/torch stack isn't installed."""
    try:
        from ultralytics import YOLO
        return YOLO, None
    except Exception as exc:  # ImportError or downstream torch errors
        return None, str(exc)


class ModelReferenceMixin:
    def _toast(self, message, kind="info", duration=2800):
        if getattr(self, "_booting", False):
            return
        if hasattr(self, "toasts"):
            self.toasts.show(message, kind, duration)
    def load_default_assets(self):
        if os.path.exists(self.default_model_path):
            self.model_path_input.setText(self.default_model_path)
            self.load_model(self.default_model_path)
        else:
            self.set_model_status("Model file not found. Select a .pt model.", ok=False)

        if os.path.exists(self.default_refs_path):
            self.load_reference_file(self.default_refs_path, push_state=False, show_messages=False)
            self.stats_label.setText("Default references loaded from Refs.json.")

    def set_model_status(self, message, ok):
        self.model_status.setText(message)
        self.model_status.setObjectName("statusLine" if ok else "statusBad")
        self.model_status.style().unpolish(self.model_status)
        self.model_status.style().polish(self.model_status)
        # Surface problems even when the Station card is collapsed.
        if not ok and hasattr(self, "station_card"):
            self.station_card.set_expanded(True, animate=not getattr(self, "_booting", False))

    def select_model_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select YOLO Model", self.project_root, "PyTorch Model (*.pt)"
        )
        if file_path:
            self.model_path_input.setText(file_path)

    def load_model_button(self):
        model_path = self.model_path_input.text().strip()
        if not model_path:
            QMessageBox.warning(self, "Model", "Please select a model file first.")
            return
        self.load_model(model_path)

    def load_model(self, model_path):
        yolo_class, import_error = _load_yolo_class()
        if yolo_class is None:
            self.set_model_status("YOLO backend unavailable — install ultralytics.", ok=False)
            self.stats_label.setText(
                "Model backend (ultralytics) not installed. UI is view-only until it is available."
            )
            self._toast("YOLO backend unavailable", "warn", duration=4000)
            return
        try:
            candidate_model = yolo_class(model_path)
            names = candidate_model.names
            if not isinstance(names, dict):
                names = {idx: str(name) for idx, name in enumerate(names)}
        except Exception as exc:
            QMessageBox.critical(self, "Model Error", f"Unable to load model:\n{exc}")
            self.set_model_status("Model load failed.", ok=False)
            self._toast("Model failed to load", "error")
            return

        self.model = candidate_model
        self.model_names = names
        self.current_model_path = model_path
        self.model_path_input.setText(model_path)
        self.populate_class_combo()
        self.set_model_status(f"Model loaded: {os.path.basename(model_path)}", ok=True)
        self.stats_label.setText("Model ready for inspection.")
        self._toast(f"Model loaded · {os.path.basename(model_path)}", "success")
        self._update_action_buttons()
        self.refresh_image()

    def populate_class_combo(self):
        class_names = [str(v) for _, v in sorted(self.model_names.items(), key=lambda item: item[0])]
        self.combo_classes.clear()
        if class_names:
            self.combo_classes.addItems(class_names)
        else:
            self.combo_classes.addItem("class")

    def save_state(self):
        self.undo_stack.append(copy.deepcopy(self.reference_points))
        self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack:
            self.stats_label.setText("No more actions to undo.")
            return
        self.redo_stack.append(copy.deepcopy(self.reference_points))
        self.reference_points = self.undo_stack.pop()
        self.update_reference_status()
        self.refresh_image()
        self.stats_label.setText("Undo applied.")

    def redo(self):
        if not self.redo_stack:
            self.stats_label.setText("No more actions to redo.")
            return
        self.undo_stack.append(copy.deepcopy(self.reference_points))
        self.reference_points = self.redo_stack.pop()
        self.update_reference_status()
        self.refresh_image()
        self.stats_label.setText("Redo applied.")

    def add_reference_point(self, x, y, label):
        if not label:
            QMessageBox.warning(self, "Reference", "Please select a class before adding a point.")
            return
        self.save_state()
        self.reference_points.append({"x": int(x), "y": int(y), "label": str(label)})
        self.update_reference_status()
        self.refresh_image()
        self.stats_label.setText(f"Reference added at ({x}, {y}) as {label}.")

    def clear_references(self):
        if not self.reference_points:
            return
        self.save_state()
        self.reference_points = []
        self.update_reference_status()
        self.refresh_image()
        self.stats_label.setText("All references cleared.")

    def toggle_edit_mode(self):
        self.is_edit_mode = self.btn_edit_mode.isChecked()
        if self.is_edit_mode:
            self.btn_edit_mode.setText("Disable Edit Mode")
            self.stats_label.setText("Edit mode active: click on image to add reference points.")
        else:
            self.btn_edit_mode.setText("Enable Edit Mode")
            self.refresh_image()

    def update_reference_status(self):
        self.ref_status.setText(f"References: {len(self.reference_points)} points")

    def save_references(self):
        suggested = self.ref_path_input.text().strip() or self.default_refs_path
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Reference Profile", suggested, "JSON Files (*.json)"
        )
        if not file_path:
            return
        self.save_reference_file(file_path)

    def save_default_references(self):
        self.save_reference_file(self.default_refs_path)

    def add_extra_and_save_default(self):
        self.add_extra_to_references(save_default=True)

    def add_extra_to_references(self, save_default=False):
        if not self.last_inspection_result:
            QMessageBox.information(
                self,
                "EXTRA to REF",
                "Run an inspection first so the system can find EXTRA components.",
            )
            return

        extras = self.last_inspection_result.get("extra", [])
        if not extras:
            QMessageBox.information(self, "EXTRA to REF", "No EXTRA components found in latest inspection.")
            return

        self.save_state()
        added = 0
        skipped = 0
        dedupe_distance = max(8, int(self.match_dist_spin.value() * 0.2))

        for det in extras:
            candidate = {"x": int(det["x"]), "y": int(det["y"]), "label": str(det["label"])}
            if self.is_reference_duplicate(candidate, dedupe_distance):
                skipped += 1
                continue
            self.reference_points.append(candidate)
            added += 1

        self.update_reference_status()
        self.refresh_image()

        if save_default:
            self.save_reference_file(self.default_refs_path)

        if added == 0:
            self.stats_label.setText("EXTRA->REF skipped: all extra points already exist in references.")
            QMessageBox.information(
                self,
                "EXTRA to REF",
                f"No new points added. {skipped} point(s) matched existing references.",
            )
            return

        msg = f"Added {added} EXTRA component(s) to REF."
        if skipped:
            msg += f" Skipped duplicates: {skipped}."
        if save_default:
            msg += " Saved to Refs.json."
        self.stats_label.setText(msg)
        QMessageBox.information(self, "EXTRA to REF", msg)

    def is_reference_duplicate(self, candidate, distance_threshold):
        for ref in self.reference_points:
            if ref["label"] != candidate["label"]:
                continue
            if math.hypot(ref["x"] - candidate["x"], ref["y"] - candidate["y"]) <= distance_threshold:
                return True
        return False

    def save_reference_file(self, file_path):
        try:
            with open(file_path, "w", encoding="utf-8") as handle:
                json.dump(self.reference_points, handle, indent=2)
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", f"Could not save references:\n{exc}")
            return
        self.ref_path_input.setText(file_path)
        self.stats_label.setText(f"Reference profile saved: {os.path.basename(file_path)}")
        self._toast(f"Saved · {os.path.basename(file_path)}", "success")

    def load_references(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Reference Profile", self.project_root, "JSON Files (*.json)"
        )
        if file_path:
            self.load_reference_file(file_path, push_state=True, show_messages=True)

    def load_default_references(self):
        if not os.path.exists(self.default_refs_path):
            QMessageBox.warning(self, "References", "Refs.json not found in project folder.")
            return
        self.load_reference_file(self.default_refs_path, push_state=True, show_messages=True)

    def load_reference_file(self, file_path, push_state=True, show_messages=True):
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, list):
                raise ValueError("Reference file must be a JSON list.")
            validated = []
            for i, item in enumerate(payload):
                if not isinstance(item, dict):
                    raise ValueError(f"Item {i} is not a JSON object.")
                x = item.get("x")
                y = item.get("y")
                label = item.get("label")
                if x is None or y is None or label is None:
                    raise ValueError(f"Item {i} is missing required field(s): x, y, or label.")
                validated.append(
                    {
                        "x": int(x),
                        "y": int(y),
                        "label": str(label),
                    }
                )
        except Exception as exc:
            QMessageBox.critical(self, "Reference Error", f"Failed to load references:\n{exc}")
            return

        if push_state:
            self.save_state()
        self.reference_points = validated
        self.ref_path_input.setText(file_path)
        self.update_reference_status()
        self.refresh_image()
        if show_messages:
            self.stats_label.setText(
                f"Loaded {len(validated)} reference points from {os.path.basename(file_path)}."
            )
            self._toast(f"Loaded {len(validated)} reference points", "success")

    def update_confidence(self, value):
        self.conf_label.setText(f"Confidence: {value}%")
        self.request_live_refresh()
