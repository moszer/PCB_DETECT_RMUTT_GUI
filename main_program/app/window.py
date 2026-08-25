import os

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMainWindow

from .mixins.browse_mixin import BrowseMixin
from .mixins.camera_mixin import CameraMixin
from .mixins.history_mixin import HistoryMixin
from .mixins.inspection_mixin import InspectionMixin
from .mixins.interaction_mixin import InteractionMixin
from .mixins.model_reference_mixin import ModelReferenceMixin
from .mixins.settings_mixin import SettingsMixin
from .mixins.ui_mixin import UIMixin
from .toast import ToastManager
from .utils import resolve_asset_path


class DefectDetectionGUI(
    InteractionMixin,
    UIMixin,
    ModelReferenceMixin,
    InspectionMixin,
    BrowseMixin,
    CameraMixin,
    HistoryMixin,
    SettingsMixin,
    QMainWindow,
):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Defect Inspection Station")
        self.setMinimumSize(1100, 700)

        self.script_root = os.path.dirname(os.path.abspath(__file__))
        self.main_program_root = os.path.abspath(os.path.join(self.script_root, ".."))
        self.project_root = os.path.abspath(os.path.join(self.script_root, "..", ".."))
        self.logo_path = os.path.join(self.main_program_root, "image", "logo.png")
        self.default_model_path = resolve_asset_path(self.script_root, self.project_root, "best.pt")
        self.default_refs_path = resolve_asset_path(self.script_root, self.project_root, "Refs.json")
        self.default_log_path = resolve_asset_path(
            self.script_root,
            self.project_root,
            "inspection_log.csv",
            create_in_project=True,
        )
        if os.path.exists(self.logo_path):
            self.setWindowIcon(QIcon(self.logo_path))

        self._current_theme = "light"

        self.model = None
        self.model_names = {}
        self.current_model_path = ""

        self.reference_points = []
        self.undo_stack = []
        self.redo_stack = []
        self.is_edit_mode = False

        self.current_image_path = None
        self.folder_path = ""
        self.folder_images = []
        self.folder_index = -1
        self.current_image_pixmap = None
        self.current_annotated_frame = None
        self.original_image_size = (0, 0)
        self.last_inspection_result = None

        self._base_frame = None
        self._last_detections = []
        self._detection_status = {}
        self.selected_detection_index = None

        self.zoom_factor = 1.0
        self.min_zoom_factor = 0.2
        self.max_zoom_factor = 8.0

        self._camera_worker = None
        self._camera_latest_frame = None

        self.total_count = 0
        self.pass_count = 0
        self.fail_count = 0
        self.history_rows = []

        self.init_ui()
        self.toasts = ToastManager(self)
        self.apply_styles()
        self.setup_interactions()

        self._booting = True
        self.load_default_assets()
        self.load_settings()
        self._on_station_meta_changed()
        self._booting = False
