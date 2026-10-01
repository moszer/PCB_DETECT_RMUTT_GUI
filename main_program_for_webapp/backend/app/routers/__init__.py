"""FastAPI routers."""
from .aoi import router as aoi_router
from .auth import router as auth_router
from .camera import router as camera_router
from .datasets import router as datasets_router
from .history import router as history_router
from .inspection import router as inspection_router
from .references import router as references_router
from .system import router as system_router
from .ws import router as ws_router

__all__ = [
    "aoi_router",
    "auth_router",
    "camera_router",
    "datasets_router",
    "history_router",
    "inspection_router",
    "references_router",
    "system_router",
    "ws_router",
]
