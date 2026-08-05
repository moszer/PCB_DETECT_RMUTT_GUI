from PyQt6.QtCore import Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QLabel


class ReferenceLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_gui = parent
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText("Load image to start inspection\n\nDrag & drop an image here  ·  Ctrl+O")
        self.setStyleSheet("border: 2px dashed #b0b8c4; background-color: #f6f8fa; color: #4b5563; border-radius: 8px;")

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
