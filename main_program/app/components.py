"""Custom-painted widgets: yield bar, busy overlay spinner, collapsible card."""
from PyQt6.QtCore import Qt, QTimer, QRectF, QEvent, QEasingCurve, QPropertyAnimation
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QFont
from PyQt6.QtWidgets import QWidget, QFrame, QPushButton, QVBoxLayout


class CollapsibleCard(QFrame):
    """Sidebar card with a clickable header that expands/collapses its body.

    Callers attach a layout to `card.body`, then call
    `card.set_expanded(default, animate=False)` once populated.
    """

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("collapseCard")
        self._title = title
        self._expanded = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header = QPushButton()
        self._header.setObjectName("collapseHeader")
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.clicked.connect(self.toggle)

        self.body = QWidget()
        self.body.setObjectName("collapseBody")

        outer.addWidget(self._header)
        outer.addWidget(self.body)
        self._update_header()

    def is_expanded(self):
        return self._expanded

    def toggle(self):
        self.set_expanded(not self._expanded, animate=True)

    def set_expanded(self, expanded, animate=True):
        self._expanded = bool(expanded)
        self._update_header()
        if not animate:
            self.body.setMaximumHeight(16777215 if self._expanded else 0)
            return
        start = self.body.height()
        end = self.body.sizeHint().height() if self._expanded else 0
        anim = QPropertyAnimation(self.body, b"maximumHeight", self)
        anim.setDuration(220)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        if self._expanded:
            anim.finished.connect(lambda: self.body.setMaximumHeight(16777215))
        self._anim = anim
        anim.start()

    def _update_header(self):
        chevron = "▾" if self._expanded else "▸"
        self._header.setText(f"{chevron}   {self._title.upper()}")


class YieldBar(QWidget):
    """A slim rounded progress bar whose fill ratio (0..1) is animated externally."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ratio = 0.0
        self._track = QColor("#dbe2ec")
        self._fill = QColor("#4f46e5")
        self.setFixedHeight(8)

    def set_colors(self, track, fill):
        self._track = QColor(track)
        self._fill = QColor(fill)
        self.update()

    def set_ratio(self, ratio):
        self._ratio = max(0.0, min(1.0, float(ratio)))
        self.update()

    def ratio(self):
        return self._ratio

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)
        radius = r.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(self._track))
        p.drawRoundedRect(QRectF(r), radius, radius)
        if self._ratio > 0:
            fill_w = max(r.height(), r.width() * self._ratio)
            fill_rect = QRectF(r.x(), r.y(), fill_w, r.height())
            p.setBrush(QBrush(self._fill))
            p.drawRoundedRect(fill_rect, radius, radius)
        p.end()


class BusyOverlay(QWidget):
    """Translucent overlay with a rotating arc spinner, layered over the image view."""

    def __init__(self, host):
        super().__init__(host)
        self._host = host
        self._angle = 0
        self._message = "Analyzing"
        self._bg = QColor(15, 17, 23, 165)
        self._arc = QColor("#6366f1")
        self._text = QColor("#e2e8f0")
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self.hide()
        host.installEventFilter(self)
        self._sync_geometry()

    def set_theme(self, bg, arc, text):
        self._bg = QColor(bg)
        self._arc = QColor(arc)
        self._text = QColor(text)
        self.update()

    def eventFilter(self, obj, event):
        if obj is self._host and event.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show):
            self._sync_geometry()
        return super().eventFilter(obj, event)

    def _sync_geometry(self):
        self.setGeometry(self._host.rect())

    def _tick(self):
        self._angle = (self._angle + 6) % 360
        self.update()

    def start(self, message="Analyzing"):
        self._message = message
        self._sync_geometry()
        self.raise_()
        self.show()
        if not self._timer.isActive():
            self._timer.start()

    def stop(self):
        self._timer.stop()
        self.hide()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), self._bg)

        cx = self.width() / 2
        cy = self.height() / 2 - 14
        radius = 22

        # faint full ring
        track_pen = QPen(QColor(self._arc.red(), self._arc.green(), self._arc.blue(), 55))
        track_pen.setWidth(5)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(track_pen)
        p.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

        # rotating arc
        pen = QPen(self._arc)
        pen.setWidth(5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        start_angle = -self._angle * 16
        p.drawArc(rect, start_angle, 110 * 16)

        # message
        p.setPen(self._text)
        font = QFont(self.font())
        font.setPointSize(12)
        font.setBold(True)
        p.setFont(font)
        text_rect = QRectF(0, cy + radius + 8, self.width(), 30)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, f"{self._message}…")
        p.end()
