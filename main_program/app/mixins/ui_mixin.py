import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QFrame,
)

from ..styles import get_stylesheet, reference_label_style, tokens_for
from ..widgets import ReferenceLabel, ElidedLabel
from ..components import YieldBar, BusyOverlay, CollapsibleCard, ToggleSwitch


class UIMixin:
    """Inspection workspace with dedicated command, metric and canvas regions."""

    def init_ui(self):
        self._toggle_switches = []

        self.main_widget = QWidget()
        self.main_widget.setObjectName("rootWidget")
        self.setCentralWidget(self.main_widget)

        outer = QVBoxLayout(self.main_widget)
        outer.setContentsMargins(20, 16, 20, 12)
        outer.setSpacing(12)

        self.build_topbar()
        outer.addWidget(self.topbar)
        self.build_metrics_strip()
        outer.addWidget(self.metrics_strip)

        body = QHBoxLayout()
        body.setSpacing(14)
        outer.addLayout(body, 1)

        self.build_left_panel()
        body.addWidget(self.left_scroll, 0)

        self.build_center_column()
        body.addWidget(self.center_widget, 1)

        self.build_right_panel()
        body.addWidget(self.right_panel, 0)

        self._build_statusbar()
        self.update_nav_controls()
        self._update_action_buttons()
        self._update_zoom_controls_enabled()
        self.apply_responsive_layout()

    def apply_responsive_layout(self):
        """Keep setup and component details compact while prioritizing the canvas."""
        width = self.width()

        if width > 0 and hasattr(self, "left_scroll"):
            self.left_scroll.setFixedWidth(max(280, min(320, round(width * 0.21))))

        if width > 0 and hasattr(self, "right_panel"):
            self.right_panel.setFixedWidth(max(248, min(300, round(width * 0.20))))


    # ────────────────────────────────────────────────────────── top bar
    def build_topbar(self):
        self.topbar = QFrame()
        self.topbar.setObjectName("topBar")
        self.topbar.setFixedHeight(68)
        row = QHBoxLayout(self.topbar)
        row.setContentsMargins(16, 8, 16, 8)
        row.setSpacing(10)
        self.btn_toggle_left = QPushButton("☰")
        self.btn_toggle_left.setObjectName("iconBtn")
        self.btn_toggle_left.setToolTip("Show / hide inspection setup")
        self.btn_toggle_left.setAccessibleName("Toggle inspection setup")
        self.btn_toggle_left.clicked.connect(self.toggle_left_panel)
        row.addWidget(self.btn_toggle_left)
        self.logo_label = QLabel()
        self.logo_label.setObjectName("appLogo")
        self.logo_label.setFixedSize(40, 44)
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._load_logo()
        row.addWidget(self.logo_label)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        title = QLabel("PCB INSPECT  /  RMUTT")
        title.setObjectName("appTitle")
        self.topbar_subtitle = ElidedLabel("PCB component verification")
        self.topbar_subtitle.setObjectName("appSubtitle")
        titles.addWidget(title)
        titles.addWidget(self.topbar_subtitle)
        row.addLayout(titles, 1)
        self.model_badge = QLabel("●  Model offline")
        self.model_badge.setObjectName("modelBadge")
        row.addWidget(self.model_badge)
        self.btn_toggle_history = QPushButton("History")
        self.btn_toggle_history.setObjectName("ghostBtn")
        self.btn_toggle_history.setCheckable(True)
        self.btn_toggle_history.clicked.connect(self.toggle_history_panel)
        row.addWidget(self.btn_toggle_history)
        self.btn_theme_toggle = QPushButton()
        self.btn_theme_toggle.setObjectName("ghostBtn")
        self.btn_theme_toggle.setToolTip("Switch appearance  (Ctrl+D)")
        self.btn_theme_toggle.clicked.connect(self.toggle_theme)
        self._update_theme_button_text()
        row.addWidget(self.btn_theme_toggle)
        self.btn_select = QPushButton("＋  Open image")
        self.btn_select.setObjectName("primaryBtn")
        self.btn_select.setToolTip("Open an image and inspect it  (Ctrl+O)")
        self.btn_select.clicked.connect(self.select_image)
        row.addWidget(self.btn_select)

    def build_metrics_strip(self):
        self.metrics_strip = QWidget()
        row = QHBoxLayout(self.metrics_strip)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        specs = [
            ("INSPECTED", "total_label", "statValueAccent", "This session"),
            ("PASSED", "pass_label", "statValuePass", "Meets reference profile"),
            ("REJECTED", "fail_label", "statValueFail", "Requires review"),
            ("PASS YIELD", "yield_value", "statValue", "Passed / inspected"),
        ]
        for caption, attr, style, hint in specs:
            card = QFrame()
            card.setObjectName("statCard")
            card.setFixedHeight(86)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(16, 10, 16, 10)
            layout.setSpacing(2)
            cap = QLabel(caption)
            cap.setObjectName("statLabel")
            layout.addWidget(cap)
            values = QHBoxLayout()
            value = QLabel("—" if attr == "yield_value" else "0")
            value.setObjectName(style)
            setattr(self, attr, value)
            values.addWidget(value)
            values.addStretch()
            if attr == "yield_value":
                self.yield_bar = YieldBar()
                self.yield_bar.setFixedWidth(72)
                values.addWidget(self.yield_bar)
            layout.addLayout(values)
            subtitle = QLabel(hint)
            subtitle.setObjectName("metricHint")
            layout.addWidget(subtitle)
            row.addWidget(card, 1)

    # ────────────────────────────────────────────────────────── left control panel
    def _sidebar_card(self, title, expanded, grid=False):
        """Create a collapsible sidebar card; returns (card, body_layout)."""
        card = CollapsibleCard(title)
        layout = QGridLayout(card.body) if grid else QVBoxLayout(card.body)
        layout.setContentsMargins(14, 2, 14, 14)
        card._default_expanded = expanded
        return card, layout

    def build_left_panel(self):
        self.left_panel = QWidget()
        self.left_panel.setObjectName("leftPanel")
        self.left_layout = QVBoxLayout(self.left_panel)
        self.left_layout.setContentsMargins(12, 16, 12, 16)
        self.left_layout.setSpacing(12)

        self.left_scroll = QScrollArea()
        self.left_scroll.setObjectName("leftScroll")
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.left_scroll.setFixedWidth(304)
        self.left_scroll.setWidget(self.left_panel)

        heading = QLabel("INSPECTION SETUP")
        heading.setObjectName("eyebrow")
        self.left_layout.addWidget(heading)
        hint = QLabel("Configure your inspection station")
        hint.setObjectName("sectionHint")
        self.left_layout.addWidget(hint)
        self.build_inspection_group()
        self.build_camera_group()
        self.build_display_group()
        self.build_reference_group()
        self.build_station_group()
        self.left_layout.addStretch()
        note = QLabel("RMUTT  ·  PCB inspection lab\nImage, folder and camera workflows")
        note.setObjectName("sidebarFootnote")
        self.left_layout.addWidget(note)

    def toggle_left_panel(self):
        self.left_scroll.setVisible(not self.left_scroll.isVisible())

    def build_inspection_group(self):
        card, layout = self._sidebar_card("Detection thresholds", expanded=True, grid=True)
        layout.setVerticalSpacing(8)
        layout.setHorizontalSpacing(9)

        self.conf_label = QLabel("Confidence: 25%")
        self.conf_label.setObjectName("fieldLabel")
        self.conf_slider = QSlider(Qt.Orientation.Horizontal)
        self.conf_slider.setAccessibleName("Detection confidence threshold")
        self.conf_slider.setToolTip("Minimum confidence required to include a detection.")
        self.conf_slider.setRange(1, 100)
        self.conf_slider.setValue(25)
        self.conf_slider.valueChanged.connect(self.update_confidence)

        self.match_dist_spin = QSpinBox()
        self.match_dist_spin.setAccessibleName("Reference match distance in pixels")
        self.match_dist_spin.setToolTip("Maximum distance between a detection and its reference point, in original-image pixels.")
        self.match_dist_spin.setRange(5, 250)
        self.match_dist_spin.setValue(50)
        self.match_dist_spin.setSuffix(" px")
        self.match_dist_spin.valueChanged.connect(self.request_live_refresh)

        layout.addWidget(self.conf_label, 0, 0, 1, 2)
        layout.addWidget(self.conf_slider, 1, 0, 1, 2)
        layout.addWidget(self._field_label("Match distance"), 2, 0)
        layout.addWidget(self.match_dist_spin, 2, 1)
        self.inspection_card = card
        card.set_expanded(card._default_expanded, animate=False)
        self.left_layout.addWidget(card)

    def build_camera_group(self):
        card, layout = self._sidebar_card("Camera source", expanded=False, grid=True)
        layout.setVerticalSpacing(8)
        layout.setHorizontalSpacing(9)

        self.camera_index_spin = QSpinBox()
        self.camera_index_spin.setRange(0, 9)
        self.camera_index_spin.setValue(0)

        self.btn_camera_toggle = QPushButton("▶  Start Camera")
        self.btn_camera_toggle.setObjectName("ghostBtn")
        self.btn_camera_toggle.setCheckable(True)
        self.btn_camera_toggle.setToolTip("Start / stop the live camera preview")
        self.btn_camera_toggle.clicked.connect(self.toggle_camera)

        self.btn_camera_capture = QPushButton("Capture && inspect")
        self.btn_camera_capture.setObjectName("primaryBtn")
        self.btn_camera_capture.setToolTip("Freeze the current camera frame and run inspection on it")
        self.btn_camera_capture.setEnabled(False)
        self.btn_camera_capture.clicked.connect(self.capture_and_inspect)

        self.camera_status = QLabel("Camera: idle")
        self.camera_status.setObjectName("sectionHint")

        layout.addWidget(self._field_label("Camera index"), 0, 0)
        layout.addWidget(self.camera_index_spin, 0, 1)
        layout.addWidget(self.btn_camera_toggle, 1, 0, 1, 2)
        layout.addWidget(self.btn_camera_capture, 2, 0, 1, 2)
        layout.addWidget(self.camera_status, 3, 0, 1, 2)
        self.camera_card = card
        card.set_expanded(card._default_expanded, animate=False)
        self.left_layout.addWidget(card)

    def build_display_group(self):
        card, layout = self._sidebar_card("Display & logging", expanded=False)
        layout.setSpacing(11)

        self.check_labels = ToggleSwitch("Show YOLO labels")
        self.check_labels.setChecked(True)
        self.check_labels.stateChanged.connect(self.request_live_refresh)

        self.check_coords = ToggleSwitch("Show coordinates")
        self.check_coords.setChecked(False)
        self.check_coords.stateChanged.connect(self.request_live_refresh)

        self.check_show_extra = ToggleSwitch("Highlight extras")
        self.check_show_extra.setChecked(True)
        self.check_show_extra.stateChanged.connect(self.request_live_refresh)

        self.check_fail_extra = ToggleSwitch("Fail on extra detections")
        self.check_fail_extra.setChecked(True)
        self.check_fail_extra.stateChanged.connect(self.request_live_refresh)

        self.check_auto_log = ToggleSwitch("Auto-log to CSV")
        self.check_auto_log.setChecked(True)

        toggles = (
            self.check_labels,
            self.check_coords,
            self.check_show_extra,
            self.check_fail_extra,
            self.check_auto_log,
        )
        self._toggle_switches.extend(toggles)
        for toggle in toggles:
            layout.addWidget(toggle)

        self.display_card = card
        card.set_expanded(card._default_expanded, animate=False)
        self.left_layout.addWidget(card)

    def build_station_group(self):
        card, layout = self._sidebar_card("Station & model", expanded=False, grid=True)
        layout.setVerticalSpacing(9)
        layout.setHorizontalSpacing(9)

        self.station_id_input = QLineEdit()
        self.station_id_input.setPlaceholderText("e.g. Line-01")
        self.station_id_input.editingFinished.connect(self._on_station_meta_changed)
        self.operator_input = QLineEdit()
        self.operator_input.setPlaceholderText("e.g. Operator-A")
        self.operator_input.editingFinished.connect(self._on_station_meta_changed)
        self.model_path_input = QLineEdit()
        self.model_path_input.setPlaceholderText("Select YOLO model (.pt)")
        self.model_path_input.setReadOnly(True)
        self.model_path_input.textChanged.connect(self.model_path_input.setToolTip)
        self.model_status = QLabel("Model: not loaded")
        self.model_status.setObjectName("statusBad")
        self.model_status.setWordWrap(True)

        self.device_combo = QComboBox()
        self.device_combo.addItem("Auto (prefer NVIDIA)", "auto")
        self.device_combo.addItem("NVIDIA GPU (CUDA:0)", "cuda:0")
        self.device_combo.addItem("CPU", "cpu")
        self.device_combo.setToolTip("Auto uses NVIDIA CUDA when available. GPU mode requires CUDA.")
        self.device_combo.currentIndexChanged.connect(self.on_device_preference_changed)
        self.device_status = QLabel("Device will be checked on the first inspection.")
        self.device_status.setObjectName("sectionHint")
        self.device_status.setWordWrap(True)

        self.btn_select_model = QPushButton("Browse")
        self.btn_select_model.setObjectName("ghostBtn")
        self.btn_select_model.clicked.connect(self.select_model_file)
        self.btn_load_model = QPushButton("Load Model")
        self.btn_load_model.clicked.connect(self.load_model_button)

        model_btn_row = QHBoxLayout()
        model_btn_row.setSpacing(9)
        model_btn_row.addWidget(self.btn_select_model)
        model_btn_row.addWidget(self.btn_load_model)

        layout.addWidget(self._field_label("Station ID"), 0, 0)
        layout.addWidget(self.station_id_input, 0, 1)
        layout.addWidget(self._field_label("Operator"), 1, 0)
        layout.addWidget(self.operator_input, 1, 1)
        layout.addWidget(self._field_label("Model"), 2, 0)
        layout.addWidget(self.model_path_input, 2, 1)
        layout.addLayout(model_btn_row, 3, 0, 1, 2)
        layout.addWidget(self.model_status, 4, 0, 1, 2)
        layout.addWidget(self._field_label("Processor"), 5, 0)
        layout.addWidget(self.device_combo, 5, 1)
        layout.addWidget(self.device_status, 6, 0, 1, 2)
        self.station_card = card
        card.set_expanded(card._default_expanded, animate=False)
        self.left_layout.addWidget(card)

    def build_reference_group(self):
        card, layout = self._sidebar_card("Reference profile", expanded=False, grid=True)
        layout.setVerticalSpacing(8)
        layout.setHorizontalSpacing(9)

        self.ref_status = QLabel("References: 0 points")
        self.ref_status.setObjectName("sectionHint")
        self.combo_classes = QComboBox()
        self.combo_classes.addItem("class")

        self.btn_edit_mode = QPushButton("✎  Enable Edit Mode")
        self.btn_edit_mode.setObjectName("editModeBtn")
        self.btn_edit_mode.setCheckable(True)
        self.btn_edit_mode.setToolTip("Click on the image to add reference points  (Ctrl+E)")
        self.btn_edit_mode.clicked.connect(self.toggle_edit_mode)
        self.btn_clear_ref = QPushButton("Clear")
        self.btn_clear_ref.setObjectName("dangerBtn")
        self.btn_clear_ref.clicked.connect(self.clear_references)
        self.btn_undo = QPushButton("↶ Undo")
        self.btn_undo.setObjectName("ghostBtn")
        self.btn_undo.clicked.connect(self.undo)
        self.btn_redo = QPushButton("↷ Redo")
        self.btn_redo.setObjectName("ghostBtn")
        self.btn_redo.clicked.connect(self.redo)
        self.btn_save_ref = QPushButton("Save As…")
        self.btn_save_ref.setObjectName("ghostBtn")
        self.btn_save_ref.clicked.connect(self.save_references)
        self.btn_load_ref = QPushButton("Load…")
        self.btn_load_ref.setObjectName("ghostBtn")
        self.btn_load_ref.clicked.connect(self.load_references)

        self.ref_path_input = QLineEdit()
        self.ref_path_input.setPlaceholderText("Reference profile path")
        self.ref_path_input.setReadOnly(True)

        self.btn_add_extra_ref = QPushButton("Adopt Extras")
        self.btn_add_extra_ref.setObjectName("ghostBtn")
        self.btn_add_extra_ref.setToolTip("Add EXTRA detections from the last inspection as reference points")
        self.btn_add_extra_ref.clicked.connect(self.add_extra_to_references)
        self.btn_add_extra_ref_save = QPushButton("Adopt + Save")
        self.btn_add_extra_ref_save.setObjectName("ghostBtn")
        self.btn_add_extra_ref_save.clicked.connect(self.add_extra_and_save_default)

        self.ref_path_input.setToolTip(self.ref_path_input.text())
        self.ref_path_input.textChanged.connect(self.ref_path_input.setToolTip)

        undo_redo_row = QHBoxLayout()
        undo_redo_row.setSpacing(9)
        undo_redo_row.addWidget(self.btn_undo)
        undo_redo_row.addWidget(self.btn_redo)

        load_save_row = QHBoxLayout()
        load_save_row.setSpacing(9)
        load_save_row.addWidget(self.btn_load_ref)
        load_save_row.addWidget(self.btn_save_ref)

        adopt_row = QHBoxLayout()
        adopt_row.setSpacing(9)
        adopt_row.addWidget(self.btn_add_extra_ref)
        adopt_row.addWidget(self.btn_add_extra_ref_save)

        layout.addWidget(self._field_label("Target Class"), 0, 0)
        layout.addWidget(self.combo_classes, 0, 1)
        layout.addWidget(self.btn_edit_mode, 1, 0, 1, 2)
        layout.addLayout(undo_redo_row, 2, 0, 1, 2)
        layout.addWidget(self.btn_clear_ref, 3, 0, 1, 2)
        layout.addLayout(load_save_row, 4, 0, 1, 2)
        layout.addWidget(self.ref_path_input, 5, 0, 1, 2)
        layout.addLayout(adopt_row, 6, 0, 1, 2)
        layout.addWidget(self.ref_status, 7, 0, 1, 2)
        self.reference_card = card
        card.set_expanded(card._default_expanded, animate=False)
        self.left_layout.addWidget(card)

    # ────────────────────────────────────────────────────────── center column
    def build_center_column(self):
        self.center_widget = QWidget()
        self.center_layout = QVBoxLayout(self.center_widget)
        self.center_layout.setContentsMargins(0, 0, 0, 0)
        self.center_layout.setSpacing(12)

        self.build_browse_bar()
        self.build_image_view()
        self.build_history_panel()

    def build_browse_bar(self):
        bar = QFrame()
        bar.setObjectName("browseBar")
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)
        self.browse_bar = bar
        heading = QHBoxLayout()
        title = QLabel("Inspection workspace")
        title.setObjectName("workspaceTitle")
        heading.addWidget(title)
        heading.addStretch()
        self.btn_reinspect = QPushButton("↻  Inspect again")
        self.btn_reinspect.setObjectName("ghostBtn")
        self.btn_reinspect.setToolTip("Inspect the current image again  (Ctrl+R / F5)")
        self.btn_reinspect.clicked.connect(self.inspect_current_image)
        heading.addWidget(self.btn_reinspect)
        self.btn_save_annotated = QPushButton("Save image")
        self.btn_save_annotated.setObjectName("ghostBtn")
        self.btn_save_annotated.setToolTip("Save annotated image  (Ctrl+S)")
        self.btn_save_annotated.clicked.connect(self.save_annotated_image)
        heading.addWidget(self.btn_save_annotated)
        layout.addLayout(heading)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_select_folder = QPushButton("Open folder")
        self.btn_select_folder.setObjectName("ghostBtn")
        self.btn_select_folder.setToolTip("Browse a folder of images  (Ctrl+Shift+O)")
        self.btn_select_folder.clicked.connect(self.select_folder)
        row.addWidget(self.btn_select_folder)
        self.folder_name_label = ElidedLabel("No folder open")
        self.folder_name_label.setObjectName("sectionHint")
        row.addWidget(self.folder_name_label, 1)
        self.btn_prev_image = QPushButton("‹")
        self.btn_prev_image.setObjectName("iconBtn")
        self.btn_prev_image.setAccessibleName("Previous image")
        self.btn_prev_image.setToolTip("Previous image  (Ctrl+← / PgUp)")
        self.btn_prev_image.clicked.connect(self.show_prev_image)
        self.nav_value_label = QLabel("—")
        self.nav_value_label.setObjectName("navValue")
        self.btn_next_image = QPushButton("›")
        self.btn_next_image.setObjectName("iconBtn")
        self.btn_next_image.setAccessibleName("Next image")
        self.btn_next_image.setToolTip("Next image  (Ctrl+→ / PgDown)")
        self.btn_next_image.clicked.connect(self.show_next_image)
        row.addWidget(self.btn_prev_image)
        row.addWidget(self.nav_value_label)
        row.addWidget(self.btn_next_image)
        layout.addLayout(row)
        self.center_layout.addWidget(bar)

    def build_image_view(self):
        self.image_scroll = QScrollArea()
        self.image_scroll.setObjectName("imageScroll")
        self.image_scroll.setWidgetResizable(False)
        self.image_scroll.viewport().setStyleSheet("background: #101e2a;")
        self.image_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_scroll.setMinimumSize(260, 150)
        self.image_display = ReferenceLabel(self)
        self.image_display.setObjectName("imageDisplay")
        self.image_display.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.image_scroll.setWidget(self.image_display)
        self.busy_overlay = BusyOverlay(self.image_scroll)
        self.center_layout.addWidget(self.image_scroll, 1)

        self.canvas_toolbar = QWidget()
        tools = QHBoxLayout(self.canvas_toolbar)
        tools.setContentsMargins(0, 0, 0, 0)
        self.canvas_hint = ElidedLabel("CANVAS  /  Drop an image to begin")
        self.canvas_hint.setObjectName("sectionHint")
        tools.addWidget(self.canvas_hint, 1)
        self.zoom_value_label = QLabel("100%")
        self.zoom_value_label.setObjectName("zoomValue")
        for attr, text, tip, handler in (
            ("btn_zoom_out", "−", "Zoom out  (Ctrl+-)", self.zoom_out),
            ("btn_zoom_in", "+", "Zoom in  (Ctrl++)", self.zoom_in),
            ("btn_zoom_fit", "Fit", "Fit to view  (Ctrl+0)", self.zoom_fit),
        ):
            button = QPushButton(text)
            button.setObjectName("iconBtn")
            button.setToolTip(tip)
            button.setAccessibleName(tip.split("  ")[0])
            button.clicked.connect(handler)
            setattr(self, attr, button)
        tools.addWidget(self.btn_zoom_out)
        tools.addWidget(self.zoom_value_label)
        tools.addWidget(self.btn_zoom_in)
        tools.addWidget(self.btn_zoom_fit)
        self.center_layout.addWidget(self.canvas_toolbar)
        self._build_verdict_badge()
        self.center_layout.addWidget(self.verdict_card)

    def _build_verdict_badge(self):
        """A stable result strip outside the image so no components are obscured."""
        self.verdict_card = QFrame()
        self.verdict_card.setObjectName("verdictCard")
        vc = QHBoxLayout(self.verdict_card)
        vc.setContentsMargins(14, 12, 14, 12)
        vc.setSpacing(18)
        summary = QVBoxLayout()
        summary.setSpacing(3)
        self.verdict_label = QLabel("READY")
        self.verdict_label.setObjectName("verdictBig")
        self.verdict_image_name = ElidedLabel("Awaiting first inspection")
        self.verdict_image_name.setObjectName("verdictImage")
        self.verdict_reason = ElidedLabel("Open an image or capture a camera frame.")
        self.verdict_reason.setObjectName("verdictReason")
        summary.addWidget(self.verdict_label)
        summary.addWidget(self.verdict_image_name)
        summary.addWidget(self.verdict_reason)
        vc.addLayout(summary, 1)
        pills = QHBoxLayout()
        pills.setSpacing(8)
        self.pill_expect = self._detail_pill("EXPECT", "pillExpect")
        self.pill_ok = self._detail_pill("OK", "pillOk")
        self.pill_miss = self._detail_pill("MISSING", "pillMiss")
        self.pill_wrong = self._detail_pill("WRONG", "pillWrong")
        self.pill_extra = self._detail_pill("EXTRA", "pillExtra")
        for holder in (self.pill_expect, self.pill_ok, self.pill_miss, self.pill_wrong, self.pill_extra):
            holder._value_label.setText("—")
            pills.addWidget(holder)
        vc.addLayout(pills)

    def build_history_panel(self):
        """Hidden by default; toggled from the top bar instead of always
        occupying vertical space in the main column."""
        self.history_panel = QFrame()
        self.history_panel.setObjectName("historyPanel")
        self.history_panel.setVisible(False)
        layout = QVBoxLayout(self.history_panel)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("INSPECTION HISTORY")
        title.setObjectName("rightPanelTitle")
        header.addWidget(title)
        header.addStretch()
        self.btn_export_history = QPushButton("Export CSV")
        self.btn_export_history.setObjectName("ghostBtn")
        self.btn_export_history.clicked.connect(self.export_history_csv)
        header.addWidget(self.btn_export_history)
        self.btn_reset_counter = QPushButton("Reset Counters")
        self.btn_reset_counter.setObjectName("ghostBtn")
        self.btn_reset_counter.clicked.connect(self.reset_counters)
        header.addWidget(self.btn_reset_counter)
        btn_close_history = QPushButton("✕")
        btn_close_history.setObjectName("panelCloseBtn")
        btn_close_history.setToolTip("Hide history")
        btn_close_history.clicked.connect(self.toggle_history_panel)
        header.addWidget(btn_close_history)
        layout.addLayout(header)

        self.history_table = QTableWidget(0, 8)
        self.history_table.setHorizontalHeaderLabels(
            ["Time", "Image", "Verdict", "OK", "Missing", "Wrong", "Extra", "Conf%"]
        )
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        for col in [3, 4, 5, 6, 7]:
            self.history_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setShowGrid(False)
        self.history_empty = QLabel("No inspections yet\nOpen an image or capture a board to build your session history.")
        self.history_empty.setObjectName("sectionHint")
        self.history_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.history_empty.setWordWrap(True)
        self.history_table.setMinimumHeight(100)
        self.history_table.verticalHeader().setDefaultSectionSize(36)
        layout.addWidget(self.history_table)
        layout.addWidget(self.history_empty, 1)
        self.history_table.hide()

        self.center_layout.addWidget(self.history_panel, 1)

    def toggle_history_panel(self):
        visible = not self.history_panel.isVisible()
        self.history_panel.setVisible(visible)
        self.btn_toggle_history.setChecked(visible)
        for widget in (self.browse_bar, self.image_scroll, self.canvas_toolbar, self.verdict_card):
            widget.setVisible(not visible)
        self.right_panel.setVisible(not visible and self.selected_detection_index is not None)

    # ────────────────────────────────────────────────────────── right contextual panel
    def build_right_panel(self):
        self.right_panel = QFrame()
        self.right_panel.setObjectName("rightPanel")
        self.right_panel.setFixedWidth(320)
        self.right_panel.setVisible(False)
        layout = QVBoxLayout(self.right_panel)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("COMPONENT DETAIL")
        title.setObjectName("rightPanelTitle")
        header.addWidget(title)
        header.addStretch()
        btn_close = QPushButton("✕")
        btn_close.setObjectName("panelCloseBtn")
        btn_close.setToolTip("Close")
        btn_close.clicked.connect(self.close_right_panel)
        header.addWidget(btn_close)
        layout.addLayout(header)

        self.detail_class_value = self._detail_row(layout, "CLASS")
        self.detail_conf_value = self._detail_row(layout, "CONFIDENCE")
        self.detail_coords_value = self._detail_row(layout, "COORDINATES")
        self.detail_status_value = self._detail_row(layout, "STATUS")

        layout.addStretch()
        self.right_panel_placeholder = QLabel(
            "Click a detected component on the image to inspect it here."
        )
        self.right_panel_placeholder.setObjectName("sectionHint")
        self.right_panel_placeholder.setWordWrap(True)
        layout.addWidget(self.right_panel_placeholder)

    def _detail_row(self, parent_layout, caption):
        col = QVBoxLayout()
        col.setSpacing(2)
        cap = QLabel(caption)
        cap.setObjectName("detailLabel")
        value = QLabel("—")
        value.setObjectName("detailValue")
        value.setWordWrap(True)
        col.addWidget(cap)
        col.addWidget(value)
        parent_layout.addLayout(col)
        return value

    def close_right_panel(self):
        self.selected_detection_index = None
        if hasattr(self, "_recompose_and_display"):
            self._recompose_and_display()
        if hasattr(self, "update_right_panel"):
            self.update_right_panel(None)
        else:
            self.right_panel.setVisible(False)

    # ────────────────────────────────────────────────────────── status bar
    def _build_statusbar(self):
        self.stats_label = ElidedLabel("System ready.")
        self.stats_label.setObjectName("statusBarText")
        self.perf_label = QLabel("")
        self.perf_label.setObjectName("perfLabel")

        bar = self.statusBar()
        bar.addWidget(self.stats_label, 1)
        bar.addPermanentWidget(self.perf_label)

    # ────────────────────────────────────────────────────────── helpers
    def _field_label(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("fieldLabel")
        return lbl

    def _detail_pill(self, caption, value_object_name):
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        value = QLabel("0")
        value.setObjectName(value_object_name)
        cap = QLabel(caption)
        cap.setObjectName("pillCap")
        col.addWidget(value)
        col.addWidget(cap)
        holder._value_label = value
        return holder

    def _load_logo(self):
        if getattr(self, "logo_path", None) and os.path.exists(self.logo_path):
            logo_pixmap = QPixmap(self.logo_path)
            if not logo_pixmap.isNull():
                scaled_logo = logo_pixmap.scaled(
                    30, 30,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.logo_label.setPixmap(scaled_logo)
                return
        self.logo_label.setText("◎")

    def _set_pill(self, holder, value):
        holder._value_label.setText(str(value))

    def set_verdict_image_name(self, name):
        """Retain the full filename; ElidedLabel fits it to the available width."""
        self.verdict_image_name.setText(name)

    def apply_styles(self):
        theme = getattr(self, "_current_theme", "light")
        self.setStyleSheet(get_stylesheet(theme))
        tokens = tokens_for(theme)
        if hasattr(self, "image_display") and not self.current_image_pixmap:
            self.image_display.setStyleSheet(reference_label_style(theme))
        if hasattr(self, "yield_bar"):
            self.yield_bar.set_colors(tokens["slider_groove"], tokens["accent"])
        if hasattr(self, "busy_overlay"):
            self.busy_overlay.set_theme(
                QColorFromTokens(tokens["bg_image_area"], 205), tokens["accent"], tokens["text_primary"]
            )
        self.image_display.set_theme(tokens)
        for button in self.findChildren(QPushButton):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        if self.selected_detection_index is not None:
            self.update_right_panel(self._last_detections[self.selected_detection_index])
        for toggle in getattr(self, "_toggle_switches", []):
            toggle.set_colors(tokens["toggle_track_off"], tokens["accent"], "#ffffff")
        if hasattr(self, "toasts"):
            self.toasts.set_theme(theme)

    def toggle_theme(self):
        current = getattr(self, "_current_theme", "light")
        self._current_theme = "dark" if current == "light" else "light"
        self._update_theme_button_text()
        self.apply_styles()
        if hasattr(self, "fade_content"):
            self.fade_content()
        if hasattr(self, "toasts"):
            self.toasts.show(f"{self._current_theme.capitalize()} mode", "info", duration=1400)

    def _reset_result_summary(self, verdict="READY", title="Awaiting inspection", reason="Open an image or capture a camera frame."):
        self.last_inspection_result = None
        self.current_annotated_frame = None
        self.selected_detection_index = None
        self._last_detections = []
        self._detection_status = {}
        self.update_right_panel(None)
        self._repolish(self.verdict_card, "verdictCard")
        self._repolish(self.verdict_label, "verdictBig")
        self.verdict_label.setText(verdict)
        self.verdict_image_name.setText(title)
        self.verdict_reason.setText(reason)
        for pill in (self.pill_expect, self.pill_ok, self.pill_miss, self.pill_wrong, self.pill_extra):
            pill._value_label.setText("—")
        self._update_action_buttons()

    def _update_action_buttons(self):
        has_model = self.model is not None
        busy = getattr(self, "_inference_running", False)
        camera_live = getattr(self, "_camera_worker", None) is not None
        self.device_combo.setEnabled(not busy)
        self.btn_load_model.setEnabled(not busy)
        self.btn_select_model.setEnabled(not busy)
        self.btn_select.setEnabled(not busy and not camera_live)
        self.btn_reinspect.setEnabled(has_model and bool(self.current_image_path) and not busy and not camera_live)
        self.btn_save_annotated.setEnabled(self.current_annotated_frame is not None and not busy and not camera_live)
        has_extras = bool(self.last_inspection_result and self.last_inspection_result["extra"])
        self.btn_add_extra_ref.setEnabled(has_model and has_extras and not busy and not camera_live)
        self.btn_add_extra_ref_save.setEnabled(has_model and has_extras and not busy and not camera_live)
        self.btn_export_history.setEnabled(bool(self.history_rows))
        self.btn_camera_toggle.setEnabled(not busy)
        self.btn_camera_capture.setEnabled(camera_live and self._camera_latest_frame is not None and has_model)

    def _update_zoom_controls_enabled(self):
        """Zoom is meaningless with no image on screen — keep the controls
        (and the % readout) inert instead of letting them drift to a
        confusing value like 512% on an empty canvas."""
        has_image = bool(self.current_image_pixmap)
        for widget in (self.btn_zoom_in, self.btn_zoom_out, self.btn_zoom_fit):
            widget.setEnabled(has_image)

    def _update_theme_button_text(self):
        theme = getattr(self, "_current_theme", "light")
        self.btn_theme_toggle.setText("Light" if theme == "dark" else "Dark")

    def _on_station_meta_changed(self):
        station = self.station_id_input.text().strip() or "—"
        operator = self.operator_input.text().strip()
        subtitle = f"Station {station}" + (f"  ·  {operator}" if operator else "")
        if hasattr(self, "topbar_subtitle"):
            self.topbar_subtitle.setText(subtitle if station != "—" else "PCB component verification")


def QColorFromTokens(hex_color, alpha):
    from PyQt6.QtGui import QColor
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c
