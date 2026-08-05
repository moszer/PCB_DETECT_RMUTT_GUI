_SHARED_BASE = """
* {{
    font-family: 'SF Pro Display', 'SF Pro Text', 'Segoe UI', 'Inter', 'Helvetica Neue', Arial, sans-serif;
    outline: none;
}}
QMainWindow, QWidget#rootWidget {{
    background-color: {bg_main};
}}
QWidget {{
    color: {text_primary};
    font-size: 13px;
}}
QToolTip {{
    background: {bg_elevated};
    color: {text_primary};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px 9px;
}}

/* ── Top Bar ── */
QWidget#topBar {{
    background: {bg_topbar};
    border: 1px solid {border};
    border-radius: 14px;
}}
QLabel#appTitle {{
    font-size: 19px;
    font-weight: 800;
    color: {text_heading};
    letter-spacing: -0.4px;
}}
QLabel#appSubtitle {{
    font-size: 11px;
    font-weight: 600;
    color: {text_muted};
    letter-spacing: 0.4px;
}}
QLabel#appLogo {{
    background: {logo_bg};
    border-radius: 12px;
}}

/* ── Sidebar ── */
QWidget#leftPanel {{
    background: transparent;
}}
QScrollArea#leftScroll {{
    background: {bg_panel};
    border: 1px solid {border};
    border-radius: 14px;
}}

/* ── Cards / Group Boxes ── */
QGroupBox#panelGroup {{
    font-weight: 700;
    font-size: 12px;
    border: 1px solid {border};
    border-radius: 12px;
    margin-top: 12px;
    padding: 16px 12px 12px 12px;
    background: {bg_card};
}}
QGroupBox#panelGroup::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    top: 2px;
    padding: 2px 8px;
    color: {text_muted};
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1.2px;
    background: transparent;
}}

/* ── Collapsible sidebar cards ── */
QFrame#collapseCard {{
    border: 1px solid {border};
    border-radius: 12px;
    background: {bg_card};
}}
QPushButton#collapseHeader {{
    background: transparent;
    border: none;
    border-radius: 12px;
    color: {text_muted};
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1.2px;
    text-align: left;
    padding: 11px 14px 9px 14px;
    min-height: 0px;
}}
QPushButton#collapseHeader:hover {{
    color: {accent};
    background: transparent;
}}

/* ── KPI strip divider ── */
QFrame#vline {{
    background: {border};
    border: none;
}}

/* ── Section chip label (icon + text headers) ── */
QLabel#sectionHint {{
    color: {text_muted};
    font-size: 11px;
    font-weight: 600;
}}
QLabel#fieldLabel {{
    color: {text_secondary};
    font-size: 12px;
    font-weight: 600;
}}

/* ── Verdict HUD Card ── */
/* Backgrounds are deliberately translucent: this badge floats over the board
   image, so an opaque card would hide the very components being inspected. */
QFrame#verdictCard {{
    border-radius: 16px;
    border: 1px solid {border};
    background: {badge_bg};
}}
QFrame#verdictCardPass {{
    border-radius: 16px;
    border: 1px solid {pass_border};
    background: {badge_pass_bg};
}}
QFrame#verdictCardFail {{
    border-radius: 16px;
    border: 1px solid {fail_border};
    background: {badge_fail_bg};
}}
QLabel#verdictBig {{
    font-size: 34px;
    font-weight: 900;
    letter-spacing: 1px;
    color: {text_muted};
}}
QLabel#verdictBigPass {{ font-size: 34px; font-weight: 900; letter-spacing: 1px; color: {pass_strong}; }}
QLabel#verdictBigFail {{ font-size: 34px; font-weight: 900; letter-spacing: 1px; color: {fail_strong}; }}
QLabel#verdictReason {{
    font-size: 12px;
    font-weight: 600;
    color: {text_secondary};
}}
QLabel#verdictImage {{
    font-size: 12px;
    font-weight: 700;
    color: {text_heading};
}}

/* ── Detail count pills (OK / Missing / Wrong / Extra) ── */
QLabel#pillOk, QLabel#pillMiss, QLabel#pillWrong, QLabel#pillExtra, QLabel#pillExpect {{
    border-radius: 9px;
    padding: 6px 4px;
    font-size: 12px;
    font-weight: 800;
    qproperty-alignment: AlignCenter;
}}
QLabel#pillExpect {{ background: {chip_bg}; color: {text_secondary}; }}
QLabel#pillOk    {{ background: {pass_soft}; color: {pass_strong}; }}
QLabel#pillMiss  {{ background: {fail_soft}; color: {fail_strong}; }}
QLabel#pillWrong {{ background: {warn_soft}; color: {warn_strong}; }}
QLabel#pillExtra {{ background: {info_soft}; color: {info_strong}; }}
QLabel#pillCap {{ color: {text_muted}; font-size: 10px; font-weight: 700; letter-spacing: 0.6px; qproperty-alignment: AlignCenter; }}

/* ── KPI Stat Cards ── */
QFrame#statCard {{
    border-radius: 14px;
    border: 1px solid {border};
    background: {bg_card};
}}
QLabel#statValue {{ font-size: 26px; font-weight: 900; color: {text_heading}; }}
QLabel#statValuePass {{ font-size: 26px; font-weight: 900; color: {pass_strong}; }}
QLabel#statValueFail {{ font-size: 26px; font-weight: 900; color: {fail_strong}; }}
QLabel#statValueAccent {{ font-size: 26px; font-weight: 900; color: {accent}; }}
QLabel#statLabel {{ font-size: 10px; font-weight: 800; letter-spacing: 1px; color: {text_muted}; }}

/* ── Buttons ── */
QPushButton {{
    border: 1px solid {btn_border};
    border-radius: 10px;
    background: {btn_bg};
    color: {text_primary};
    padding: 8px 14px;
    font-weight: 600;
    min-height: 34px;
}}
QPushButton:hover {{
    background: {btn_hover};
    border-color: {accent};
}}
QPushButton:pressed {{
    background: {btn_pressed};
}}
QPushButton:disabled {{
    color: {text_disabled};
    background: {btn_bg};
    border-color: {border};
}}
QPushButton:checked {{
    background: {accent};
    color: #ffffff;
    border-color: {accent_dark};
}}
QPushButton#primaryBtn {{
    background: {accent};
    color: #ffffff;
    border: 1px solid {accent_dark};
    font-weight: 800;
    font-size: 14px;
    min-height: 44px;
}}
QPushButton#primaryBtn:hover {{ background: {accent_dark}; border-color: {accent_dark}; }}
QPushButton#primaryBtn:pressed {{ background: {accent_darker}; }}
QPushButton#primaryBtn:disabled {{ background: {btn_bg}; color: {text_disabled}; border-color: {border}; }}
QPushButton#ghostBtn {{
    background: transparent;
    border: 1px solid {border};
    color: {text_secondary};
    min-height: 30px;
    padding: 6px 12px;
}}
QPushButton#ghostBtn:hover {{ background: {btn_hover}; color: {text_primary}; border-color: {accent}; }}
QPushButton#dangerBtn {{
    background: transparent;
    border: 1px solid {fail_border};
    color: {fail_strong};
}}
QPushButton#dangerBtn:hover {{ background: {fail_soft}; }}
QPushButton#iconBtn {{
    background: {bg_card};
    border: 1px solid {border};
    border-radius: 10px;
    min-width: 32px;
    min-height: 34px;
    padding: 4px 8px;
    font-weight: 700;
}}
QPushButton#iconBtn:hover {{ background: {btn_hover}; border-color: {accent}; }}

/* ── Zoom badge ── */
QLabel#zoomValue {{
    border: 1px solid {border};
    border-radius: 10px;
    background: {bg_card};
    padding: 4px 6px;
    min-width: 40px;
    qproperty-alignment: AlignCenter;
    font-weight: 800;
    color: {accent};
}}

/* ── Inputs ── */
QLineEdit, QComboBox, QSpinBox {{
    border: 1px solid {input_border};
    border-radius: 10px;
    padding: 7px 11px;
    background: {input_bg};
    color: {text_primary};
    selection-color: #ffffff;
    selection-background-color: {accent};
    min-height: 30px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border-color: {accent};
}}
QLineEdit:read-only {{
    background: {bg_readonly};
    color: {text_secondary};
}}
QComboBox QAbstractItemView {{
    color: {text_primary};
    background: {bg_elevated};
    selection-background-color: {accent};
    selection-color: #ffffff;
    border: 1px solid {border};
    border-radius: 8px;
    padding: 4px;
}}
QComboBox::drop-down {{ border: none; padding-right: 10px; width: 18px; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 18px; border: none; background: transparent; }}

/* ── Checkboxes ── */
QCheckBox {{
    color: {text_primary};
    spacing: 9px;
    min-height: 26px;
    font-size: 12px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 2px solid {input_border};
    background: {input_bg};
}}
QCheckBox::indicator:hover {{ border-color: {accent}; }}
QCheckBox::indicator:checked {{
    background: {accent};
    border-color: {accent_dark};
}}

/* ── Slider ── */
QSlider::groove:horizontal {{
    border: none;
    height: 6px;
    background: {slider_groove};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {bg_card};
    border: 3px solid {accent};
    width: 15px;
    height: 15px;
    margin: -7px 0;
    border-radius: 10px;
}}
QSlider::handle:horizontal:hover {{ border-color: {accent_dark}; }}
QSlider::sub-page:horizontal {{
    background: {accent};
    border-radius: 3px;
}}

/* ── Scrollbars ── */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px 2px 4px 0;
}}
QScrollBar::handle:vertical {{
    background: {scrollbar_handle};
    border-radius: 4px;
    min-height: 36px;
}}
QScrollBar::handle:vertical:hover {{ background: {scrollbar_hover}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0 4px 2px 4px;
}}
QScrollBar::handle:horizontal {{
    background: {scrollbar_handle};
    border-radius: 4px;
    min-width: 36px;
}}
QScrollBar::handle:horizontal:hover {{ background: {scrollbar_hover}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}

/* ── Status line ── */
QLabel#statusLine {{
    background: {bg_status};
    border: 1px solid {border};
    border-radius: 10px;
    padding: 9px 14px;
    font-size: 12px;
    font-weight: 600;
    color: {text_secondary};
}}
QLabel#statusBad {{
    color: {fail_strong};
    font-weight: 700;
    font-size: 12px;
}}
QLabel#perfLabel {{
    color: {text_muted};
    font-size: 11px;
    font-weight: 600;
}}

/* ── Table ── */
QTableWidget {{
    border: none;
    background: transparent;
    gridline-color: transparent;
    color: {text_primary};
    alternate-background-color: {table_alt};
}}
QTableWidget::item {{
    padding: 4px 6px;
    border-bottom: 1px solid {table_grid};
}}
QTableWidget::item:selected {{
    background: {row_selected};
    color: {text_heading};
}}
QHeaderView::section {{
    background: {table_header_bg};
    border: none;
    border-bottom: 2px solid {table_grid};
    padding: 9px 6px;
    font-weight: 800;
    font-size: 11px;
    letter-spacing: 0.4px;
    color: {text_muted};
}}
QTableCornerButton::section {{ background: {table_header_bg}; border: none; }}

/* ── Image viewer ── */
QScrollArea#imageScroll {{
    background: {bg_image_area};
    border: 1px solid {border};
    border-radius: 14px;
}}

/* ── Contextual right panel (selected component detail) ── */
QFrame#rightPanel {{
    background: {bg_panel};
    border: 1px solid {border};
    border-radius: 14px;
}}
QLabel#rightPanelTitle {{
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 1.2px;
    color: {text_muted};
}}
QPushButton#panelCloseBtn {{
    background: transparent;
    border: none;
    color: {text_muted};
    font-weight: 800;
    min-height: 24px;
    min-width: 24px;
    padding: 0px;
}}
QPushButton#panelCloseBtn:hover {{ color: {fail_strong}; }}
QLabel#detailLabel {{
    color: {text_muted};
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.8px;
}}
QLabel#detailValue {{
    color: {text_heading};
    font-size: 15px;
    font-weight: 800;
}}

/* ── Toggleable history panel ── */
QFrame#historyPanel {{
    background: {bg_panel};
    border: 1px solid {border};
    border-radius: 14px;
}}

/* ── Edit-mode toggle: warn amber once active, since it changes what clicks do ── */
QPushButton#editModeBtn:checked {{
    background: {warn_strong};
    color: #1a1206;
    border-color: {warn_strong};
}}

/* ── Native QMainWindow status bar (bottom bar) ── */
QStatusBar {{
    background: {bg_status};
    border-top: 1px solid {border};
    color: {text_secondary};
    font-size: 11px;
    font-weight: 600;
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {text_secondary}; font-size: 11px; font-weight: 600; }}
QLabel#statusBarText {{
    background: transparent;
    border: none;
    padding: 0px 4px;
    color: {text_secondary};
    font-size: 11px;
    font-weight: 600;
}}
"""

