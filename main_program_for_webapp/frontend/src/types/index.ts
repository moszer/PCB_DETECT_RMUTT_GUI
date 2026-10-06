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
  /** Last HOME's repeated slow switch touches per axis (spread = repeatability in steps). */
  home_info?: Record<"X" | "Y", { spread_steps: number; touches: number }> | null;
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
  /** The slot in the saved (last) frame: the reference box moved by that frame's stage shift. */
  box_in_frame?: number[];
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
  /** Anti-shake: time waited for a still picture, and frames re-taken because they shook. */
  stabilize?: { still: boolean | null; waited_sec: number; motion_px: number; shaken_frames: number };
  /** The point's frames warped onto its reference picture (board alignment). */
  alignment?: { applied: boolean; angle_deg?: number; shift_px?: [number, number]; reason?: string } | null;
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
  board_alignment?: BoardAlignment | null;
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


export interface FrameBox {
  label: string;
  conf: number;
  /** Normalized [x1, y1, x2, y2]. */
  box: [number, number, number, number];
}

export interface CapturedFrame {
  index: number;
  preview: string | null;
  boxes: FrameBox[];
}

/** Every frame analyzed so far for the point a scan is working on. */
export interface PointFrames {
  key: string;
  pointIndex: number;
  target: number;
  frames: CapturedFrame[];
}

export interface ScanProgressEvent {
  event: "active_run" | "board_aligning" | "board_aligned" | "point_start" | "point_capturing" | "point_frame" | "point_complete" | "complete" | "aborted" | "error";
  run_id?: string;
  point_index?: number;
  total_points?: number;
  target_mm?: [number, number];
  zoom?: number;
  name?: string;
  frame_index?: number;
  target_frames?: number;
  /** point_frame: small JPEG data URL of the analyzed frame + its boxes (normalized). */
  preview?: string | null;
  boxes?: FrameBox[];
  message?: string;
  error?: string;
  report?: AOIRunReport;
  alignment?: BoardAlignment;
}

/** How the board was found placed vs. its taught points (measured before the scan). */
export interface BoardAlignment {
  /** ok: points moved and frames deskewed; no_calibration: frames only; not_found: no match. */
  status: "ok" | "no_calibration" | "not_found";
  angle_deg?: number;
  offset_mm?: [number, number];
  residual_mm?: number;
  angle_source?: "two_points" | "image";
  measured?: { point: number; name?: string; registered: boolean; angle_deg?: number; inliers?: number }[];
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
  host?: string | null;
  device?: string | null;
  model?: string | null;
  /** The board's real condition, marked by hand (for board-level accuracy / F1). */
  ground_truth?: "good" | "defective" | null;
}

type TimingStat = { mean: number; std: number; median: number; p95: number; min: number; max: number; n: number } | null;

export interface PerformanceReport {
  system: Record<string, unknown> & { hostname?: string; board?: string; ram_gb?: number; gpu?: string };
  benchmark: (Record<string, unknown> & { time: number; label?: string; file?: string; throughput_fps?: number | null; timing_ms?: Record<string, TimingStat>; map?: Record<string, number | string> | null; settings?: Record<string, unknown> }) | null;
  scans: { finished: number; all: number; scan_time_s: TimingStat; hosts: string[] };
  images: { count: number; inference_ms: TimingStat; total_ms: TimingStat; throughput_fps: number | null };
  board: { labeled: number; decided: number; review: number; tp: number; tn: number; fp: number; fn: number; accuracy: number | null; precision: number | null; recall: number | null; f1: number | null };
  table: Array<[string, string]>;
}

export type BenchmarkState =
  | { status: "idle" }
  | { status: "running"; stage: string; done: number; total: number; started: number }
  | { status: "done"; result: NonNullable<PerformanceReport["benchmark"]> }
  | { status: "error"; error: string };

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

export interface RemoteAccess {
  lan: Array<{ interface: string; url: string }>;
  frontend_port: number;
  installed: boolean;
  default_passcode?: boolean;
  state?: string;
  auth_url?: string | null;
  dns_name?: string | null;
  ipv4?: string | null;
  https?: boolean;
  version?: string | null;
  serve?: { port: number; funnel: boolean; url: string } | null;
  others?: Array<{ port: number; target: string; funnel: boolean }>;
  direct_url?: string;
}

export interface HardwareSnapshot {
  time: number;
  platform: "jetson" | "linux" | "other";
  model: string | null;
  cpu: { cores: Array<{ id: number; usage: number; mhz: number | null; max_mhz: number | null; governor: string | null }>; usage: number; load: number[] };
  memory: { total_mb: number; used_mb: number; swap_total_mb: number; swap_used_mb: number };
  temperatures: Array<{ name: string; c: number }>;
  gpu?: { mhz: number; max_mhz: number; min_mhz: number; usage: number | null } | null;
  emc?: { mhz: number; max_mhz: number; min_mhz: number } | null;
  power_rails?: Array<{ name: string; watts: number; volts: number; amps: number; crit_amps: number | null }>;
  fan?: { percent: number | null; rpm: number | null; mode: "auto" | "manual"; manual_percent: number | null; profile: string | null; profiles: string[] };
  power_mode?: { current: number | null; modes: Array<{ id: number; name: string }> } | null;
  clocks_max?: boolean;
  over_current?: Record<string, number> | null;
  control_available?: boolean;
  helper_outdated?: boolean;
}

export type AIProvider = "gemini" | "openrouter";

