import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFontMetrics, QPixmap
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
from ..widgets import ReferenceLabel
from ..components import YieldBar, BusyOverlay, CollapsibleCard, ToggleSwitch


class UIMixin:
    """Clean Industrial Dashboard layout: a 64px-ish top bar (branding, KPIs,
    actions), a 280px collapsible control panel, a center viewport (the image
    is the dominant element) with a floating verdict badge and an on-demand
    history panel, a 320px contextual panel for the selected component, and
    the native QMainWindow status bar for timing/status text."""

    def init_ui(self):
        self._toggle_switches = []

        self.main_widget = QWidget()
        self.main_widget.setObjectName("rootWidget")
        self.setCentralWidget(self.main_widget)

        outer = QVBoxLayout(self.main_widget)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(12)

        self.build_topbar()
        outer.addWidget(self.topbar)

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
        self._update_action_buttons()
        self.apply_responsive_layout()

    def apply_responsive_layout(self):
        """Scale the side panels and history panel with the window size instead
        of leaving them pinned to fixed pixel dimensions. Floors match the
        narrowest size the sidebar's button rows are verified to fit at."""
        width = self.width()
        height = self.height()

        if width > 0 and hasattr(self, "left_scroll"):
            self.left_scroll.setFixedWidth(max(300, min(380, round(width * 0.20))))

        if width > 0 and hasattr(self, "right_panel"):
            self.right_panel.setFixedWidth(max(300, min(400, round(width * 0.22))))

        if height > 0 and hasattr(self, "history_panel"):
            self.history_panel.setMaximumHeight(max(200, min(420, round(height * 0.30))))

    # ────────────────────────────────────────────────────────── top bar
    def build_topbar(self):
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(70)
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(8)
        self.topbar = bar

        self.btn_toggle_left = QPushButton("☰")
        self.btn_toggle_left.setObjectName("iconBtn")
        self.btn_toggle_left.setToolTip("Show / hide the control panel")
        self.btn_toggle_left.clicked.connect(self.toggle_left_panel)
        row.addWidget(self.btn_toggle_left)

        self.logo_label = QLabel()
        self.logo_label.setObjectName("appLogo")
        self.logo_label.setFixedSize(40, 40)
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
        row.addSpacing(6)
        row.addWidget(self._vline())

        # KPI strip — global production stats, single source of truth (not
        # repeated elsewhere in the UI). Wrapped in its own card so the numbers
        # read as one grouped stat cluster instead of loose floating text.
        stat_card = QFrame()
        stat_card.setObjectName("statCard")
        stat_row = QHBoxLayout(stat_card)
        stat_row.setContentsMargins(10, 4, 10, 4)
        stat_row.setSpacing(9)

        block, self.total_label = self._stat_block("TOTAL", "statValueAccent")
        stat_row.addWidget(block)
        stat_row.addWidget(self._vline())
        block, self.pass_label = self._stat_block("PASS", "statValuePass")
        stat_row.addWidget(block)
        stat_row.addWidget(self._vline())
        block, self.fail_label = self._stat_block("FAIL", "statValueFail")
        stat_row.addWidget(block)
        stat_row.addWidget(self._vline())
        yield_block, self.yield_value = self._stat_block("YIELD", "statValue")
        self.yield_bar = YieldBar()
        self.yield_bar.setFixedWidth(60)
        yield_block.layout().insertWidget(2, self.yield_bar)
        self.yield_value.setText("—")
        stat_row.addWidget(yield_block)

        row.addWidget(stat_card)
        row.addStretch()

        self.btn_select = QPushButton("Select")
        self.btn_select.setObjectName("primaryBtn")
        self.btn_select.setToolTip("Open an inspection image  (Ctrl+O)")
        self.btn_select.clicked.connect(self.select_image)
        row.addWidget(self.btn_select)

        self.btn_reinspect = QPushButton("↻")
        self.btn_reinspect.setObjectName("iconBtn")
        self.btn_reinspect.setToolTip("Re-run inspection on the current image  (Ctrl+R)")
        self.btn_reinspect.clicked.connect(self.inspect_current_image)
        row.addWidget(self.btn_reinspect)

        self.btn_save_annotated = QPushButton("⤓")
        self.btn_save_annotated.setObjectName("iconBtn")
        self.btn_save_annotated.setToolTip("Save the annotated image  (Ctrl+S)")
        self.btn_save_annotated.clicked.connect(self.save_annotated_image)
        row.addWidget(self.btn_save_annotated)

        self.btn_export_history = QPushButton("CSV")
        self.btn_export_history.setObjectName("iconBtn")
        self.btn_export_history.setToolTip("Export inspection history to CSV")
        self.btn_export_history.clicked.connect(self.export_history_csv)
        row.addWidget(self.btn_export_history)

        self.btn_toggle_history = QPushButton("History")
        self.btn_toggle_history.setObjectName("iconBtn")
        self.btn_toggle_history.setCheckable(True)
        self.btn_toggle_history.setToolTip("Show / hide inspection history")
        self.btn_toggle_history.clicked.connect(self.toggle_history_panel)
        row.addWidget(self.btn_toggle_history)

        row.addWidget(self._vline())

        self.btn_theme_toggle = QPushButton()
        self.btn_theme_toggle.setObjectName("iconBtn")
        self.btn_theme_toggle.setToolTip("Toggle Dark / Light Mode  (Ctrl+D)")
        self.btn_theme_toggle.clicked.connect(self.toggle_theme)
        self._update_theme_button_text()
        row.addWidget(self.btn_theme_toggle)

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

        row.addWidget(self.btn_zoom_out)
        row.addWidget(self.zoom_value_label)
        row.addWidget(self.btn_zoom_in)
        row.addWidget(self.btn_zoom_fit)

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
        self.left_layout.setContentsMargins(12, 12, 12, 12)
        self.left_layout.setSpacing(12)

        self.left_scroll = QScrollArea()
        self.left_scroll.setObjectName("leftScroll")
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.left_scroll.setFixedWidth(304)
        self.left_scroll.setWidget(self.left_panel)

        self.build_inspection_group()
        self.build_display_group()
        self.build_reference_group()
        self.build_station_group()
        self.left_layout.addStretch()

    def toggle_left_panel(self):
        self.left_scroll.setVisible(not self.left_scroll.isVisible())

    def build_inspection_group(self):
        card, layout = self._sidebar_card("🔍  Inspection", expanded=True, grid=True)
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

        layout.addWidget(self.conf_label, 0, 0, 1, 2)
        layout.addWidget(self.conf_slider, 1, 0, 1, 2)
        layout.addWidget(self._field_label("Match distance"), 2, 0)
        layout.addWidget(self.match_dist_spin, 2, 1)
        self.inspection_card = card
        card.set_expanded(card._default_expanded, animate=False)
        self.left_layout.addWidget(card)

    def build_display_group(self):
        card, layout = self._sidebar_card("👁️  Display", expanded=False)
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
        card, layout = self._sidebar_card("⚙️  Station & Model", expanded=False, grid=True)
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
        self.station_card = card
        card.set_expanded(card._default_expanded, animate=False)
        self.left_layout.addWidget(card)

    def build_reference_group(self):
        card, layout = self._sidebar_card("✏️  Reference Profile", expanded=False, grid=True)
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

        self.build_image_view()
        self.build_history_panel()

    def build_image_view(self):
        viewport = QWidget()
        grid = QGridLayout(viewport)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setSpacing(0)

        self.image_scroll = QScrollArea()
        self.image_scroll.setObjectName("imageScroll")
        self.image_scroll.setWidgetResizable(False)
        self.image_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.image_display = ReferenceLabel(self)
        self.image_display.setObjectName("imageDisplay")
        self.image_display.setMinimumSize(320, 220)
        self.image_display.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.image_scroll.setWidget(self.image_display)
        grid.addWidget(self.image_scroll, 0, 0)

        self._build_verdict_badge()
        grid.addWidget(self.verdict_card, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self.busy_overlay = BusyOverlay(self.image_scroll)

        self.center_layout.addWidget(viewport, 1)

    def _build_verdict_badge(self):
        """The PASS/FAIL result — a compact badge floating over the top-left
        corner of the viewport, instead of a full-width card competing with
        the image for attention.

        Hidden until the first inspection produces a result (revealed by
        update_result_panel), so the empty viewport shows only its own
        placeholder rather than a second 'load an image' message sitting on
        top of it next to a row of meaningless zero counts."""
        self.verdict_card = QFrame()
        self.verdict_card.setObjectName("verdictCard")
        self.verdict_card.setMaximumWidth(300)
        self.verdict_card.setVisible(False)
        vc = QVBoxLayout(self.verdict_card)
        vc.setContentsMargins(16, 11, 16, 12)
        vc.setSpacing(5)

        self.verdict_label = QLabel("READY")
        self.verdict_label.setObjectName("verdictBig")
        vc.addWidget(self.verdict_label)

        # Not word-wrapped: dataset filenames run 80+ chars and would stack the
        # badge three lines taller, covering more of the board. Elided instead,
        # with the full name on hover (see set_verdict_image_name).
        self.verdict_image_name = QLabel("No image loaded")
        self.verdict_image_name.setObjectName("verdictImage")
        vc.addWidget(self.verdict_image_name)

        self.verdict_reason = QLabel("Load an image to begin inspection.")
        self.verdict_reason.setObjectName("verdictReason")
        self.verdict_reason.setWordWrap(True)
        vc.addWidget(self.verdict_reason)

        pills = QHBoxLayout()
        pills.setSpacing(6)
        self.pill_expect = self._detail_pill("EXPECT", "pillExpect")
        self.pill_ok = self._detail_pill("OK", "pillOk")
        self.pill_miss = self._detail_pill("MISSING", "pillMiss")
        self.pill_wrong = self._detail_pill("WRONG", "pillWrong")
        self.pill_extra = self._detail_pill("EXTRA", "pillExtra")
        for holder in (self.pill_expect, self.pill_ok, self.pill_miss, self.pill_wrong, self.pill_extra):
            pills.addWidget(holder)
        vc.addLayout(pills)

    def build_history_panel(self):
        """Hidden by default; toggled from the top bar instead of always
        occupying vertical space in the main column."""
        self.history_panel = QFrame()
        self.history_panel.setObjectName("historyPanel")
        self.history_panel.setVisible(False)
        self.history_panel.setMaximumHeight(280)
        layout = QVBoxLayout(self.history_panel)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("INSPECTION HISTORY")
        title.setObjectName("rightPanelTitle")
        header.addWidget(title)
        header.addStretch()
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
        self.history_table.setMinimumHeight(140)
        layout.addWidget(self.history_table)

        self.center_layout.addWidget(self.history_panel, 0)

    def toggle_history_panel(self):
        visible = not self.history_panel.isVisible()
        self.history_panel.setVisible(visible)
        self.btn_toggle_history.setChecked(visible)

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
        self.stats_label = QLabel("System ready.")
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

    def _stat_block(self, caption, value_object_name):
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
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
        """Fit a filename onto the badge's single name line. Elides in the
        middle so both the descriptive head and the distinguishing tail
        (dataset id + extension) stay readable; full name goes to the tooltip."""
        metrics = QFontMetrics(self.verdict_image_name.font())
        # Badge max width less its 16px side margins and 1px borders.
        available = max(80, self.verdict_card.maximumWidth() - 36)
        self.verdict_image_name.setText(
            metrics.elidedText(name, Qt.TextElideMode.ElideMiddle, available)
        )
        self.verdict_image_name.setToolTip(name)

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

    def _update_action_buttons(self):
        has_model = self.model is not None
        self.btn_reinspect.setEnabled(has_model)
        self.btn_add_extra_ref.setEnabled(has_model)
        self.btn_add_extra_ref_save.setEnabled(has_model)

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