LIGHT_TOKENS = dict(
    bg_main="#eaeef4",
    bg_panel="#f6f8fb",
    bg_card="#ffffff",
    bg_elevated="#ffffff",
    bg_topbar="#ffffff",
    bg_status="#f1f5f9",
    bg_readonly="#f1f4f9",
    bg_image_area="#f4f7fb",
    logo_bg="#eef2ff",
    border="#dde3ec",
    btn_border="#cdd6e2",
    btn_bg="#ffffff",
    btn_hover="#eef2f8",
    btn_pressed="#e2e8f1",
    input_border="#cdd6e2",
    input_bg="#ffffff",
    text_primary="#1e293b",
    text_secondary="#475569",
    text_heading="#0f172a",
    text_muted="#94a3b8",
    text_disabled="#a9b4c2",
    accent="#4f46e5",
    accent_dark="#4338ca",
    accent_darker="#3730a3",
    pass_strong="#059669",
    pass_soft="#e7f7ef",
    pass_border="#a7e3c8",
    fail_strong="#dc2626",
    fail_soft="#fdecec",
    fail_border="#f4b8b8",
    warn_strong="#d97706",
    warn_soft="#fdf1e3",
    warn_border="#f3d3a0",
    info_strong="#0891b2",
    info_soft="#e4f6fb",
    info_border="#a8e0ec",
    chip_bg="#f1f5f9",
    scrollbar_handle="#cbd5e1",
    scrollbar_hover="#94a3b8",
    slider_groove="#dbe2ec",
    table_grid="#eef2f7",
    table_alt="#f8fafc",
    table_header_bg="#f4f7fb",
    row_selected="#e6e9fb",
    toggle_track_off="#cbd5e1",
    badge_bg="rgba(255, 255, 255, 0.86)",
    badge_pass_bg="rgba(226, 248, 238, 0.88)",
    badge_fail_bg="rgba(253, 232, 232, 0.88)",
)

