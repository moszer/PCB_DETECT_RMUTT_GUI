"""Keyboard shortcuts, drag-and-drop, Ctrl+scroll zoom, and launch/theme fades."""
import os

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeySequence, QShortcut

from ..animations import fade_in
from ..utils import IMAGE_EXTENSIONS


class InteractionMixin:
    def setup_interactions(self):
        self.setAcceptDrops(True)
        self._first_show_done = False
        self._install_shortcuts()
        if hasattr(self, "image_scroll"):
            self.image_scroll.viewport().installEventFilter(self)

    def _install_shortcuts(self):
        def bind(seq, handler):
            shortcut = QShortcut(QKeySequence(seq), self)
            shortcut.activated.connect(handler)
            return shortcut

        bind("Ctrl+O", self.select_image)
        bind("Ctrl+Shift+O", self.select_folder)
        bind("Ctrl+Right", self.show_next_image)
        bind("Ctrl+Left", self.show_prev_image)
        bind("PgDown", self.show_next_image)
        bind("PgUp", self.show_prev_image)
        bind("Ctrl+R", self.inspect_current_image)
        bind("F5", self.inspect_current_image)
        bind("Ctrl+S", self.save_annotated_image)
        bind("Ctrl+E", lambda: self.btn_edit_mode.click())
        bind("Ctrl+D", self.toggle_theme)
        bind("Ctrl++", self.zoom_in)
        bind("Ctrl+=", self.zoom_in)
        bind("Ctrl+-", self.zoom_out)
        bind("Ctrl+0", self.zoom_fit)
        bind("Ctrl+Z", self.undo)
        bind("Ctrl+Shift+Z", self.redo)
        bind("Ctrl+Y", self.redo)

    def eventFilter(self, obj, event):
        if hasattr(self, "image_scroll") and obj is self.image_scroll.viewport():
            if (
                event.type() == QEvent.Type.Wheel
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                and self.current_image_pixmap
            ):
                if event.angleDelta().y() > 0:
                    self.zoom_in()
                else:
                    self.zoom_out()
                return True
            if event.type() == QEvent.Type.Resize:
                # Layout changes (e.g. collapsing the history card) resize the
                # viewer without a window resize — keep the placeholder filling it.
                self._sync_placeholder_size()
        return super().eventFilter(obj, event)

    # ── Drag & drop an image (or a folder of images) onto the window ──
    def dragEnterEvent(self, event):
        if self._drop_path(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        path = self._drop_path(event)
        if path is None:
            event.ignore()
            return
        event.acceptProposedAction()
        if os.path.isdir(path):
            self.load_image_folder(path)
        else:
            self.open_image_path(path)

    def _drop_path(self, event):
        mime = event.mimeData()
        if not mime.hasUrls():
            return None
        for url in mime.urls():
            local = url.toLocalFile()
            if not local:
                continue
            if os.path.isdir(local) or local.lower().endswith(IMAGE_EXTENSIONS):
                return local
        return None

    # ── Fades ──
    def fade_content(self, start=0.25, duration=240):
        if hasattr(self, "main_widget"):
            fade_in(self.main_widget, duration=duration, start=start)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_first_show_done", False):
            self._first_show_done = True
            self.fade_content(start=0.0, duration=340)
