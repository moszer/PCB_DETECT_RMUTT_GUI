import json
import os
import logging
import uuid
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict

# Root directory of the repository (parent of backend/)
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Default paths
DEFAULT_MODEL_PATH = str(REPO_ROOT / "best.pt")
DEFAULT_EXP_MODEL_PATH = str(REPO_ROOT / "exp.pt")
DEFAULT_REFS_PATH = str(REPO_ROOT / "Refs.json")

# Web Backend Storage (Kept separate from main_program)
STORAGE_DIR = Path(os.environ.get("PCB_STORAGE_DIR", str(BACKEND_ROOT / "data"))).resolve()
UPLOADS_DIR = STORAGE_DIR / "uploads"
RUNS_DIR = STORAGE_DIR / "runs"
REFERENCES_DIR = STORAGE_DIR / "references"
DATASETS_DIR = STORAGE_DIR / "datasets"
DB_PATH = STORAGE_DIR / "inspection.db"

# Ensure directories exist
for directory in (STORAGE_DIR, UPLOADS_DIR, RUNS_DIR, REFERENCES_DIR, DATASETS_DIR):
    directory.mkdir(parents=True, exist_ok=True)


class Settings(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    # Server network settings
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = Field(default_factory=lambda: [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "*"  # Allows access from local LAN devices (iPad/PC)
    ])

    # Hardware & Model defaults
    default_model: str = DEFAULT_MODEL_PATH if Path(DEFAULT_MODEL_PATH).is_file() else (
        DEFAULT_EXP_MODEL_PATH if Path(DEFAULT_EXP_MODEL_PATH).is_file() else "best.pt"
    )
    device_preference: str = os.environ.get("PCB_DEVICE", "auto")
    default_conf: float = Field(0.25, ge=0, le=1)
    default_match_dist: float = Field(50.0, gt=0)
    default_fail_on_extra: bool = True

    # Camera defaults
    camera_index: int = 0
    camera_width: int = 1920
    camera_height: int = 1080
    camera_fps: int = 30
    camera_backend: str = "default"  # or 'avfoundation', 'v4l2'

    # Machine & AOI defaults
    steps_per_mm: float = Field(512.0, gt=0)
    default_speed: int = 800
    default_settle_sec: float = 0.5
    soft_limit_x_mm: float = Field(38.0, gt=0)
    soft_limit_y_mm: float = Field(38.0, gt=0)
    firmware_baud: int = 9600
    serial_startup_delay: float = 2.5

    # Control Lease & Auth
    lease_ttl_seconds: float = 20.0
    operator_passcode: str = os.environ.get("PCB_OPERATOR_PASSCODE", "rmutt-aoi")
    station_name: str = "RMUTT-AOI-01"
    # Extra folders scanned for YOLO weights (e.g. another training project's runs/).
    model_search_dirs: list[str] = Field(default_factory=list)
    default_operator: str = "Operator"


SETTINGS_FILE = STORAGE_DIR / "settings.json"


def save_settings_to_disk(s: Settings):
    try:
        data = s.model_dump()
        temporary = SETTINGS_FILE.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(SETTINGS_FILE)
    except OSError as exc:
        raise RuntimeError(f"Failed to save station settings: {exc}") from exc


def load_saved_settings(s: Settings):
    if not SETTINGS_FILE.is_file():
        return
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Settings must be an object")
        saved_model = data.get("default_model")
        if saved_model and not Path(str(saved_model)).is_file():
            candidate = next((p / Path(str(saved_model)).name for p in (REPO_ROOT, REPO_ROOT.parent) if (p / Path(str(saved_model)).name).is_file()), None)
            data["default_model"] = str(candidate) if candidate else s.default_model
        if "PCB_OPERATOR_PASSCODE" in os.environ:
            data["operator_passcode"] = os.environ["PCB_OPERATOR_PASSCODE"]
        validated = Settings.model_validate({**s.model_dump(), **{k:v for k,v in data.items() if v is not None}})
        for key, value in validated.model_dump().items():
            setattr(s, key, value)
    except (OSError, ValueError, TypeError):
        logging.getLogger(__name__).warning("Saved settings are invalid; using defaults")


settings = Settings()
load_saved_settings(settings)

