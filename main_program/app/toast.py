"""Lightweight toast notifications that slide in from the bottom-right."""
from PyQt6.QtCore import Qt, QEasingCurve, QPropertyAnimation, QPoint, QTimer
from PyQt6.QtWidgets import QFrame, QLabel, QHBoxLayout, QGraphicsOpacityEffect


_KIND_COLORS = {
    "light": {
        "info": ("#ffffff", "#4f46e5", "#1e293b"),
        "success": ("#e7f7ef", "#059669", "#065f46"),
        "error": ("#fdecec", "#dc2626", "#991b1b"),
        "warn": ("#fdf1e3", "#d97706", "#92400e"),
    },
    "dark": {
        "info": ("#20263a", "#6366f1", "#e2e8f0"),
        "success": ("#12281f", "#34d399", "#d1fae5"),
        "error": ("#2a1518", "#f87171", "#fecaca"),
        "warn": ("#2a2011", "#fbbf24", "#fde68a"),
    },
}

_ICONS = {"info": "ℹ", "success": "✓", "error": "✕", "warn": "!"}


class ToastManager:
    def __init__(self, host):
        self.host = host
        self.theme = "light"
        self._toasts = []

    def set_theme(self, theme):
        self.theme = theme

    def show(self, message, kind="info", duration=2800):
        bg, accent, fg = _KIND_COLORS.get(self.theme, _KIND_COLORS["light"]).get(
            kind, _KIND_COLORS[self.theme]["info"]
        )
        toast = QFrame(self.host)
        toast.setObjectName("toast")
        toast.setStyleSheet(
            f"""
            QFrame#toast {{
                background: {bg};
                border: 1px solid {accent};
                border-left: 4px solid {accent};
                border-radius: 11px;
            }}
            QLabel#toastIcon {{ color: {accent}; font-size: 15px; font-weight: 900; }}
            QLabel#toastMsg {{ color: {fg}; font-size: 12px; font-weight: 600; }}
            """
        )
        layout = QHBoxLayout(toast)
        layout.setContentsMargins(14, 10, 16, 10)
        layout.setSpacing(10)

        icon = QLabel(_ICONS.get(kind, "ℹ"))
        icon.setObjectName("toastIcon")
        msg = QLabel(message)
        msg.setObjectName("toastMsg")
        msg.setWordWrap(True)
        msg.setMaximumWidth(300)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(msg, 1)

        toast.adjustSize()
        effect = QGraphicsOpacityEffect(toast)
        toast.setGraphicsEffect(effect)
        toast._opacity = effect

        self._toasts.append(toast)
        self._reposition()
        toast.show()
        toast.raise_()

        start_pos = toast.pos() + QPoint(0, 18)
        slide = QPropertyAnimation(toast, b"pos", toast)
        slide.setDuration(300)
        slide.setStartValue(start_pos)
        slide.setEndValue(toast.pos())
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)

        fade = QPropertyAnimation(effect, b"opacity", toast)
        fade.setDuration(300)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)

        toast._in_anims = (slide, fade)
        slide.start()
        fade.start()

        QTimer.singleShot(duration, lambda: self._dismiss(toast))

    def _dismiss(self, toast):
        if toast not in self._toasts:
            return
        effect = getattr(toast, "_opacity", None)
        if effect is None:
            self._remove(toast)
            return
        fade = QPropertyAnimation(effect, b"opacity", toast)
        fade.setDuration(260)
        fade.setStartValue(1.0)
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.Type.InCubic)
        fade.finished.connect(lambda: self._remove(toast))
        toast._out_anim = fade
        fade.start()

    def _remove(self, toast):
        if toast in self._toasts:
            self._toasts.remove(toast)
        toast.hide()
        toast.deleteLater()
        self._reposition()

    def _reposition(self):
        margin = 22
        y = self.host.height() - margin
        for toast in reversed(self._toasts):
            toast.adjustSize()
            w = toast.width()
            h = toast.height()
            x = self.host.width() - w - margin
            y -= h
            toast.move(QPoint(x, y))
            y -= 10

    def reflow(self):
        self._reposition()
