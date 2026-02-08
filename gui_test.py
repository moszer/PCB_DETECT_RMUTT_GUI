import copy
import csv
import datetime as dt
import json
import math
import os
import sys

import cv2
from ultralytics import YOLO
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage, QMouseEvent, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QCheckBox,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QComboBox,
    QHeaderView,
    QAbstractItemView,
    QScrollArea,
    QFrame,
    QSizePolicy,
)


class ReferenceLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_gui = parent
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText("Load image to start inspection")
        self.setStyleSheet("border: 2px dashed #a0a8b3; background-color: #f6f8fa; color: #4b5563;")

    def mousePressEvent(self, event: QMouseEvent):
        if not self.parent_gui:
            return
        if not self.parent_gui.is_edit_mode or not self.parent_gui.current_image_pixmap:
            return
        pixmap = self.pixmap()
        if not pixmap:
            return

        pos = event.position()
        scaled_w = pixmap.width()
        scaled_h = pixmap.height()
        click_x = pos.x()
        click_y = pos.y()

        if 0 <= click_x <= scaled_w and 0 <= click_y <= scaled_h:
            orig_w, orig_h = self.parent_gui.original_image_size
            if orig_w <= 0 or orig_h <= 0:
                return
            real_x = int(click_x * (orig_w / scaled_w))
            real_y = int(click_y * (orig_h / scaled_h))
            selected_class = self.parent_gui.combo_classes.currentText()
            self.parent_gui.add_reference_point(real_x, real_y, selected_class)


class DefectDetectionGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Factory Defect Inspection Station")
        self.setMinimumSize(1260, 760)

        self.project_root = os.path.dirname(os.path.abspath(__file__))
        self.default_model_path = os.path.join(self.project_root, "best.pt")
        self.default_refs_path = os.path.join(self.project_root, "Refs.json")
        self.default_log_path = os.path.join(self.project_root, "inspection_log.csv")

        self.model = None
        self.model_names = {}
        self.current_model_path = ""

        self.reference_points = []
        self.undo_stack = []
        self.redo_stack = []
        self.is_edit_mode = False

        self.current_image_path = None
        self.current_image_pixmap = None
        self.current_annotated_frame = None
        self.original_image_size = (0, 0)
        self.last_inspection_result = None

        self.zoom_factor = 1.0
        self.min_zoom_factor = 0.2
        self.max_zoom_factor = 8.0

        self.total_count = 0
        self.pass_count = 0
        self.fail_count = 0
        self.history_rows = []

        self.init_ui()
        self.apply_styles()
        self.load_default_assets()

    def init_ui(self):
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.root_layout = QHBoxLayout(self.main_widget)
        self.root_layout.setContentsMargins(12, 12, 12, 12)
        self.root_layout.setSpacing(12)

        self.left_panel = QWidget()
        self.left_panel.setObjectName("leftPanel")
        self.left_panel.setMinimumWidth(430)
        self.left_layout = QVBoxLayout(self.left_panel)
        self.left_layout.setContentsMargins(10, 10, 10, 10)
        self.left_layout.setSpacing(10)

        self.left_scroll = QScrollArea()
        self.left_scroll.setObjectName("leftScroll")
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.left_scroll.setMinimumWidth(450)
        self.left_scroll.setMaximumWidth(560)
        self.left_scroll.setWidget(self.left_panel)

        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(10)

        self.root_layout.addWidget(self.left_scroll, 0)
        self.root_layout.addWidget(self.right_panel, 1)

        self.build_station_group()
        self.build_inspection_group()
        self.build_reference_group()
        self.build_result_group()
        self.build_production_group()
        self.build_image_view()
        self.build_history_table()

    def build_station_group(self):
        group = self.create_group("Station")
        layout = QGridLayout(group)

        self.station_id_input = QLineEdit("Line-01")
        self.operator_input = QLineEdit("Operator-A")
        self.model_path_input = QLineEdit()
        self.model_path_input.setPlaceholderText("Select YOLO model (.pt)")
        self.model_path_input.setReadOnly(True)
        self.model_status = QLabel("Model: not loaded")
        self.model_status.setObjectName("statusBad")

        self.btn_select_model = QPushButton("Select Model")
        self.btn_select_model.clicked.connect(self.select_model_file)
        self.btn_load_model = QPushButton("Load Model")
        self.btn_load_model.clicked.connect(self.load_model_button)

        layout.addWidget(QLabel("Station ID"), 0, 0)
        layout.addWidget(self.station_id_input, 0, 1, 1, 2)
        layout.addWidget(QLabel("Operator"), 1, 0)
        layout.addWidget(self.operator_input, 1, 1, 1, 2)
        layout.addWidget(QLabel("Model"), 2, 0)
        layout.addWidget(self.model_path_input, 2, 1, 1, 2)
        layout.addWidget(self.btn_select_model, 3, 1)
        layout.addWidget(self.btn_load_model, 3, 2)
        layout.addWidget(self.model_status, 4, 0, 1, 3)
        group.setLayout(layout)
        self.left_layout.addWidget(group)

    def build_inspection_group(self):
        group = self.create_group("Inspection")
        layout = QGridLayout(group)

        self.conf_label = QLabel("Confidence: 25%")
        self.conf_slider = QSlider(Qt.Orientation.Horizontal)
        self.conf_slider.setRange(1, 100)
        self.conf_slider.setValue(25)
        self.conf_slider.valueChanged.connect(self.update_confidence)

        self.match_dist_spin = QSpinBox()
        self.match_dist_spin.setRange(5, 250)
        self.match_dist_spin.setValue(50)
        self.match_dist_spin.valueChanged.connect(self.refresh_image)

        self.check_labels = QCheckBox("Show YOLO labels")
        self.check_labels.setChecked(True)
        self.check_labels.stateChanged.connect(self.refresh_image)

        self.check_coords = QCheckBox("Show coordinates")
        self.check_coords.setChecked(False)
        self.check_coords.stateChanged.connect(self.refresh_image)

        self.check_show_extra = QCheckBox("Highlight extra detections")
        self.check_show_extra.setChecked(True)
        self.check_show_extra.stateChanged.connect(self.refresh_image)

        self.check_fail_extra = QCheckBox("Fail on extra detections")
        self.check_fail_extra.setChecked(True)
        self.check_fail_extra.stateChanged.connect(self.refresh_image)

        self.check_auto_log = QCheckBox("Auto-log to CSV")
        self.check_auto_log.setChecked(True)

        layout.addWidget(self.conf_label, 0, 0)
        layout.addWidget(self.conf_slider, 0, 1, 1, 2)
        layout.addWidget(QLabel("Match distance (px)"), 1, 0)
        layout.addWidget(self.match_dist_spin, 1, 1, 1, 2)
        layout.addWidget(self.check_labels, 2, 0, 1, 3)
        layout.addWidget(self.check_coords, 3, 0, 1, 3)
        layout.addWidget(self.check_show_extra, 4, 0, 1, 3)
        layout.addWidget(self.check_fail_extra, 5, 0, 1, 3)
        layout.addWidget(self.check_auto_log, 6, 0, 1, 3)
        group.setLayout(layout)
        self.left_layout.addWidget(group)

    def build_reference_group(self):
        group = self.create_group("Reference")
        layout = QGridLayout(group)

        self.ref_status = QLabel("References: 0 points")
        self.combo_classes = QComboBox()
        self.combo_classes.addItem("class")

        self.btn_edit_mode = QPushButton("Enable Edit Mode")
        self.btn_edit_mode.setCheckable(True)
        self.btn_edit_mode.clicked.connect(self.toggle_edit_mode)
        self.btn_clear_ref = QPushButton("Clear")
        self.btn_clear_ref.clicked.connect(self.clear_references)
        self.btn_undo = QPushButton("Undo")
        self.btn_undo.clicked.connect(self.undo)
        self.btn_redo = QPushButton("Redo")
        self.btn_redo.clicked.connect(self.redo)
        self.btn_save_ref = QPushButton("Save Profile")
        self.btn_save_ref.clicked.connect(self.save_references)
        self.btn_load_ref = QPushButton("Load Profile")
        self.btn_load_ref.clicked.connect(self.load_references)

        self.ref_path_input = QLineEdit()
        self.ref_path_input.setPlaceholderText("Reference profile path")
        self.ref_path_input.setReadOnly(True)

        self.btn_load_default_ref = QPushButton("Load Refs.json")
        self.btn_load_default_ref.clicked.connect(self.load_default_references)
        self.btn_save_default_ref = QPushButton("Save Refs.json")
        self.btn_save_default_ref.clicked.connect(self.save_default_references)
        self.btn_add_extra_ref = QPushButton("Add EXTRA -> REF")
        self.btn_add_extra_ref.clicked.connect(self.add_extra_to_references)
        self.btn_add_extra_ref_save = QPushButton("Add EXTRA + Save")
        self.btn_add_extra_ref_save.clicked.connect(self.add_extra_and_save_default)

        layout.addWidget(QLabel("Target Class"), 0, 0)
        layout.addWidget(self.combo_classes, 0, 1, 1, 2)
        layout.addWidget(self.btn_edit_mode, 1, 0, 1, 3)
        layout.addWidget(self.btn_undo, 2, 0)
        layout.addWidget(self.btn_redo, 2, 1)
        layout.addWidget(self.btn_clear_ref, 2, 2)
        layout.addWidget(self.btn_load_ref, 3, 0, 1, 2)
        layout.addWidget(self.btn_save_ref, 3, 2)
        layout.addWidget(self.ref_path_input, 4, 0, 1, 3)
        layout.addWidget(self.btn_load_default_ref, 5, 0, 1, 2)
        layout.addWidget(self.btn_save_default_ref, 5, 2)
        layout.addWidget(self.btn_add_extra_ref, 6, 0, 1, 2)
        layout.addWidget(self.btn_add_extra_ref_save, 6, 2)
        layout.addWidget(self.ref_status, 7, 0, 1, 3)
        group.setLayout(layout)
        self.left_layout.addWidget(group)

    def build_result_group(self):
        group = self.create_group("Result")
        layout = QVBoxLayout(group)

        self.verdict_label = QLabel("READY")
        self.verdict_label.setObjectName("verdictNeutral")
        self.verdict_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verdict_label.setMinimumHeight(52)

        self.summary_label = QLabel("Load an image and run inspection.")
        self.summary_label.setWordWrap(True)

        self.btn_select = QPushButton("Select Image")
        self.btn_select.clicked.connect(self.select_image)
        self.btn_reinspect = QPushButton("Inspect Current Image")
        self.btn_reinspect.clicked.connect(self.inspect_current_image)
        self.btn_save_annotated = QPushButton("Save Annotated Image")
        self.btn_save_annotated.clicked.connect(self.save_annotated_image)

        layout.addWidget(self.verdict_label)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.btn_select)
        layout.addWidget(self.btn_reinspect)
        layout.addWidget(self.btn_save_annotated)
        group.setLayout(layout)
        self.left_layout.addWidget(group)

    def build_production_group(self):
        group = self.create_group("Production")
        layout = QGridLayout(group)

        self.total_label = QLabel("Total: 0")
        self.pass_label = QLabel("PASS: 0")
        self.fail_label = QLabel("FAIL: 0")

        self.btn_reset_counter = QPushButton("Reset Counters")
        self.btn_reset_counter.clicked.connect(self.reset_counters)
        self.btn_export_history = QPushButton("Export History CSV")
        self.btn_export_history.clicked.connect(self.export_history_csv)

        layout.addWidget(self.total_label, 0, 0)
        layout.addWidget(self.pass_label, 0, 1)
        layout.addWidget(self.fail_label, 0, 2)
        layout.addWidget(self.btn_reset_counter, 1, 0, 1, 2)
        layout.addWidget(self.btn_export_history, 1, 2)
        group.setLayout(layout)
        self.left_layout.addWidget(group)
        self.left_layout.addStretch()

    def build_image_view(self):
        header_row = QHBoxLayout()
        header = QLabel("Inspection View")
        header.setObjectName("mainTitle")
        header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.btn_zoom_out = QPushButton("Zoom -")
        self.btn_zoom_out.clicked.connect(self.zoom_out)
        self.btn_zoom_fit = QPushButton("Fit")
        self.btn_zoom_fit.clicked.connect(self.zoom_fit)
        self.btn_zoom_in = QPushButton("Zoom +")
        self.btn_zoom_in.clicked.connect(self.zoom_in)
        self.zoom_value_label = QLabel("100%")
        self.zoom_value_label.setObjectName("zoomValue")

        header_row.addWidget(header)
        header_row.addStretch()
        header_row.addWidget(self.zoom_value_label)
        header_row.addWidget(self.btn_zoom_out)
        header_row.addWidget(self.btn_zoom_fit)
        header_row.addWidget(self.btn_zoom_in)

        self.image_scroll = QScrollArea()
        self.image_scroll.setObjectName("imageScroll")
        self.image_scroll.setWidgetResizable(False)
        self.image_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.image_display = ReferenceLabel(self)
        self.image_display.setMinimumSize(700, 430)
        self.image_display.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.image_scroll.setWidget(self.image_display)

        self.stats_label = QLabel("System ready.")
        self.stats_label.setObjectName("statusLine")

        self.right_layout.addLayout(header_row)
        self.right_layout.addWidget(self.image_scroll, 1)
        self.right_layout.addWidget(self.stats_label)

    def build_history_table(self):
        group = self.create_group("Inspection History")
        layout = QVBoxLayout(group)

        self.history_table = QTableWidget(0, 7)
        self.history_table.setHorizontalHeaderLabels(
            ["Time", "Image", "Verdict", "OK", "Missing", "Wrong", "Extra"]
        )
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        for col in [3, 4, 5, 6]:
            self.history_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setMinimumHeight(220)

        layout.addWidget(self.history_table)
        group.setLayout(layout)
        self.right_layout.addWidget(group)

    def create_group(self, title):
        group = QGroupBox(title)
        group.setObjectName("panelGroup")
        return group

    def apply_styles(self):
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #e9edf2;
                font-size: 13px;
            }
            QWidget {
                color: #1f2933;
            }
            QWidget#leftPanel {
                background: #f8fafc;
                border: 1px solid #c8d1db;
                border-radius: 8px;
            }
            QScrollArea#leftScroll {
                background: #f8fafc;
                border: 1px solid #c8d1db;
                border-radius: 8px;
            }
            QGroupBox#panelGroup {
                font-weight: 700;
                border: 1px solid #c7d0da;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 8px;
                background: #ffffff;
            }
            QGroupBox#panelGroup::title {
                left: 10px;
                padding: 0 4px;
                color: #2f3b4a;
            }
            QLabel#mainTitle {
                font-size: 20px;
                font-weight: 700;
                color: #1f2933;
                padding: 4px 2px;
            }
            QLabel#zoomValue {
                border: 1px solid #c1ccd8;
                border-radius: 6px;
                background: #ffffff;
                padding: 6px 10px;
                min-width: 54px;
                qproperty-alignment: AlignCenter;
                font-weight: 700;
            }
            QLabel {
                color: #1f2933;
            }
            QLabel#statusLine {
                background: #f7fafc;
                border: 1px solid #d2d9e2;
                border-radius: 6px;
                padding: 8px;
                font-size: 13px;
                color: #1f2933;
            }
            QLabel#statusBad {
                color: #bf1d1d;
                font-weight: 600;
            }
            QPushButton {
                border: 1px solid #9fb0c1;
                border-radius: 6px;
                background: #ffffff;
                color: #1f2933;
                padding: 7px 10px;
                font-weight: 600;
                min-height: 34px;
            }
            QPushButton:hover {
                background: #f1f5f9;
            }
            QPushButton:pressed {
                background: #dde6ee;
            }
            QPushButton:checked {
                background: #f59e0b;
                color: #111827;
                border-color: #d18a07;
            }
            QLineEdit, QComboBox, QSpinBox {
                border: 1px solid #c1ccd8;
                border-radius: 6px;
                padding: 5px 7px;
                background: #ffffff;
                color: #1f2933;
                selection-color: #ffffff;
                selection-background-color: #2563eb;
                min-height: 30px;
            }
            QLineEdit:read-only {
                background: #f3f6fa;
                color: #1f2933;
            }
            QComboBox QAbstractItemView {
                color: #1f2933;
                background: #ffffff;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
            }
            QCheckBox {
                color: #1f2933;
                spacing: 8px;
                min-height: 24px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QPushButton:disabled,
            QLineEdit:disabled,
            QComboBox:disabled,
            QSpinBox:disabled,
            QCheckBox:disabled,
            QLabel:disabled {
                color: #6b7280;
            }
            QTableWidget {
                border: 1px solid #c7d0da;
                border-radius: 6px;
                background: #ffffff;
                gridline-color: #e2e8f0;
                color: #111827;
            }
            QHeaderView::section {
                background: #eef2f7;
                border: none;
                border-right: 1px solid #dae2eb;
                padding: 6px;
                font-weight: 700;
                color: #334155;
            }
            QScrollArea#imageScroll {
                background: #f7fafc;
                border: 1px solid #d2d9e2;
                border-radius: 6px;
            }
            QLabel#verdictNeutral {
                border-radius: 8px;
                background: #9ca3af;
                color: #ffffff;
                font-size: 24px;
                font-weight: 800;
                padding: 8px;
            }
            QLabel#verdictPass {
                border-radius: 8px;
                background: #0f8a4b;
                color: #ffffff;
                font-size: 24px;
                font-weight: 800;
                padding: 8px;
            }
            QLabel#verdictFail {
                border-radius: 8px;
                background: #c62828;
                color: #ffffff;
                font-size: 24px;
                font-weight: 800;
                padding: 8px;
            }
            """
        )

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
        try:
            candidate_model = YOLO(model_path)
            names = candidate_model.names
            if not isinstance(names, dict):
                names = {idx: str(name) for idx, name in enumerate(names)}
        except Exception as exc:
            QMessageBox.critical(self, "Model Error", f"Unable to load model:\n{exc}")
            self.set_model_status("Model load failed.", ok=False)
            return

        self.model = candidate_model
        self.model_names = names
        self.current_model_path = model_path
        self.model_path_input.setText(model_path)
        self.populate_class_combo()
        self.set_model_status(f"Model loaded: {os.path.basename(model_path)}", ok=True)
        self.stats_label.setText("Model ready for inspection.")
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
            for item in payload:
                validated.append(
                    {
                        "x": int(item["x"]),
                        "y": int(item["y"]),
                        "label": str(item["label"]),
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

    def update_confidence(self, value):
        self.conf_label.setText(f"Confidence: {value}%")
        self.refresh_image()

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

    def run_inference(self, image_path, record_history=False):
        if not self.model:
            self.stats_label.setText("Model not loaded. Select and load a model file.")
            return

        conf_value = self.conf_slider.value() / 100.0
        try:
            results = self.model.predict(source=image_path, conf=conf_value, save=False, device="cpu")
        except Exception as exc:
            QMessageBox.critical(self, "Inference Error", f"Could not run inference:\n{exc}")
            return

        annotated_frame = None
        detections = []

        for result in results:
            annotated_frame = result.plot(labels=self.check_labels.isChecked())
            for box in result.boxes:
                cls_idx = int(box.cls[0])
                cls_name = str(self.model_names.get(cls_idx, cls_idx))
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
                confidence = float(box.conf[0])
                detections.append(
                    {"x": cx, "y": cy, "label": cls_name, "conf": confidence, "box": (x1, y1, x2, y2)}
                )
                if self.check_coords.isChecked():
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
            fallback = cv2.imread(image_path)
            if fallback is None:
                QMessageBox.critical(self, "Image Error", "Unable to open selected image file.")
                return
            annotated_frame = fallback

        inspection_result = self.evaluate_inspection(detections)
        self.last_inspection_result = inspection_result
        self.draw_reference_overlay(annotated_frame, inspection_result)

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

        if record_history:
            self.update_production_counters(inspection_result)
            self.append_history(image_path, inspection_result)

    def evaluate_inspection(self, detections):
        if not self.reference_points:
            return {
                "verdict": "FAIL",
                "reason": "No reference profile loaded.",
                "ok": 0,
                "missing": [],
                "wrong": [],
                "extra": detections,
                "reference_eval": [],
                "total_refs": 0,
            }

        match_dist = float(self.match_dist_spin.value())
        unmatched_det_indexes = set(range(len(detections)))
        reference_eval = []
        missing = []
        wrong = []
        ok_count = 0

        for ref in self.reference_points:
            best_idx = None
            best_dist = float("inf")
            for idx in unmatched_det_indexes:
                det = detections[idx]
                dist = math.hypot(ref["x"] - det["x"], ref["y"] - det["y"])
                if dist < best_dist:
                    best_dist = dist
                    best_idx = idx

            if best_idx is not None and best_dist <= match_dist:
                det = detections[best_idx]
                unmatched_det_indexes.remove(best_idx)
                if det["label"] == ref["label"]:
                    ok_count += 1
                    reference_eval.append({"ref": ref, "det": det, "status": "OK", "distance": best_dist})
                else:
                    wrong.append({"ref": ref, "det": det, "distance": best_dist})
                    reference_eval.append({"ref": ref, "det": det, "status": "WRONG", "distance": best_dist})
            else:
                missing.append(ref)
                reference_eval.append({"ref": ref, "det": None, "status": "MISSING", "distance": None})

        extra = [detections[idx] for idx in sorted(unmatched_det_indexes)]

        fail_reasons = []
        if missing:
            fail_reasons.append(f"Missing {len(missing)}")
        if wrong:
            fail_reasons.append(f"Wrong class {len(wrong)}")
        if self.check_fail_extra.isChecked() and extra:
            fail_reasons.append(f"Extra {len(extra)}")

        verdict = "PASS" if not fail_reasons else "FAIL"
        reason = "All expected components matched." if verdict == "PASS" else ", ".join(fail_reasons)

        return {
            "verdict": verdict,
            "reason": reason,
            "ok": ok_count,
            "missing": missing,
            "wrong": wrong,
            "extra": extra,
            "reference_eval": reference_eval,
            "total_refs": len(self.reference_points),
        }

    def draw_reference_overlay(self, frame, inspection_result):
        for entry in inspection_result["reference_eval"]:
            ref = entry["ref"]
            rx, ry = int(ref["x"]), int(ref["y"])
            status = entry["status"]
            if status == "OK":
                color = (50, 205, 50)
                label = f"{ref['label']} OK"
            elif status == "WRONG":
                color = (0, 165, 255)
                found = entry["det"]["label"] if entry["det"] else "none"
                label = f"{ref['label']}!= {found}"
            else:
                color = (0, 0, 255)
                label = f"{ref['label']} MISS"

            cv2.circle(frame, (rx, ry), 14, color, 2)
            cv2.circle(frame, (rx, ry), 3, color, -1)
            if self.check_labels.isChecked():
                cv2.putText(
                    frame,
                    label,
                    (rx + 10, ry - 8),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    color,
                    1,
                    cv2.LINE_AA,
                )

    def update_result_panel(self, inspection_result, image_path):
        verdict = inspection_result["verdict"]
        if verdict == "PASS":
            self.verdict_label.setText("PASS")
            self.verdict_label.setObjectName("verdictPass")
        elif verdict == "FAIL":
            self.verdict_label.setText("FAIL")
            self.verdict_label.setObjectName("verdictFail")
        else:
            self.verdict_label.setText(verdict)
            self.verdict_label.setObjectName("verdictNeutral")

        self.verdict_label.style().unpolish(self.verdict_label)
        self.verdict_label.style().polish(self.verdict_label)

        missing_count = len(inspection_result["missing"])
        wrong_count = len(inspection_result["wrong"])
        extra_count = len(inspection_result["extra"])
        ok_count = inspection_result["ok"]

        image_name = os.path.basename(image_path) if image_path else "-"
        self.summary_label.setText(
            f"{image_name}\n"
            f"Expected: {inspection_result['total_refs']} | OK: {ok_count} | "
            f"Missing: {missing_count} | Wrong: {wrong_count} | Extra: {extra_count}\n"
            f"Reason: {inspection_result['reason']}"
        )
        self.stats_label.setText(
            f"Inspection complete | Result: {verdict} | "
            f"Expected {inspection_result['total_refs']} / OK {ok_count} / Missing {missing_count} / Wrong {wrong_count}"
        )

    def display_cv_image(self, frame):
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, channels = rgb_frame.shape
        self.original_image_size = (w, h)
        bytes_per_line = channels * w
        image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        self.current_image_pixmap = QPixmap.fromImage(image)
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

    def update_production_counters(self, inspection_result):
        self.total_count += 1
        if inspection_result["verdict"] == "PASS":
            self.pass_count += 1
        else:
            self.fail_count += 1
        self.total_label.setText(f"Total: {self.total_count}")
        self.pass_label.setText(f"PASS: {self.pass_count}")
        self.fail_label.setText(f"FAIL: {self.fail_count}")

    def reset_counters(self):
        self.total_count = 0
        self.pass_count = 0
        self.fail_count = 0
        self.total_label.setText("Total: 0")
        self.pass_label.setText("PASS: 0")
        self.fail_label.setText("FAIL: 0")
        self.stats_label.setText("Production counters reset.")

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
        self.history_table.insertRow(0)
        values = [
            row["time"],
            row["image"],
            row["verdict"],
            str(row["ok"]),
            str(row["missing"]),
            str(row["wrong"]),
            str(row["extra"]),
        ]
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            if col == 2:
                if value == "PASS":
                    item.setBackground(Qt.GlobalColor.darkGreen)
                    item.setForeground(Qt.GlobalColor.white)
                else:
                    item.setBackground(Qt.GlobalColor.darkRed)
                    item.setForeground(Qt.GlobalColor.white)
            self.history_table.setItem(0, col, item)

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
                            row["source_path"],
                            row["model"],
                        ]
                    )
        except Exception:
            self.stats_label.setText("Inspection completed, but auto-log write failed.")

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
                            row["source_path"],
                            row["model"],
                        ]
                    )
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", f"Could not export CSV:\n{exc}")
            return
        self.stats_label.setText(f"History exported: {os.path.basename(export_path)}")

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
            return
        self.stats_label.setText(f"Annotated image saved: {os.path.basename(out_path)}")

    def resizeEvent(self, event):
        self.scale_image_to_label()
        super().resizeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DefectDetectionGUI()
    window.show()
    sys.exit(app.exec())