export interface AIConfig {
  provider: AIProvider;
  configured: boolean;
  model: string;
  providers: Record<AIProvider, { key_set: boolean; key_hint: string | null; models: string }>;
}

export interface HubModel {
  path: string;
  run: string | null;
  kind: "best" | "last" | "other";
  size_mb: number;
  downloaded: boolean;
  local_path: string;
}

export interface ModelFile {
  filename: string;
  path: string;
  size_mb: number;
  modified_at?: number;
  source?: "run" | "project" | "custom";
  kind?: "best" | "last" | null;
  folder?: string;
  /** Present when the file sits in an Ultralytics run folder (<run>/weights/). */
  run?: {
    run: string;
    epochs_done?: number;
    best_epoch?: number;
    map50?: number;
    map50_95?: number;
    train_imgsz?: string;
    train_epochs?: string;
    train_model?: string;
  } | null;
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

/** A named, saved set of test points (reloadable later). */
export interface PointSetMeta {
  id: string;
  name: string;
  point_count: number;
  component_count: number;
  created_at: number;
  updated_at: number;
}

export interface PointSet extends PointSetMeta {
  points: CustomPointRequest[];
}

/** Text printed on a part, read by /api/inspection/ocr. */
export interface OcrResult {
  text: string;
  lines: { text: string; confidence: number }[];
  /** Orientation (degrees) the text was read at. */
  rotation: number;
  confidence: number;
}

/** A resistor's value estimated from its colour bands (/api/inspection/resistor). Display only. */
export interface ResistorResult {
  /** e.g. "1 kΩ ±5%"; empty when no valid code was read. */
  text: string;
  ohms: number | null;
  tolerance_pct?: number | null;
  e_series?: "E12" | "E24" | null;
  /** Bands in reading order: the matched colour and the colour the camera saw. */
  bands: { color: string | null; name_th: string; seen_hex: string; position: number }[];
  confidence: number;
  alternatives: string[];
  reason?: string;
}

/** Height map of one part from /api/aoi/depth (motion stereo). */
export interface DepthResult {
  grid_w: number;
  grid_h: number;
  /** Row-major heights in mm above the surrounding board (frame orientation). */
  heights: number[];
  /** Cells measured directly (others are filled in from their neighbours). */
  valid: boolean[];
  /** The part's box inside the map (0..1). */
  box_in_roi: [number, number, number, number];
  roi: [number, number, number, number];
  roi_size_px: [number, number];
  texture: string | null;
  mm_per_px: number;
  camera_distance_mm: number;
  baseline_mm: number;
  captured_ago_sec: number;
  stats: {
    max_mm: number | null;
    median_mm: number | null;
    valid_ratio: number;
    box_valid_ratio: number;
    board_shift_px: number;
    board_residual_px: number;
    /** Side shots that went into the map, out of those taken. */
    views_used: number;
    views_total: number;
    /** Views left out for disagreeing with the others about the part's height. */
    views_dropped?: number;
    /** Typical disagreement between the shots (mm); null with a single shot. */
    spread_mm: number | null;
  };
}

/** One move checked by the camera (stage_monitor_service). */
export interface StageErrorSample {
  time: number;
  from_mm: [number, number];
  to_mm: [number, number];
  move_mm: [number, number];
  /** Where the carriage ended up vs. where it was sent (mm, +X: further along +X). */
  error_mm: [number, number];
  error_um: number;
  response: number;
}

export interface StageErrorState {
  status: "idle" | "ready" | "measuring" | "needs_calibration" | "no_camera" | "no_texture";
  samples: StageErrorSample[];
  summary: { n: number; rms_um?: [number, number]; max_um?: number; last_um?: number };
}

/** One stage axis from the camera-based calibration (lengths in commanded mm). */
export interface StageAxisCalibration {
  px_per_mm: number;
  backlash_mm: number;
  backlash_cross_mm: number;
  linearity_mm: number;
  straightness_mm: number;
  points: number;
  /** [commanded mm, error along the axis mm, approached in +]. */
  errors: Array<[number, number, boolean]>;
  scale_error_pct?: number;
  suggested_steps_per_mm?: number;
}

export interface StageCalibrationResult {
  x: StageAxisCalibration;
  y: StageAxisCalibration;
  camera_rotation_deg: number;
  squareness_deg: number;
  xy_scale_ratio: number;
  stage_to_image: number[][];
  mm_per_px: number | null;
  repeatability: {
    plus?: { n: number; rms_mm: number; max_mm: number };
    minus?: { n: number; rms_mm: number; max_mm: number };
    compensated?: { n: number; rms_mm: number; max_mm: number; worst_pair_mm: number };
    direction_gap_mm?: [number, number];
  };
  suggested_approach_mm: number;
  time: number;
  center_mm: [number, number];
  range_mm: number;
  steps_per_mm: number;
  approach_mm_during_test: number;
  checkerboard: [number, number] | null;
  square_mm: number | null;
}

export interface StageCalibrationStatus {
  state: "idle" | "running" | "done" | "error" | "cancelled";
  step?: number;
  total?: number;
  message?: string;
  center_mm?: [number, number];
  last: StageCalibrationResult | null;
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
  model_search_dirs: string[];
  depth_camera_distance_mm: number;
  depth_baseline_mm: number;
  depth_views: number;
  stage_approach_mm: number;
  stabilize_enabled: boolean;
  stabilize_max_wait_sec: number;
  stabilize_threshold_px: number;
  board_align_enabled: boolean;
  camera_rotate_deg: number;
  stage_sound_enabled: boolean;
  board_align_max_deg: number;
  board_align_max_mm: number;
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
