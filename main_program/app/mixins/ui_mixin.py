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
    QCheckBox,
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
from ..widgets import ReferenceLabel
from ..components import YieldBar, BusyOverlay, CollapsibleCard


class UIMixin:
    def init_ui(self):
        self.main_widget = QWidget()
        self.main_widget.setObjectName("rootWidget")
        self.setCentralWidget(self.main_widget)
        self.root_layout = QHBoxLayout(self.main_widget)
        self.root_layout.setContentsMargins(14, 14, 14, 14)
        self.root_layout.setSpacing(14)

        # ── Sidebar ──
        self.left_panel = QWidget()
        self.left_panel.setObjectName("leftPanel")
        self.left_layout = QVBoxLayout(self.left_panel)
        self.left_layout.setContentsMargins(12, 12, 12, 12)
        self.left_layout.setSpacing(12)

        self.left_scroll = QScrollArea()
        self.left_scroll.setObjectName("leftScroll")
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.left_scroll.setMinimumWidth(438)
        self.left_scroll.setMaximumWidth(500)
        self.left_scroll.setWidget(self.left_panel)

        # ── Right / work area ──
        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(12)

        self.root_layout.addWidget(self.left_scroll, 0)
        self.root_layout.addWidget(self.right_panel, 1)

        # Sidebar content
        self.build_actions_card()
        self.build_station_group()
        self.build_inspection_group()
        self.build_reference_group()
        self.left_layout.addStretch()

        # Work-area content
        self.build_topbar()
        self.build_hud()
        self.build_image_view()
        self.build_status_row()
        self.build_history_table()

        self._update_action_buttons()

    # ────────────────────────────────────────────────────────── sidebar
    def _sidebar_card(self, title, expanded, grid=False):
        """Create a collapsible sidebar card; returns (card, body_layout)."""
        card = CollapsibleCard(title)
        layout = QGridLayout(card.body) if grid else QVBoxLayout(card.body)
        layout.setContentsMargins(14, 2, 14, 14)
        card._default_expanded = expanded
        return card, layout

    def build_actions_card(self):
        card, layout = self._sidebar_card("Actions", expanded=True)
        layout.setSpacing(9)

        self.btn_select = QPushButton("＋  Select Image")
        self.btn_select.setObjectName("primaryBtn")
        self.btn_select.setToolTip("Open an inspection image  (Ctrl+O)")
        self.btn_select.clicked.connect(self.select_image)

        row = QHBoxLayout()
        row.setSpacing(9)
        self.btn_reinspect = QPushButton("↻  Re-Inspect")
        self.btn_reinspect.setToolTip("Re-run inspection on the current image  (Space)")
        self.btn_reinspect.clicked.connect(self.inspect_current_image)
        self.btn_save_annotated = QPushButton("⤓  Save Result")
        self.btn_save_annotated.setToolTip("Save the annotated image  (Ctrl+S)")
        self.btn_save_annotated.clicked.connect(self.save_annotated_image)
        row.addWidget(self.btn_reinspect)
        row.addWidget(self.btn_save_annotated)

        layout.addWidget(self.btn_select)
        layout.addLayout(row)
        self.actions_card = card
        card.set_expanded(card._default_expanded, animate=False)
        self.left_layout.addWidget(card)

    def build_station_group(self):
        card, layout = self._sidebar_card("Station", expanded=False, grid=True)
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
        self.model_status = QLabel("Model: not loaded")
        self.model_status.setObjectName("statusBad")
        self.model_status.setWordWrap(True)

        self.btn_select_model = QPushButton("Browse")
        self.btn_select_model.setObjectName("ghostBtn")
        self.btn_select_model.clicked.connect(self.select_model_file)
        self.btn_load_model = QPushButton("Load Model")
        self.btn_load_model.clicked.connect(self.load_model_button)

        layout.addWidget(self._field_label("Station ID"), 0, 0)
        layout.addWidget(self.station_id_input, 0, 1, 1, 2)
        layout.addWidget(self._field_label("Operator"), 1, 0)
        layout.addWidget(self.operator_input, 1, 1, 1, 2)
        layout.addWidget(self._field_label("Model"), 2, 0)
        layout.addWidget(self.model_path_input, 2, 1, 1, 2)
        layout.addWidget(self.btn_select_model, 3, 1)
        layout.addWidget(self.btn_load_model, 3, 2)
        layout.addWidget(self.model_status, 4, 0, 1, 3)
        self.station_card = card
        card.set_expanded(card._default_expanded, animate=False)
        self.left_layout.addWidget(card)

    def build_inspection_group(self):
        card, layout = self._sidebar_card("Inspection", expanded=True, grid=True)
        layout.setVerticalSpacing(8)
        layout.setHorizontalSpacing(9)

        self.conf_label = QLabel("Confidence: 25%")
        self.conf_label.setObjectName("fieldLabel")
        self.conf_slider = QSlider(Qt.Orientation.Horizontal)
        self.conf_slider.setRange(1, 100)
        self.conf_slider.setValue(25)
        self.conf_slider.valueChanged.connect(self.update_confidence)

        self.match_dist_spin = QSpinBox()
        self.match_dist_spin.setRange(5, 250)
        self.match_dist_spin.setValue(50)
        self.match_dist_spin.setSuffix(" px")
        self.match_dist_spin.valueChanged.connect(self.request_live_refresh)

        self.check_labels = QCheckBox("Show YOLO labels")
        self.check_labels.setChecked(True)
        self.check_labels.stateChanged.connect(self.request_live_refresh)

        self.check_coords = QCheckBox("Show coordinates")
        self.check_coords.setChecked(False)
        self.check_coords.stateChanged.connect(self.request_live_refresh)

        self.check_show_extra = QCheckBox("Highlight extra detections")
        self.check_show_extra.setChecked(True)
        self.check_show_extra.stateChanged.connect(self.request_live_refresh)

        self.check_fail_extra = QCheckBox("Fail on extra detections")
        self.check_fail_extra.setChecked(True)
        self.check_fail_extra.stateChanged.connect(self.request_live_refresh)

        self.check_auto_log = QCheckBox("Auto-log to CSV")
        self.check_auto_log.setChecked(True)

        layout.addWidget(self.conf_label, 0, 0, 1, 2)
        layout.addWidget(self.conf_slider, 1, 0, 1, 3)
        layout.addWidget(self._field_label("Match distance"), 2, 0)
        layout.addWidget(self.match_dist_spin, 2, 1, 1, 2)
        layout.addWidget(self.check_labels, 3, 0, 1, 3)
        layout.addWidget(self.check_coords, 4, 0, 1, 3)
        layout.addWidget(self.check_show_extra, 5, 0, 1, 3)
        layout.addWidget(self.check_fail_extra, 6, 0, 1, 3)
        layout.addWidget(self.check_auto_log, 7, 0, 1, 3)
        self.inspection_card = card
        card.set_expanded(card._default_expanded, animate=False)
        self.left_layout.addWidget(card)

    def build_reference_group(self):
        card, layout = self._sidebar_card("Reference Profile", expanded=False, grid=True)
        layout.setVerticalSpacing(8)
        layout.setHorizontalSpacing(9)

        self.ref_status = QLabel("References: 0 points")
        self.ref_status.setObjectName("sectionHint")
        self.combo_classes = QComboBox()
        self.combo_classes.addItem("class")

        self.btn_edit_mode = QPushButton("✎  Enable Edit Mode")
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

        self.btn_load_default_ref = QPushButton("Load Refs.json")
        self.btn_load_default_ref.setObjectName("ghostBtn")
        self.btn_load_default_ref.clicked.connect(self.load_default_references)
        self.btn_save_default_ref = QPushButton("Save Refs.json")
        self.btn_save_default_ref.setObjectName("ghostBtn")
        self.btn_save_default_ref.clicked.connect(self.save_default_references)
        self.btn_add_extra_ref = QPushButton("Adopt Extras")
        self.btn_add_extra_ref.setObjectName("ghostBtn")
        self.btn_add_extra_ref.setToolTip("Add EXTRA detections from the last inspection as reference points")
        self.btn_add_extra_ref.clicked.connect(self.add_extra_to_references)
        self.btn_add_extra_ref_save = QPushButton("Adopt + Save")
        self.btn_add_extra_ref_save.setObjectName("ghostBtn")
        self.btn_add_extra_ref_save.clicked.connect(self.add_extra_and_save_default)

        layout.addWidget(self._field_label("Target Class"), 0, 0)
        layout.addWidget(self.combo_classes, 0, 1, 1, 2)
        layout.addWidget(self.btn_edit_mode, 1, 0, 1, 3)
        layout.addWidget(self.btn_undo, 2, 0)
        layout.addWidget(self.btn_redo, 2, 1)
        layout.addWidget(self.btn_clear_ref, 2, 2)
        layout.addWidget(self.btn_load_ref, 3, 0)
        layout.addWidget(self.btn_save_ref, 3, 1, 1, 2)
        layout.addWidget(self.ref_path_input, 4, 0, 1, 3)
        layout.addWidget(self.btn_load_default_ref, 5, 0, 1, 2)
        layout.addWidget(self.btn_save_default_ref, 5, 2)
        layout.addWidget(self.btn_add_extra_ref, 6, 0, 1, 2)
        layout.addWidget(self.btn_add_extra_ref_save, 6, 2)
        layout.addWidget(self.ref_status, 7, 0, 1, 3)
        self.reference_card = card
        card.set_expanded(card._default_expanded, animate=False)
        self.left_layout.addWidget(card)

    # ────────────────────────────────────────────────────────── work area
    def build_topbar(self):
        bar = QWidget()
        bar.setObjectName("topBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 12, 14, 12)
        row.setSpacing(12)

        self.logo_label = QLabel()
        self.logo_label.setObjectName("appLogo")
        self.logo_label.setFixedSize(44, 44)
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._load_logo()

        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title = QLabel("Defect Inspection Station")
        title.setObjectName("appTitle")
        self.topbar_subtitle = QLabel("PCB component verification")
        self.topbar_subtitle.setObjectName("appSubtitle")
        title_col.addWidget(title)
        title_col.addWidget(self.topbar_subtitle)

        row.addWidget(self.logo_label)
        row.addLayout(title_col)
        row.addStretch()

        self.btn_theme_toggle = QPushButton()
        self.btn_theme_toggle.setObjectName("iconBtn")
        self.btn_theme_toggle.setToolTip("Toggle Dark / Light Mode  (Ctrl+D)")
        self.btn_theme_toggle.clicked.connect(self.toggle_theme)
        self._update_theme_button_text()

        self.zoom_value_label = QLabel("100%")
        self.zoom_value_label.setObjectName("zoomValue")
        self.btn_zoom_out = QPushButton("－")
        self.btn_zoom_out.setObjectName("iconBtn")
        self.btn_zoom_out.setToolTip("Zoom out  (Ctrl+-)")
        self.btn_zoom_out.clicked.connect(self.zoom_out)
        self.btn_zoom_fit = QPushButton("Fit")
        self.btn_zoom_fit.setObjectName("iconBtn")
        self.btn_zoom_fit.setToolTip("Fit to view  (Ctrl+0)")
        self.btn_zoom_fit.clicked.connect(self.zoom_fit)
        self.btn_zoom_in = QPushButton("＋")
        self.btn_zoom_in.setObjectName("iconBtn")
        self.btn_zoom_in.setToolTip("Zoom in  (Ctrl++)")
        self.btn_zoom_in.clicked.connect(self.zoom_in)

        row.addWidget(self.btn_theme_toggle)
        row.addSpacing(4)
        row.addWidget(self.btn_zoom_out)
        row.addWidget(self.zoom_value_label)
        row.addWidget(self.btn_zoom_in)
        row.addWidget(self.btn_zoom_fit)

        self.right_layout.addWidget(bar)

    def build_hud(self):
        self.hud_widget = QWidget()
        hud = QHBoxLayout(self.hud_widget)
        hud.setContentsMargins(0, 0, 0, 0)
        hud.setSpacing(12)

        # Verdict card
        self.verdict_card = QFrame()
        self.verdict_card.setObjectName("verdictCard")
        self.verdict_card.setMinimumWidth(330)
        vc = QVBoxLayout(self.verdict_card)
        vc.setContentsMargins(18, 11, 18, 12)
        vc.setSpacing(5)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.verdict_label = QLabel("READY")
        self.verdict_label.setObjectName("verdictBig")
        self.verdict_image_name = QLabel("No image loaded")
        self.verdict_image_name.setObjectName("verdictImage")
        self.verdict_image_name.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.verdict_label)
        top.addStretch()
        top.addWidget(self.verdict_image_name)
        vc.addLayout(top)

        self.verdict_reason = QLabel("Load an image to begin inspection.")
        self.verdict_reason.setObjectName("verdictReason")
        self.verdict_reason.setWordWrap(True)
        vc.addWidget(self.verdict_reason)

        vc.addStretch()

        pills = QHBoxLayout()
        pills.setSpacing(7)
        self.pill_expect = self._detail_pill("EXPECT", "pillExpect")
        self.pill_ok = self._detail_pill("OK", "pillOk")
        self.pill_miss = self._detail_pill("MISSING", "pillMiss")
        self.pill_wrong = self._detail_pill("WRONG", "pillWrong")
        self.pill_extra = self._detail_pill("EXTRA", "pillExtra")
        for holder in (self.pill_expect, self.pill_ok, self.pill_miss, self.pill_wrong, self.pill_extra):
            pills.addWidget(holder)
        vc.addLayout(pills)

        hud.addWidget(self.verdict_card, 3)

        # KPI strip — one card, stats separated by hairline dividers
        strip = QFrame()
        strip.setObjectName("statCard")
        srow = QHBoxLayout(strip)
        srow.setContentsMargins(22, 12, 22, 12)
        srow.setSpacing(20)

        block, self.total_label = self._stat_block("TOTAL", "statValueAccent")
        srow.addWidget(block)
        srow.addWidget(self._vline())
        block, self.pass_label = self._stat_block("PASS", "statValuePass")
        srow.addWidget(block)
        srow.addWidget(self._vline())
        block, self.fail_label = self._stat_block("FAIL", "statValueFail")
        srow.addWidget(block)
        srow.addWidget(self._vline())
        yield_block, self.yield_value = self._stat_block("YIELD", "statValue")
        self.yield_bar = YieldBar()
        self.yield_bar.setFixedWidth(110)
        yield_block.layout().insertWidget(2, self.yield_bar)
        self.yield_value.setText("—")
        srow.addWidget(yield_block)
        srow.addStretch()

        hud.addWidget(strip, 4)

        self.right_layout.addWidget(self.hud_widget)

    def build_image_view(self):
        self.image_scroll = QScrollArea()
        self.image_scroll.setObjectName("imageScroll")
        self.image_scroll.setWidgetResizable(False)
        self.image_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.image_display = ReferenceLabel(self)
        self.image_display.setObjectName("imageDisplay")
        self.image_display.setMinimumSize(320, 220)
        self.image_display.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.image_scroll.setWidget(self.image_display)

        self.busy_overlay = BusyOverlay(self.image_scroll)

        self.right_layout.addWidget(self.image_scroll, 1)

    def build_status_row(self):
        row = QHBoxLayout()
        row.setSpacing(10)
        self.stats_label = QLabel("System ready.")
        self.stats_label.setObjectName("statusLine")
        self.perf_label = QLabel("")
        self.perf_label.setObjectName("perfLabel")
        self.perf_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.stats_label, 1)
        row.addWidget(self.perf_label, 0)
        self.right_layout.addLayout(row)

    def build_history_table(self):
        card, layout = self._sidebar_card("Inspection History", expanded=True)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.addStretch()
        self.btn_reset_counter = QPushButton("Reset Counters")
        self.btn_reset_counter.setObjectName("ghostBtn")
        self.btn_reset_counter.clicked.connect(self.reset_counters)
        self.btn_export_history = QPushButton("⤓ Export CSV")
        self.btn_export_history.setObjectName("ghostBtn")
        self.btn_export_history.clicked.connect(self.export_history_csv)
        header.addWidget(self.btn_reset_counter)
        header.addWidget(self.btn_export_history)
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
        self.history_table.setMinimumHeight(140)
        self.history_table.setMaximumHeight(200)

        layout.addWidget(self.history_table)
        self.history_card = card
        card.set_expanded(card._default_expanded, animate=False)
        self.right_layout.addWidget(card)

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

    def _stat_block(self, caption, value_object_name):
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        col.addStretch()
        value = QLabel("0")
        value.setObjectName(value_object_name)
        cap = QLabel(caption)
        cap.setObjectName("statLabel")
        col.addWidget(value)
        col.addWidget(cap)
        col.addStretch()
        return holder, value

    def _vline(self):
        line = QFrame()
        line.setObjectName("vline")
        line.setFixedWidth(1)
        return line

    def _load_logo(self):
        if getattr(self, "logo_path", None) and os.path.exists(self.logo_path):
            logo_pixmap = QPixmap(self.logo_path)
            if not logo_pixmap.isNull():
                scaled_logo = logo_pixmap.scaled(
                    34, 34,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.logo_label.setPixmap(scaled_logo)
                return
        self.logo_label.setText("◎")

    def _set_pill(self, holder, value):
        holder._value_label.setText(str(value))

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

    def _update_action_buttons(self):
        has_model = self.model is not None
        self.btn_reinspect.setEnabled(has_model)
        self.btn_add_extra_ref.setEnabled(has_model)
        self.btn_add_extra_ref_save.setEnabled(has_model)

    def _update_theme_button_text(self):
        theme = getattr(self, "_current_theme", "light")
        self.btn_theme_toggle.setText("☀  Light" if theme == "dark" else "☾  Dark")

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
