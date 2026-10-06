"""Shared Pydantic data contracts for PCB Inspection & AOI."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel as PydanticBaseModel, Field, ConfigDict, model_validator

# Reject NaN/Infinity before they reach motion, image or persistence code.
class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

# Core Inspection Verdicts
Verdict = Literal["PASS", "FAIL", "REVIEW", "ERROR"]
DetectionStatus = Literal["OK", "WRONG", "EXTRA", "UNMATCHED"]
ReferenceStatus = Literal["OK", "MISSING", "WRONG"]
DevicePreference = Literal["auto", "mps", "cuda", "cpu"]


class BoundingBox(BaseModel):
    """Bounding box in absolute image pixels [x1, y1, x2, y2]."""
    x1: float
    y1: float
    x2: float
    y2: float

    def to_list(self) -> List[float]:
        return [self.x1, self.y1, self.x2, self.y2]


class Detection(BaseModel):
    """Single YOLO detection item."""
    id: int
    label: str
    conf: float
    box: List[float]  # [x1, y1, x2, y2] in pixels
    cx: float         # Center X
    cy: float         # Center Y
    status: DetectionStatus = "UNMATCHED"
    matched_ref_index: Optional[int] = None


class ReferencePoint(BaseModel):
    """Expected component location and class label."""
    id: Optional[str] = None
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    label: str = Field(min_length=1)
    tolerance_px: Optional[float] = Field(None, gt=0)


class ReferenceSummary(BaseModel):
    """Metadata summary of a reference profile for listing."""
    id: str
    name: str
    description: Optional[str] = ""
    profile_type: Literal["single", "aoi_grid"] = "single"
    points_count: int = 0
    created_at: float
    updated_at: float


class ReferenceProfile(BaseModel):
    """Collection of reference points (single-image or multi-position AOI)."""
    id: str
    name: str
    description: Optional[str] = ""
    profile_type: Literal["single", "aoi_grid"] = "single"
    points: List[ReferencePoint] = Field(default_factory=list)
    # For aoi_grid: mapping of "point_idx" or "col_row" -> List[ReferencePoint]
    grid_points: Dict[str, List[ReferencePoint]] = Field(default_factory=dict)
    scan_signature: Optional[Dict[str, Any]] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class ReferenceEvaluation(BaseModel):
    """Comparison result for a single reference point."""
    ref_index: int
    ref: ReferencePoint
    status: ReferenceStatus
    distance: Optional[float] = None
    det: Optional[Detection] = None


class InspectionSummary(BaseModel):
    """Aggregate counts for an inspection."""
    total_refs: int = 0
    ok: int = 0
    missing: int = 0
    wrong: int = 0
    extra: int = 0
    total_detections: int = 0


class InspectionResult(BaseModel):
    """Full outcome of an inspection pass."""
    verdict: Verdict
    reason: Optional[str] = None
    summary: InspectionSummary
    detections: List[Detection] = Field(default_factory=list)
    reference_eval: List[ReferenceEvaluation] = Field(default_factory=list)
    speed_ms: Dict[str, float] = Field(default_factory=dict)
    image_width: int
    image_height: int
    image_url: Optional[str] = None
    annotated_url: Optional[str] = None
    device_used: str = "unknown"
    model_used: str = ""
    timestamp: float = Field(default_factory=time.time)
    is_simulation: bool = False


class MachineState(BaseModel):
    """Nano XY Stage motion state."""
    connected: bool = False
    mode: Literal["simulation", "serial"] = "simulation"
    port: Optional[str] = None
    ready: bool = False
    homed: bool = False
    position_steps: Tuple[int, int] = (0, 0)
    position_mm: Tuple[float, float] = (0.0, 0.0)
    limits_steps: Tuple[int, int] = (21167, 20446)
    soft_limits_mm: Tuple[float, float] = (38.0, 38.0)
    is_moving: bool = False
    last_error: Optional[str] = None
    last_event: Optional[str] = None
    rx_log: List[str] = Field(default_factory=list)
    # Last HOME's repeated switch touches per axis: {"X": {"spread_steps": 2, "touches": 3}, ...}
    home_info: Optional[Dict[str, Dict[str, int]]] = None


class CustomPointRequest(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    x_mm: float
    y_mm: float
    zoom: float = Field(1.0, ge=1, le=5)
    reference_image: Optional[str] = None
    expected_components: Optional[List[Dict[str, Any]]] = None

    @model_validator(mode="after")
    def validate_components(self):
        seen = set()
        for item in self.expected_components or []:
            ident = str(item.get("id", "")).strip()
            name = str(item.get("name", "")).strip()
            box = item.get("bbox")
            if not ident or ident in seen or not name:
                raise ValueError("Each component needs a unique ID and a class name")
            if not isinstance(box, (list, tuple)) or len(box) != 4 or not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in box):
                raise ValueError("Component bbox must contain four normalized coordinates in 0..1")
            if box[2] <= box[0] or box[3] <= box[1]:
                raise ValueError("Component bbox must have positive width and height")
            seen.add(ident)
        return self


class ScanPlanRequest(BaseModel):
    """Parameters for raster scan grid or custom points list."""
    plan_mode: Literal["grid", "custom"] = "grid"
    origin_x_mm: float = 0.0
    origin_y_mm: float = 0.0
    columns: int = Field(2, ge=1, le=100)
    rows: int = Field(2, ge=1, le=100)
    pitch_x_mm: float = 10.0
    pitch_y_mm: float = 10.0
    speed: int = Field(800, ge=20, le=1500)
    settle_sec: float = Field(0.5, ge=0, le=30)
    custom_points: Optional[List[CustomPointRequest]] = None


    @model_validator(mode="after")
    def check_plan(self):
        if self.plan_mode == "custom" and not (1 <= len(self.custom_points or []) <= 400):
            raise ValueError("Custom plan requires 1–400 points")
        if self.plan_mode == "grid" and self.rows*self.columns > 400:
            raise ValueError("Use at most 400 scan points")
        return self


class ScanPoint(BaseModel):
    """Single point in a raster or custom scan path."""
    index: int
    name: Optional[str] = None
    col: int = 0
    row: int = 0
    x_steps: int
    y_steps: int
    x_mm: float
    y_mm: float
    zoom: float = Field(1.0, ge=1, le=5)
    reference_image: Optional[str] = None
    expected_components: Optional[List[Dict[str, Any]]] = None


class AOIPointResult(BaseModel):
    """Inspection result for one point in an AOI scan."""
    point_index: int
    name: Optional[str] = None
    col: int
    row: int
    x_mm: float
    y_mm: float
    zoom: float = Field(1.0, ge=1, le=5)
    verdict: Verdict
    reason: Optional[str] = None
    image_path: str
    annotated_path: str
    image_url: str
    annotated_url: str
    summary: InspectionSummary
    detections: List[Detection] = Field(default_factory=list)
    speed_ms: Dict[str, float] = Field(default_factory=dict)
    component_eval: Optional[List[Dict[str, Any]]] = None
    multiframe_info: Optional[Dict[str, Any]] = None


class AOIRunReport(BaseModel):
    """Full report of an AOI automated scan."""
    id: str
    status: Literal["idle", "running", "complete", "aborted", "error"] = "idle"
    is_simulation: bool = True
    is_golden_scan: bool = False
    reference_id: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    completed_at: Optional[float] = None
    plan: ScanPlanRequest
    points: List[ScanPoint] = Field(default_factory=list)
    total_points: int = 0
    results: List[AOIPointResult] = Field(default_factory=list)
    current_point_index: int = 0
    overall_verdict: Verdict = "REVIEW"
    pass_count: int = 0
    fail_count: int = 0
    review_count: int = 0
    error_count: int = 0
    error_message: Optional[str] = None
    # How the board was found placed vs. its taught points (angle, offset) — see board_alignment.
    board_alignment: Optional[Dict[str, Any]] = None


class ControlLease(BaseModel):
    """Machine operator control lease for multi-client safety."""
    active_operator_id: Optional[str] = None
    client_ip: Optional[str] = None
    granted_at: Optional[float] = None
    expires_at: Optional[float] = None
    is_controlled: bool = False
    operator_name: Optional[str] = None


class SystemStatus(BaseModel):
    """Health and status of all subsystems."""
    server_time: float = Field(default_factory=time.time)
    camera_active: bool = False
    camera_is_mock: bool = False
    camera_resolution: Optional[Tuple[int, int]] = None
    camera_fps: float = 0.0
    model_loaded: bool = False
    model_path: str = ""
    active_device: str = "cpu"
    device_detail: str = ""
    machine: MachineState
    control_lease: ControlLease
    active_scan: Optional[Dict[str, Any]] = None
