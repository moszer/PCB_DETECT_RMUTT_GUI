import csv
import datetime as dt
import os

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QTableWidgetItem

from ..animations import animate_number, animate_bar
from ..styles import tokens_for


class HistoryMixin:
    def update_production_counters(self, inspection_result):
        self.total_count += 1
        if inspection_result["verdict"] == "PASS":
            self.pass_count += 1
        else:
            self.fail_count += 1
        animate_number(self.total_label, self.total_count)
        animate_number(self.pass_label, self.pass_count)
        animate_number(self.fail_label, self.fail_count)
        self._update_yield()

    def _update_yield(self):
        if self.total_count > 0:
            ratio = self.pass_count / self.total_count
            self.yield_value.setText(f"{ratio * 100:.0f}%")
        else:
            ratio = 0.0
            self.yield_value.setText("—")
        if hasattr(self, "yield_bar"):
            animate_bar(self, "_yield_anim_wrapper", self.yield_bar.set_ratio, ratio)

    def reset_counters(self):
        self.total_count = 0
        self.pass_count = 0
        self.fail_count = 0
        animate_number(self.total_label, 0)
        animate_number(self.pass_label, 0)
        animate_number(self.fail_label, 0)
        self._update_yield()
        self.stats_label.setText("Production counters reset.")
        if hasattr(self, "toasts"):
            self.toasts.show("Counters reset", "info", duration=1600)

    def append_history(self, image_path, inspection_result):
        timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = {
            "time": timestamp,
            "image": os.path.basename(image_path),
            "verdict": inspection_result["verdict"],
            "ok": inspection_result["ok"],
            "missing": len(inspection_result["missing"]),
            "wrong": len(inspection_result["wrong"]),
            "extra": len(inspection_result["extra"]),
            "conf": self.conf_slider.value(),
            "station_id": self.station_id_input.text().strip(),
            "operator": self.operator_input.text().strip(),
            "source_path": image_path,
            "model": self.current_model_path,
        }
        self.history_rows.insert(0, row)
        self.insert_history_row(row)

        if self.history_table.rowCount() > 300:
            self.history_table.removeRow(self.history_table.rowCount() - 1)
            self.history_rows = self.history_rows[:300]

        if self.check_auto_log.isChecked():
            self.append_to_log_file(row)

    def insert_history_row(self, row):
        tokens = tokens_for(getattr(self, "_current_theme", "light"))
        self.history_table.insertRow(0)
        values = [
            row["time"],
            row["image"],
            row["verdict"],
            str(row["ok"]),
            str(row["missing"]),
            str(row["wrong"]),
            str(row["extra"]),
            f"{row['conf']}%",
        ]
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            if col == 2:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if value == "PASS":
                    item.setForeground(QBrush(QColor(tokens["pass_strong"])))
                else:
                    item.setForeground(QBrush(QColor(tokens["fail_strong"])))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            elif col >= 3:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.history_table.setItem(0, col, item)

        self._flash_history_row(tokens["row_selected"])

    def _flash_history_row(self, hex_color):
        """Briefly highlight the freshly inserted row, then fade back.
        Item references are captured so the highlight follows the row as it shifts down."""
        flash = QBrush(QColor(hex_color))
        cols = self.history_table.columnCount()
        items = [self.history_table.item(0, col) for col in range(cols)]
        for item in items:
            if item is not None:
                item.setBackground(flash)

        def _clear():
            for item in items:
                if item is not None:
                    item.setBackground(QBrush())

        QTimer.singleShot(650, _clear)

    def append_to_log_file(self, row):
        write_header = not os.path.exists(self.default_log_path)
        try:
            with open(self.default_log_path, "a", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                if write_header:
                    writer.writerow(
                        [
                            "time",
                            "station_id",
                            "operator",
                            "image",
                            "verdict",
                            "ok",
                            "missing",
                            "wrong",
                            "extra",
                            "conf_pct",
                            "source_path",
                            "model",
                        ]
                    )
                writer.writerow(
                    [
                        row["time"],
                        row["station_id"],
                        row["operator"],
                        row["image"],
                        row["verdict"],
                        row["ok"],
                        row["missing"],
                        row["wrong"],
                        row["extra"],
                        row["conf"],
                        row["source_path"],
                        row["model"],
                    ]
                )
        except Exception as exc:
            self.stats_label.setText(f"Auto-log write failed: {exc}")

    def export_history_csv(self):
        if not self.history_rows:
            QMessageBox.information(self, "Export", "No inspection history to export.")
            return
        default_name = f"inspection_history_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        export_path, _ = QFileDialog.getSaveFileName(
            self, "Export Inspection History", os.path.join(self.project_root, default_name), "CSV Files (*.csv)"
        )
        if not export_path:
            return
        try:
            with open(export_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    [
                        "time",
                        "station_id",
                        "operator",
                        "image",
                        "verdict",
                        "ok",
                        "missing",
                        "wrong",
                        "extra",
                        "conf_pct",
                        "source_path",
                        "model",
                    ]
                )
                for row in self.history_rows:
                    writer.writerow(
                        [
                            row["time"],
                            row["station_id"],
                            row["operator"],
                            row["image"],
                            row["verdict"],
                            row["ok"],
                            row["missing"],
                            row["wrong"],
                            row["extra"],
                            row.get("conf", ""),
                            row["source_path"],
                            row["model"],
                        ]
                    )
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", f"Could not export CSV:\n{exc}")
            return
        self.stats_label.setText(f"History exported: {os.path.basename(export_path)}")
        if hasattr(self, "toasts"):
            self.toasts.show(f"Exported · {os.path.basename(export_path)}", "success")
