import json
import os

from PyQt6.QtCore import QAbstractAnimation


class SettingsMixin:
    def _settings_path(self):
        return os.path.join(self.main_program_root, "settings.json")

    def save_settings(self):
        data = {
            "inference_device": self.device_combo.currentData(),
            "conf": self.conf_slider.value(),
            "match_dist": self.match_dist_spin.value(),
            "show_labels": self.check_labels.isChecked(),
            "show_coords": self.check_coords.isChecked(),
            "show_extra": self.check_show_extra.isChecked(),
            "fail_on_extra": self.check_fail_extra.isChecked(),
            "auto_log": self.check_auto_log.isChecked(),
            "station_id": self.station_id_input.text().strip(),
            "operator": self.operator_input.text().strip(),
            "theme": getattr(self, "_current_theme", "light"),
            "model_path": self.model_path_input.text().strip(),
            "ref_path": self.ref_path_input.text().strip(),
            "cards": {
                "station": self.station_card.is_expanded(),
                "inspection": self.inspection_card.is_expanded(),
                "camera": self.camera_card.is_expanded(),
                "display": self.display_card.is_expanded(),
                "reference": self.reference_card.is_expanded(),
            },
            "folder_path": self.folder_path,
            "history_visible": self.history_panel.isVisible(),
            "left_panel_visible": self.left_scroll.isVisible(),
        }
        try:
            with open(self._settings_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass  # Don't interrupt close on save failure

    def load_settings(self):
        path = self._settings_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return

        device_index = self.device_combo.findData(data.get("inference_device", "auto"))
        if device_index >= 0:
            self.device_combo.setCurrentIndex(device_index)

        if "conf" in data:
            self.conf_slider.setValue(int(data["conf"]))
            self.conf_label.setText(f"Confidence: {data['conf']}%")
        if "match_dist" in data:
            self.match_dist_spin.setValue(int(data["match_dist"]))
        if "show_labels" in data:
            self.check_labels.setChecked(bool(data["show_labels"]))
        if "show_coords" in data:
            self.check_coords.setChecked(bool(data["show_coords"]))
        if "show_extra" in data:
            self.check_show_extra.setChecked(bool(data["show_extra"]))
        if "fail_on_extra" in data:
            self.check_fail_extra.setChecked(bool(data["fail_on_extra"]))
        if "auto_log" in data:
            self.check_auto_log.setChecked(bool(data["auto_log"]))
        if "station_id" in data:
            self.station_id_input.setText(data["station_id"])
        if "operator" in data:
            self.operator_input.setText(data["operator"])
        if "theme" in data and data["theme"] != getattr(self, "_current_theme", "light"):
            self._current_theme = data["theme"]
            self._update_theme_button_text()
            self.apply_styles()
        if data.get("model_path") and os.path.isfile(data["model_path"]):
            if os.path.abspath(data["model_path"]) != os.path.abspath(self.current_model_path or self.default_model_path):
                self.load_model(data["model_path"])
        if data.get("ref_path") and os.path.isfile(data["ref_path"]):
            self.load_reference_file(data["ref_path"], push_state=False, show_messages=False)
        # Only the dialog's starting directory is restored — no folder is
        # re-scanned or re-inspected on launch.
        folder = data.get("folder_path", "")
        if folder and os.path.isdir(folder):
            self.folder_path = folder
        cards = data.get("cards", {})
        for name, card in (
            ("station", getattr(self, "station_card", None)),
            ("inspection", getattr(self, "inspection_card", None)),
            ("camera", getattr(self, "camera_card", None)),
            ("display", getattr(self, "display_card", None)),
            ("reference", getattr(self, "reference_card", None)),
        ):
            if card is not None and name in cards:
                card.set_expanded(bool(cards[name]), animate=False)

        if "history_visible" in data and bool(data["history_visible"]) != (not self.history_panel.isHidden()):
            self.toggle_history_panel()
        if "left_panel_visible" in data:
            self.left_scroll.setVisible(bool(data["left_panel_visible"]))

    def closeEvent(self, event):
        # A closed window can remain alive until deleteLater is processed.
        # Stop callbacks that would otherwise touch its widgets during teardown.
        for animation in self.findChildren(QAbstractAnimation):
            animation.stop()
        self.save_settings()
        if getattr(self, "_camera_worker", None) is not None:
            self.stop_camera()
        # Wait for any running inference worker before closing
        if hasattr(self, "_inference_worker") and self._inference_worker.isRunning():
            self._inference_worker.wait(3000)
        super().closeEvent(event)
