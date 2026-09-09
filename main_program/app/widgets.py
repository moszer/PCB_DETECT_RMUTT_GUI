from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QMouseEvent, QPainter, QColor, QPen, QFont, QPainterPath
from PyQt6.QtWidgets import QLabel, QSizePolicy


class ElidedLabel(QLabel):
    """Keep full text available on hover without forcing the window wider."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setToolTip(text)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(self.foregroundRole()))
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideMiddle, self.contentsRect().width())
        painter.drawText(self.contentsRect(), self.alignment() | Qt.AlignmentFlag.AlignVCenter, text)


class ReferenceLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_gui = parent
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tokens = {}
        self.setAccessibleName("PCB inspection canvas. Drop an image or use Open image.")

    def set_theme(self, tokens):
        self._tokens = tokens
        self.update()

    def paintEvent(self, event):
        if self.parent_gui and self.parent_gui.current_image_pixmap:
            super().paintEvent(event)
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 9, 9)
        p.setClipPath(clip)
        p.fillRect(self.rect(), QColor("#101e2a"))
        p.setPen(QPen(QColor("#243544"), 1))
        for x in range(20, self.width(), 24):
            for y in range(20, self.height(), 24):
                p.drawPoint(x, y)
        cx, cy = self.width() / 2, self.height() / 2 - 32
        if self.height() >= 260:
            p.setBrush(QColor("#132f38"))
            p.setPen(QPen(QColor("#2b6267"), 1.5))
            p.drawRoundedRect(QRectF(cx - 36, cy - 70, 72, 72), 18, 18)
            p.setBrush(QColor("#173f45"))
            p.setPen(QPen(QColor("#5ed4be"), 2))
            p.drawRoundedRect(QRectF(cx - 15, cy - 49, 30, 30), 4, 4)
            for offset in (-8, 0, 8):
                p.drawLine(QPointF(cx + offset, cy - 56), QPointF(cx + offset, cy - 49))
                p.drawLine(QPointF(cx + offset, cy - 19), QPointF(cx + offset, cy - 12))
                p.drawLine(QPointF(cx - 22, cy - 34 + offset), QPointF(cx - 15, cy - 34 + offset))
                p.drawLine(QPointF(cx + 15, cy - 34 + offset), QPointF(cx + 22, cy - 34 + offset))
        font = QFont(self.font())
        font.setPixelSize(23 if self.width() > 500 else 19)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor("#e8f0f6"))
        p.drawText(QRectF(0, cy + 20, self.width(), 32), Qt.AlignmentFlag.AlignCenter, "Your next inspection starts here")
        font.setPixelSize(12)
        font.setBold(False)
        p.setFont(font)
        p.setPen(QColor("#9eb2c4"))
        p.drawText(QRectF(0, cy + 62, self.width(), 22), Qt.AlignmentFlag.AlignCenter, "Drop a PCB image or folder into this workspace")
        p.setPen(QColor("#66cdbd"))
        p.drawText(QRectF(0, cy + 91, self.width(), 22), Qt.AlignmentFlag.AlignCenter, "Open image  ·  Ctrl+O     /     Camera source in setup")
        p.end()

    def mousePressEvent(self, event: QMouseEvent):
        if not self.parent_gui or not self.parent_gui.current_image_pixmap:
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
            if orig_w <= 0 or orig_h <= 0 or scaled_w <= 0 or scaled_h <= 0:
                return
            real_x = int(click_x * (orig_w / scaled_w))
            real_y = int(click_y * (orig_h / scaled_h))

            if self.parent_gui.is_edit_mode:
                selected_class = self.parent_gui.combo_classes.currentText()
                self.parent_gui.add_reference_point(real_x, real_y, selected_class)
            elif hasattr(self.parent_gui, "select_detection_at"):
                self.parent_gui.select_detection_at(real_x, real_y)
