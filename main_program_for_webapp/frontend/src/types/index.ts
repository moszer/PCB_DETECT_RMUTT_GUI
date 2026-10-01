export type Verdict = "PASS" | "FAIL" | "REVIEW" | "ERROR";
export type DetectionStatus = "OK" | "WRONG" | "EXTRA" | "UNMATCHED";
export type ReferenceStatus = "OK" | "MISSING" | "WRONG";

export interface Detection {
  id: number;
  label: string;
  conf: number;
  box: [number, number, number, number]; // [x1, y1, x2, y2]
  cx: number;
  cy: number;
  status: DetectionStatus;
  matched_ref_index?: number | null;
}

export interface ReferencePoint {
  id?: string;
  x: number;
  y: number;
  label: string;
  tolerance_px?: number | null;
}

export interface ReferenceEvaluation {
  ref_index: number;
  ref: ReferencePoint;
  status: ReferenceStatus;
  distance?: number | null;
  det?: Detection | null;
}

export interface InspectionSummary {
  total_refs: number;
  ok: number;
  missing: number;
  wrong: number;
  extra: number;
  total_detections: number;
}

export interface InspectionResult {
  verdict: Verdict;
  reason?: string | null;
  summary: InspectionSummary;
  detections: Detection[];
  reference_eval: ReferenceEvaluation[];
  speed_ms: { [key: string]: number };
  image_width: number;
  image_height: number;
  image_url?: string | null;
  annotated_url?: string | null;
  device_used: string;
  model_used: string;
  timestamp: number;
  is_simulation?: boolean;
}

export interface MachineState {
  connected: boolean;
  mode: "simulation" | "serial";
  port?: string | null;
  ready: boolean;
  homed: boolean;
  position_steps: [number, number];
  position_mm: [number, number];
  limits_steps: [number, number];
  soft_limits_mm: [number, number];
  is_moving: boolean;
  last_error?: string | null;
  last_event?: string | null;
  rx_log: string[];
}

export interface ControlLease {
  active_operator_id?: string | null;
  client_ip?: string | null;
  granted_at?: number | null;
  expires_at?: number | null;
  is_controlled: boolean;
  operator_name?: string | null;
}

export interface SystemStatus {
  server_time: number;
  camera_active: boolean;
  camera_is_mock?: boolean;
  camera_resolution?: [number, number] | null;
  camera_fps: number;
  model_loaded: boolean;
  model_path: string;
  active_device: string;
  device_detail: string;
  machine: MachineState;
  control_lease: ControlLease;
  active_scan?: ActiveScanSummary | null;
}

export interface ActiveScanSummary {
  id: string;
  status: AOIRunReport["status"];
  point_index: number;
  total_points: number;
  pass_count: number;
  fail_count: number;
  review_count: number;
  error_count: number;
  overall_verdict: Verdict;
}

export interface CustomPointRequest {
  id?: string;
  name?: string;
  x_mm: number;
  y_mm: number;
  zoom: number;
  reference_image?: string | null;
  expected_components?: ExpectedComponentPayload[];
}

/** Golden component slot taught for a marked point (bbox normalized 0..1). */
export interface ExpectedComponentPayload {
  id: string;
  name: string;
  bbox: [number, number, number, number];
}

export interface ScanPlanRequest {
  plan_mode?: "grid" | "custom";
  origin_x_mm: number;
  origin_y_mm: number;
  columns: number;
  rows: number;
  pitch_x_mm: number;
  pitch_y_mm: number;
  speed: number;
  settle_sec: number;
  custom_points?: CustomPointRequest[];
  imgsz?: number;
}

export interface ScanPoint {
  index: number;
  name?: string;
  col: number;
  row: number;
  x_steps: number;
  y_steps: number;
  x_mm: number;
  y_mm: number;
  zoom?: number;
  reference_image?: string | null;
  expected_components?: ExpectedComponentPayload[];
}

export type SlotStatus = "confirmed" | "uncertain" | "missing" | "wrong";

/** One expected component's multi-frame outcome (backend evaluate_multiframe_round). */
export interface ComponentEvaluation {
  expected: { id: string; name: string; box?: number[]; bbox?: number[] };
  hits: number;
  total_frames: number;
  target_frames: number;
  pass_threshold: number;
  status: SlotStatus;
  wrong_label?: string | null;
}

export interface MultiframeInfo {
  target_frames: number;
  pass_threshold: number;
  pass_ratio: number;
  total_frames: number;
  confirmed_count: number;
  missing_count: number;
  wrong_count: number;
  /** Largest whole-frame shift vs. the reference that was compensated (pixels). */
  max_offset_px?: number;
}

export interface AOIPointResult {
  point_index: number;
  name?: string;
  col: number;
  row: number;
  x_mm: number;
  y_mm: number;
  zoom?: number;
  verdict: Verdict;
  reason?: string | null;
  image_path: string;
  annotated_path: string;
  image_url: string;
  annotated_url: string;
  summary: InspectionSummary;
  detections: Detection[];
  speed_ms: { [key: string]: number };
  component_eval?: ComponentEvaluation[] | null;
  multiframe_info?: MultiframeInfo | null;
}

