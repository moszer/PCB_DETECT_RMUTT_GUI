"""AOI stage, camera and per-position inspection workspace."""
import json
import math
import os
import time
from datetime import datetime
from pathlib import Path
from threading import Lock

import cv2
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMenu, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from .aoi_motion import MotionClient, SimulatedTransport, raster_points
from .components import CollapsibleCard
from .inspection_logic import (
    draw_detections_overlay,
    draw_multiframe_overlay,
    evaluate_inspection,
    evaluate_multiframe_round,
    match_frame_detections,
    slot_status,
    box_iou,
)
from .mixins.inspection_mixin import InferenceWorker
from .inference_runtime import select_device


class AOICamera(QThread):
    failed = pyqtSignal(str)

    def __init__(self, index, resolution):
        super().__init__()
        self.index, self.resolution = index, resolution
        self.lock = Lock()
        self.latest = None

    def snapshot(self):
        with self.lock:
            return self.latest

    def run(self):
        cap = None
        try:
            cap = cv2.VideoCapture(self.index)
            try:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            except Exception:
                pass
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not cap.isOpened():
                raise IOError("Camera could not be opened")
            while not self.isInterruptionRequested():
                started = time.monotonic()
                ok, frame = cap.read()
                if not ok:
                    raise IOError("Camera disconnected")
                with self.lock:
                    # Timestamp before read: never label a pre-move frame as fresh.
                    self.latest = (started, frame)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            if cap is not None:
                cap.release()


class AOIInference(InferenceWorker):
    frame_progress = pyqtSignal(int, int, list, list)  # frame_num, target_frames, current_detections, hits

    def __init__(
        self,
        model,
        image_path,
        conf_value,
        model_names,
        device_preference="auto",
        target_frames=1,
        pass_threshold=None,
        camera=None,
        zoom=1.0,
        crop_func=None,
        expected_components=None,
        imgsz=None,
    ):
        super().__init__(model, image_path, conf_value, model_names, device_preference, imgsz=imgsz)
        self.target_frames = max(1, target_frames or 1)
        self.pass_threshold = pass_threshold
        self.camera = camera
        self.zoom = zoom
        self.crop_func = crop_func
        self.expected_components = expected_components or []
        self.multiframe_result = None

    def run(self):
        # Also catch decoding/postprocessing failures outside the base predict try.
        try:
            device = select_device(self.device_preference)
            self.device_selected.emit(device.label, device.detail)
            predict_kwargs = {
                "conf": self.conf_value,
                "save": False,
                "device": device.device,
            }
            if self.imgsz:
                predict_kwargs["imgsz"] = int(self.imgsz)
            results = self.model.predict(
                source=self.image_path, **predict_kwargs
            )
            base_frame = None
            detections = []
            speed = {"preprocess": 0.0, "inference": 0.0, "postprocess": 0.0}

            for result in results:
                base_frame = result.orig_img.copy()
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

            if base_frame is None:
                fallback = cv2.imread(self.image_path)
                if fallback is None:
                    self.error.emit("Unable to open selected image file.")
                    return
                base_frame = fallback

            all_frames_detections = [detections]

            if self.target_frames > 1:
                hits = [0] * len(self.expected_components)
                if self.expected_components:
                    m1 = match_frame_detections(self.expected_components, detections)
                    for ei in m1["matched_expected"]:
                        hits[ei] += 1
                    self.frame_progress.emit(1, self.target_frames, detections, list(hits))

                for frame_i in range(2, self.target_frames + 1):
                    time.sleep(0.04)
                    next_frame = None
                    if self.camera and self.camera.isRunning():
                        snap = self.camera.snapshot()
                        if snap is not None:
                            _, raw = snap
                            if raw is not None:
                                next_frame = self.crop_func(raw, self.zoom) if (self.zoom > 1.01 and self.crop_func) else raw.copy()
                    if next_frame is None:
                        next_frame = base_frame.copy()

                    frame_path = Path(self.image_path).parent / f"{Path(self.image_path).stem}_f{frame_i:02d}.png"
                    cv2.imwrite(str(frame_path), next_frame)

                    f_results = self.model.predict(
                        source=str(frame_path), **predict_kwargs
                    )
                    f_dets = []
                    for r in f_results:
                        for k in speed:
                            speed[k] += r.speed.get(k, 0.0)
                        for box in r.boxes:
                            cls_idx = int(box.cls[0])
                            cls_name = str(self.model_names.get(cls_idx, cls_idx))
                            x1, y1, x2, y2 = box.xyxy[0].tolist()
                            cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
                            f_dets.append(
                                {"x": cx, "y": cy, "label": cls_name, "conf": float(box.conf[0]), "box": (x1, y1, x2, y2)}
                            )
                    all_frames_detections.append(f_dets)

                    if self.expected_components:
                        m_k = match_frame_detections(self.expected_components, f_dets)
                        for ei in m_k["matched_expected"]:
                            hits[ei] += 1
                        self.frame_progress.emit(frame_i, self.target_frames, f_dets, list(hits))

                for k in speed:
                    speed[k] /= self.target_frames

            if self.expected_components and self.target_frames > 1:
                self.multiframe_result = evaluate_multiframe_round(
                    self.expected_components,
                    all_frames_detections,
                    target_frames=self.target_frames,
                    pass_threshold=self.pass_threshold
                )

            self.finished.emit(detections, base_frame, speed)
        except Exception as exc:
            self.error.emit(str(exc))



