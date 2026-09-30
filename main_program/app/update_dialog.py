"""Update checks and installation run off the GUI thread."""
from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from .updater import GitUpdater


class UpdateWorker(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.result.emit(self.operation())
        except Exception as exc:
            self.failed.emit(str(exc))


class UpdateDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("PCB Inspect — Software updates")
        self.setMinimumSize(580, 420)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.updater = GitUpdater(parent.project_root)
        self.info = None
        self.worker = None
        self.installed = False
        self._busy = False
        layout = QVBoxLayout(self)
        self.status = QLabel("Check GitHub for the latest version on main.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.versions = QLabel("Current version: checking…")
        self.versions.setWordWrap(True)
        layout.addWidget(self.versions)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        layout.addWidget(self.details, 1)
        note = QLabel("Local edits and file collisions stop the update. After installation, close and reopen the app.")
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        self.check_button = QPushButton("Check for updates")
        self.install_button = QPushButton("Install update")
        self.install_button.setEnabled(False)
        self.close_button = QPushButton("Close")
        for button in (self.check_button, self.install_button, self.close_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.check_button.clicked.connect(self.check)
        self.install_button.clicked.connect(self.install)
        self.close_button.clicked.connect(self.accept)

    def start(self, operation, handler):
        self._busy = True
        self.check_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.worker = UpdateWorker(operation, self)
        self.worker.result.connect(handler)
        self.worker.failed.connect(self.failure)
        self.worker.finished.connect(self.finished_work)
        self.worker.start()

    def finished_work(self):
        self._busy = False
        self.check_button.setEnabled(not self.installed)
        self.close_button.setEnabled(True)
        self.install_button.setEnabled(bool(self.info and self.info.available and not self.installed))

    def check(self):
        if self._busy:
            return
        self.info = None
        self.status.setText("Checking GitHub…")
        self.details.clear()
        self.start(self.updater.check, self.checked)

    def checked(self, info):
        self.info = info
        self.versions.setText(f"Installed: {info.version}\nGitHub main: {info.latest_version}")
        self.details.setPlainText(info.commits or "No new commits.")
        if info.current == info.target:
            self.status.setText("You are up to date with GitHub main.")
            if info.blocker:
                self.details.appendPlainText(
                    "\nNo installation is needed. Before a future update:\n" + info.blocker
                )
        elif info.blocker:
            self.status.setText("Automatic update is unavailable.")
            self.details.appendPlainText("\n" + info.blocker)
        elif info.available:
            self.status.setText("An update is available. Review the changes, then install.")
        else:
            self.status.setText("You are up to date.")
        if any("requirements" in p or p.endswith("pyproject.toml") for p in info.changes):
            self.details.appendPlainText("\nDependencies changed: follow the updated README for your platform before reopening. "
                                         "Python/CUDA packages are not installed automatically.")

    def install(self):
        if self._busy or not self.info or not self.info.available:
            return
        owner = self.parent()
        if getattr(owner, "_inference_running", False) or getattr(owner, "_camera_worker", None) is not None:
            self.status.setText("Stop the camera and wait for inspection to finish before installing.")
            return
        owner.save_settings()
        self.status.setText("Installing the reviewed version…")
        self.start(lambda: self.updater.install(self.info), self.did_install)

    def did_install(self, backup):
        self.installed = True
        self.status.setText("Update installed. Close and reopen PCB Inspect to use the new version.")
        self.versions.setText(f"Installed on disk: {self.info.latest_version}\nRunning version: {self.info.version} (restart required)")
        if backup:
            self.details.appendPlainText("\nPrevious model/data files saved to:\n" + backup)
        self.close_button.setText("Close application")

    def failure(self, message):
        self.info = None
        self.status.setText("Update could not be completed.")
        self.details.setPlainText(message)
        self.versions.setText("Version check incomplete; try again.")

    def done(self, result):
        if self._busy:
            return
        super().done(result)
        if self.installed:
            self.parent().close()

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)
