"""AOI XY stage motion control and automated scanning router."""
from typing import Any, Dict, List, Literal, Optional
from fastapi import APIRouter, Header, HTTPException
from pydantic import Field

from ..core.schemas import BaseModel, AOIRunReport, CustomPointRequest, MachineState, ScanPlanRequest, ScanPoint
from ..core.security import lease_manager
from ..services.aoi_scan_service import aoi_scan_service
from ..services.dataset_service import dataset_service
from ..services.depth_service import depth_service
from ..services import point_set_store
from ..services.machine_service import machine_service
from ..services.stage_calibration_service import stage_calibration_service
from ..services.stage_monitor_service import stage_monitor_service

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



class PointSetRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    points: Optional[List[CustomPointRequest]] = Field(None, max_length=200)


class DepthRequest(BaseModel):
    x_mm: float
    y_mm: float
    zoom: float = Field(1.0, ge=1, le=5)
    # The part's box, normalized to the (zoomed) inspection image.
    bbox: List[float] = Field(..., min_length=4, max_length=4)
    recapture: bool = False


class CalibrationRequest(BaseModel):
    # Optional checkerboard (inner corners) of known square size for the absolute scale.
    checkerboard_cols: Optional[int] = Field(None, ge=3, le=40)
    checkerboard_rows: Optional[int] = Field(None, ge=3, le=40)
    square_mm: Optional[float] = Field(None, gt=0, le=50)
    # "axes": ±2 mm passes around the current spot; "map": a grid over the whole travel.
    mode: Literal["axes", "map"] = "axes"
    # Map nodes per axis (raised automatically so neighbouring pictures overlap).
    density: int = Field(5, ge=3, le=15)


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
    """Every motion or station mutation requires an active operator lease."""
    active_token = token or alt_token
    if not lease_manager.is_operator(active_token):
        raise HTTPException(status_code=403, detail="Active operator token required.")



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
        if aoi_scan_service.is_running or dataset_service.is_running or stage_calibration_service.is_running:
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
    stage_calibration_service.stop()
    machine_service.disconnect()
    return {"success": True, "state": machine_service.get_state()}


@router.post("/home")
def home_stage(
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id")
):
    _require_operator_lease(x_operator_token, x_operator_id)
    try:
        if aoi_scan_service.is_running or dataset_service.is_running or stage_calibration_service.is_running:
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
        if aoi_scan_service.is_running or dataset_service.is_running or stage_calibration_service.is_running:
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
        if aoi_scan_service.is_running or dataset_service.is_running or stage_calibration_service.is_running:
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


# ── Saved sets of test points ──

def _dump(points: List[CustomPointRequest]) -> List[dict]:
    return [p.model_dump(exclude_none=True) for p in points]


@router.get("/point-sets")
def list_point_sets():
    return {"sets": point_set_store.list_sets()}


@router.get("/point-sets/{set_id}")
def get_point_set(set_id: str):
    found = point_set_store.get_set(set_id)
    if not found:
        raise HTTPException(status_code=404, detail="ไม่พบชุดจุดตรวจนี้")
    return found


@router.post("/point-sets")
def create_point_set(
    req: PointSetRequest,
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id"),
):
    """Create a board (named set of points); it may start empty and fill up as points are marked."""
    _require_operator_lease(x_operator_token, x_operator_id)
    try:
        return point_set_store.create_set(req.name or "", _dump(req.points or []))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/point-sets/{set_id}")
