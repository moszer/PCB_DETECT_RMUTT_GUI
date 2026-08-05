import os

from PyQt6.QtCore import Qt, QTimer, QRectF, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPixmap, QPainter, QColor, QBrush, QPen, QFont
from PyQt6.QtWidgets import QWidget, QGraphicsOpacityEffect, QApplication


class _ProgressStripe(QWidget):
    """A slim indeterminate progress bar with a sweeping accent segment."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = 0.0
        self.setFixedHeight(4)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _tick(self):
        self._phase = (self._phase + 0.018) % 1.0
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        radius = r.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(255, 255, 255, 34)))
        p.drawRoundedRect(QRectF(r), radius, radius)

        seg_w = r.width() * 0.32
        travel = r.width() + seg_w
        x = -seg_w + self._phase * travel
        p.setBrush(QBrush(QColor("#6366f1")))
        p.drawRoundedRect(QRectF(x, 0, seg_w, r.height()), radius, radius)
        p.end()


class SplashScreen(QWidget):
    """Branded, animated splash: fades in, sweeps a progress bar, fades out."""

    def __init__(self, logo_path: str, duration_ms: int = 1600):
        super().__init__()
        self._duration_ms = duration_ms
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.SplashScreen
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(460, 300)

        self._logo = QPixmap(logo_path) if os.path.exists(logo_path) else QPixmap()
        if not self._logo.isNull():
            self._logo = self._logo.scaled(
                84, 84, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )

        self._stripe = _ProgressStripe(self)
        self._stripe.setGeometry(70, 232, 320, 4)

        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)

        self._center_on_screen()

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        card = self.rect().adjusted(1, 1, -1, -1)

        p.setPen(QPen(QColor("#2a3145"), 1))
        p.setBrush(QBrush(QColor("#141824")))
        p.drawRoundedRect(QRectF(card), 20, 20)

        # accent top strip
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#6366f1")))
        p.drawRoundedRect(QRectF(card.x(), card.y(), card.width(), 6), 20, 20)
        p.drawRect(QRectF(card.x(), card.y() + 4, card.width(), 6))

        if not self._logo.isNull():
            lx = (self.width() - self._logo.width()) // 2
            p.drawPixmap(lx, 44, self._logo)
        else:
            p.setPen(QColor("#6366f1"))
            f = QFont(self.font()); f.setPointSize(40); f.setBold(True); p.setFont(f)
            p.drawText(QRectF(0, 40, self.width(), 88), Qt.AlignmentFlag.AlignCenter, "◎")

        p.setPen(QColor("#f1f5f9"))
        title_font = QFont(self.font()); title_font.setPointSize(17); title_font.setBold(True)
        p.setFont(title_font)
        p.drawText(QRectF(0, 150, self.width(), 30), Qt.AlignmentFlag.AlignCenter, "Defect Inspection Station")

        p.setPen(QColor("#6b788f"))
        sub_font = QFont(self.font()); sub_font.setPointSize(10)
        p.setFont(sub_font)
        p.drawText(QRectF(0, 182, self.width(), 22), Qt.AlignmentFlag.AlignCenter, "PCB component verification")

        p.setPen(QColor("#4a5568"))
        small = QFont(self.font()); small.setPointSize(9)
        p.setFont(small)
        p.drawText(QRectF(0, 258, self.width(), 20), Qt.AlignmentFlag.AlignCenter, "Loading model & references…")
        p.end()

    def _fade(self, start, end, duration, on_finished=None):
        anim = QPropertyAnimation(self._effect, b"opacity", self)
        anim.setDuration(duration)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        if on_finished:
            anim.finished.connect(on_finished)
        self._anim = anim
        anim.start()

    def show_and_close_after(self, callback):
        self.show()
        self.raise_()
        self._stripe.start()
        self._fade(0.0, 1.0, 320)
        QTimer.singleShot(self._duration_ms, callback)

    def finish(self, window):
        self._stripe.stop()

        def _close():
            self.close()

        self._fade(1.0, 0.0, 260, on_finished=_close)
