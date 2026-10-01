"""AOI XY stage motion control and automated scanning router."""
from typing import Any, Dict, List, Literal, Optional
from fastapi import APIRouter, Header, HTTPException
from pydantic import Field

from ..core.schemas import BaseModel, AOIRunReport, MachineState, ScanPlanRequest, ScanPoint
from ..core.security import lease_manager
from ..services.aoi_scan_service import aoi_scan_service
from ..services.dataset_service import dataset_service
from ..services.machine_service import machine_service

router = APIRouter(prefix="/api/aoi", tags=["aoi"])


class ConnectRequest(BaseModel):
    mode: Literal["simulation", "serial"] = "simulation"
    port: Optional[str] = None
    baud: int = 9600


class JogRequest(BaseModel):
    dx_mm: float
    dy_mm: float
    speed: int = Field(800, ge=20, le=1500)


class MoveRequest(BaseModel):
    x_steps: Optional[int] = None
    y_steps: Optional[int] = None
    x_mm: Optional[float] = None
    y_mm: Optional[float] = None
    speed: int = Field(800, ge=20, le=1500)



class StartScanRequest(BaseModel):
    plan: ScanPlanRequest
    is_golden_scan: bool = False
    reference_id: Optional[str] = None
    conf_thresh: float = Field(0.25, ge=0, le=1)
    match_dist: float = Field(50.0, gt=0)
    fail_on_extra: bool = True
    imgsz: Optional[int] = Field(None, ge=128, le=4096)
    multiframe_enabled: bool = True
    target_frames: int = Field(10, ge=1, le=50)
    pass_ratio: float = Field(0.8, gt=0, le=1)


def _require_operator_lease(
    token: Optional[str] = None,
    alt_token: Optional[str] = None
):
    """Verify that caller holds the active operator lease if station is reserved."""
    active_token = token or alt_token
    lease = lease_manager.get_lease_info()
    if lease.is_controlled:
        if not active_token or not lease_manager.is_operator(active_token):
            raise HTTPException(
                status_code=403,
                detail=f"Station is controlled by '{lease.operator_name}'. Valid operator token required."
            )



@router.get("/ports")
def list_ports():
    return {"ports": machine_service.list_ports()}


@router.post("/connect")
def connect_stage(
    req: ConnectRequest,
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id")
):
    _require_operator_lease(x_operator_token, x_operator_id)
    try:
        if aoi_scan_service.is_running or dataset_service.is_running:
            raise ValueError("Stop the current scan before reconnecting")
        machine_service.connect(mode=req.mode, port=req.port, baud=req.baud)
        return {"success": True, "state": machine_service.get_state()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/disconnect")
def disconnect_stage(
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id")
):
    _require_operator_lease(x_operator_token, x_operator_id)
    aoi_scan_service.stop_scan()
    dataset_service.stop_capture()
    machine_service.disconnect()
    return {"success": True, "state": machine_service.get_state()}


@router.post("/home")
def home_stage(
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id")
):
    _require_operator_lease(x_operator_token, x_operator_id)
    try:
        if aoi_scan_service.is_running or dataset_service.is_running:
            raise ValueError("Cannot HOME during a scan")
        machine_service.home()
        return {"success": True, "state": machine_service.get_state()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/jog")
def jog_stage(
    req: JogRequest,
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id")
):
    _require_operator_lease(x_operator_token, x_operator_id)
    try:
        if aoi_scan_service.is_running or dataset_service.is_running:
            raise ValueError("Cannot jog during a scan")
        machine_service.jog(req.dx_mm, req.dy_mm, req.speed)
        return {"success": True, "state": machine_service.get_state()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/move")
def move_stage(
    req: MoveRequest,
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id")
):
    _require_operator_lease(x_operator_token, x_operator_id)
    try:
        if aoi_scan_service.is_running or dataset_service.is_running:
            raise ValueError("Cannot move manually during a scan")
        if req.x_steps is not None and req.y_steps is not None:
            machine_service.move_to_steps(req.x_steps, req.y_steps, req.speed)
        elif req.x_mm is not None and req.y_mm is not None:
            x_steps = int(round(req.x_mm * machine_service.steps_per_mm))
            y_steps = int(round(req.y_mm * machine_service.steps_per_mm))
            machine_service.move_to_steps(x_steps, y_steps, req.speed)
        else:
            raise HTTPException(status_code=400, detail="Must provide x_steps/y_steps or x_mm/y_mm")
        return {"success": True, "state": machine_service.get_state()}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/stop")
def stop_stage():
    """Emergency STOP: Accessible to anyone at all times for safety."""
    aoi_scan_service.stop_scan()
    dataset_service.stop_capture()
    machine_service.stop()
    return {"success": True, "message": "STOP command executed."}


@router.post("/motors-off")
def motors_off(
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id")
):
    _require_operator_lease(x_operator_token, x_operator_id)
    aoi_scan_service.stop_scan()
    machine_service.motors_off()
    return {"success": True, "state": machine_service.get_state()}


@router.post("/plan", response_model=List[ScanPoint])
def plan_scan(req: ScanPlanRequest):
    """Preview raster scan points in mm and steps without moving."""
    try:
        return aoi_scan_service.plan_scan(req)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/scan/start", response_model=AOIRunReport)
def start_scan(
    req: StartScanRequest,
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id")
):
    _require_operator_lease(x_operator_token, x_operator_id)
    try:
        if dataset_service.is_running:
            raise RuntimeError("Stop the dataset capture before starting an AOI scan")
        report = aoi_scan_service.start_scan(
            plan=req.plan,
            is_golden_scan=req.is_golden_scan,
            reference_id=req.reference_id,
            conf_thresh=req.conf_thresh,
            match_dist=req.match_dist,
            fail_on_extra=req.fail_on_extra,
            imgsz=req.imgsz,
            multiframe_enabled=req.multiframe_enabled,
            target_frames=req.target_frames,
            pass_ratio=req.pass_ratio
        )
        return report
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/scan/stop")
def stop_scan():
    """Immediately abort active automated scan."""
    aoi_scan_service.stop_scan()
    return {"success": True, "message": "Scan aborted."}


@router.get("/scan/status")
def get_scan_status():
    report = aoi_scan_service.current_run
    if not report:
        return {"status": "idle"}
    return report