DARK_TOKENS = dict(
    # "Clean Industrial Dashboard" palette — slate-900/800/700 + blue-500 accent.
    bg_main="#0f172a",
    bg_panel="#0f172a",
    bg_card="#1e293b",
    bg_elevated="#1e293b",
    bg_topbar="#1e293b",
    bg_status="#1e293b",
    bg_readonly="#17202f",
    bg_image_area="#0b1220",
    logo_bg="#1e293b",
    border="#334155",
    btn_border="#334155",
    btn_bg="#1e293b",
    btn_hover="#243244",
    btn_pressed="#2c3b52",
    input_border="#334155",
    input_bg="#131c2e",
    text_primary="#f1f5f9",
    text_secondary="#94a3b8",
    text_heading="#f8fafc",
    text_muted="#64748b",
    text_disabled="#475569",
    accent="#3b82f6",
    accent_dark="#2563eb",
    accent_darker="#1d4ed8",
    pass_strong="#10b981",
    pass_soft="#0f2a22",
    pass_border="#155e46",
    fail_strong="#ef4444",
    fail_soft="#2a1215",
    fail_border="#7f1d1d",
    warn_strong="#f59e0b",
    warn_soft="#2a1f0a",
    warn_border="#78350f",
    info_strong="#38bdf8",
    info_soft="#0c2436",
    info_border="#0e7490",
    chip_bg="#1e293b",
    scrollbar_handle="#334155",
    scrollbar_hover="#475569",
    slider_groove="#334155",
    table_grid="#1e293b",
    table_alt="#131c2e",
    table_header_bg="#1e293b",
    row_selected="#1e2b45",
    toggle_track_off="#334155",
    badge_bg="rgba(30, 41, 59, 0.82)",
    badge_pass_bg="rgba(6, 46, 34, 0.84)",
    badge_fail_bg="rgba(60, 16, 20, 0.84)",
)


def tokens_for(theme: str = "light") -> dict:
    return LIGHT_TOKENS if theme == "light" else DARK_TOKENS


REFERENCE_LABEL_STYLE = {
    "light": (
        "QLabel#imageDisplay {{ border: 2px dashed {border}; background-color: {bg_image_area};"
        " color: {text_muted}; border-radius: 12px; font-size: 14px; font-weight: 600; }}"
    ),
    "dark": (
        "QLabel#imageDisplay {{ border: 2px dashed {border}; background-color: {bg_image_area};"
        " color: {text_muted}; border-radius: 12px; font-size: 14px; font-weight: 600; }}"
    ),
}


def reference_label_style(theme: str = "light") -> str:
    tokens = tokens_for(theme)
    return REFERENCE_LABEL_STYLE[theme].format(**tokens)


def get_stylesheet(theme: str = "light") -> str:
    return _SHARED_BASE.format(**tokens_for(theme))