def update_point_set(
    set_id: str,
    req: PointSetRequest,
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id"),
):
    """Rename and/or replace the points of a saved set (fields left out stay as they are)."""
    _require_operator_lease(x_operator_token, x_operator_id)
    try:
        updated = point_set_store.update_set(set_id, req.name, _dump(req.points) if req.points is not None else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not updated:
        raise HTTPException(status_code=404, detail="ไม่พบชุดจุดตรวจนี้")
    return updated


@router.delete("/point-sets/{set_id}")
def delete_point_set(
    set_id: str,
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id"),
):
    _require_operator_lease(x_operator_token, x_operator_id)
    if not point_set_store.delete_set(set_id):
        raise HTTPException(status_code=404, detail="ไม่พบชุดจุดตรวจนี้")
    return {"success": True}


@router.post("/depth")
def measure_depth(
    req: DepthRequest,
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id"),
):
    """Height map of one part: moves to the point, shoots two frames a few mm apart (cached)."""
    _require_operator_lease(x_operator_token, x_operator_id)
    if aoi_scan_service.is_running or dataset_service.is_running or stage_calibration_service.is_running:
        raise HTTPException(status_code=409, detail="Stop the scan before measuring in 3D")
    x1, y1, x2, y2 = req.bbox
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise HTTPException(status_code=400, detail="bbox must be normalized [x1, y1, x2, y2]")
    try:
        return depth_service.measure(req.x_mm, req.y_mm, req.zoom, req.bbox, req.recapture)
    except (ValueError, RuntimeError, TimeoutError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class BeepRequest(BaseModel):
    tune: Literal["done", "pass", "fail", "error", "test"] = "test"


@router.post("/beep")
def beep(
    req: BeepRequest,
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id"),
):
    """Play a short tune on the stage motors (test of the machine's own sounds)."""
    _require_operator_lease(x_operator_token, x_operator_id)
    if aoi_scan_service.is_running or stage_calibration_service.is_running:
        raise HTTPException(status_code=409, detail="สเตจกำลังทำงานอยู่")
    if not machine_service.can_play:
        raise HTTPException(status_code=400, detail="เฟิร์มแวร์ยังไม่รองรับเสียง หรือยังไม่ได้เชื่อมต่อสเตจ")
    from ..config import settings

    if not settings.stage_sound_enabled:
        raise HTTPException(status_code=400, detail="ปิดเสียงจากมอเตอร์อยู่ในหน้าตั้งค่า")
    started = machine_service.play(req.tune)
    return {"success": started}


@router.get("/stage-error")
def stage_error():
    """Positioning error of the last moves, measured with the camera (see stage_monitor_service)."""
    return stage_monitor_service.snapshot()


@router.post("/stage-error/reset")
def reset_stage_error():
    stage_monitor_service.reset()
    return stage_monitor_service.snapshot()


@router.get("/calibration")
def calibration_status():
    """Progress of the running stage calibration and the last saved result."""
    return stage_calibration_service.status()


@router.get("/calibration/checkerboard.png")
def checkerboard_png(cols: int = 9, rows: int = 6, square_mm: float = 5.0):
    """A printable checkerboard (300 DPI: print at 100 % / actual size, then measure a square)."""
    import io

    from fastapi.responses import Response
    from PIL import Image

    from ..core.stage_calibration import checkerboard_image

    if not (3 <= cols <= 40 and 3 <= rows <= 40 and 0.5 <= square_mm <= 50):
        raise HTTPException(status_code=400, detail="cols/rows 3-40, square_mm 0.5-50")
    buf = io.BytesIO()
    Image.fromarray(checkerboard_image((cols, rows), square_mm)).save(buf, format="PNG", dpi=(300, 300))
    name = f"checkerboard_{cols}x{rows}_{square_mm:g}mm.png"
    return Response(buf.getvalue(), media_type="image/png", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/calibration/speckle.{fmt}")
def speckle_target(fmt: str, paper: str = "a4", dot_mm: float = 1.0):
    """Flat random-blob target for the whole-travel map (PDF prints at exact size)."""
    import io

    from fastapi.responses import Response
    from PIL import Image

    from ..core.stage_calibration import PAPER_MM, speckle_image

    if fmt not in ("pdf", "png") or paper not in PAPER_MM or not 0.3 <= dot_mm <= 5:
        raise HTTPException(status_code=400, detail="fmt pdf|png, paper a4|a3, dot_mm 0.3-5")
    img = Image.fromarray(speckle_image(paper, dot_mm))
    buf = io.BytesIO()
    if fmt == "pdf":
        img.convert("1").save(buf, format="PDF", resolution=300.0)
        media = "application/pdf"
    else:
        img.save(buf, format="PNG", dpi=(300, 300))
        media = "image/png"
    name = f"stage_map_target_{paper}_{dot_mm:g}mm.{fmt}"
    return Response(buf.getvalue(), media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/calibration/start")
def start_calibration(
    req: CalibrationRequest,
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id"),
):
    """Measure the stage's scale, backlash, straightness and repeatability around the current position."""
    _require_operator_lease(x_operator_token, x_operator_id)
    board = None
    if req.checkerboard_cols and req.checkerboard_rows and req.square_mm:
        board = (req.checkerboard_cols, req.checkerboard_rows)
    try:
        return stage_calibration_service.start(board, req.square_mm if board else None, mode=req.mode, density=req.density)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/calibration/stop")
def stop_calibration(
    x_operator_token: Optional[str] = Header(None, alias="X-Operator-Token"),
    x_operator_id: Optional[str] = Header(None, alias="X-Operator-Id"),
):
    _require_operator_lease(x_operator_token, x_operator_id)
    stage_calibration_service.stop()
    return stage_calibration_service.status()


@router.post("/stop")
def stop_stage():
    """Emergency STOP: Accessible to anyone at all times for safety."""
    aoi_scan_service.stop_scan()
    dataset_service.stop_capture()
    stage_calibration_service.stop()
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
        if machine_service.get_state().mode == "serial":
            from ..quality_gate import require_approved
            from ..services.inference_service import inference_service

            require_approved(inference_service.model_path)
        if dataset_service.is_running:
            raise RuntimeError("Stop the dataset capture before starting an AOI scan")
        if stage_calibration_service.is_running:
            raise RuntimeError("รอให้ calibrate ราง XY เสร็จก่อนเริ่มสแกน")
        depth_service.clear()  # a new scan usually means a new board: drop old stereo pairs
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