export interface AOIRunReport {
  id: string;
  status: "idle" | "running" | "complete" | "aborted" | "error";
  is_simulation: boolean;
  is_golden_scan: boolean;
  reference_id?: string | null;
  created_at: number;
  completed_at?: number | null;
  plan: ScanPlanRequest;
  points: ScanPoint[];
  total_points?: number;
  results: AOIPointResult[];
  current_point_index: number;
  overall_verdict: Verdict;
  pass_count: number;
  fail_count: number;
  review_count: number;
  error_count: number;
  error_message?: string | null;
}

export interface ReferenceSummary {
  id: string;
  name: string;
  description?: string;
  profile_type: "single" | "aoi_grid";
  points_count: number;
  created_at: number;
  updated_at: number;
}

export interface ReferenceProfile {
  id: string;
  name: string;
  description?: string;
  profile_type: "single" | "aoi_grid";
  points: ReferencePoint[];
  grid_points: { [key: string]: ReferencePoint[] };
  scan_signature?: Record<string, unknown> | null;
  image_width?: number;
  image_height?: number;
  created_at: number;
  updated_at: number;
}


export interface ScanProgressEvent {
  event: "active_run" | "point_start" | "point_capturing" | "point_frame" | "point_complete" | "complete" | "aborted" | "error";
  run_id?: string;
  point_index?: number;
  total_points?: number;
  target_mm?: [number, number];
  zoom?: number;
  name?: string;
  frame_index?: number;
  target_frames?: number;
  message?: string;
  error?: string;
  report?: AOIRunReport;
}

export interface SingleInspectionRecord {
  id: number;
  verdict: Verdict;
  reason?: string | null;
  model_used?: string | null;
  device_used?: string | null;
  image_url?: string;
  annotated_url?: string;
  detections: Detection[];
  summary: InspectionSummary;
  speed_ms: { [key: string]: number };
  created_at: number;
}

export interface RunRecord {
  id: string;
  status: AOIRunReport["status"];
  is_simulation: number | boolean;
  is_golden_scan: number | boolean;
  reference_id?: string | null;
  created_at: number;
  completed_at?: number | null;
  overall_verdict: Verdict;
  total_points: number;
  pass_count: number;
  fail_count: number;
  review_count: number;
  error_count: number;
  error_message?: string | null;
  results?: AOIPointResult[];
}

export interface Statistics {
  total_runs: number;
  pass_runs: number;
  fail_runs: number;
  review_runs: number;
  error_runs: number;
  board_yield_rate: number;
  point_yield_rate: number;
  total_pass_points: number;
  total_fail_points: number;
  simulation_runs: number;
  golden_runs: number;
  single_inspections_count: number;
}

export interface ModelFile {
  filename: string;
  path: string;
  size_mb: number;
  modified_at?: number;
}

export interface CameraDevice {
  index: number;
  name: string;
  active: boolean;
}

export interface SerialPort {
  device: string;
  description: string;
  hwid: string;
  is_usb: boolean;
}

export interface StationSettings {
  station_name: string;
  default_operator: string;
  default_conf: number;
  default_match_dist: number;
  default_fail_on_extra: boolean;
  soft_limit_x_mm: number;
  soft_limit_y_mm: number;
  default_model: string;
  device_preference: string;
  has_passcode: boolean;
}

export interface ComputeDevice {
  id: string;
  label: string;
  available: boolean;
  detail: string;
}

/* ── Training datasets ───────────────────────────────── */

export type DatasetStatus = "capturing" | "complete" | "aborted" | "error";

export interface DatasetImage {
  file: string;
  x_mm: number;
  y_mm: number;
  width: number;
  height: number;
  boxes: number;
  labeled_by: "model" | "manual" | null;
}

export interface DatasetSummary {
  id: string;
  name: string;
  status: DatasetStatus;
  created_at: number;
  updated_at: number;
  image_count: number;
  planned: number;
  box_count: number;
  cover: string | null;
}

export interface Dataset {
  id: string;
  name: string;
  status: DatasetStatus;
  created_at: number;
  updated_at: number;
  corners: Array<[number, number]>;
  planned: number;
  resolution: [number, number];
  model: string | null;
  classes: string[];
  images: DatasetImage[];
  error: string | null;
}

/** A label box in normalized [x1, y1, x2, y2]. */
export interface LabelBox {
  label: string;
  bbox: [number, number, number, number];
}

export interface DatasetProgressEvent {
  event: "start" | "moving" | "captured" | "complete" | "aborted" | "error";
  dataset: { id: string; name: string; status: DatasetStatus; planned: number; captured: number; error: string | null };
  index?: number;
  target_mm?: [number, number];
  image?: DatasetImage;
}
