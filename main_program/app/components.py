"""Custom-painted widgets: yield bar, busy overlay spinner, collapsible card, toggle switch."""
from PyQt6.QtCore import Qt, QTimer, QRectF, QSize, QEvent, QEasingCurve, QPropertyAnimation, pyqtProperty
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QFont
from PyQt6.QtWidgets import QWidget, QFrame, QPushButton, QCheckBox, QVBoxLayout


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


class ToggleSwitch(QCheckBox):
    """A sliding pill-shaped toggle switch. QSS can't paint this shape convincingly,
    so — like YieldBar/BusyOverlay — it's custom-painted and themed via set_colors()."""

    _WIDTH = 40
    _HEIGHT = 22

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._track_off = QColor("#cbd5e1")
        self._track_on = QColor("#6366f1")
        self._knob = QColor("#ffffff")
        self._pos = 1.0 if self.isChecked() else 0.0
        self._anim = QPropertyAnimation(self, b"handlePosition", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate_to)
        self.setMinimumHeight(self._HEIGHT + 4)

    def set_colors(self, track_off, track_on, knob):
        self._track_off = QColor(track_off)
        self._track_on = QColor(track_on)
        self._knob = QColor(knob)
        self.update()

    def _animate_to(self, checked):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def _get_handle_position(self):
        return self._pos

    def _set_handle_position(self, value):
        self._pos = value
        self.update()

    handlePosition = pyqtProperty(float, fget=_get_handle_position, fset=_set_handle_position)

    def sizeHint(self):
        base = super().sizeHint()
        text_w = self.fontMetrics().horizontalAdvance(self.text()) if self.text() else 0
        extra = self._WIDTH + 10 + text_w if self.text() else self._WIDTH
        return QSize(extra + 4, max(base.height(), self._HEIGHT + 4))

    def hitButton(self, pos):
        return self.contentsRect().contains(pos)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        y = (self.height() - self._HEIGHT) // 2
        track_rect = QRectF(0, y, self._WIDTH, self._HEIGHT)
        radius = self._HEIGHT / 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._blend(self._track_off, self._track_on, self._pos)))
        painter.drawRoundedRect(track_rect, radius, radius)

        knob_d = self._HEIGHT - 6
        knob_x = 3 + self._pos * (self._WIDTH - knob_d - 6)
        painter.setBrush(QBrush(self._knob))
        painter.drawEllipse(QRectF(knob_x, y + 3, knob_d, knob_d))

        if self.text():
            painter.setPen(QPen(self.palette().windowText().color()))
            painter.setFont(QFont(self.font()))
            text_rect = self.rect().adjusted(self._WIDTH + 10, 0, 0, 0)
            painter.drawText(
                text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text()
            )
        painter.end()

    @staticmethod
    def _blend(c1, c2, t):
        r = c1.red() + (c2.red() - c1.red()) * t
        g = c1.green() + (c2.green() - c1.green()) * t
        b = c1.blue() + (c2.blue() - c1.blue()) * t
        return QColor(int(r), int(g), int(b))