class Full4KViewerDialog(QDialog):
    """High-resolution 4K image viewer with zoom in/out, fit to window, and 100% 1:1 pixel view."""
    def __init__(self, image_path_or_rgb, title="4K Full View", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"AOI 4K High-Resolution Viewer — {title}")
        self.resize(1120, 760)
        self.setStyleSheet("""
            QDialog { background: #080f1a; color: #f1f5f9; }
            QPushButton {
                background: #1e293b; border: 1px solid #334155; border-radius: 6px;
                color: #f1f5f9; padding: 5px 12px; font-weight: 600; font-size: 11px;
            }
            QPushButton:hover { background: #334155; border-color: #38bdf8; }
            QLabel { color: #cbd5e1; }
        """)

        if isinstance(image_path_or_rgb, (str, Path)):
            self.pixmap = QPixmap(str(image_path_or_rgb))
        else:
            rgb = image_path_or_rgb
            image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()
            self.pixmap = QPixmap.fromImage(image)

        self.scale_factor = 1.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        # Top Bar
        top_bar = QHBoxLayout()
        w, h = self.pixmap.width(), self.pixmap.height()
        res_lbl = QLabel(f"📷 ความละเอียดภาพ: {w} × {h} พิกเซล (4K UHD แท้ 100%)")
        res_lbl.setStyleSheet("color: #10b981; font-weight: 700; font-size: 12px;")
        top_bar.addWidget(res_lbl, 1)

        btn_fit = QPushButton("พอดีจอ (Fit)")
        btn_fit.clicked.connect(self.zoom_fit)
        top_bar.addWidget(btn_fit)

        btn_100 = QPushButton("ขนาดจริง 100% (1:1 4K)")
        btn_100.setStyleSheet("background: #0284c7; color: white; border: 1px solid #38bdf8;")
        btn_100.clicked.connect(self.zoom_100)
        top_bar.addWidget(btn_100)

        btn_in = QPushButton("Zoom In (+)")
        btn_in.clicked.connect(lambda: self.adjust_zoom(1.25))
        top_bar.addWidget(btn_in)

        btn_out = QPushButton("Zoom Out (−)")
        btn_out.clicked.connect(lambda: self.adjust_zoom(0.8))
        top_bar.addWidget(btn_out)

        self.zoom_lbl = QLabel("100%")
        self.zoom_lbl.setStyleSheet("color: #38bdf8; font-weight: 700; min-width: 50px;")
        top_bar.addWidget(self.zoom_lbl)

        btn_close = QPushButton("ปิดหน้าต่าง")
        btn_close.clicked.connect(self.close)
        top_bar.addWidget(btn_close)
        layout.addLayout(top_bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("background: #020617; border: 1px solid #1e293b; border-radius: 8px;")
        self.img_lbl = QLabel()
        self.img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_lbl.setPixmap(self.pixmap)
        self.scroll.setWidget(self.img_lbl)
        layout.addWidget(self.scroll, 1)

        QTimer.singleShot(60, self.zoom_fit)

    def zoom_fit(self):
        viewport_size = self.scroll.viewport().size()
        scale_w = viewport_size.width() / max(1, self.pixmap.width())
        scale_h = viewport_size.height() / max(1, self.pixmap.height())
        self.scale_factor = min(scale_w, scale_h)
        self._apply_zoom()

    def zoom_100(self):
        self.scale_factor = 1.0
        self._apply_zoom()

    def adjust_zoom(self, factor):
        self.scale_factor = max(0.1, min(5.0, self.scale_factor * factor))
        self._apply_zoom()

    def _apply_zoom(self):
        new_w = max(10, int(self.pixmap.width() * self.scale_factor))
        new_h = max(10, int(self.pixmap.height() * self.scale_factor))
        scaled = self.pixmap.scaled(new_w, new_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.img_lbl.setPixmap(scaled)
        self.img_lbl.resize(new_w, new_h)
        self.zoom_lbl.setText(f"{int(self.scale_factor * 100)}%")


class AOIDialog(QDialog):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.setWindowTitle("PCB Inspect — AOI Scan")
        self.resize(1150, 820)
        self.setMinimumSize(880, 560)
        self.machine = self.camera = self.inference = None
        self.active = self.closing = False
        self.phase = "idle"
        self.profile = None
        self.report = None
        self.point_index = 0
        self.viewed_point_index = 0
        self._filmstrip_cards = []
        self.marked_points = []
        self.marked_references = {}
        self.scan_mode = "grid"
        self.current_live_zoom = 1.0
        self._raw_live_frame = None
        self.view_mode = "dual"
        self.last_preview = 0
        self._ports_initialized = False
        self.endpoint = ""
        self.aspect_mode = "1:1"
        self._build_ui()
        self._update_resolution_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)
        self.refresh_ports()
        self.refresh_available_models(initial=True)
        self._controls()

    def button(self, text, callback, layout=None):
        button = QPushButton(text)
        button.setAutoDefault(False)
        button.setObjectName("ghostBtn")
        button.clicked.connect(callback)
        if layout is not None:
            layout.addWidget(button)
        return button

    def number(self, value, maximum=1000, decimals=2):
        field = QDoubleSpinBox()
        field.setDecimals(decimals)
        field.setRange(0, maximum)
        field.setValue(value)
        return field

    def _build_ui(self):
        self.setStyleSheet("""
            QDialog {
                background: #0f172a;
                color: #f1f5f9;
            }
            QGroupBox {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 10px;
                margin-top: 14px;
                padding: 14px 10px 10px 10px;
                font-weight: 700;
                font-size: 12px;
                color: #38bdf8;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 12px;
                padding: 1px 8px;
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 4px;
                color: #38bdf8;
                font-size: 11px;
                font-weight: 700;
            }
            QLabel {
                color: #cbd5e1;
                font-size: 12px;
            }
            QComboBox, QSpinBox, QDoubleSpinBox {
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px 8px;
                color: #f1f5f9;
                font-size: 12px;
                min-height: 24px;
            }
            QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
                border-color: #38bdf8;
            }
            QComboBox::drop-down {
                border: none;
            }
            QPushButton {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 6px;
                color: #f1f5f9;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #334155;
                border-color: #38bdf8;
            }
            QPushButton:disabled {
                background: #0f172a;
                border-color: #1e293b;
                color: #475569;
            }
            QPushButton#primaryBtn {
                background: #0d9488;
                border: 1px solid #14b8a6;
                color: #ffffff;
                font-weight: 700;
                font-size: 13px;
                border-radius: 8px;
                padding: 8px 18px;
            }
            QPushButton#primaryBtn:hover {
                background: #0f766e;
                border-color: #2dd4bf;
            }
            QPushButton#primaryBtn:disabled {
                background: #132a2a;
                border-color: #1c3c3c;
                color: #436d6d;
            }
            QTableWidget {
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 8px;
                gridline-color: #1e293b;
                color: #cbd5e1;
                font-size: 12px;
            }
            QHeaderView::section {
                background: #1e293b;
                color: #94a3b8;
                font-weight: 700;
                padding: 6px;
                border: none;
                border-bottom: 1px solid #334155;
            }
            QProgressBar {
                background: #0f172a;
                border: 1px solid #334155;
                border-radius: 6px;
                text-align: center;
                color: #f1f5f9;
                font-size: 11px;
                font-weight: 700;
                height: 18px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0d9488, stop:1 #38bdf8);
                border-radius: 5px;
            }
            /* Splitters */
            QSplitter::handle {
                background: #1e293b;
                border-radius: 2px;
            }
            QSplitter::handle:hover {
                background: #0284c7;
            }
            QSplitter::handle:horizontal {
                width: 6px;
                margin: 4px 1px;
            }
            QSplitter::handle:vertical {
                height: 6px;
                margin: 1px 4px;
            }
            /* Collapsible Cards */
            QFrame#collapseCard {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 10px;
            }
            QPushButton#collapseHeader {
                background: #1e293b;
                border: none;
                border-radius: 10px;
                color: #38bdf8;
                font-size: 12px;
                font-weight: 700;
                text-align: left;
                padding: 10px 14px;
                min-height: 20px;
            }
            QPushButton#collapseHeader:hover {
                background: #28374f;
                color: #7dd3fc;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # ── Compact Header & Top Status ──
        header = QHBoxLayout()
        header.setSpacing(10)

        title_box = QHBoxLayout()
        title_box.setSpacing(8)
        title = QLabel("AOI Optical Inspection")
        title.setStyleSheet("font-size: 16px; font-weight: 800; color: #f8fafc;")
        title_box.addWidget(title)

        tag = QLabel("RMUTT v2.0")
        tag.setStyleSheet("font-size: 10px; color: #38bdf8; font-weight: 700; background: #0f172a; border: 1px solid #1e293b; border-radius: 4px; padding: 2px 6px;")
        title_box.addWidget(tag)
        header.addLayout(title_box, 1)

        self.conn_badge = QLabel("● DISCONNECTED")
        self.conn_badge.setStyleSheet("background: #2a1215; color: #ef4444; border: 1px solid #7f1d1d; border-radius: 6px; padding: 4px 10px; font-weight: 700; font-size: 11px;")
        header.addWidget(self.conn_badge)

        self.lbl_model_badge = QLabel("● NO MODEL")
        self.lbl_model_badge.setStyleSheet("background: #2a1215; color: #ef4444; border: 1px solid #7f1d1d; border-radius: 6px; padding: 4px 10px; font-weight: 700; font-size: 11px;")
        header.addWidget(self.lbl_model_badge)

        self.advanced_btn = QPushButton("⚙️ ตั้งค่าเพิ่มเติม ▼")
        self.advanced_btn.setAutoDefault(False)
        self.advanced_btn.setCheckable(True)
        self.advanced_btn.setStyleSheet("padding: 4px 10px; font-size: 11px; font-weight: 600; background: #1e293b; color: #94a3b8; border: 1px solid #334155; border-radius: 6px;")
        self.advanced_btn.toggled.connect(self._toggle_advanced_drawer)
        header.addWidget(self.advanced_btn)
        root.addLayout(header)

        # ── Step 1 & 2 Unified: Single Compact Control Bar (Machine + Model + imgsz + Stop) ──
        top_bar = QFrame()
        top_bar.setStyleSheet("background: #1e293b; border: 1px solid #334155; border-radius: 8px;")
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(10, 6, 10, 6)
        top_bar_layout.setSpacing(8)

        lbl_m_sec = QLabel("เครื่อง:")
        lbl_m_sec.setStyleSheet("color: #38bdf8; font-weight: 700; font-size: 11px;")
        top_bar_layout.addWidget(lbl_m_sec)

        self.mode = QComboBox()
        self.mode.addItems(["Simulation (No hardware)", "Serial (Nano v2 · 9600)"])
        self.mode.setStyleSheet("font-size: 11px; font-weight: 600; min-width: 140px;")
        top_bar_layout.addWidget(self.mode)

        self.connect_btn = self.button("Connect", self.connect_machine, top_bar_layout)
        self.connect_btn.setStyleSheet("font-size: 11px; font-weight: 700; padding: 4px 10px;")

        self.home_btn = self.button("⌂ HOME", lambda: self.command("HOME"), top_bar_layout)
        self.home_btn.setStyleSheet("font-size: 11px; font-weight: 700; padding: 4px 10px;")

        # Divider line
        div1 = QFrame()
        div1.setFrameShape(QFrame.Shape.VLine)
        div1.setStyleSheet("color: #334155; max-height: 20px;")
        top_bar_layout.addWidget(div1)

        lbl_ai_sec = QLabel("โมเดล AI:")
        lbl_ai_sec.setStyleSheet("color: #10b981; font-weight: 700; font-size: 11px;")
        top_bar_layout.addWidget(lbl_ai_sec)

        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(180)
        self.model_combo.setStyleSheet("font-size: 11px; font-weight: 600;")
        self.model_combo.currentIndexChanged.connect(self._on_model_combo_changed)
        top_bar_layout.addWidget(self.model_combo, 1)

        self.btn_browse_folder = QPushButton("📂 โฟลเดอร์")
        self.btn_browse_folder.setAutoDefault(False)
        self.btn_browse_folder.setToolTip("เลือกโฟลเดอร์ที่เก็บโมเดล YOLO (สแกนหาไฟล์ .pt ทั้งหมดในโฟลเดอร์และโฟลเดอร์ย่อย)")
        self.btn_browse_folder.setStyleSheet("font-size: 11px; font-weight: 700; padding: 4px 8px; background: #0f2a22; color: #10b981; border: 1px solid #059669; border-radius: 6px;")
        self.btn_browse_folder.clicked.connect(self.browse_model_folder)
        top_bar_layout.addWidget(self.btn_browse_folder)

        self.btn_browse_model = QPushButton("📁 เลือกไฟล์")
        self.btn_browse_model.setAutoDefault(False)
        self.btn_browse_model.setToolTip("เลือกไฟล์โมเดล (.pt) เปิดไปยังโฟลเดอร์โมเดลโดยตรง")
        self.btn_browse_model.setStyleSheet("font-size: 11px; font-weight: 700; padding: 4px 8px; background: #1e3a5f; color: #38bdf8; border: 1px solid #0284c7; border-radius: 6px;")
        self.btn_browse_model.clicked.connect(self.browse_model)
        top_bar_layout.addWidget(self.btn_browse_model)

        lbl_res_sec = QLabel("imgsz:")
        lbl_res_sec.setStyleSheet("color: #38bdf8; font-weight: 700; font-size: 11px;")
        top_bar_layout.addWidget(lbl_res_sec)

        self.aoi_imgsz_combo = QComboBox()
        self.aoi_imgsz_combo.addItem("640 · เร็ว (640×640)", 640)
        self.aoi_imgsz_combo.addItem("960 · ปานกลาง (960×960)", 960)
        self.aoi_imgsz_combo.addItem("1280 · คมชัดสูง (1280×1280)", 1280)
        self.aoi_imgsz_combo.addItem("1600 · ละเอียดมาก (1600×1600)", 1600)
        self.aoi_imgsz_combo.addItem("1920 · Full HD (1920×1920)", 1920)
        self.aoi_imgsz_combo.addItem("2560 · 2K QHD (2560×2560)", 2560)
        self.aoi_imgsz_combo.addItem("3840 · 4K Native (3840×3840)", 3840)
        host_sz = getattr(self.host, "_detect_imgsz", 640)
        sz_idx = self.aoi_imgsz_combo.findData(host_sz)
        if sz_idx >= 0:
            self.aoi_imgsz_combo.setCurrentIndex(sz_idx)
        else:
            self.aoi_imgsz_combo.setCurrentIndex(0)
        self.aoi_imgsz_combo.currentIndexChanged.connect(self._on_aoi_imgsz_changed)
        self.aoi_imgsz_combo.setToolTip("ความละเอียดภาพสด (Live Camera) และภาพบันทึกผลลัพธ์ (Output Result) จะปรับตามค่านี้ทั้งหมด")
        self.aoi_imgsz_combo.setStyleSheet("font-size: 11px; font-weight: 600; color: #38bdf8; min-width: 135px;")
        top_bar_layout.addWidget(self.aoi_imgsz_combo)

        self.stop_btn = QPushButton("⛔ STOP")
        self.stop_btn.setAutoDefault(False)
        self.stop_btn.clicked.connect(self.stop)
        self.stop_btn.setStyleSheet("background: #b91c1c; color: white; font-weight: 800; padding: 5px 14px; border: 1px solid #ef4444; border-radius: 6px; font-size: 11px;")
        top_bar_layout.addWidget(self.stop_btn)

        root.addWidget(top_bar)

        # ── Collapsible Advanced Settings Drawer (Hidden by default) ──
        self.advanced_drawer = QFrame()
        self.advanced_drawer.setStyleSheet("background: #0f172a; border: 1px solid #1e293b; border-radius: 8px;")
        drawer_vbox = QVBoxLayout(self.advanced_drawer)
        drawer_vbox.setContentsMargins(10, 8, 10, 8)
        drawer_vbox.setSpacing(6)

        # Drawer Row 1: Hardware detailed settings
        dr_row1 = QHBoxLayout()
        dr_row1.setSpacing(8)

        lbl_port = QLabel("พอร์ต USB:")
        lbl_port.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600;")
        dr_row1.addWidget(lbl_port)

        self.port = QComboBox()
        self.port.setStyleSheet("font-size: 11px;")
        dr_row1.addWidget(self.port, 1)

        self.refresh_btn = self.button("Refresh", self.refresh_ports, dr_row1)
        self.off_btn = self.button("Motors OFF", lambda: self.command("OFF"), dr_row1)

        self.log_btn = QPushButton("Show Log")
        self.log_btn.setAutoDefault(False)
        self.log_btn.setCheckable(True)
        self.log_btn.setStyleSheet("padding: 4px 8px; font-size: 11px;")
        dr_row1.addWidget(self.log_btn)

        self.position_label = QLabel("Machine disconnected")
        self.position_label.setStyleSheet("color: #e2e8f0; font-weight: 600; font-size: 11px; background: #080f1a; border: 1px solid #334155; border-radius: 4px; padding: 3px 8px;")
        dr_row1.addWidget(self.position_label)
        drawer_vbox.addLayout(dr_row1)

        # Drawer Row 2: AI details & Inference controls
        dr_row2 = QHBoxLayout()
        dr_row2.setSpacing(8)

        self.btn_open_model_folder = QPushButton("🔍 เปิดโฟลเดอร์ใน Finder")
        self.btn_open_model_folder.setAutoDefault(False)
        self.btn_open_model_folder.setToolTip("เปิดตำแหน่งโฟลเดอร์โมเดลใน Finder")
        self.btn_open_model_folder.setStyleSheet("font-size: 11px; font-weight: 600; padding: 4px 8px; background: #1e293b; color: #38bdf8; border: 1px solid #334155; border-radius: 6px;")
        self.btn_open_model_folder.clicked.connect(self.open_model_folder)
        dr_row2.addWidget(self.btn_open_model_folder)

        self.btn_refresh_models = QPushButton("🔄 รีเฟรช")
        self.btn_refresh_models.setAutoDefault(False)
        self.btn_refresh_models.setStyleSheet("font-size: 11px; padding: 4px 8px; border-radius: 6px;")
        self.btn_refresh_models.clicked.connect(lambda: self.refresh_available_models(initial=False))
        dr_row2.addWidget(self.btn_refresh_models)

        lbl_dev = QLabel("Processor:")
        lbl_dev.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600;")
        dr_row2.addWidget(lbl_dev)

        self.aoi_device_combo = QComboBox()
        self.aoi_device_combo.addItem("Auto (Best)", "auto")
        self.aoi_device_combo.addItem("Apple MPS", "mps")
        self.aoi_device_combo.addItem("CUDA GPU", "cuda")
        self.aoi_device_combo.addItem("CPU", "cpu")
        if hasattr(self.host, "device_combo"):
            d_idx = self.aoi_device_combo.findData(self.host.device_combo.currentData())
            if d_idx >= 0:
                self.aoi_device_combo.setCurrentIndex(d_idx)
        self.aoi_device_combo.currentIndexChanged.connect(self._on_aoi_device_changed)
        self.aoi_device_combo.setStyleSheet("font-size: 11px;")
        dr_row2.addWidget(self.aoi_device_combo)

        lbl_cf = QLabel("Conf:")
        lbl_cf.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600;")
        dr_row2.addWidget(lbl_cf)

        self.aoi_conf_spin = QSpinBox()
        self.aoi_conf_spin.setRange(5, 95)
        self.aoi_conf_spin.setValue(self.host.conf_slider.value() if hasattr(self.host, "conf_slider") else 25)
        self.aoi_conf_spin.setSuffix("%")
        self.aoi_conf_spin.valueChanged.connect(self._on_aoi_conf_changed)
        self.aoi_conf_spin.setStyleSheet("font-weight: 700; font-size: 11px; max-width: 60px;")
        dr_row2.addWidget(self.aoi_conf_spin)

        self.lbl_imgsz_hint = QLabel("⚡ 640px: ค่ามาตรฐาน")
        self.lbl_imgsz_hint.setStyleSheet("color: #64748b; font-size: 10px; font-weight: 500;")
        dr_row2.addWidget(self.lbl_imgsz_hint, 1)
        drawer_vbox.addLayout(dr_row2)

        # Drawer Row 3: Status hint
        self.status = QLabel("Click Connect → HOME to initialize XY stage.")
        self.status.setStyleSheet("color: #94a3b8; font-size: 11px; padding-left: 2px;")
        self.status.setWordWrap(True)
        drawer_vbox.addWidget(self.status)

        # Drawer Row 4: Wire Log (Toggled by self.log_btn)
        self.wire_log = QPlainTextEdit()
        self.wire_log.setReadOnly(True)
        self.wire_log.setMaximumBlockCount(250)
        self.wire_log.setMaximumHeight(85)
        self.wire_log.setStyleSheet("background: #080f1a; border: 1px solid #1e2e4a; color: #38bdf8; font-family: monospace; font-size: 11px;")
        self.wire_log.hide()
        self.log_btn.toggled.connect(self.wire_log.setVisible)
        drawer_vbox.addWidget(self.wire_log)

        self.advanced_drawer.hide()
        root.addWidget(self.advanced_drawer)

        # ── Main Body (Left Settings Tabs & Right Viewport) ──
        self.settings = QTabWidget()
        self.settings.setMinimumWidth(320)
        self.settings.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #1e293b;
                border-radius: 8px;
                background: #080f1a;
                margin-top: -1px;
            }
            QTabBar::tab {
                background: #0f172a;
                color: #94a3b8;
                padding: 8px 10px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                border: 1px solid #1e293b;
                border-bottom: none;
                font-weight: 700;
                font-size: 11px;
            }
            QTabBar::tab:selected {
                background: #080f1a;
                color: #38bdf8;
                border: 1px solid #1e293b;
                border-bottom: 2px solid #38bdf8;
            }
            QTabBar::tab:hover:!selected {
                background: #1e293b;
                color: #e2e8f0;
            }
        """)

        # ── Tab 1: Point Marking & Teaching (📍 มาร์คจุด) ──
        mark_tab = QWidget()
        mark_layout = QVBoxLayout(mark_tab)
        mark_layout.setContentsMargins(12, 12, 12, 12)
        mark_layout.setSpacing(10)

        mark_hdr_row = QHBoxLayout()
        lbl_mark_t = QLabel("📌 มาร์คตำแหน่งตรวจสอบ")
        lbl_mark_t.setStyleSheet("color: #38bdf8; font-weight: 700; font-size: 12px;")
        mark_hdr_row.addWidget(lbl_mark_t, 1)

        self.lbl_mark_count = QLabel("ยังไม่มีจุดที่มาร์คไว้ (0 จุด)")
        self.lbl_mark_count.setStyleSheet("color: #94a3b8; font-size: 11px;")
        mark_hdr_row.addWidget(self.lbl_mark_count)
        mark_layout.addLayout(mark_hdr_row)

        # Live Camera Zoom for Marking Each Point
        zoom_mark_row = QHBoxLayout()
        zoom_mark_row.setSpacing(4)
        lbl_zm = QLabel("🔍 ระดับซูมจุดนี้:")
        lbl_zm.setStyleSheet("color: #cbd5e1; font-weight: 600; font-size: 11px;")
        zoom_mark_row.addWidget(lbl_zm)

        self.live_zoom_spin = QDoubleSpinBox()
        self.live_zoom_spin.setRange(1.0, 5.0)
        self.live_zoom_spin.setSingleStep(0.2)
        self.live_zoom_spin.setDecimals(1)
        self.live_zoom_spin.setValue(1.0)
        self.live_zoom_spin.setSuffix("x")
        self.live_zoom_spin.setStyleSheet("font-weight: 700; font-size: 12px; min-width: 62px;")
        self.live_zoom_spin.valueChanged.connect(self._on_live_zoom_changed)
        zoom_mark_row.addWidget(self.live_zoom_spin)

        for z_val in (1.0, 1.5, 2.0, 3.0):
            z_btn = QPushButton(f"{z_val:.1f}x")
            z_btn.setAutoDefault(False)
            z_btn.setFixedWidth(36)
            z_btn.setStyleSheet("padding: 3px 2px; font-size: 10px; font-weight: 600;")
            z_btn.clicked.connect(lambda _, val=z_val: self.live_zoom_spin.setValue(val))
            zoom_mark_row.addWidget(z_btn)
        mark_layout.addLayout(zoom_mark_row)

        # Primary Action: Mark Point
        self.btn_mark_point = QPushButton("➕ มาร์คจุดนี้ (ถ่ายภาพต้นฉบับ)")
        self.btn_mark_point.setAutoDefault(False)
        self.btn_mark_point.setStyleSheet("background: #0284c7; color: white; font-weight: 700; font-size: 12px; padding: 9px 12px; border-radius: 6px;")
        self.btn_mark_point.clicked.connect(self.mark_current_point)
        mark_layout.addWidget(self.btn_mark_point)

        # Sub-actions
        ref_btn_row = QHBoxLayout()
        ref_btn_row.setSpacing(4)
        self.btn_view_ref = QPushButton("👁 ดูภาพต้นฉบับ")
        self.btn_view_ref.setAutoDefault(False)
        self.btn_view_ref.setStyleSheet("background: #1e293b; color: #10b981; font-size: 11px; padding: 6px; border-radius: 5px; border: 1px solid #059669;")
        self.btn_view_ref.clicked.connect(self.view_selected_point_reference)
        ref_btn_row.addWidget(self.btn_view_ref, 1)

        self.btn_update_zoom = QPushButton("🔄 อัปเดตซูมให้จุดนี้")
        self.btn_update_zoom.setAutoDefault(False)
        self.btn_update_zoom.setStyleSheet("background: #1e293b; color: #38bdf8; font-size: 11px; padding: 6px; border-radius: 5px; border: 1px solid #334155;")
        self.btn_update_zoom.clicked.connect(self.update_selected_point_zoom)
        ref_btn_row.addWidget(self.btn_update_zoom, 1)
        mark_layout.addLayout(ref_btn_row)

        del_btn_row = QHBoxLayout()
        del_btn_row.setSpacing(4)
        self.btn_delete_point_tab = QPushButton("🗑 ลบจุดที่เลือก")
        self.btn_delete_point_tab.setAutoDefault(False)
        self.btn_delete_point_tab.setToolTip("ลบจุดที่เลือกในตารางหรือแกลเลอรี")
        self.btn_delete_point_tab.setStyleSheet("background: #2a1215; color: #ef4444; border: 1px solid #7f1d1d; font-size: 11px; padding: 6px; border-radius: 6px; font-weight: 600;")
        self.btn_delete_point_tab.clicked.connect(lambda: self.delete_selected_point())
        del_btn_row.addWidget(self.btn_delete_point_tab, 1)

        self.btn_remove_mark = QPushButton("↩ ลบล่าสุด")
        self.btn_remove_mark.setAutoDefault(False)
        self.btn_remove_mark.setStyleSheet("background: #1e293b; color: #cbd5e1; font-size: 11px; padding: 6px; border-radius: 6px;")
        self.btn_remove_mark.clicked.connect(self.remove_last_marked_point)
        del_btn_row.addWidget(self.btn_remove_mark, 1)

        self.btn_clear_marks = QPushButton("🗑 ล้างหมด")
        self.btn_clear_marks.setAutoDefault(False)
        self.btn_clear_marks.setStyleSheet("background: #1e293b; color: #ef4444; font-size: 11px; padding: 6px; border-radius: 6px;")
        self.btn_clear_marks.clicked.connect(self.clear_marked_points)
        del_btn_row.addWidget(self.btn_clear_marks, 1)
        mark_layout.addLayout(del_btn_row)

        # Multi-frame Completeness Box
        mf_frame = QFrame()
        mf_frame.setStyleSheet("""
            QFrame {
                background: #0f172a;
                border: 1px solid #1e293b;
                border-radius: 8px;
                padding: 6px;
            }
        """)
        mf_layout = QVBoxLayout(mf_frame)
        mf_layout.setContentsMargins(8, 8, 8, 8)
        mf_layout.setSpacing(6)

        mf_header = QHBoxLayout()
        self.check_multiframe = QCheckBox("ตรวจ Component ครบ (Multi-frame)")
        self.check_multiframe.setChecked(True)
        self.check_multiframe.setStyleSheet("font-weight: 700; font-size: 11px; color: #38bdf8;")
        self.check_multiframe.toggled.connect(self._on_multiframe_toggled)
        mf_header.addWidget(self.check_multiframe, 1)

        self.lbl_mf_badge = QLabel("10F")
        self.lbl_mf_badge.setStyleSheet("background: rgba(14, 165, 233, 0.15); color: #38bdf8; font-weight: 700; font-size: 10px; padding: 2px 6px; border-radius: 4px; border: 1px solid rgba(14, 165, 233, 0.3);")
        mf_header.addWidget(self.lbl_mf_badge)
        mf_layout.addLayout(mf_header)

        self.lbl_mf_stats = QLabel("ตรวจเฉลี่ย: 10 เฟรม · เกณฑ์ผ่าน ≥ 8/10 (80%)")
        self.lbl_mf_stats.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 600;")
        mf_layout.addWidget(self.lbl_mf_stats)

        lbl_presets = QLabel("ระยะเวลาตรวจ (PRESETS):")
        lbl_presets.setStyleSheet("color: #64748b; font-size: 9px; font-weight: 700;")
        mf_layout.addWidget(lbl_presets)

        preset_grid = QGridLayout()
        preset_grid.setSpacing(4)
        preset_btns = [
            (3, "3F (ด่วน)"),
            (5, "5F (เร็ว)"),
            (10, "10F (แนะนำ)"),
            (15, "15F (ละเอียด)"),
            (20, "20F (เสถียร)"),
            (30, "30F (สูงสุด)"),
        ]
        self._mf_preset_buttons = []
        for idx, (frames, label) in enumerate(preset_btns):
            p_btn = QPushButton(label)
            p_btn.setAutoDefault(False)
            p_btn.setStyleSheet("padding: 4px 2px; font-size: 10px; font-weight: 600; background: #1e293b; color: #cbd5e1; border-radius: 4px;")
            p_btn.clicked.connect(lambda _, f=frames: self._apply_multiframe_preset(f))
            preset_grid.addWidget(p_btn, idx // 3, idx % 3)
            self._mf_preset_buttons.append((frames, p_btn))
        mf_layout.addLayout(preset_grid)

        stepper_row = QHBoxLayout()
        stepper_row.setSpacing(6)
        lbl_step = QLabel("จำนวนเฟรม:")
        lbl_step.setStyleSheet("color: #cbd5e1; font-size: 10px;")
        stepper_row.addWidget(lbl_step)

        self.multiframe_spin = QSpinBox()
        self.multiframe_spin.setRange(1, 50)
        self.multiframe_spin.setValue(10)
        self.multiframe_spin.setStyleSheet("font-weight: 700; font-size: 11px;")
        self.multiframe_spin.valueChanged.connect(self._on_multiframe_settings_changed)
        stepper_row.addWidget(self.multiframe_spin)

        lbl_ratio = QLabel("เกณฑ์ผ่าน:")
        lbl_ratio.setStyleSheet("color: #cbd5e1; font-size: 10px;")
        stepper_row.addWidget(lbl_ratio)

        self.pass_ratio_spin = QSpinBox()
        self.pass_ratio_spin.setRange(50, 100)
        self.pass_ratio_spin.setValue(80)
        self.pass_ratio_spin.setSuffix("%")
        self.pass_ratio_spin.setStyleSheet("font-weight: 700; font-size: 11px;")
        self.pass_ratio_spin.valueChanged.connect(self._on_multiframe_settings_changed)
        stepper_row.addWidget(self.pass_ratio_spin)
        mf_layout.addLayout(stepper_row)

        badges_row = QHBoxLayout()
        badges_row.setSpacing(4)
        for b_text, b_color in [("PASS (≥ 8/10)", "#10b981"), ("WARN (4-7/10)", "#f59e0b"), ("FAIL (< 4/10)", "#ef4444")]:
            b_lbl = QLabel(b_text)
            b_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            b_lbl.setStyleSheet(f"background: rgba(30, 41, 59, 0.8); color: {b_color}; font-size: 9px; font-weight: 700; padding: 2px 4px; border-radius: 4px; border: 1px solid rgba(255, 255, 255, 0.1);")
            badges_row.addWidget(b_lbl)
        mf_layout.addLayout(badges_row)

        mark_layout.addWidget(mf_frame)

        self.btn_replay_marks = QPushButton("▶ Replay ตรวจ Component ครบตามจุดที่มาร์ค (10F)")
        self.btn_replay_marks.setAutoDefault(False)
        self.btn_replay_marks.setStyleSheet("background: #0d9488; color: white; font-weight: 700; font-size: 12px; padding: 8px; border-radius: 6px;")
        self.btn_replay_marks.clicked.connect(self.start_replay_marked_scan)
        mark_layout.addWidget(self.btn_replay_marks)
        mark_layout.addStretch(1)

        self.settings.addTab(mark_tab, "📍 มาร์คจุด")

        # ── Tab 2: Manual Jog & Alignment (🕹️ จ๊อกกิ้ง) ──
        jog_tab = QWidget()
        jog_layout = QVBoxLayout(jog_tab)
        jog_layout.setContentsMargins(12, 12, 12, 12)
        jog_layout.setSpacing(10)

        self.pos_display = QLabel("X: 0.000 mm    Y: 0.000 mm")
        self.pos_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pos_display.setStyleSheet("background: #040810; color: #10b981; font-family: monospace; font-size: 14px; font-weight: 700; border: 1px solid #1e293b; border-radius: 6px; padding: 10px;")
        jog_layout.addWidget(self.pos_display)

        self.set_origin_btn = QPushButton("📍 ใช้ตำแหน่งปัจจุบันเป็น Origin (Set Origin)")
        self.set_origin_btn.setAutoDefault(False)
        self.set_origin_btn.setStyleSheet("background: #1e3a5f; color: #38bdf8; border: 1px solid #0284c7; font-weight: 700; padding: 8px; border-radius: 6px;")
        self.set_origin_btn.clicked.connect(self.set_origin_from_current)
        jog_layout.addWidget(self.set_origin_btn)

        step_row = QHBoxLayout()
        step_row.setSpacing(6)
        lbl_s = QLabel("Step:")
        lbl_s.setStyleSheet("font-size: 12px; color: #94a3b8;")
        step_row.addWidget(lbl_s)
        self.jog_step = self.number(1.0, 10, 2)
        self.jog_step.setMinimum(0.01)
        for val in (0.1, 0.5, 1.0, 5.0):
            qbtn = QPushButton(f"{val}")
            qbtn.setFixedWidth(38)
            qbtn.setAutoDefault(False)
            qbtn.setStyleSheet("padding: 4px; font-size: 11px;")
            qbtn.clicked.connect(lambda _, v=val: self.jog_step.setValue(v))
            step_row.addWidget(qbtn)
        step_row.addWidget(self.jog_step, 1)
        jog_layout.addLayout(step_row)

        dpad = QGridLayout()
        dpad.setSpacing(6)
        btn_yp = self.button("▲ Y+", lambda: self.jog(0, 1))
        btn_ym = self.button("▼ Y−", lambda: self.jog(0, -1))
        btn_xp = self.button("▶ X+", lambda: self.jog(1, 0))
        btn_xm = self.button("◀ X−", lambda: self.jog(-1, 0))
        for b in (btn_yp, btn_ym, btn_xp, btn_xm):
            b.setMinimumHeight(40)
            b.setStyleSheet("font-weight: 700; font-size: 13px; background: #1e293b;")
        dpad.addWidget(btn_yp, 0, 1)
        dpad.addWidget(btn_xm, 1, 0)
        lbl_jog_center = QLabel("JOG")
        lbl_jog_center.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_jog_center.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 700;")
        dpad.addWidget(lbl_jog_center, 1, 1)
        dpad.addWidget(btn_xp, 1, 2)
        dpad.addWidget(btn_ym, 2, 1)
        self.jog_buttons = [btn_xm, btn_xp, btn_ym, btn_yp]
        jog_layout.addLayout(dpad)

        self.snap_btn_jog = QPushButton("📸 ถ่ายภาพเล็งจุดนี้ (Snap Point)")
        self.snap_btn_jog.setAutoDefault(False)
        self.snap_btn_jog.setStyleSheet("background: #0f2a22; color: #10b981; border: 1px solid #059669; font-weight: 700; padding: 8px; border-radius: 6px;")
        self.snap_btn_jog.clicked.connect(self.snap_and_inspect)
        jog_layout.addWidget(self.snap_btn_jog)
        jog_layout.addStretch(1)

        self.settings.addTab(jog_tab, "🕹️ จ๊อกกิ้ง")

        # ── Tab 3: Scan Grid (📐 สแกนตาราง) ──
        grid_tab = QWidget()
        grid_layout = QVBoxLayout(grid_tab)
        grid_layout.setContentsMargins(12, 12, 12, 12)
        grid_layout.setSpacing(10)

        gform = QGridLayout()
        gform.setSpacing(8)

        self.origin_x, self.origin_y = self.number(0.0), self.number(0.0)
        self.pitch_x, self.pitch_y = self.number(5.0), self.number(5.0)
        self.columns, self.rows = QSpinBox(), QSpinBox()
        for field in (self.columns, self.rows):
            field.setRange(1, 100)
            field.setValue(2)
        self.limit_x = self.number(38.0, 1000, 2)
        self.limit_y = self.number(38.0, 1000, 2)
        self.limit_x.valueChanged.connect(self._sync_soft_limits)
        self.limit_y.valueChanged.connect(self._sync_soft_limits)

        for spin in (self.origin_x, self.origin_y, self.pitch_x, self.pitch_y, self.columns, self.rows):
            spin.valueChanged.connect(self._update_grid_summary)

        gform.addWidget(QLabel("Origin X:"), 0, 0)
        gform.addWidget(self.origin_x, 0, 1)
        gform.addWidget(QLabel("Origin Y:"), 0, 2)
        gform.addWidget(self.origin_y, 0, 3)

        gform.addWidget(QLabel("Pitch X:"), 1, 0)
        gform.addWidget(self.pitch_x, 1, 1)
        gform.addWidget(QLabel("Pitch Y:"), 1, 2)
        gform.addWidget(self.pitch_y, 1, 3)

        gform.addWidget(QLabel("Columns:"), 2, 0)
        gform.addWidget(self.columns, 2, 1)
        gform.addWidget(QLabel("Rows:"), 2, 2)
        gform.addWidget(self.rows, 2, 3)

        gform.addWidget(QLabel("Soft Lim X:"), 3, 0)
        gform.addWidget(self.limit_x, 3, 1)
        gform.addWidget(QLabel("Soft Lim Y:"), 3, 2)
        gform.addWidget(self.limit_y, 3, 3)
        grid_layout.addLayout(gform)

        self.grid_summary = QLabel("4 points (2×2) · span 5.0 × 5.0 mm")
        self.grid_summary.setStyleSheet("background: #1e3a5f; color: #38bdf8; font-size: 12px; font-weight: 700; padding: 8px; border-radius: 6px; text-align: center;")
        self.grid_summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid_layout.addWidget(self.grid_summary)

        self.plan_btn = QPushButton("👁 ตรวจสอบพิกัด (Preview points)")
        self.plan_btn.setAutoDefault(False)
        self.plan_btn.clicked.connect(self.preview_plan)
        grid_layout.addWidget(self.plan_btn)
        grid_layout.addStretch(1)

        self.settings.addTab(grid_tab, "📐 สแกนตาราง")

        # ── Tab 4: Camera & Hardware Motion Settings (⚙️ กล้อง/สเตจ) ──
        cam_tab = QWidget()
        cam_layout = QVBoxLayout(cam_tab)
        cam_layout.setContentsMargins(12, 12, 12, 12)
        cam_layout.setSpacing(10)

        cam_row1 = QHBoxLayout()
        self.camera_index = QSpinBox()
        self.camera_index.setRange(0, 15)
        self.camera_index.setValue(self.host.camera_index_spin.value())
        cam_row1.addWidget(QLabel("Cam Index:"))
        cam_row1.addWidget(self.camera_index)

        self.resolution = QComboBox()
        self.resolution.addItem("4K · 3840×2160", (3840, 2160))
        self.resolution.addItem("Full HD · 1920×1080", (1920, 1080))
        cam_row1.addWidget(self.resolution, 1)
        cam_layout.addLayout(cam_row1)

        self.camera_btn = QPushButton("Start camera")
        self.camera_btn.setAutoDefault(False)
        self.camera_btn.clicked.connect(self.toggle_camera)
        cam_layout.addWidget(self.camera_btn)

        pform = QGridLayout()
        pform.setSpacing(8)
        self.speed = QSpinBox()
        self.speed.setRange(20, 1500)
        self.speed.setValue(800)
        self.settle = self.number(0.8, 10)
        self.settle.setMinimum(0.2)
        self.match = self.number(20.0, 1000)
        self.scale = self.number(512.0, 10000, 3)
        self.scale.setMinimum(0.001)

        pform.addWidget(QLabel("Speed (steps/s):"), 0, 0)
        pform.addWidget(self.speed, 0, 1)
        pform.addWidget(QLabel("Settle (s):"), 0, 2)
        pform.addWidget(self.settle, 0, 3)
        pform.addWidget(QLabel("Match tol (px):"), 1, 0)
        pform.addWidget(self.match, 1, 1)
        pform.addWidget(QLabel("Steps/mm:"), 1, 2)
        pform.addWidget(self.scale, 1, 3)
        cam_layout.addLayout(pform)
        cam_layout.addStretch(1)

        self.settings.addTab(cam_tab, "⚙️ กล้อง/สเตจ")

        # Scroll area for left panel with flexible width
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.settings)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setMinimumWidth(300)

        # ── Right Side: Viewport & Inspection Table ──
        workspace_widget = QWidget()
        workspace = QVBoxLayout(workspace_widget)
        workspace.setContentsMargins(0, 0, 0, 0)
        workspace.setSpacing(8)

        # Viewport Card (Dual View: Live Camera & Captured Inspection)
        vp_box = QFrame()
        vp_layout = QVBoxLayout(vp_box)
        vp_layout.setContentsMargins(0, 0, 0, 0)
        vp_layout.setSpacing(6)

        vp_header_lbl = QLabel("Inspection Viewports · จอภาพตรวจสอบ (Live Camera & Captured Result)")
        vp_header_lbl.setStyleSheet("color: #94a3b8; font-weight: 700; font-size: 11px; padding-left: 4px;")
        vp_layout.addWidget(vp_header_lbl)

        vp_top = QHBoxLayout()
        vp_top.setSpacing(6)

        self.btn_view_dual = QPushButton("⊞ แสดงคู่ (Dual)")
        self.btn_view_dual.setAutoDefault(False)
        self.btn_view_dual.setCheckable(True)
        self.btn_view_dual.setChecked(True)
        self.btn_view_dual.setStyleSheet("font-size: 11px; padding: 4px 8px; font-weight: 600;")
        self.btn_view_dual.clicked.connect(lambda: self._set_view_mode("dual"))
        vp_top.addWidget(self.btn_view_dual)

        self.btn_view_live = QPushButton("📹 กล้องสด (Live)")
        self.btn_view_live.setAutoDefault(False)
        self.btn_view_live.setCheckable(True)
        self.btn_view_live.setStyleSheet("font-size: 11px; padding: 4px 8px; font-weight: 600;")
        self.btn_view_live.clicked.connect(lambda: self._set_view_mode("live"))
        vp_top.addWidget(self.btn_view_live)

        self.btn_view_captured = QPushButton("📸 ภาพที่ถ่าย (Captured)")
        self.btn_view_captured.setAutoDefault(False)
        self.btn_view_captured.setCheckable(True)
        self.btn_view_captured.setStyleSheet("font-size: 11px; padding: 4px 8px; font-weight: 600;")
        self.btn_view_captured.clicked.connect(lambda: self._set_view_mode("captured"))
        vp_top.addWidget(self.btn_view_captured)

        vp_top.addSpacing(6)

        self.check_crosshair = QCheckBox("Show Crosshair (เส้นเล็ง)")
        self.check_crosshair.setChecked(True)
        self.check_crosshair.setStyleSheet("color: #38bdf8; font-size: 11px; font-weight: 600;")
        self.check_crosshair.toggled.connect(self._on_crosshair_toggled)
        vp_top.addWidget(self.check_crosshair)

        vp_top.addSpacing(8)

        lbl_aspect = QLabel("สัดส่วนภาพ:")
        lbl_aspect.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600;")
        vp_top.addWidget(lbl_aspect)

        self.aspect_combo = QComboBox()
        self.aspect_combo.addItem("1:1 จัตุรัส (ตรงตาม imgsz)", "1:1")
        self.aspect_combo.addItem("16:9 เต็มเซนเซอร์ (Full)", "16:9")
        self.aspect_combo.addItem("Native ต้นฉบับกล้อง", "native")
        self.aspect_combo.setStyleSheet("font-size: 11px; font-weight: 600; color: #38bdf8;")
        self.aspect_combo.currentIndexChanged.connect(self._on_aspect_changed)
        vp_top.addWidget(self.aspect_combo)

        vp_top.addStretch(1)

        self.snap_btn = QPushButton("📸 ถ่ายภาพทดสอบ (Test Snap)")
        self.snap_btn.setAutoDefault(False)
        self.snap_btn.setStyleSheet("background: #0284c7; color: white; font-weight: 700; font-size: 11px; padding: 4px 12px; border-radius: 6px;")
        self.snap_btn.clicked.connect(self.snap_and_inspect)
        vp_top.addWidget(self.snap_btn)

        vp_layout.addLayout(vp_top)

        # Splitter between Live Stream (Left) and Captured Photo (Right)
        self.view_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.view_splitter.setChildrenCollapsible(False)
        self.view_splitter.setHandleWidth(6)

        # ── Left Viewport: Live Camera ──
        self.live_panel = QFrame()
        self.live_panel.setStyleSheet("background: #080f1a; border: 1px solid #1e293b; border-radius: 8px;")
        live_layout = QVBoxLayout(self.live_panel)
        live_layout.setContentsMargins(6, 6, 6, 6)
        live_layout.setSpacing(4)

        live_hdr = QHBoxLayout()
        lbl_live = QLabel("📹 กล้องสด (Live Camera)")
        lbl_live.setStyleSheet("color: #38bdf8; font-weight: 700; font-size: 11px;")
        live_hdr.addWidget(lbl_live, 1)
        self.camera_info = QLabel("Live: 640 × 640 px (รอเปิดกล้อง)")
        self.camera_info.setStyleSheet("color: #64748b; font-size: 10px; font-weight: 600;")
        live_hdr.addWidget(self.camera_info)
        live_layout.addLayout(live_hdr)

        self.preview = QLabel("Live camera feed\nภาพสดตามความละเอียดที่เลือกจะแสดงที่นี่")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(220, 160)
        self.preview.setStyleSheet("background: #040810; color: #475569; border-radius: 6px;")
        live_layout.addWidget(self.preview, 1)
        self.view_splitter.addWidget(self.live_panel)

        # ── Right Viewport: Captured Preview ──
        self.captured_panel = QFrame()
        self.captured_panel.setStyleSheet("background: #080f1a; border: 1px solid #1e293b; border-radius: 8px;")
        captured_layout = QVBoxLayout(self.captured_panel)
        captured_layout.setContentsMargins(6, 6, 6, 6)
        captured_layout.setSpacing(4)

        captured_hdr = QHBoxLayout()
        self.captured_title = QLabel("📸 ภาพที่ถ่ายล่าสุด (Captured Inspection)")
        self.captured_title.setStyleSheet("color: #10b981; font-weight: 700; font-size: 11px;")
        captured_hdr.addWidget(self.captured_title, 1)

        self.captured_badge = QLabel("READY")
        self.captured_badge.setStyleSheet("background: #1e293b; color: #94a3b8; border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: 700;")
        captured_hdr.addWidget(self.captured_badge)
        captured_layout.addLayout(captured_hdr)

        self.captured_preview = QLabel(
            "ยังไม่มีภาพถ่าย (No capture yet)\nเมื่อสแกนหรือกดถ่ายรูป ภาพผลลัพธ์ (ตามความละเอียดที่เลือก) จะมาแสดงที่นี่"
        )
        self.captured_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.captured_preview.setMinimumSize(220, 160)
        self.captured_preview.setStyleSheet(
            "background: #020617; border: 1px solid #1e293b; border-radius: 8px; color: #64748b; font-size: 11px;"
        )
        captured_layout.addWidget(self.captured_preview, 1)

        # Navigation Bar for browsing captured images
        nav_bar = QHBoxLayout()
        nav_bar.setSpacing(4)

        self.btn_cap_prev = QPushButton("◀ ก่อนหน้า")
        self.btn_cap_prev.setAutoDefault(False)
        self.btn_cap_prev.setStyleSheet("font-size: 11px; padding: 4px 8px; font-weight: 600;")
        self.btn_cap_prev.clicked.connect(self.prev_captured_point)
        nav_bar.addWidget(self.btn_cap_prev)

        self.cap_page_lbl = QLabel("จุดที่ — / —")
        self.cap_page_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cap_page_lbl.setStyleSheet("color: #f1f5f9; font-weight: 700; font-size: 11px;")
        nav_bar.addWidget(self.cap_page_lbl, 1)

        self.btn_cap_next = QPushButton("ถัดไป ▶")
        self.btn_cap_next.setAutoDefault(False)
        self.btn_cap_next.setStyleSheet("font-size: 11px; padding: 4px 8px; font-weight: 600;")
        self.btn_cap_next.clicked.connect(self.next_captured_point)
        nav_bar.addWidget(self.btn_cap_next)

        self.btn_full_4k = QPushButton("🔍 ดูภาพเต็มตา")
        self.btn_full_4k.setAutoDefault(False)
        self.btn_full_4k.setStyleSheet("background: #1e3a5f; color: #38bdf8; border: 1px solid #0284c7; font-size: 10px; font-weight: 700; padding: 4px 8px; border-radius: 4px;")
        self.btn_full_4k.clicked.connect(self.view_full_4k_image)
        nav_bar.addWidget(self.btn_full_4k)

        self.btn_open_folder = QPushButton("📁 โฟลเดอร์ผลลัพธ์")
        self.btn_open_folder.setAutoDefault(False)
        self.btn_open_folder.setStyleSheet("font-size: 10px; padding: 4px 8px; color: #94a3b8;")
        self.btn_open_folder.clicked.connect(self.open_run_folder)
        nav_bar.addWidget(self.btn_open_folder)

        captured_layout.addLayout(nav_bar)

        self.captured_info = QLabel("Ready to capture · ความละเอียดภาพ Output: 640 × 640 px (ตรงตามที่เลือกไว้)")
        self.captured_info.setStyleSheet("color: #64748b; font-size: 10px; padding: 2px;")
        captured_layout.addWidget(self.captured_info)

        self.view_splitter.addWidget(self.captured_panel)
        self.view_splitter.setSizes([380, 380])
        vp_layout.addWidget(self.view_splitter, 1)

        # ── Middle Strip: Horizontal Filmstrip of Captured 4K Points ──
        self.filmstrip_box = QFrame()
        self.filmstrip_box.setStyleSheet("background: #0f172a; border: 1px solid #1e293b; border-radius: 8px;")
        filmstrip_layout = QVBoxLayout(self.filmstrip_box)
        filmstrip_layout.setContentsMargins(6, 4, 6, 4)
        filmstrip_layout.setSpacing(4)

        filmstrip_hdr = QHBoxLayout()
        lbl_fs = QLabel("🖼️ แกลเลอรีภาพถ่ายทุกจุด (Filmstrip — เลื่อนดูและคลิกเพื่อดูภาพ 4K แต่ละจุด)")
        lbl_fs.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600;")
        filmstrip_hdr.addWidget(lbl_fs, 1)

        self.lbl_fs_count = QLabel("0 ภาพ (4K)")
        self.lbl_fs_count.setStyleSheet("color: #38bdf8; font-size: 11px; font-weight: 700;")
        filmstrip_hdr.addWidget(self.lbl_fs_count)
        filmstrip_layout.addLayout(filmstrip_hdr)

        self.filmstrip_scroll = QScrollArea()
        self.filmstrip_scroll.setWidgetResizable(True)
        self.filmstrip_scroll.setFixedHeight(82)
        self.filmstrip_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.filmstrip_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.filmstrip_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.filmstrip_content = QWidget()
        self.filmstrip_strip = QHBoxLayout(self.filmstrip_content)
        self.filmstrip_strip.setContentsMargins(2, 2, 2, 2)
        self.filmstrip_strip.setSpacing(6)
        self.filmstrip_strip.addStretch(1)
        self.filmstrip_scroll.setWidget(self.filmstrip_content)
        filmstrip_layout.addWidget(self.filmstrip_scroll)

        # Table Card
        tbl_box = QFrame()
        tbl_layout = QVBoxLayout(tbl_box)
        tbl_layout.setContentsMargins(0, 0, 0, 0)
        tbl_layout.setSpacing(4)

        tbl_hdr_layout = QHBoxLayout()
        tbl_header_lbl = QLabel("Inspection Points · รายการจุดตรวจสอบ")
        tbl_header_lbl.setStyleSheet("color: #94a3b8; font-weight: 700; font-size: 11px; padding-left: 4px;")
        tbl_hdr_layout.addWidget(tbl_header_lbl, 1)

        self.btn_goto_point = QPushButton("🎯 เลื่อนกล้องไปจุดที่เลือก (Go to Point)")
        self.btn_goto_point.setAutoDefault(False)
        self.btn_goto_point.setStyleSheet("background: #1e3a5f; color: #38bdf8; border: 1px solid #0284c7; font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 4px;")
        self.btn_goto_point.clicked.connect(self.move_to_selected_point)
        tbl_hdr_layout.addWidget(self.btn_goto_point)

        self.btn_delete_point = QPushButton("🗑 ลบจุดที่เลือก")
        self.btn_delete_point.setAutoDefault(False)
        self.btn_delete_point.setToolTip("ลบจุดตรวจสอบที่เลือกในตาราง (Delete Selected Point)")
        self.btn_delete_point.setStyleSheet("background: #2a1215; color: #ef4444; border: 1px solid #7f1d1d; font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 4px;")
        self.btn_delete_point.clicked.connect(lambda: self.delete_selected_point())
        tbl_hdr_layout.addWidget(self.btn_delete_point)

        tbl_layout.addLayout(tbl_hdr_layout)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Point", "X mm", "Y mm", "State", "Components", "Zoom"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.cellDoubleClicked.connect(lambda r, c: self.move_to_selected_point())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_table_context_menu)

        orig_key_press = self.table.keyPressEvent
        def _table_key_press(event):
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                self.delete_selected_point()
                event.accept()
                return
            orig_key_press(event)
        self.table.keyPressEvent = _table_key_press

        tbl_layout.addWidget(self.table)

        # Vertical Splitter between Preview, Filmstrip & Table
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_splitter.setChildrenCollapsible(False)
        right_splitter.setHandleWidth(6)
        right_splitter.addWidget(vp_box)
        right_splitter.addWidget(self.filmstrip_box)
        right_splitter.addWidget(tbl_box)
        right_splitter.setSizes([380, 85, 170])
        workspace.addWidget(right_splitter, 1)

        # Action Bar & Progress
        act_box = QVBoxLayout()
        act_box.setSpacing(6)

        self.progress = QProgressBar()
        act_box.addWidget(self.progress)

        self.reference_label = QLabel("No AOI reference: results will be REVIEW. Golden-board detections must be checked before use.")
        self.reference_label.setStyleSheet("color: #64748b; font-size: 11px;")
        self.reference_label.setWordWrap(True)
        act_box.addWidget(self.reference_label)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        lbl_mode = QLabel("โหมดสแกน:")
        lbl_mode.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600;")
        actions.addWidget(lbl_mode)

        self.scan_source_combo = QComboBox()
        self.scan_source_combo.addItem("📐 ตามตารางสแกน (Grid)", "grid")
        self.scan_source_combo.addItem("📍 ตามจุดที่มาร์ค (Marked)", "marked")
        self.scan_source_combo.currentIndexChanged.connect(self._on_scan_source_changed)
        self.scan_source_combo.setStyleSheet("font-size: 11px; font-weight: 600;")
        actions.addWidget(self.scan_source_combo)

        self.load_btn = self.button("📂 Load reference…", self.load_reference, actions)
        self.teach_btn = self.button("🌟 Scan golden board", lambda: self.start_scan(True), actions)
        self.scan_btn = QPushButton("🚀 Start AOI scan")
        self.scan_btn.setAutoDefault(False)
        self.scan_btn.setObjectName("primaryBtn")
        self.scan_btn.clicked.connect(lambda: self.start_scan(False))
        actions.addWidget(self.scan_btn, 1)

        self.button("Close", self.reject, actions)
        act_box.addLayout(actions)
        workspace.addLayout(act_box)

        # Main Splitter (Left Settings Panel vs Right Workspace)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.setChildrenCollapsible(False)
        main_splitter.setHandleWidth(6)
        main_splitter.addWidget(scroll)
        main_splitter.addWidget(workspace_widget)
        main_splitter.setSizes([380, 750])
        root.addWidget(main_splitter, 1)

    def _toggle_advanced_drawer(self, checked):
        if hasattr(self, "advanced_drawer"):
            self.advanced_drawer.setVisible(checked)
        if hasattr(self, "advanced_btn"):
            self.advanced_btn.setText("⚙️ ซ่อนการตั้งค่า ▲" if checked else "⚙️ ตั้งค่าเพิ่มเติม ▼")

    def refresh_ports(self):
        selected = self.port.currentData()
        self.port.clear()
        try:
            from serial.tools import list_ports
            ports = sorted(list_ports.comports(), key=lambda p: (
                0 if (p.vid, p.pid) == (0x1a86, 0x7523) else 1 if p.vid is not None else 2,
                p.device,
            ))
            for port in ports:
                label = "USB" if port.vid is not None else "System / virtual"
                self.port.addItem(f"{port.device} · {label} · {port.description}", port.device)
            previous = self.port.findData(selected) if selected else -1
            if previous >= 0:
                self.port.setCurrentIndex(previous)
            if not self._ports_initialized and ports and ports[0].vid is not None:
                self.mode.setCurrentIndex(1)
                self.status.setText(f"USB controller found: {ports[0].device}. Click Connect; then wait for firmware v2.")
            if not ports:
                self.port.addItem("No serial ports found · connect USB and refresh", None)
        except ImportError:
            self.port.addItem("Install pyserial for hardware mode", None)
            self.status.setText("Serial unavailable in this Python environment. Install pyserial using this interpreter.")
        self._ports_initialized = True

    def _get_model_start_dir(self):
        if hasattr(self, "_custom_model_dir") and self._custom_model_dir and Path(self._custom_model_dir).exists():
            return str(self._custom_model_dir)
        curr = getattr(self.host, "current_model_path", None)
        if curr and Path(curr).exists():
            return str(Path(curr).parent)
        main_root = getattr(self.host, "main_program_root", None)
        if main_root:
            p = Path(main_root).parent
            if (p / "trained").exists():
                return str(p / "trained")
            if p.exists():
                return str(p)
        proj_root = getattr(self.host, "project_root", None)
        if proj_root:
            p_pcb = Path(proj_root) / "PCB Electronic components" / "runs"
            if p_pcb.exists():
                return str(p_pcb)
            if Path(proj_root).exists():
                return str(proj_root)
        return os.getcwd()

    def find_available_models(self):
        models = []
        seen_paths = set()

        curr = getattr(self.host, "current_model_path", None)
        if curr and Path(curr).exists():
            p_res = str(Path(curr).resolve())
            p_name = Path(curr).name
            models.append((f"{p_name} (Active)", p_res))
            seen_paths.add(p_res)

        search_dirs = []
        if hasattr(self, "_custom_model_dir") and self._custom_model_dir and Path(self._custom_model_dir).exists():
            search_dirs.append(Path(self._custom_model_dir))

        proj_root = getattr(self.host, "project_root", None)
        main_root = getattr(self.host, "main_program_root", None)

        if main_root:
            p = Path(main_root).parent
            if p.exists():
                search_dirs.extend([
                    p,
                    p / "trained",
                    p / "backend" / "data" / "models",
                ])

        if proj_root:
            pr = Path(proj_root)
            search_dirs.extend([
                pr,
                pr / "defect detection yolo",
                pr / "defect detection yolo" / "trained",
                pr / "PCB Electronic components" / "runs",
            ])

        for s_dir in search_dirs:
            if not s_dir.exists():
                continue
            try:
                for f in sorted(s_dir.glob("*.pt")):
                    p_str = str(f.resolve())
                    if p_str not in seen_paths and not f.name.startswith("."):
                        label = f.name
                        if proj_root:
                            try:
                                label = str(f.relative_to(proj_root))
                            except Exception:
                                pass
                        models.append((label, p_str))
                        seen_paths.add(p_str)
                if "runs" in s_dir.name.lower():
                    for f in sorted(s_dir.glob("**/weights/*.pt")):
                        p_str = str(f.resolve())
                        if p_str not in seen_paths and not f.name.startswith("."):
                            try:
                                run_name = f.parent.parent.name
                                label = f"runs/{run_name}/{f.name}"
                            except Exception:
                                label = f.name
                            models.append((label, p_str))
                            seen_paths.add(p_str)
            except Exception:
                pass
        return models

    def refresh_available_models(self, initial=False):
        if not hasattr(self, "model_combo"):
            return
        curr = getattr(self.host, "current_model_path", "")
        models = self.find_available_models()

        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        selected_idx = -1
        for idx, (label, path) in enumerate(models):
            self.model_combo.addItem(label, path)
            if curr and (path == curr or Path(path).resolve() == Path(curr).resolve()):
                selected_idx = idx

        if selected_idx >= 0:
            self.model_combo.setCurrentIndex(selected_idx)
        elif self.model_combo.count() > 0 and not initial and not curr:
            self.model_combo.setCurrentIndex(0)
            self.change_model(self.model_combo.currentData())
        self.model_combo.blockSignals(False)
        self._update_model_ui()

    def _update_model_ui(self):
        if not hasattr(self, "lbl_model_badge"):
            return
        curr = getattr(self.host, "current_model_path", "")
        names = getattr(self.host, "model_names", {})
        has_model = getattr(self.host, "model", None) is not None

        if has_model:
            m_name = Path(curr).name if curr else "Active Model"
            cls_count = len(names) if names else 0
            self.lbl_model_badge.setText(f"● {m_name} ({cls_count} classes)")
            self.lbl_model_badge.setStyleSheet(
                "background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid #059669; "
                "font-weight: 700; font-size: 11px; padding: 4px 8px; border-radius: 6px;"
            )
            classes_str = ", ".join(list(names.values())[:10])
            if cls_count > 10:
                classes_str += f" +{cls_count - 10} more"
            self.lbl_model_badge.setToolTip(f"File: {curr}\nClasses ({cls_count}): {classes_str}")
        else:
            self.lbl_model_badge.setText("● NO MODEL")
            self.lbl_model_badge.setStyleSheet(
                "background: #2a1215; color: #ef4444; border: 1px solid #7f1d1d; "
                "font-weight: 700; font-size: 11px; padding: 4px 8px; border-radius: 6px;"
            )
            self.lbl_model_badge.setToolTip("No YOLO model loaded. Select a model from dropdown or browse a .pt file.")

    def _on_model_combo_changed(self, index):
        if index < 0 or not hasattr(self, "model_combo"):
            return
        path = self.model_combo.currentData()
        curr = getattr(self.host, "current_model_path", "")
        if path and path != curr:
            self.change_model(path)

    def browse_model_folder(self):
        if self.active:
            self.error("กำลังทำการตรวจจับอยู่ ไม่สามารถเปลี่ยนโมเดลระหว่างตรวจได้")
            return
        start_dir = self._get_model_start_dir()
        folder_path = QFileDialog.getExistingDirectory(
            self, "เลือกโฟลเดอร์ที่เก็บโมเดล YOLO (.pt)", start_dir
        )
        if not folder_path:
            return

        folder = Path(folder_path).resolve()
        self._custom_model_dir = str(folder)

        pt_files = []
        try:
            for f in sorted(folder.glob("*.pt")):
                if f.is_file() and not f.name.startswith("."):
                    pt_files.append(f)
            for f in sorted(folder.glob("**/weights/*.pt")):
                if f.is_file() and not f.name.startswith(".") and f not in pt_files:
                    pt_files.append(f)
            if not pt_files:
                for f in sorted(folder.glob("**/*.pt")):
                    if f.is_file() and not f.name.startswith(".") and "venv" not in str(f) and f not in pt_files:
                        pt_files.append(f)
        except Exception as exc:
            self.error(f"เกิดข้อผิดพลาดในการค้นหาโมเดลในโฟลเดอร์: {exc}")
            return

        if not pt_files:
            self.error(f"ไม่พบไฟล์โมเดล (.pt) ในโฟลเดอร์:\n{folder}")
            return

        self.model_combo.blockSignals(True)
        for f in pt_files:
            p_str = str(f.resolve())
            idx = self.model_combo.findData(p_str)
            if idx < 0:
                try:
                    rel = str(f.relative_to(folder))
                except Exception:
                    rel = f.name
                label = f"📁 {folder.name}/{rel}" if rel != f.name else f"📁 {f.name}"
                self.model_combo.addItem(label, p_str)

        best_pt = None
        for f in pt_files:
            if f.name.lower() == "best.pt":
                best_pt = str(f.resolve())
                break
        if not best_pt:
            newest = max(pt_files, key=lambda x: x.stat().st_mtime)
            best_pt = str(newest.resolve())

        target_idx = self.model_combo.findData(best_pt)
        if target_idx >= 0:
            self.model_combo.setCurrentIndex(target_idx)
        self.model_combo.blockSignals(False)

        ok = self.change_model(best_pt)
        if ok:
            self.status.setText(f"📂 เลือกโฟลเดอร์ '{folder.name}' สำเร็จ: พบ {len(pt_files)} โมเดล · โหลด {Path(best_pt).name}")

    def open_model_folder(self):
        folder = self._get_model_start_dir()
        if folder and Path(folder).exists():
            import subprocess
            try:
                subprocess.Popen(["open", str(folder)])
                self.status.setText(f"📂 เปิดโฟลเดอร์โมเดลใน Finder: {folder}")
            except Exception as exc:
                self.error(f"ไม่สามารถเปิดโฟลเดอร์ได้: {exc}")
        else:
            self.error("ยังไม่พบตำแหน่งโฟลเดอร์โมเดล")

    def browse_model(self):
        if self.active:
            self.error("กำลังทำการตรวจจับอยู่ ไม่สามารถเปลี่ยนโมเดลระหว่างตรวจได้")
            return
        start_dir = self._get_model_start_dir()
        file_path, _ = QFileDialog.getOpenFileName(
            self, "เลือกไฟล์ YOLO Model (.pt)", start_dir, "PyTorch Model (*.pt)"
        )
        if not file_path:
            return

        file_path = str(Path(file_path).resolve())
        self._custom_model_dir = str(Path(file_path).parent)
        idx = self.model_combo.findData(file_path)
        if idx < 0:
            self.model_combo.addItem(f"{Path(file_path).name} (Custom)", file_path)
            idx = self.model_combo.count() - 1

        self.model_combo.setCurrentIndex(idx)
        self.change_model(file_path)

    def change_model(self, model_path):
        if self.active:
            self.error("กำลังทำการตรวจจับอยู่ ไม่สามารถเปลี่ยนโมเดลระหว่างตรวจได้")
            return False
        if not model_path:
            return False

        try:
            if (
                self.host.model is not None
                and getattr(self.host, "current_model_path", "") == model_path
            ):
                self._update_model_ui()
                return True

            if hasattr(self.host, "load_model"):
                self.host.load_model(str(model_path))
            else:
                from ultralytics import YOLO
                m = YOLO(str(model_path))
                self.host.model = m
                names = m.names if isinstance(m.names, dict) else {i: n for i, n in enumerate(m.names)}
                self.host.model_names = names
                self.host.current_model_path = str(model_path)

            self._update_model_ui()
            if hasattr(self, "_ensure_marked_references_detected"):
                self._ensure_marked_references_detected()
                if hasattr(self, "marked_points") and self.marked_points:
                    self._show_points(self.marked_points)

            m_name = Path(model_path).name
            cls_count = len(getattr(self.host, "model_names", {}))
            self.status.setText(f"🧠 โหลดโมเดลสำเร็จ: {m_name} (พร้อมตรวจ {cls_count} คลาส)")
            self._controls()
            return True
        except Exception as exc:
            self.error(f"โหลดโมเดลไม่สำเร็จ: {exc}")
            return False

    def _on_aoi_device_changed(self, index):
        if hasattr(self.host, "device_combo") and index >= 0 and hasattr(self, "aoi_device_combo"):
            dev_val = self.aoi_device_combo.currentData()
            h_idx = self.host.device_combo.findData(dev_val)
            if h_idx >= 0 and self.host.device_combo.currentIndex() != h_idx:
                self.host.device_combo.setCurrentIndex(h_idx)

    def _on_aoi_conf_changed(self, value):
        if hasattr(self.host, "conf_slider"):
            if self.host.conf_slider.value() != value:
                self.host.conf_slider.setValue(value)

    def current_imgsz(self):
        if not hasattr(self, "aoi_imgsz_combo"):
            return 640
        data = self.aoi_imgsz_combo.currentData()
        if data is not None:
            try:
                return int(data)
            except (ValueError, TypeError):
                pass
        text = self.aoi_imgsz_combo.currentText()
        digits = "".join(ch for ch in text if ch.isdigit())
        if digits:
            try:
                return int(digits)
            except ValueError:
                pass
        return 640

    def _on_aoi_imgsz_changed(self, index):
        sz = self.current_imgsz()
        if hasattr(self.host, "_detect_imgsz"):
            self.host._detect_imgsz = sz
        if hasattr(self, "lbl_imgsz_hint"):
            if sz >= 1920:
                self.lbl_imgsz_hint.setText(f"🔍 {sz}px: คมชัดระดับ Ultra สำหรับ Live & Output (ใช้ VRAM มากขึ้น)")
                self.lbl_imgsz_hint.setStyleSheet("color: #38bdf8; font-size: 10px; font-weight: 600;")
            elif sz >= 1280:
                self.lbl_imgsz_hint.setText(f"🔍 {sz}px: ความละเอียด 1280px สำหรับ Live & Output (แนะนำสำหรับ PCB ชิ้นส่วนเล็ก)")
                self.lbl_imgsz_hint.setStyleSheet("color: #10b981; font-size: 10px; font-weight: 600;")
            elif sz >= 960:
                self.lbl_imgsz_hint.setText(f"⚡ {sz}px: คมชัดปานกลาง สมดุลความเร็วและรายละเอียด")
                self.lbl_imgsz_hint.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 500;")
            else:
                self.lbl_imgsz_hint.setText(f"⚡ {sz}px: ค่ามาตรฐาน ประมวลผลเร็ว")
                self.lbl_imgsz_hint.setStyleSheet("color: #64748b; font-size: 10px; font-weight: 500;")

        self._update_resolution_ui()

        # Immediately refresh live camera frame if available
        if hasattr(self, "_raw_live_frame") and self._raw_live_frame is not None:
            self.show_frame(self._raw_live_frame)

        # Re-detect components on marked points with new resolution if available
        if hasattr(self, "_ensure_marked_references_detected"):
            self._ensure_marked_references_detected(force=True)
            if hasattr(self, "marked_points") and self.marked_points:
                self._show_points(self.marked_points)

        self.status.setText(f"📐 ปรับความละเอียด Live & Output เป็น {sz}×{sz} px เรียบร้อย")

    def _update_resolution_ui(self):
        sz = self.current_imgsz()
        mode = getattr(self, "aspect_mode", "1:1")
        if mode == "1:1":
            res_str = f"{sz} × {sz} px"
        elif mode == "16:9":
            h = int(round(sz * 9 / 16))
            res_str = f"{sz} × {h} px (16:9)"
        else:
            res_str = "Native ต้นฉบับ"

        if hasattr(self, "captured_info") and (not hasattr(self, "_last_captured_frame") or self._last_captured_frame is None):
            self.captured_info.setText(f"Ready to capture · ความละเอียดภาพ Output: {res_str} (ตรงตามที่เลือกไว้)")
            self.captured_info.setStyleSheet("color: #64748b; font-size: 10px; padding: 2px;")

        if hasattr(self, "camera_info") and not getattr(self, "camera", None):
            self.camera_info.setText(f"Live: {res_str} (รอเปิดกล้อง)")

    def _on_aspect_changed(self, index):
        if hasattr(self, "aspect_combo"):
            self.aspect_mode = self.aspect_combo.currentData()
        self._update_resolution_ui()
        if hasattr(self, "_raw_live_frame") and self._raw_live_frame is not None:
            self.show_frame(self._raw_live_frame)
        self.status.setText(f"ปรับสัดส่วนภาพ Live & Output เป็น: {self.aspect_combo.currentText()}")

    def connect_machine(self):
        if self.machine and not self.machine.closed:
            self.stop()
            self.machine.close()
            self.status.setText("Disconnected. HOME again after reconnecting.")
        else:
            try:
                if self.mode.currentIndex() == 0:
                    transport = SimulatedTransport()
                    self.endpoint = "SIMULATION (motors are not connected)"
                else:
                    import serial
                    port = self.port.currentData()
                    if not port:
                        raise ValueError("Select a serial port first.")
                    transport = serial.Serial(port, 9600, timeout=0, write_timeout=.2,
                                              exclusive=True if os.name == "posix" else None)
                    self.endpoint = port + " @ 9600 baud"
                try:
                    self.machine = MotionClient(transport, startup_delay=2.5 if self.mode.currentIndex() else 0)
                except Exception:
                    transport.close()
                    raise
                self.wire_log.clear()
                self.wire_log.appendPlainText("CONNECT  " + self.endpoint)
                self.status.setText(f"Connecting {self.endpoint} · waiting for Nano startup / firmware v2…")
            except Exception as exc:
                self.error(str(exc))
        self._controls()

    def effective_limits(self):
        if not self.machine or not self.machine.ready:
            return (0, 0)
        mx_hw, my_hw = self.machine.limits
        scale = self.scale.value() if self.scale.value() > 0 else 512.0
        val_x, val_y = self.limit_x.value(), self.limit_y.value()
        hw_x_mm = mx_hw / scale
        hw_y_mm = my_hw / scale
        soft_x = mx_hw if (val_x <= 0 or val_x >= hw_x_mm - 1e-4) else round(val_x * scale)
        soft_y = my_hw if (val_y <= 0 or val_y >= hw_y_mm - 1e-4) else round(val_y * scale)
        return (max(0, min(mx_hw, soft_x)), max(0, min(my_hw, soft_y)))

    def _sync_soft_limits(self):
        if self.machine:
            self.machine.soft_limits = self.effective_limits()

    def _on_machine_ready(self):
        if not self.machine:
            return
        mx, my = self.machine.limits
        scale = self.scale.value() if self.scale.value() > 0 else 512.0
        hw_x_mm = round(mx / scale, 2)
        hw_y_mm = round(my / scale, 2)
        self.limit_x.setMaximum(hw_x_mm)
        self.limit_y.setMaximum(hw_y_mm)
        if self.limit_x.value() <= 0 or self.limit_x.value() > hw_x_mm:
            self.limit_x.setValue(min(38.0, hw_x_mm))
        if self.limit_y.value() <= 0 or self.limit_y.value() > hw_y_mm:
            self.limit_y.setValue(min(38.0, hw_y_mm))
        self._sync_soft_limits()

    def command(self, kind, x=0, y=0):
        try:
            if not self.machine:
                raise ValueError("Connect the stage first.")
            if kind == "MOVE":
                eff_x, eff_y = self.effective_limits()
                if not (0 <= x <= eff_x and 0 <= y <= eff_y):
                    scale = self.scale.value()
                    raise ValueError(f"Move exceeds soft limit (0–{eff_x/scale:.2f}, 0–{eff_y/scale:.2f} mm)")
            self.machine.command(kind, x, y, self.speed.value())
            self.status.setText(f"Stage: {kind}")
        except Exception as exc:
            self.error(str(exc))
        self._controls()

    def jog(self, dx, dy):
        step = round(self.jog_step.value() * self.scale.value())
        x, y = self.machine.position
        target_x = x + dx * step
        target_y = y + dy * step
        eff_x, eff_y = self.effective_limits()
        scale = self.scale.value()
        if not (0 <= target_x <= eff_x and 0 <= target_y <= eff_y):
            self.status.setText(f"Jog blocked by soft limit (Range: 0–{eff_x/scale:.2f} × 0–{eff_y/scale:.2f} mm)")
            return
        self.command("MOVE", target_x, target_y)

    def toggle_camera(self):
        if self.camera:
            self.camera.requestInterruption()
            self.camera_btn.setText("Stopping camera…")
        else:
            self.camera = AOICamera(self.camera_index.value(), self.resolution.currentData())
            self.camera.failed.connect(self.error)
            self.camera.start()
            self.camera_btn.setText("Stop camera")
        self._controls()

    def _apply_zoom_crop(self, img, zoom):
        if zoom <= 1.01:
            return img
        h, w = img.shape[:2]
        crop_w = max(10, int(w / zoom))
        crop_h = max(10, int(h / zoom))
        x1 = max(0, (w - crop_w) // 2)
        y1 = max(0, (h - crop_h) // 2)
        cropped = img[y1:y1 + crop_h, x1:x1 + crop_w]
        return cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LANCZOS4)

    def _process_frame_for_active_resolution(self, frame, zoom=1.0, target_sz=None):
        """
        Process raw camera sensor frame according to the user-selected resolution (imgsz)
        and framing/aspect mode so that both the live stream and the output captured frames
        match the exact resolution selected by the user.
        """
        if frame is None or frame.size == 0:
            return frame

        if target_sz is None:
            target_sz = self.current_imgsz()

        aspect_mode = getattr(self, "aspect_mode", "1:1")
        h, w = frame.shape[:2]

        if aspect_mode == "native":
            if zoom > 1.01:
                return self._apply_zoom_crop(frame, zoom)
            return frame.copy()

        if aspect_mode == "16:9":
            target_w = target_sz
            target_h = max(10, int(round(target_sz * h / w)))
            if zoom > 1.01:
                crop_w = max(10, int(w / zoom))
                crop_h = max(10, int(h / zoom))
                x1 = max(0, (w - crop_w) // 2)
                y1 = max(0, (h - crop_h) // 2)
                cropped = frame[y1:y1 + crop_h, x1:x1 + crop_w]
            else:
                cropped = frame
            interp = cv2.INTER_AREA if cropped.shape[1] > target_w else cv2.INTER_LANCZOS4
            return cv2.resize(cropped, (target_w, target_h), interpolation=interp)

        # Default: "1:1" Square matching YOLO imgsz input (e.g. 640x640, 1280x1280)
        side = min(h, w)
        if zoom > 1.01:
            crop_side = max(10, int(side / zoom))
        else:
            crop_side = side

        x1 = max(0, (w - crop_side) // 2)
        y1 = max(0, (h - crop_side) // 2)
        cropped = frame[y1:y1 + crop_side, x1:x1 + crop_side]

        if cropped.shape[0] == target_sz and cropped.shape[1] == target_sz:
            return cropped

        interp = cv2.INTER_AREA if cropped.shape[0] > target_sz else cv2.INTER_LANCZOS4
        return cv2.resize(cropped, (target_sz, target_sz), interpolation=interp)

    def _on_live_zoom_changed(self, value):
        self.current_live_zoom = round(float(value), 1)
        if hasattr(self, "_raw_live_frame") and self._raw_live_frame is not None:
            self.show_frame(self._raw_live_frame)

    def update_selected_point_zoom(self):
        rows = self.table.selectedItems()
        if not rows:
            self.error("กรุณาคลิกเลือกจุดในตารางก่อนกดอัปเดตระดับซูม")
            return
        row = rows[0].row()
        zoom = round(float(self.live_zoom_spin.value()), 1)
        if getattr(self, "scan_mode", "grid") == "marked" and getattr(self, "marked_points", None) and row < len(self.marked_points):
            pt = self.marked_points[row]
            self.marked_points[row] = (pt[0], pt[1], zoom)
            self._show_points(self.marked_points)
            self.table.selectRow(row)
            self.status.setText(f"🔄 อัปเดตจุดที่ {row+1} ให้ซูม {zoom:.1f}x เรียบร้อย")
        elif getattr(self, "points", None) and row < len(self.points):
            pt = self.points[row]
            self.points[row] = (pt[0], pt[1], zoom)
            self._show_points(self.points)
            self.table.selectRow(row)
            self.status.setText(f"🔄 อัปเดตจุดที่ {row+1} ให้ซูม {zoom:.1f}x เรียบร้อย")

    def _apply_multiframe_preset(self, frames):
        if hasattr(self, "multiframe_spin"):
            self.multiframe_spin.setValue(frames)

    def _on_multiframe_settings_changed(self):
        target = self.multiframe_spin.value() if hasattr(self, "multiframe_spin") else 10
        ratio = (self.pass_ratio_spin.value() / 100.0) if hasattr(self, "pass_ratio_spin") else 0.8
        threshold = max(1, math.ceil(target * ratio))
        if hasattr(self, "lbl_mf_badge"):
            self.lbl_mf_badge.setText(f"{target}F")
        if hasattr(self, "lbl_mf_stats"):
            self.lbl_mf_stats.setText(f"ตรวจเฉลี่ย: {target} เฟรม · เกณฑ์ผ่าน ≥ {threshold}/{target} ({int(ratio*100)}%)")
        self._update_mark_ui()

    def _on_multiframe_toggled(self, checked):
        if hasattr(self, "multiframe_spin"):
            self.multiframe_spin.setEnabled(checked)
        if hasattr(self, "pass_ratio_spin"):
            self.pass_ratio_spin.setEnabled(checked)
        if hasattr(self, "_mf_preset_buttons"):
            for _, btn in self._mf_preset_buttons:
                btn.setEnabled(checked)
        self._update_mark_ui()

    def mark_current_point(self):
        if not self.machine:
            self.error("กรุณากด Connect เครื่องก่อนมาร์คจุด")
            return
        if not self.machine.ready:
            self.error("เครื่องจักรยังไม่พร้อมใช้งาน")
            return
        if not self.machine.homed and self.mode.currentIndex() != 0:
            self.error("กรุณากด ⌂ HOME เครื่องก่อนมาร์คจุด เพื่อให้อ้างอิงพิกัดได้อย่างถูกต้อง")
            return
        
        x, y = self.machine.position
        scale = self.scale.value() if self.scale.value() > 0 else 512.0
        zoom = round(float(getattr(self, "current_live_zoom", 1.0)), 1)
        point_idx = len(self.marked_points)

        # ── 1. ถ่ายภาพต้นฉบับ (Capture Reference Frame) ──
        snapshot = self.camera.snapshot() if self.camera else None
        ref_frame = None
        raw_frame = None
        if snapshot is not None:
            _, raw_frame = snapshot
            if raw_frame is not None:
                ref_frame = self._process_frame_for_active_resolution(raw_frame, zoom=zoom)

        if ref_frame is None:
            sz = self.current_imgsz()
            ref_frame = np.zeros((sz, sz, 3), dtype=np.uint8)

        # บันทึกภาพต้นฉบับลงโฟลเดอร์ aoi_references
        ref_dir = Path(self.host.main_program_root) / "aoi_references"
        ref_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ref_filename = f"ref_point_{point_idx+1:03d}_{ts}.png"
        ref_path = ref_dir / ref_filename
        cv2.imwrite(str(ref_path), ref_frame)

        # ── 2. ตรวจจับชิ้นส่วนต้นแบบ (Detect Expected Baseline Components) ──
        ref_detections = []
        if self.host.model is not None:
            try:
                conf = (self.host.conf_slider.value() / 100.0) if hasattr(self.host, "conf_slider") else 0.25
                device_pref = self.host.device_combo.currentData() if hasattr(self.host, "device_combo") else "auto"
                dev = select_device(device_pref)
                imgsz = self.current_imgsz()
                predict_kwargs = {"source": str(ref_path), "conf": conf, "save": False, "device": dev.device}
                if imgsz:
                    predict_kwargs["imgsz"] = int(imgsz)
                results = self.host.model.predict(**predict_kwargs)
                for r in results:
                    for box in r.boxes:
                        cls_idx = int(box.cls[0])
                        cls_name = str(self.host.model_names.get(cls_idx, cls_idx))
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
                        confidence = float(box.conf[0])
                        ref_detections.append({
                            "id": f"P{len(ref_detections)+1}",
                            "label": cls_name,
                            "name": cls_name,
                            "conf": confidence,
                            "box": [float(x1), float(y1), float(x2), float(y2)],
                            "x": cx,
                            "y": cy,
                        })
            except Exception:
                pass

        if not hasattr(self, "marked_references"):
            self.marked_references = {}

        self.marked_references[point_idx] = {
            "point_index": point_idx + 1,
            "pos": (int(x), int(y)),
            "zoom": zoom,
            "image_path": str(ref_path),
            "image": ref_frame.copy(),
            "raw_image": raw_frame.copy() if raw_frame is not None else None,
            "detections": ref_detections,
            "timestamp": ts,
        }

        self.marked_points.append((int(x), int(y), zoom))
        
        if hasattr(self, "scan_source_combo"):
            self.scan_source_combo.blockSignals(True)
            self.scan_source_combo.setCurrentIndex(1)
            self.scan_source_combo.blockSignals(False)
        self.scan_mode = "marked"
        
        self._show_points(self.marked_points)
        self._update_mark_ui()

        # Update preview to show the captured reference
        overlay = ref_frame.copy()
        draw_detections_overlay(overlay, ref_detections)
        if hasattr(self, "_show_captured_frame"):
            self._show_captured_frame(
                overlay,
                point_info=f"Reference #{point_idx+1} ({zoom:.1f}x)",
                verdict="REFERENCE",
                num_components=len(ref_detections),
                is_bgr=True
            )

        comp_msg = f" (พบต้นแบบ {len(ref_detections)} ชิ้นส่วน)" if ref_detections else ""
        self.status.setText(
            f"📍 มาร์คจุดที่ {len(self.marked_points)}: ถ่ายต้นฉบับสำเร็จ{comp_msg} · "
            f"X={x/scale:.3f} mm, Y={y/scale:.3f} mm · ซูม {zoom:.1f}x (รวม {len(self.marked_points)} จุด)"
        )

    def delete_selected_point(self, index=None):
        if self.active:
            self.error("กำลังทำการตรวจจับอยู่ ไม่สามารถลบจุดระหว่างตรวจได้")
            return

        if not getattr(self, "marked_points", None):
            self.error("ยังไม่มีจุดที่มาร์คไว้ให้ลบ")
            return

        if index is None:
            rows = self.table.selectedItems()
            if rows:
                index = rows[0].row()
            elif hasattr(self, "viewed_point_index") and 0 <= self.viewed_point_index < len(self.marked_points):
                index = self.viewed_point_index
            else:
                index = len(self.marked_points) - 1

        if index < 0 or index >= len(self.marked_points):
            self.error(f"ไม่พบจุดที่ #{index+1}")
            return

        removed_pt = self.marked_points.pop(index)

        # Re-index marked_references so keys remain 0, 1, ..., n-1
        if hasattr(self, "marked_references"):
            new_refs = {}
            for k, ref in sorted(self.marked_references.items()):
                if k < index:
                    new_refs[k] = ref
                elif k > index:
                    ref["point_index"] = k
                    new_refs[k - 1] = ref
            self.marked_references = new_refs

        # Re-index report results if any
        if hasattr(self, "report") and isinstance(self.report, dict) and "results" in self.report:
            results = self.report["results"]
            if 0 <= index < len(results):
                results.pop(index)
                for idx, res in enumerate(results):
                    res["point_index"] = idx + 1

        self._show_points(self.marked_points)
        self._update_mark_ui()

        new_len = len(self.marked_points)
        if new_len > 0:
            new_sel = min(index, new_len - 1)
            self.table.selectRow(new_sel)
            self._preview_point_image(new_sel)
        else:
            self.viewed_point_index = 0
            if hasattr(self, "captured_preview"):
                self.captured_preview.setText("ยังไม่มีภาพถ่าย (No capture yet)\nเมื่อสแกนหรือกดถ่ายรูป ภาพ 4K จะมาแสดงที่นี่")
            if hasattr(self, "cap_page_lbl"):
                self.cap_page_lbl.setText("จุดที่ — / —")

        scale = self.scale.value() if self.scale.value() > 0 else 512.0
        self.status.setText(
            f"🗑 ลบจุดที่ #{index+1} (X={removed_pt[0]/scale:.3f}, Y={removed_pt[1]/scale:.3f}) เรียบร้อยแล้ว "
            f"(เหลือจุดที่มาร์คไว้ {new_len} จุด)"
        )

    def remove_last_marked_point(self):
        if not self.marked_points:
            return
        self.delete_selected_point(len(self.marked_points) - 1)

    def _on_table_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item:
            return
        row = item.row()
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #0f172a;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px;
                font-size: 11px;
            }
            QMenu::item {
                padding: 6px 14px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: #1e3a5f;
                color: #38bdf8;
            }
        """)
        act_goto = menu.addAction(f"🎯 เลื่อนกล้องไปจุดที่ #{row+1}")
        act_ref = menu.addAction(f"👁 ดูภาพต้นฉบับจุดที่ #{row+1}")
        menu.addSeparator()
        act_del = menu.addAction(f"🗑 ลบจุดที่ #{row+1}")

        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == act_goto:
            self.table.selectRow(row)
            self.move_to_selected_point()
        elif action == act_ref:
            self.table.selectRow(row)
            self.view_selected_point_reference()
        elif action == act_del:
            self.delete_selected_point(row)

    def _on_filmstrip_context_menu(self, global_pos, idx):
        if idx < 0 or not getattr(self, "points", None) or idx >= len(self.points):
            return
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #0f172a;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px;
                font-size: 11px;
            }
            QMenu::item {
                padding: 6px 14px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background: #1e3a5f;
                color: #38bdf8;
            }
        """)
        act_view = menu.addAction(f"👁 ดูภาพจุดที่ #{idx+1}")
        act_goto = menu.addAction(f"🎯 เลื่อนกล้องไปจุดที่ #{idx+1}")
        menu.addSeparator()
        act_del = menu.addAction(f"🗑 ลบจุดที่ #{idx+1}")

        action = menu.exec(global_pos)
        if action == act_view:
            self.select_point(idx)
        elif action == act_goto:
            self.select_point(idx)
            self.move_to_selected_point()
        elif action == act_del:
            self.delete_selected_point(idx)

    def clear_marked_points(self):
        if not self.marked_points:
            return
        self.marked_points.clear()
        if hasattr(self, "marked_references"):
            self.marked_references.clear()
        self._show_points([])
        self._update_mark_ui()
        self.status.setText("🗑 ล้างรายการจุดที่มาร์คไว้ทั้งหมดเรียบร้อยแล้ว")

    def view_selected_point_reference(self):
        rows = self.table.selectedItems()
        if not rows:
            if getattr(self, "marked_points", None):
                row = 0
            else:
                self.error("ยังไม่มีจุดที่เลือก กรุณาเลือกจุดในตาราง")
                return
        else:
            row = rows[0].row()
        if not hasattr(self, "marked_references") or row not in self.marked_references:
            self.error(f"จุดที่ #{row+1} ยังไม่มีภาพต้นฉบับ")
            return
        ref_data = self.marked_references[row]
        img = ref_data.get("image")
        if img is None and ref_data.get("image_path") and Path(ref_data["image_path"]).exists():
            img = cv2.imread(ref_data["image_path"])
        if img is not None:
            overlay = img.copy()
            draw_detections_overlay(overlay, ref_data.get("detections", []))
            cnt = len(ref_data.get("detections", []))
            zoom = ref_data.get("zoom", 1.0)
            self._set_view_mode("captured")
            self._show_captured_frame(
                overlay,
                point_info=f"Reference #{row+1} ({zoom:.1f}x)",
                verdict="REFERENCE",
                num_components=cnt,
                is_bgr=True
            )
            self.status.setText(f"📸 แสดงภาพต้นฉบับจุดที่ #{row+1} (พบชิ้นส่วนต้นแบบ {cnt} ชิ้น)")

    def move_to_selected_point(self):
        rows = self.table.selectedItems()
        if not rows:
            self.error("กรุณาเลือกจุดในตารางที่ต้องการเลื่อนไป")
            return
        row = rows[0].row()
        if not getattr(self, "points", None) or row >= len(self.points):
            return
        if self.active:
            self.error("กำลังทำการสแกนอยู่ ไม่สามารถเลื่อนแบบแมนนวลได้")
            return
        if not self.machine or not self.machine.ready:
            self.error("เครื่องจักรยังไม่ได้เชื่อมต่อ")
            return
        pt = self.points[row]
        target_x, target_y = pt[0], pt[1]
        zoom = pt[2] if len(pt) > 2 else 1.0
        self.command("MOVE", target_x, target_y)
        if hasattr(self, "live_zoom_spin"):
            self.live_zoom_spin.setValue(zoom)
        scale = self.scale.value() if self.scale.value() > 0 else 512.0
        self.status.setText(f"🎯 กำลังเลื่อนกล้องไปยังจุดที่ {row+1} (X={target_x/scale:.3f} mm, Y={target_y/scale:.3f} mm · ซูม {zoom:.1f}x)...")

    def _ensure_marked_references_detected(self, force=False):
        """If model was loaded after points were marked or resolution changed, re-detect components on saved reference images."""
        if not self.host.model or not hasattr(self, "marked_references"):
            return
        conf = (self.host.conf_slider.value() / 100.0) if hasattr(self.host, "conf_slider") else 0.25
        device_pref = self.host.device_combo.currentData() if hasattr(self.host, "device_combo") else "auto"
        dev = select_device(device_pref)
        imgsz = self.current_imgsz()
        for idx, ref in self.marked_references.items():
            if force or not ref.get("detections"):
                if force and ref.get("raw_image") is not None:
                    img = self._process_frame_for_active_resolution(ref["raw_image"], zoom=ref.get("zoom", 1.0))
                    ref["image"] = img
                    if ref.get("image_path"):
                        cv2.imwrite(ref["image_path"], img)
                else:
                    img = ref.get("image")
                    if img is None and ref.get("image_path") and Path(ref["image_path"]).exists():
                        img = cv2.imread(ref["image_path"])
                if img is not None:
                    try:
                        src = str(ref["image_path"]) if ref.get("image_path") and Path(ref["image_path"]).exists() else img
                        predict_kwargs = {"source": src, "conf": conf, "save": False, "device": dev.device}
                        if imgsz:
                            predict_kwargs["imgsz"] = int(imgsz)
                        results = self.host.model.predict(**predict_kwargs)
                        dets = []
                        for r in results:
                            for box in r.boxes:
                                cls_idx = int(box.cls[0])
                                cls_name = str(self.host.model_names.get(cls_idx, cls_idx))
                                x1, y1, x2, y2 = box.xyxy[0].tolist()
                                cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
                                dets.append({
                                    "id": f"P{len(dets)+1}",
                                    "label": cls_name,
                                    "name": cls_name,
                                    "conf": float(box.conf[0]),
                                    "box": [float(x1), float(y1), float(x2), float(y2)],
                                    "x": cx,
                                    "y": cy,
                                })
                        ref["detections"] = dets
                    except Exception:
                        pass

    def start_replay_marked_scan(self):
        if not self.marked_points:
            self.error("ยังไม่มีจุดที่มาร์คไว้ กรุณาเลื่อนกล้องแล้วกด '➕ มาร์คจุดนี้' อย่างน้อย 1 จุดก่อน")
            return
        if hasattr(self, "scan_source_combo"):
            self.scan_source_combo.blockSignals(True)
            self.scan_source_combo.setCurrentIndex(1)
            self.scan_source_combo.blockSignals(False)
        self.scan_mode = "marked"
        self._ensure_marked_references_detected()
        self.start_scan(teach=False)

    def _update_mark_ui(self):
        count = len(self.marked_points)
        if hasattr(self, "lbl_mark_count"):
            if count == 0:
                self.lbl_mark_count.setText("ยังไม่มีจุดที่มาร์คไว้ (0 จุด)")
                self.lbl_mark_count.setStyleSheet("color: #94a3b8; font-size: 11px;")
            else:
                self.lbl_mark_count.setText(f"📌 มาร์คไว้แล้ว {count} จุด (พร้อมตรวจ Component ครบ)")
                self.lbl_mark_count.setStyleSheet("color: #38bdf8; font-size: 11px; font-weight: 700;")
        if hasattr(self, "btn_replay_marks"):
            tf = self.multiframe_spin.value() if hasattr(self, "multiframe_spin") else 10
            is_mf = self.check_multiframe.isChecked() if hasattr(self, "check_multiframe") else True
            tag = f" ({tf}F)" if is_mf else ""
            if count > 0:
                self.btn_replay_marks.setText(f"▶ Replay ตรวจ Component ครบ{tag} · {count} จุด")
            else:
                self.btn_replay_marks.setText(f"▶ Replay ตรวจ Component ครบ{tag} (0 จุด)")
        self._controls()

    def _on_scan_source_changed(self, index):
        mode = self.scan_source_combo.currentData()
        self.scan_mode = mode
        if mode == "marked":
            self._show_points(self.marked_points)
            self.status.setText(f"เลือกโหมด: ถ่ายตามจุดที่มาร์คไว้ ({len(self.marked_points)} จุด)")
        else:
            try:
                self.preview_plan()
            except Exception as exc:
                self.status.setText(f"โหมดตารางสแกน: {exc}")

    def plan(self):
        if not self.machine or not self.machine.ready:
            raise ValueError("Connect to load travel limits first.")
        
        mode = getattr(self, "scan_mode", "marked")
        if hasattr(self, "scan_source_combo"):
            mode = self.scan_source_combo.currentData()

        if mode == "marked":
            if not getattr(self, "marked_points", None):
                raise ValueError("ยังไม่มีจุดที่มาร์คไว้ กรุณาเลื่อนกล้องแล้วกด '➕ มาร์คจุดนี้' ก่อน หรือสลับเป็นโหมด 'ตามตารางสแกน'")
            return list(self.marked_points)

        return raster_points(self.origin_x.value(), self.origin_y.value(), self.columns.value(),
                             self.rows.value(), self.pitch_x.value(), self.pitch_y.value(),
                             self.scale.value(), self.effective_limits())

    def preview_plan(self):
        try:
            if hasattr(self, "scan_source_combo"):
                self.scan_source_combo.blockSignals(True)
                self.scan_source_combo.setCurrentIndex(0)
                self.scan_source_combo.blockSignals(False)
            self.scan_mode = "grid"
            points = raster_points(self.origin_x.value(), self.origin_y.value(), self.columns.value(),
                                 self.rows.value(), self.pitch_x.value(), self.pitch_y.value(),
                                 self.scale.value(), self.effective_limits())
            self._show_points(points)
            self.status.setText(f"{len(points)} points · serpentine path · first move goes to the scan origin")
        except Exception as exc:
            self.error(str(exc))

    def _show_points(self, points):
        self.points = points
        self.table.setRowCount(len(points))
        for index, pt in enumerate(points):
            x, y = pt[0], pt[1]
            zoom = pt[2] if len(pt) > 2 else 1.0
            status_text = "Pending"
            comp_text = ""
            if getattr(self, "scan_mode", "grid") == "marked" and hasattr(self, "marked_references") and index in self.marked_references:
                cnt = len(self.marked_references[index].get("detections", []))
                status_text = f"Ref ({cnt} comp)"
                comp_text = str(cnt)
            row_vals = (index+1, f"{x/self.scale.value():.3f}", f"{y/self.scale.value():.3f}", status_text, comp_text, f"{zoom:.1f}x")
            for col, value in enumerate(row_vals):
                self.table.setItem(index, col, QTableWidgetItem(str(value)))
        if hasattr(self, "_update_filmstrip"):
            self._update_filmstrip()
        if hasattr(self, "_update_navigation_controls"):
            self._update_navigation_controls()

    def load_reference(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load completed golden-board report", "", "AOI report (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text())
            if data.get("schema") != 1 or data.get("mode") != "teach" or data.get("status") != "complete":
                raise ValueError("Select a completed golden-board report.json.")
            if not data.get("results") or len(data["results"]) != len(data["points"]):
                raise ValueError("Reference does not contain every point.")
            for item in data["results"]:
                for det in item["detections"]:
                    if not isinstance(det["label"], str) or not all(math.isfinite(det[k]) and det[k] >= 0 for k in ("x", "y")):
                        raise ValueError("Invalid reference coordinates")
            self.profile = data
            self.reference_label.setText(f"Reference: {path}")
        except Exception as exc:
            self.error(f"Cannot load reference: {exc}")

    def signature(self, points):
        eff_x, eff_y = self.effective_limits()
        scale = self.scale.value()
        return {"points": [list(p) for p in points], "steps_per_mm": self.scale.value(),
                "simulation": self.mode.currentIndex() == 0, "travel_steps": list(self.machine.limits),
                "soft_limits_mm": [round(eff_x / scale, 3), round(eff_y / scale, 3)],
                "model": self.host.current_model_path, "classes": self.host.model_names,
                "confidence": self.host.conf_slider.value()/100, "camera_index": self.camera_index.value(),
                "requested_resolution": list(self.resolution.currentData())}

    def start_scan(self, teach=False):
        try:
            if self.active or (self.inference and self.inference.isRunning()):
                raise ValueError("Wait for the current inspection to finish.")
            points = self.plan()
            if not self.machine.homed or self.machine.pending:
                raise ValueError("HOME must complete before scanning.")
            if self.host.model is None:
                raise ValueError("Load a detection model in PCB Inspect first.")
            snapshot = self.camera.snapshot() if self.camera else None
            if snapshot is None or time.monotonic() - snapshot[0] > 2:
                raise ValueError("Start the camera and wait for a fresh preview.")
            signature = self.signature(points)
            if not teach and getattr(self, "scan_mode", "grid") != "marked" and self.profile and json.dumps(self.profile["signature"], sort_keys=True) != json.dumps(signature, sort_keys=True):
                raise ValueError("Reference settings differ from this scan. Use the same points, camera, model and confidence.")
            folder = Path(self.host.main_program_root) / "aoi_runs" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            folder.mkdir(parents=True, exist_ok=False)
            self.run_folder = folder
            self.report = {"schema": 1, "mode": "teach" if teach else "inspect", "status": "running",
                           "simulation": self.mode.currentIndex() == 0, "signature": signature,
                           "points": [list(p) for p in points], "results": [], "match_distance_px": self.match.value(),
                           "started_at": datetime.now().isoformat()}
            self.points, self.point_index, self.active = points, 0, True
            self._show_points(points)
            self.progress.setRange(0, len(points))
            self.progress.setValue(0)
            self._save_report()
            self._next_point()
        except Exception as exc:
            self.error(str(exc))
        self._controls()

    def _next_point(self):
        if not self.active:
            return
        if self.point_index == len(self.points):
            self.report["status"] = "complete"
            self._save_report()
            self.active, self.phase = False, "idle"
            if self.report["mode"] == "teach":
                self.profile = json.loads(json.dumps(self.report))
                self.reference_label.setText(f"Golden reference captured: {self.run_folder / 'report.json'} · review detections before relying on PASS/FAIL")
            self.status.setText(f"Scan complete · {self.run_folder}")
            return
        self.phase = "moving"
        self.machine.command("MOVE", *self.points[self.point_index][:2], self.speed.value())
        self.table.item(self.point_index, 3).setText("Moving")
        self.table.selectRow(self.point_index)

    def _on_multiframe_frame_progress(self, current_frame, total_frames, detections, hits):
        if not self.active or self.phase != "inference":
            return
        ratio = (self.pass_ratio_spin.value() / 100.0) if hasattr(self, "pass_ratio_spin") else 0.8
        pass_th = max(1, math.ceil(total_frames * ratio))
        confirmed = sum(1 for h in hits if h >= pass_th)
        total_exp = len(hits)
        pt_idx = self.point_index + 1
        tot_pts = len(self.points)
        self.status.setText(
            f"🔍 จุดที่ {pt_idx}/{tot_pts}: กำลังตรวจเฟรม {current_frame}/{total_frames}... (ตรวจพบ {confirmed}/{total_exp} ชิ้นส่วน)"
        )
        if self.table and self.point_index < self.table.rowCount():
            self.table.item(self.point_index, 3).setText(f"Frame {current_frame}/{total_frames}")

    def _capture(self, snapshot):
        _, raw_frame = snapshot
        point = self.points[self.point_index]
        zoom = point[2] if len(point) > 2 else 1.0
        frame = self._process_frame_for_active_resolution(raw_frame, zoom=zoom)
        path = self.run_folder / f"point_{self.point_index+1:03d}.png"
        if not cv2.imwrite(str(path), frame):
            raise IOError("Could not save camera image")
        self.capture_path = path
        self.phase = "inference"
        self.table.item(self.point_index, 3).setText("Inspecting")
        if hasattr(self, "_show_captured_frame"):
            self._show_captured_frame(frame, point_info=f"#{self.point_index+1} ({zoom:.1f}x)", verdict="INSPECTING...", num_components=0, is_bgr=True)

        expected_components = []
        if getattr(self, "scan_mode", "grid") == "marked" and hasattr(self, "marked_references") and self.point_index in self.marked_references:
            expected_components = self.marked_references[self.point_index].get("detections", [])
        elif self.profile and "results" in self.profile and self.point_index < len(self.profile["results"]):
            expected_components = self.profile["results"][self.point_index].get("detections", [])

        target_frames = 1
        pass_threshold = None
        if (
            getattr(self, "check_multiframe", None)
            and self.check_multiframe.isChecked()
            and getattr(self, "scan_mode", "grid") == "marked"
            and self.report.get("mode") != "teach"
        ):
            target_frames = self.multiframe_spin.value() if hasattr(self, "multiframe_spin") else 10
            ratio = (self.pass_ratio_spin.value() / 100.0) if hasattr(self, "pass_ratio_spin") else 0.8
            pass_threshold = max(1, math.ceil(target_frames * ratio))

        self.inference = AOIInference(
            self.host.model,
            str(path),
            self.host.conf_slider.value() / 100,
            self.host.model_names,
            self.host.device_combo.currentData(),
            target_frames=target_frames,
            pass_threshold=pass_threshold,
            camera=self.camera,
            zoom=zoom,
            crop_func=lambda raw, z: self._process_frame_for_active_resolution(raw, zoom=z),
            expected_components=expected_components,
            imgsz=self.current_imgsz(),
        )
        if hasattr(self.inference, "frame_progress"):
            self.inference.frame_progress.connect(self._on_multiframe_frame_progress)
        self.inference.finished.connect(self._inferred)
        self.inference.error.connect(self.error)
        self.inference.start()

    def _inferred(self, detections, frame, speed):
        if not self.active or self.phase != "inference":
            return
        try:
            size = [frame.shape[1], frame.shape[0]]
            verdict, reason = "REVIEW", "No reference for this position"

            mf_res = getattr(self.inference, "multiframe_result", None) if self.inference else None

            ref_data = None
            if hasattr(self, "marked_references") and self.point_index in self.marked_references:
                ref_data = self.marked_references[self.point_index]

            if self.report["mode"] == "teach":
                verdict, reason = "REFERENCE", "Review these detections against the golden board"
            elif mf_res is not None:
                verdict, reason = mf_res["verdict"], mf_res["reason"]
            elif ref_data and ref_data.get("detections"):
                result = evaluate_inspection(ref_data["detections"], detections, self.match.value(), True)
                verdict, reason = result["verdict"], result["reason"]
            elif self.profile:
                ref = self.profile["results"][self.point_index]
                if ref["position_steps"] != list(self.points[self.point_index][:2]) or ref["image_size"] != size:
                    raise ValueError("Reference position or captured resolution differs")
                if ref["detections"]:
                    result = evaluate_inspection(ref["detections"], detections, self.match.value(), True)
                    verdict, reason = result["verdict"], result["reason"]
                else:
                    reason = "Reference contains no components; manual review required"

            overlay = frame.copy()
            if mf_res is not None:
                draw_multiframe_overlay(overlay, mf_res)
            else:
                draw_detections_overlay(overlay, detections)

            overlay_path = self.run_folder / f"point_{self.point_index+1:03d}_annotated.png"
            if not cv2.imwrite(str(overlay_path), overlay):
                raise IOError("Could not save annotated image")
            self.show_frame(overlay)
            point = self.points[self.point_index]
            zoom = point[2] if len(point) > 2 else 1.0
            num_comps = mf_res["total_expected"] if mf_res else len(detections)
            if hasattr(self, "_show_captured_frame"):
                self._show_captured_frame(overlay, point_info=f"#{self.point_index+1} ({zoom:.1f}x)", verdict=verdict, num_components=num_comps, is_bgr=True)

            res_entry = {
                "point": self.point_index+1,
                "position_steps": list(self.machine.position),
                "zoom": zoom,
                "image": self.capture_path.name,
                "annotated_image": overlay_path.name,
                "image_size": size,
                "verdict": verdict,
                "reason": reason,
                "detections": detections,
                "timings_ms": speed,
            }
            if mf_res is not None:
                res_entry["multiframe"] = {
                    "verdict": mf_res["verdict"],
                    "target_frames": mf_res["target_frames"],
                    "frames_inspected": mf_res["frames_inspected"],
                    "pass_threshold": mf_res["pass_threshold"],
                    "confirmed_count": mf_res["confirmed_count"],
                    "missing_count": mf_res["missing_count"],
                    "wrong_count": mf_res["wrong_count"],
                    "uncertain_count": mf_res["uncertain_count"],
                    "components": [
                        {
                            "label": c["expected"]["label"],
                            "hits": c["hits"],
                            "target_frames": c["target_frames"],
                            "status": c["status"],
                            "wrong_label": c["wrong_label"],
                        } for c in mf_res["components"]
                    ],
                }
            self.report["results"].append(res_entry)
            self._save_report()
            self.table.item(self.point_index, 3).setText(verdict)
            self.table.item(self.point_index, 4).setText(str(num_comps))
            self.progress.setValue(self.point_index+1)
            self.viewed_point_index = self.point_index
            self.point_index += 1
            self.phase = "next"
            self.next_at = time.monotonic() + .25
            if hasattr(self, "_update_navigation_controls"):
                self._update_navigation_controls()
            if hasattr(self, "_update_filmstrip"):
                self._update_filmstrip()
        except Exception as exc:
            self.error(str(exc))

    def _save_report(self):
        temp = self.run_folder / "report.json.tmp"
        temp.write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.run_folder / "report.json")

    def stop(self):
        was_active = self.active
        self.active, self.phase = False, "idle"
        if self.machine and self.machine.ready and not self.machine.closed:
            try:
                self.machine.command("STOP")
            except Exception:
                self.machine.close()
        if was_active and self.report:
            self.report["status"] = "aborted"
            try:
                self._save_report()
            except Exception as exc:
                self.status.setText(f"Stopped; could not save report: {exc}")
                return
        self.status.setText("Stopped. Pending capture/inference will not advance the stage.")
        self._controls()

    def error(self, message):
        self.stop()
        self.status.setText("Error: " + message)

    def _on_crosshair_toggled(self):
        snapshot = self.camera.snapshot() if self.camera else None
        if snapshot:
            self.show_frame(snapshot[1])

    def set_origin_from_current(self):
        if self.machine and self.machine.ready:
            x, y = self.machine.position
            scale = self.scale.value() if self.scale.value() > 0 else 512.0
            self.origin_x.setValue(round(x / scale, 2))
            self.origin_y.setValue(round(y / scale, 2))
            self.status.setText(f"Origin set to: X {x/scale:.2f} mm, Y {y/scale:.2f} mm")

    def _update_grid_summary(self):
        cols = self.columns.value()
        rows = self.rows.value()
        total = cols * rows
        px = self.pitch_x.value()
        py = self.pitch_y.value()
        span_x = (cols - 1) * px
        span_y = (rows - 1) * py
        if hasattr(self, "grid_summary"):
            self.grid_summary.setText(f"{total} points ({cols}×{rows}) · span {span_x:.1f} × {span_y:.1f} mm")

    def show_frame(self, frame, is_processed=False):
        if not is_processed:
            self._raw_live_frame = frame.copy()
            zoom = getattr(self, "current_live_zoom", 1.0)
            frame = self._process_frame_for_active_resolution(frame, zoom=zoom)
        else:
            self._raw_live_frame = getattr(self, "_raw_live_frame", frame)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self._last_live_frame = rgb.copy()
        if getattr(self, "check_crosshair", None) and self.check_crosshair.isChecked():
            h, w = rgb.shape[:2]
            cx, cy = w // 2, h // 2
            teal = (22, 163, 148)
            cv2.line(rgb, (cx - 30, cy), (cx - 6, cy), teal, 1, cv2.LINE_AA)
            cv2.line(rgb, (cx + 6, cy), (cx + 30, cy), teal, 1, cv2.LINE_AA)
            cv2.line(rgb, (cx, cy - 30), (cx, cy - 6), teal, 1, cv2.LINE_AA)
            cv2.line(rgb, (cx, cy + 6), (cx, cy + 30), teal, 1, cv2.LINE_AA)
            cv2.circle(rgb, (cx, cy), 6, teal, 1, cv2.LINE_AA)
        image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()
        self.preview.setPixmap(QPixmap.fromImage(image).scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                              Qt.TransformationMode.SmoothTransformation))

    def _set_view_mode(self, mode):
        self.view_mode = mode
        if mode == "dual":
            self.live_panel.show()
            self.captured_panel.show()
            self.btn_view_dual.setChecked(True)
            self.btn_view_live.setChecked(False)
            self.btn_view_captured.setChecked(False)
        elif mode == "live":
            self.live_panel.show()
            self.captured_panel.hide()
            self.btn_view_dual.setChecked(False)
            self.btn_view_live.setChecked(True)
            self.btn_view_captured.setChecked(False)
        elif mode == "captured":
            self.live_panel.hide()
            self.captured_panel.show()
            self.btn_view_dual.setChecked(False)
            self.btn_view_live.setChecked(False)
            self.btn_view_captured.setChecked(True)
        if not self.captured_panel.isHidden():
            self._render_captured_pixmap()

    def _show_captured_frame(self, frame_or_rgb, point_info="Snapshot", verdict="PASS", num_components=0, is_bgr=True):
        if is_bgr:
            rgb = cv2.cvtColor(frame_or_rgb, cv2.COLOR_BGR2RGB)
        else:
            rgb = frame_or_rgb.copy()
        self._last_captured_frame = rgb
        self._render_captured_pixmap()

        verdict_str = str(verdict).upper()
        if "PASS" in verdict_str:
            badge_style = "background: #0f2a22; color: #10b981; border: 1px solid #155e46;"
        elif "FAIL" in verdict_str:
            badge_style = "background: #2a1215; color: #ef4444; border: 1px solid #7f1d1d;"
        elif "REVIEW" in verdict_str:
            badge_style = "background: #2a1f0a; color: #f59e0b; border: 1px solid #78350f;"
        elif "REFERENCE" in verdict_str:
            badge_style = "background: #102a3a; color: #38bdf8; border: 1px solid #0369a1;"
        elif "INSPECTING" in verdict_str:
            badge_style = "background: #2a1f0a; color: #38bdf8; border: 1px solid #0369a1;"
        else:
            badge_style = "background: #1e293b; color: #94a3b8; border: 1px solid #334155;"

        self.captured_badge.setText(verdict_str)
        self.captured_badge.setStyleSheet(f"{badge_style} border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: 700;")
        self.captured_title.setText(f"📸 จุดที่ {point_info}")
        self.captured_info.setText(f"ตรวจพบ {num_components} components · Output: {rgb.shape[1]} × {rgb.shape[0]} px (ตรงตามที่เลือกไว้)")
        self.captured_info.setStyleSheet("color: #10b981; font-weight: 600; font-size: 10px; padding: 2px;")

        if getattr(self, "view_mode", "dual") == "live":
            self._set_view_mode("dual")

    def _render_captured_pixmap(self):
        if hasattr(self, "_last_captured_frame") and self._last_captured_frame is not None:
            rgb = self._last_captured_frame
            image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()
            pix = QPixmap.fromImage(image)
            target = self.captured_preview.size()
            if target.width() > 10 and target.height() > 10:
                pix = pix.scaled(target, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.captured_preview.setPixmap(pix)

    def _get_total_points(self):
        if getattr(self, "points", None) and len(self.points) > 0:
            return len(self.points)
        return self.table.rowCount()

    def _update_navigation_controls(self):
        total = self._get_total_points()
        idx = getattr(self, "viewed_point_index", 0)
        if total > 0:
            self.cap_page_lbl.setText(f"จุดที่ {idx+1} / {total}")
            self.btn_cap_prev.setEnabled(idx > 0)
            self.btn_cap_next.setEnabled(idx < total - 1)
        else:
            self.cap_page_lbl.setText("จุดที่ — / —")
            self.btn_cap_prev.setEnabled(False)
            self.btn_cap_next.setEnabled(False)

    def select_point(self, index):
        total = self._get_total_points()
        if total <= 0 or index < 0 or index >= total:
            return
        self.viewed_point_index = index
        self.table.blockSignals(True)
        self.table.selectRow(index)
        self.table.blockSignals(False)
        self._preview_point_image(index)

    def prev_captured_point(self):
        total = self._get_total_points()
        if total <= 0:
            return
        cur = getattr(self, "viewed_point_index", 0)
        if cur > 0:
            self.select_point(cur - 1)

    def next_captured_point(self):
        total = self._get_total_points()
        if total <= 0:
            return
        cur = getattr(self, "viewed_point_index", 0)
        if cur < total - 1:
            self.select_point(cur + 1)

    def _highlight_filmstrip(self, active_index):
        for card in getattr(self, "_filmstrip_cards", []):
            if getattr(card, "_point_idx", -1) == active_index:
                card.setStyleSheet("background: #1e3a5f; border: 2px solid #38bdf8; border-radius: 6px;")
                self.filmstrip_scroll.ensureWidgetVisible(card)
            else:
                card.setStyleSheet("background: #1e293b; border: 1px solid #334155; border-radius: 6px;")

    def _update_filmstrip(self):
        if not hasattr(self, "filmstrip_strip"):
            return
        while self.filmstrip_strip.count():
            item = self.filmstrip_strip.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._filmstrip_cards = []

        total = self._get_total_points()
        captured_count = 0
        cur_idx = getattr(self, "viewed_point_index", 0)

        for i in range(total):
            card = QFrame()
            card.setFixedSize(68, 62)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            c_layout = QVBoxLayout(card)
            c_layout.setContentsMargins(4, 3, 4, 3)
            c_layout.setSpacing(2)

            top_lbl = QLabel(f"#{i+1}")
            top_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            top_lbl.setStyleSheet("color: #f1f5f9; font-size: 11px; font-weight: 700;")
            c_layout.addWidget(top_lbl)

            v_text = "Pending"
            if i < self.table.rowCount():
                v_item = self.table.item(i, 3)
                if v_item and v_item.text():
                    v_text = v_item.text()

            has_img = False
            if getattr(self, "run_folder", None):
                a_p = self.run_folder / f"point_{i+1:03d}_annotated.png"
                r_p = self.run_folder / f"point_{i+1:03d}.png"
                if a_p.exists() or r_p.exists():
                    has_img = True
                    captured_count += 1

            badge = QLabel(v_text[:4].upper())
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if "PASS" in v_text.upper():
                badge.setStyleSheet("background: #0f2a22; color: #10b981; font-size: 9px; font-weight: 700; border-radius: 3px;")
            elif "FAIL" in v_text.upper():
                badge.setStyleSheet("background: #2a1215; color: #ef4444; font-size: 9px; font-weight: 700; border-radius: 3px;")
            elif "REVIEW" in v_text.upper():
                badge.setStyleSheet("background: #2a1f0a; color: #f59e0b; font-size: 9px; font-weight: 700; border-radius: 3px;")
            elif "REF" in v_text.upper():
                badge.setStyleSheet("background: #102a3a; color: #38bdf8; font-size: 9px; font-weight: 700; border-radius: 3px;")
            else:
                badge.setStyleSheet("background: #1e293b; color: #64748b; font-size: 9px; font-weight: 600; border-radius: 3px;")
            c_layout.addWidget(badge)

            card_idx = i
            def _card_press(event, idx=card_idx):
                if event.button() == Qt.MouseButton.RightButton:
                    self._on_filmstrip_context_menu(event.globalPosition().toPoint(), idx)
                else:
                    self.select_point(idx)
            card.mousePressEvent = _card_press
            card._point_idx = i
            self._filmstrip_cards.append(card)
            self.filmstrip_strip.addWidget(card)

        self.filmstrip_strip.addStretch(1)
        self.lbl_fs_count.setText(f"{captured_count}/{total} ภาพ (4K)" if total > 0 else "0 ภาพ (4K)")
        self._highlight_filmstrip(cur_idx)

    def _on_table_selection_changed(self):
        rows = self.table.selectedItems()
        if not rows:
            return
        row = rows[0].row()
        if not self.active and getattr(self, "points", None) and row < len(self.points):
            pt = self.points[row]
            zoom = pt[2] if len(pt) > 2 else 1.0
            if hasattr(self, "live_zoom_spin"):
                self.live_zoom_spin.blockSignals(True)
                self.live_zoom_spin.setValue(zoom)
                self.current_live_zoom = zoom
                self.live_zoom_spin.blockSignals(False)
                if hasattr(self, "_raw_live_frame") and self._raw_live_frame is not None:
                    self.show_frame(self._raw_live_frame)
        self._preview_point_image(row)

    def _preview_point_image(self, row):
        total = self._get_total_points()
        if total > 0 and (row < 0 or row >= total):
            return
        self.viewed_point_index = row
        self._current_viewed_image_path = None

        found_img = False
        verdict = "Pending"
        comp = "0"
        if row < self.table.rowCount():
            v_item = self.table.item(row, 3)
            if v_item and v_item.text():
                verdict = v_item.text()
            c_item = self.table.item(row, 4)
            if c_item and c_item.text():
                comp = c_item.text()

        if getattr(self, "run_folder", None):
            anno_path = self.run_folder / f"point_{row+1:03d}_annotated.png"
            raw_path = self.run_folder / f"point_{row+1:03d}.png"
            target = anno_path if anno_path.exists() else raw_path if raw_path.exists() else None
            if target and target.exists():
                img = cv2.imread(str(target))
                if img is not None:
                    self._current_viewed_image_path = target
                    self._show_captured_frame(img, point_info=f"#{row+1}", verdict=verdict, num_components=comp, is_bgr=True)
                    found_img = True

        if not found_img and getattr(self, "profile", None) and "results" in self.profile and row < len(self.profile["results"]):
            res = self.profile["results"][row]
            verdict = res.get("verdict", verdict)
            det_count = len(res.get("detections", []))
            comp = str(det_count)
            if getattr(self, "run_folder", None):
                img_name = res.get("annotated_image") or res.get("image")
                if img_name:
                    p = self.run_folder / img_name
                    if p.exists():
                        img = cv2.imread(str(p))
                        if img is not None:
                            self._current_viewed_image_path = p
                            self._show_captured_frame(img, point_info=f"#{row+1}", verdict=verdict, num_components=comp, is_bgr=True)
                            found_img = True

        if not found_img and hasattr(self, "marked_references") and row in self.marked_references:
            ref_data = self.marked_references[row]
            img = ref_data.get("image")
            if img is None and ref_data.get("image_path") and Path(ref_data["image_path"]).exists():
                img = cv2.imread(ref_data["image_path"])
            if img is not None:
                overlay = img.copy()
                draw_detections_overlay(overlay, ref_data.get("detections", []))
                cnt = str(len(ref_data.get("detections", [])))
                zoom = ref_data.get("zoom", 1.0)
                if ref_data.get("image_path"):
                    self._current_viewed_image_path = Path(ref_data["image_path"])
                self._show_captured_frame(
                    overlay,
                    point_info=f"Reference #{row+1} ({zoom:.1f}x)",
                    verdict="REFERENCE",
                    num_components=cnt,
                    is_bgr=True
                )
                found_img = True

        if not found_img:
            self.captured_preview.setText(f"จุดที่ #{row+1}\n(ยังไม่ได้ถ่ายหรือรอคิวตรวจสอบ)")
            self.captured_badge.setText(verdict.upper())
            self.captured_badge.setStyleSheet("background: #1e293b; color: #94a3b8; border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: 700;")
            self.captured_title.setText(f"📸 จุดที่ #{row+1}")
            self.captured_info.setText("ยังไม่มีภาพถ่ายสำหรับจุดนี้")
            self._last_captured_frame = None

        self._update_navigation_controls()
        self._highlight_filmstrip(row)

    def view_full_4k_image(self):
        img_to_show = None
        if getattr(self, "_current_viewed_image_path", None) and self._current_viewed_image_path.exists():
            img_to_show = str(self._current_viewed_image_path)
        elif getattr(self, "run_folder", None) and self.run_folder.exists():
            cur = getattr(self, "viewed_point_index", 0)
            a_p = self.run_folder / f"point_{cur+1:03d}_annotated.png"
            r_p = self.run_folder / f"point_{cur+1:03d}.png"
            if a_p.exists():
                img_to_show = str(a_p)
            elif r_p.exists():
                img_to_show = str(r_p)

        # Fallback 1: check most recent run folder in aoi_runs if none active in session
        if img_to_show is None and (not getattr(self, "run_folder", None) or not self.run_folder.exists()):
            runs_dir = Path("aoi_runs")
            if runs_dir.exists():
                subdirs = sorted([p for p in runs_dir.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
                if subdirs:
                    latest = subdirs[0]
                    cur = getattr(self, "viewed_point_index", 0)
                    a_p = latest / f"point_{cur+1:03d}_annotated.png"
                    r_p = latest / f"point_{cur+1:03d}.png"
                    if a_p.exists():
                        img_to_show = str(a_p)
                    elif r_p.exists():
                        img_to_show = str(r_p)

        # Fallback 2: in-memory _last_captured_frame
        if img_to_show is None and getattr(self, "_last_captured_frame", None) is not None:
            img_to_show = self._last_captured_frame

        # Fallback 3: live camera snapshot
        if img_to_show is None and getattr(self, "camera", None):
            snap = self.camera.snapshot()
            if snap and (time.monotonic() - snap[0] <= 2):
                img_to_show = cv2.cvtColor(snap[1], cv2.COLOR_BGR2RGB)

        if img_to_show is not None:
            cur = getattr(self, "viewed_point_index", 0)
            dlg = Full4KViewerDialog(img_to_show, title=f"จุดตรวจสอบที่ #{cur+1}", parent=self)
            dlg.exec()
        else:
            QMessageBox.information(
                self,
                "ภาพ 4K",
                "ยังไม่มีภาพ 4K สำหรับจุดนี้\n\nคำแนะนำ:\n• กด 'Start AOI Scan' เพื่อเริ่มสแกนบันทึกภาพ 4K ทุกจุด\n• หรือกด '📸 ถ่ายภาพทดสอบ (Test Snap)' เพื่อดูภาพสดปัจจุบัน"
            )

    def open_run_folder(self):
        import subprocess, sys
        folder = getattr(self, "run_folder", None)
        if not folder or not folder.exists():
            runs_dir = Path("aoi_runs")
            if runs_dir.exists():
                folder = runs_dir
        if folder and folder.exists():
            try:
                if sys.platform == "darwin":
                    subprocess.Popen(["open", str(folder.resolve())])
                elif sys.platform == "win32":
                    subprocess.Popen(["explorer", str(folder.resolve())])
                else:
                    subprocess.Popen(["xdg-open", str(folder.resolve())])
            except Exception as exc:
                QMessageBox.warning(self, "เปิดโฟลเดอร์", f"ไม่สามารถเปิดโฟลเดอร์ได้: {exc}")
        else:
            QMessageBox.information(self, "โฟลเดอร์ภาพ 4K", "ยังไม่มีโฟลเดอร์เก็บภาพ 4K ในขณะนี้")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Left:
            self.prev_captured_point()
            event.accept()
        elif event.key() == Qt.Key.Key_Right:
            self.next_captured_point()
            event.accept()
        else:
            super().keyPressEvent(event)

    def snap_and_inspect(self):
        snapshot = self.camera.snapshot() if self.camera else None
        if not snapshot or time.monotonic() - snapshot[0] > 2:
            self.status.setText("Camera not ready or frame stale. Start camera first.")
            return
        raw_frame = snapshot[1]
        zoom = getattr(self, "current_live_zoom", 1.0)
        frame = self._process_frame_for_active_resolution(raw_frame, zoom=zoom)
        if self.host.model is not None:
            self.captured_info.setText("Analyzing image with YOLO model…")
            try:
                conf = self.host.conf_slider.value() / 100.0 if hasattr(self.host, "conf_slider") else 0.25
                device = self.host.device_combo.currentData() if hasattr(self.host, "device_combo") else "auto"
                imgsz = self.current_imgsz()
                predict_kwargs = {
                    "source": frame,
                    "conf": conf,
                    "device": device,
                    "verbose": False,
                }
                if imgsz:
                    predict_kwargs["imgsz"] = int(imgsz)
                results = self.host.model.predict(**predict_kwargs)
                detections = []
                if results and len(results) > 0:
                    r = results[0]
                    boxes = r.boxes
                    for i in range(len(boxes)):
                        xyxy = boxes.xyxy[i].cpu().numpy().tolist()
                        cls_id = int(boxes.cls[i].item())
                        conf_val = float(boxes.conf[i].item())
                        names = getattr(self.host, "model_names", None)
                        name = names.get(cls_id, str(cls_id)) if names else str(cls_id)
                        detections.append({
                            "label": name,
                            "conf": conf_val,
                            "box": [xyxy[0], xyxy[1], xyxy[2] - xyxy[0], xyxy[3] - xyxy[1]],
                            "x": (xyxy[0] + xyxy[2]) / 2,
                            "y": (xyxy[1] + xyxy[3]) / 2,
                        })
                overlay = frame.copy()
                draw_detections_overlay(overlay, detections)
                pos = self.machine.position if (self.machine and self.machine.ready) else (0, 0)
                scale = self.scale.value() if self.scale.value() > 0 else 512.0
                point_desc = f"Snap (X {pos[0]/scale:.2f}, Y {pos[1]/scale:.2f} mm)"
                self._show_captured_frame(overlay, point_info=point_desc, verdict="TEST SNAP", num_components=len(detections), is_bgr=True)
                self.status.setText(f"Snapshot analyzed: {len(detections)} components detected ({frame.shape[1]}×{frame.shape[0]} px).")
            except Exception as e:
                self._show_captured_frame(frame, point_info="Snapshot", verdict="RAW", num_components=0, is_bgr=True)
                self.status.setText(f"Snapshot taken (Inference error: {e})")
        else:
            self._show_captured_frame(frame, point_info="Snapshot", verdict="RAW", num_components=0, is_bgr=True)
            self.status.setText(f"Snapshot captured ({frame.shape[1]}×{frame.shape[0]} px · No YOLO model loaded).")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render_captured_pixmap()

    def _tick(self):
        try:
            if self.machine:
                self.machine.tick()
                events, self.machine.events = self.machine.events, []
                for event, value in events:
                    if event == "wire":
                        self.wire_log.appendPlainText(value)
                    elif event == "error":
                        self.error(f"{self.endpoint}: {value}")
                        self.log_btn.setChecked(True)
                    elif event == "ready":
                        self._on_machine_ready()
                        self.status.setText(f"Connected: {self.endpoint} · firmware v2 replied · HOME before scanning.")
                    elif event == "done" and value == "MOVE" and self.active and self.phase == "moving":
                        self.phase = "settling"
                        self.fresh_after = time.monotonic() + self.settle.value()
                        self.capture_deadline = self.fresh_after + 5
                        self.table.item(self.point_index, 3).setText("Settling")
                if self.machine.ready:
                    x, y = self.machine.position
                    mx, my = self.machine.limits
                    eff_x, eff_y = self.effective_limits()
                    scale = self.scale.value()
                    self.position_label.setText(
                        f"{'SIMULATION' if self.mode.currentIndex()==0 else 'HARDWARE'} · "
                        f"X {x/scale:.3f} / Y {y/scale:.3f} mm · "
                        f"travel {mx/scale:.2f} × {my/scale:.2f} mm (soft {eff_x/scale:.2f} × {eff_y/scale:.2f} mm) · "
                        f"{'HOMED' if self.machine.homed else 'HOME REQUIRED'}"
                    )
                    if hasattr(self, "pos_display"):
                        self.pos_display.setText(f"X: {x/scale:.3f} mm    Y: {y/scale:.3f} mm")
                else:
                    self.position_label.setText("Disconnected" if self.machine.closed else "Connecting…")
                    if hasattr(self, "pos_display"):
                        self.pos_display.setText("X: — mm    Y: — mm")
            snapshot = self.camera.snapshot() if self.camera else None
            if self.camera and not self.camera.isRunning():
                self.camera = None
                self.camera_btn.setText("Start camera")
                if self.active:
                    raise IOError("Camera stopped during scan")
            now = time.monotonic()
            if snapshot and now-snapshot[0] < 2:
                raw_frame = snapshot[1]
                zoom = getattr(self, "current_live_zoom", 1.0)
                frame = self._process_frame_for_active_resolution(raw_frame, zoom=zoom)
                sz_str = f"{frame.shape[1]} × {frame.shape[0]} px"
                sensor_str = f"{raw_frame.shape[1]}×{raw_frame.shape[0]}"
                self.camera_info.setText(f"Live: {sz_str} (ที่เลือกไว้) · Sensor: {sensor_str}")
                self.camera_info.setStyleSheet("color: #38bdf8; font-weight: 700; font-size: 10px;")
                if now-self.last_preview > .15 and self.phase not in ("inference", "next"):
                    self.show_frame(frame, is_processed=True)
                    self.last_preview = now
            if self.active and self.phase == "settling":
                if snapshot and snapshot[0] >= self.fresh_after:
                    self._capture(snapshot)
                elif now > self.capture_deadline:
                    raise IOError("No fresh camera frame after stage settled")
            elif self.active and self.phase == "next" and now >= self.next_at and not self.inference.isRunning():
                self._next_point()
        except Exception as exc:
            self.error(str(exc))
        self._controls()
        if self.closing and not (self.camera and self.camera.isRunning()) and not (self.inference and self.inference.isRunning()):
            self.timer.stop()
            super().reject()

    def _controls(self):
        connected = bool(self.machine and not self.machine.closed)
        ready = bool(connected and self.machine.ready)
        busy = bool(self.active or (self.inference and self.inference.isRunning()))
        idle = bool(ready and not self.machine.pending and not busy and not self.closing)
        homed = bool(self.machine and self.machine.homed)
        self.connect_btn.setText("Disconnect" if connected else "Connect")
        self.connect_btn.setEnabled(not self.closing)
        if not connected:
            self.connect_btn.setStyleSheet("background: #0d9488; color: #ffffff; font-weight: 700; border: 1px solid #14b8a6;")
        else:
            self.connect_btn.setStyleSheet("")
        self.mode.setEnabled(not connected and not busy)
        self.port.setEnabled(not connected and not busy)
        self.refresh_btn.setEnabled(not connected and not busy)
        self.settings.setEnabled(not busy and not self.closing)
        self.home_btn.setEnabled(idle)
        if idle and not homed:
            self.home_btn.setStyleSheet("background: #0284c7; color: #ffffff; font-weight: 700; border: 1px solid #38bdf8;")
        else:
            self.home_btn.setStyleSheet("")
        self.off_btn.setEnabled(idle)
        for btn in self.jog_buttons:
            btn.setEnabled(idle and homed)
        if hasattr(self, "set_origin_btn"):
            self.set_origin_btn.setEnabled(idle and homed)
        self.scale.setEnabled(not connected)
        self.camera_index.setEnabled(not self.camera)
        self.resolution.setEnabled(not self.camera)
        for btn in (self.scan_btn, self.teach_btn):
            btn.setEnabled(bool(idle and homed and self.camera and self.host.model is not None))
        self.plan_btn.setEnabled(ready and not busy)
        self.load_btn.setEnabled(not busy and not self.closing)
        if hasattr(self, "snap_btn"):
            self.snap_btn.setEnabled(bool(self.camera and self.camera.isRunning() and not busy))
        if hasattr(self, "snap_btn_jog"):
            self.snap_btn_jog.setEnabled(bool(self.camera and self.camera.isRunning() and not busy))
        if hasattr(self, "btn_mark_point"):
            self.btn_mark_point.setEnabled(idle and (homed or self.mode.currentIndex() == 0))
        has_marks = bool(len(getattr(self, "marked_points", [])) > 0)
        if hasattr(self, "btn_delete_point"):
            self.btn_delete_point.setEnabled(not busy and has_marks)
        if hasattr(self, "btn_delete_point_tab"):
            self.btn_delete_point_tab.setEnabled(not busy and has_marks)
        if hasattr(self, "btn_remove_mark"):
            self.btn_remove_mark.setEnabled(not busy and has_marks)
        if hasattr(self, "btn_clear_marks"):
            self.btn_clear_marks.setEnabled(not busy and has_marks)
        if hasattr(self, "btn_view_ref"):
            self.btn_view_ref.setEnabled(not busy and len(getattr(self, "marked_references", {})) > 0)
        if hasattr(self, "btn_replay_marks"):
            self.btn_replay_marks.setEnabled(bool(idle and (homed or self.mode.currentIndex() == 0) and self.camera and self.host.model is not None and len(getattr(self, "marked_points", [])) > 0))
        if hasattr(self, "btn_goto_point"):
            self.btn_goto_point.setEnabled(idle and (homed or self.mode.currentIndex() == 0) and len(getattr(self, "points", [])) > 0)
        if hasattr(self, "btn_update_zoom"):
            self.btn_update_zoom.setEnabled(not busy and len(getattr(self, "points", [])) > 0)
        if hasattr(self, "live_zoom_spin"):
            self.live_zoom_spin.setEnabled(not busy)
        if hasattr(self, "model_combo"):
            self.model_combo.setEnabled(not busy)
        if hasattr(self, "btn_browse_model"):
            self.btn_browse_model.setEnabled(not busy)
        if hasattr(self, "btn_browse_folder"):
            self.btn_browse_folder.setEnabled(not busy)
        if hasattr(self, "btn_open_model_folder"):
            self.btn_open_model_folder.setEnabled(not busy)
        if hasattr(self, "btn_refresh_models"):
            self.btn_refresh_models.setEnabled(not busy)
        if hasattr(self, "aoi_device_combo"):
            self.aoi_device_combo.setEnabled(not busy)
        if hasattr(self, "aoi_conf_spin"):
            self.aoi_conf_spin.setEnabled(not busy)
        if hasattr(self, "aoi_imgsz_combo"):
            self.aoi_imgsz_combo.setEnabled(not busy)

        if hasattr(self, "conn_badge"):
            if not connected:
                self.conn_badge.setText("● DISCONNECTED")
                self.conn_badge.setStyleSheet("background: #2a1215; color: #ef4444; border: 1px solid #7f1d1d; border-radius: 6px; padding: 5px 12px; font-weight: 700; font-size: 11px;")
            elif not ready:
                self.conn_badge.setText("● CONNECTING...")
                self.conn_badge.setStyleSheet("background: #2a1f0a; color: #f59e0b; border: 1px solid #78350f; border-radius: 6px; padding: 5px 12px; font-weight: 700; font-size: 11px;")
            elif not homed:
                self.conn_badge.setText("● HOME REQUIRED")
                self.conn_badge.setStyleSheet("background: #2a1f0a; color: #f59e0b; border: 1px solid #78350f; border-radius: 6px; padding: 5px 12px; font-weight: 700; font-size: 11px;")
            else:
                self.conn_badge.setText("● MACHINE READY · HOMED")
                self.conn_badge.setStyleSheet("background: #0f2a22; color: #10b981; border: 1px solid #155e46; border-radius: 6px; padding: 5px 12px; font-weight: 700; font-size: 11px;")

    def reject(self):
        if not self.closing:
            self.closing = True
            self.stop()
            if self.machine:
                self.machine.close()
            if self.camera:
                self.camera.requestInterruption()
            self.status.setText("Stopping camera and waiting for inference to finish…")
        self._controls()

    def closeEvent(self, event):
        event.ignore()
        self.reject()
