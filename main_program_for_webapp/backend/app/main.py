"""Main FastAPI Application Entrypoint for PCB AOI & Defect Detection."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import DB_PATH, DEFAULT_MODEL_PATH, STORAGE_DIR, settings
from .routers import (
    aoi_router,
    auth_router,
    camera_router,
    datasets_router,
    history_router,
    inspection_router,
    references_router,
    system_router,
    ws_router,
)
from .services import aoi_scan_service, camera_service, dataset_service, inference_service, machine_service

# Configure clean logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("pcb_backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and graceful shutdown."""
    logger.info("PCB Inspection Backend starting up...")

    # Initialize model if weights exist
    if Path(settings.default_model).is_file():
        try:
            inference_service.load_model(settings.default_model, settings.device_preference)
            logger.info("Loaded default model: %s on %s", settings.default_model, inference_service.device_info.label)
        except Exception as exc:
            logger.warning("Default model could not be loaded at startup: %s", exc)

    logger.info("Machine service ready (starting offline/disconnected).")

    # Load the OCR models in the background so the first "read text" click is fast.
    import threading
    from .core.ocr import warm_up

    threading.Thread(target=warm_up, name="ocr-warmup", daemon=True).start()

    yield

    logger.info("PCB Inspection Backend shutting down...")
    aoi_scan_service.stop_scan()
    dataset_service.stop_capture()
    camera_service.stop()
    machine_service.disconnect()



app = FastAPI(
    title="PCB AOI & Defect Detection System API",
    description="Backend API for YOLO-based PCB Component & Defect Inspection with Nano XY Stage Control.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Middleware (permits local LAN access from iPad/tablet/PC)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Frame-Timestamp", "X-Camera-Mock"],
)

# Mount static file route for image assets
# Only public assets: never expose settings (passcode), SQLite or model files.
for asset_dir in ("uploads", "runs", "references", "datasets"):
    app.mount(f"/api/storage/{asset_dir}", StaticFiles(directory=str(STORAGE_DIR / asset_dir)), name=f"storage_{asset_dir}")

# Include Routers
app.include_router(system_router)
app.include_router(auth_router)
app.include_router(camera_router)
app.include_router(datasets_router)
app.include_router(inspection_router)
app.include_router(aoi_router)
app.include_router(references_router)
app.include_router(history_router)
app.include_router(ws_router)


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "station": settings.station_name,
        "model_loaded": inference_service.is_loaded,
        "device": inference_service.device_info.label,
        "stage_connected": machine_service.get_state().connected,
        "camera_active": camera_service.is_active
    }


@app.get("/")
def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="http://localhost:3001")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False, workers=1)
