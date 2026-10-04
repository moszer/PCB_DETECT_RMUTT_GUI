import type {
  HubModel,
  AOIRunReport,
  CameraDevice,
  ComputeDevice,
  ControlLease,
  Dataset,
  DatasetImage,
  DatasetSummary,
  DepthResult,
  InspectionResult,
  OcrResult,
  PointSet,
  PointSetMeta,
  CustomPointRequest,
  LabelBox,
  ModelFile,
  ReferenceProfile,
  ReferenceSummary,
  RunRecord,
  ScanPlanRequest,
  ScanPoint,
  SerialPort,
  SingleInspectionRecord,
  StationSettings,
  Statistics,
  SystemStatus,
} from "@/types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");

const TOKEN_KEY = "pcb_operator_token";
const LEGACY_TOKEN_KEY = "pcb_operator_id";

export function getOperatorToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(TOKEN_KEY) || localStorage.getItem(LEGACY_TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setOperatorToken(token: string | null) {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(LEGACY_TOKEN_KEY);
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage unavailable (private mode): the lease simply won't survive a reload.
  }
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {});
  const token = getOperatorToken();
  if (token && !headers.has("X-Operator-Token")) headers.set("X-Operator-Token", token);

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const err = await response.json();
      if (err.detail) message = typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail);
    } catch {
      // Non-JSON error body; keep the status text.
    }
    throw new Error(message);
  }
  return response.json();
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, {
    method: "POST",
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });

const postForm = <T>(path: string, fields: Record<string, string | Blob | undefined>) => {
  const form = new FormData();
  for (const [key, value] of Object.entries(fields)) if (value !== undefined) form.append(key, value);
  return request<T>(path, { method: "POST", body: form });
};

export interface InspectOptions {
  conf: number;
  matchDist: number;
  failOnExtra: boolean;
  referenceId?: string;
  imgsz?: number;
}

const inspectFields = (o: InspectOptions) => ({
  conf: String(o.conf),
  match_dist: String(o.matchDist),
  fail_on_extra: String(o.failOnExtra),
  reference_id: o.referenceId || undefined,
  imgsz: o.imgsz ? String(o.imgsz) : undefined,
});

export interface StartScanOptions extends InspectOptions {
  plan: ScanPlanRequest;
  isGolden: boolean;
  multiframeEnabled: boolean;
  targetFrames: number;
  passRatio: number;
}

export const api = {
  // System
  getStatus: () => request<SystemStatus>("/api/system/status"),
  getSettings: () => request<StationSettings>("/api/system/settings"),
  updateSettings: (data: Partial<StationSettings> & { model_path?: string }) =>
    post<{ success: boolean; settings: StationSettings }>("/api/system/settings", data),
  getDevices: () => request<{ current_device: string; preference: string; devices: ComputeDevice[] }>("/api/system/devices"),
  setDevice: (preference: string) => post<{ success: boolean }>("/api/system/device", { preference }),
  setModel: (model_path: string) => post<{ model_path: string; device: string }>("/api/system/model", { model_path }),
  listModels: () =>
    request<{ current_model: string; models: ModelFile[]; custom_dirs: string[]; search_dirs: string[] }>("/api/system/models"),
  listHubModels: () => request<{ repo: string; url: string; models: HubModel[] }>("/api/system/models/hub"),
  downloadHubModel: (file: string) => post<{ path: string; size_mb: number }>("/api/system/models/hub/download", { file }),
  uploadModel: (file: File) =>
    postForm<{ filename: string; path: string; size_mb: number; message: string }>("/api/system/models/upload", { file }),

  // Operator lease
  acquireLease: (operator_name: string, passcode: string | undefined, force: boolean) =>
    post<{ success: boolean; operator_token?: string; message: string; lease: ControlLease }>("/api/auth/acquire", {
      operator_name,
      passcode,
      force,
    }),
  renewLease: () => post<{ success: boolean }>("/api/auth/renew"),
  releaseLease: () => post<{ success: boolean }>("/api/auth/release"),

  // Camera
  listCameras: () =>
    request<{
      devices: CameraDevice[];
      current_index: number;
      is_mock: boolean;
      resolution: [number, number];
      capture_resolution?: [number, number];
      output_mode?: "fit" | "crop";
      fps: number;
    }>(
      "/api/camera/devices"
    ),
  startCamera: (device_index: number, width: number, height: number, output?: [number, number], mode: "fit" | "crop" = "fit") =>
    post<{ success: boolean; is_mock: boolean; resolution: [number, number] }>("/api/camera/start", {
      device_index,
      width,
      height,
      fps: 30,
      output_width: output?.[0],
      output_height: output?.[1],
      output_mode: mode,
    }),

  // Inspection
  inspectUpload: (file: File, o: InspectOptions) =>
    postForm<InspectionResult>("/api/inspection/inspect-upload", { file, ...inspectFields(o) }),
  /** Read the markings inside boxes (normalized) of a stored station image. */
  readText: (image_url: string, boxes: number[][]) =>
    post<{ engine: string; results: OcrResult[] }>("/api/inspection/ocr", { image_url, boxes }),
  inspectLive: (o: InspectOptions) => postForm<InspectionResult>("/api/inspection/inspect-live", inspectFields(o)),

  // Stage & AOI
  listPorts: () => request<{ ports: SerialPort[] }>("/api/aoi/ports"),
  connectMachine: (mode: "simulation" | "serial", port?: string) => post("/api/aoi/connect", { mode, port }),
  disconnectMachine: () => post("/api/aoi/disconnect"),
  homeMachine: () => post("/api/aoi/home"),
  jogMachine: (dx_mm: number, dy_mm: number, speed: number) => post("/api/aoi/jog", { dx_mm, dy_mm, speed }),
  moveToPosition: (x_mm: number, y_mm: number, speed: number) => post("/api/aoi/move", { x_mm, y_mm, speed }),
  pointSets: {
    list: () => request<{ sets: PointSetMeta[] }>("/api/aoi/point-sets").then((r) => r.sets),
    get: (id: string) => request<PointSet>(`/api/aoi/point-sets/${encodeURIComponent(id)}`),
    create: (name: string, points: CustomPointRequest[]) => post<PointSet>("/api/aoi/point-sets", { name, points }),
    update: (id: string, patch: { name?: string; points?: CustomPointRequest[] }) =>
      request<PointSet>(`/api/aoi/point-sets/${encodeURIComponent(id)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      }),
    remove: (id: string) => request<{ success: boolean }>(`/api/aoi/point-sets/${encodeURIComponent(id)}`, { method: "DELETE" }),
  },
  /** Height map of one part (moves the stage aside and back; the photo pair is cached per point). */
  measureDepth: (req: { x_mm: number; y_mm: number; zoom: number; bbox: number[]; recapture?: boolean }) =>
    post<DepthResult>("/api/aoi/depth", req),
  stopEmergency: () => post("/api/aoi/stop"),
  motorsOff: () => post("/api/aoi/motors-off"),
  planScan: (plan: ScanPlanRequest) => post<ScanPoint[]>("/api/aoi/plan", plan),
  startScan: (o: StartScanOptions) =>
    post<AOIRunReport>("/api/aoi/scan/start", {
      plan: o.plan,
      is_golden_scan: o.isGolden,
      reference_id: o.referenceId || undefined,
      conf_thresh: o.conf,
      match_dist: o.matchDist,
      fail_on_extra: o.failOnExtra,
      imgsz: o.imgsz,
      multiframe_enabled: o.multiframeEnabled,
      target_frames: o.targetFrames,
      pass_ratio: o.passRatio,
    }),
  stopScan: () => post("/api/aoi/scan/stop"),
  getScanStatus: () => request<AOIRunReport | { status: "idle" }>("/api/aoi/scan/status"),

  // References
  listReferences: () => request<ReferenceSummary[]>("/api/references"),
  getReference: (id: string) => request<ReferenceProfile>(`/api/references/${encodeURIComponent(id)}`),
  deleteReference: (id: string) => request<{ success: boolean }>(`/api/references/${encodeURIComponent(id)}`, { method: "DELETE" }),
  importDesktopReference: () => post<ReferenceProfile>("/api/references/import-desktop"),

  // History
  listRuns: (verdict: string | undefined, limit: number, offset: number) => {
    const q = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (verdict) q.set("verdict", verdict);
    return request<{ runs: RunRecord[]; total: number }>(`/api/history/runs?${q}`);
  },
  getRun: (id: string) => request<RunRecord>(`/api/history/runs/${encodeURIComponent(id)}`),
  getStatistics: () => request<Statistics>("/api/history/statistics"),
  listSingleInspections: (limit: number, offset: number) =>
    request<{ inspections: SingleInspectionRecord[]; total: number }>(
      `/api/history/single-inspections?limit=${limit}&offset=${offset}`
    ),
};

export interface StartCaptureOptions {
  name: string;
  corners: Array<[number, number]>;
  pitchX: number;
  pitchY: number;
  speed: number;
  settleSec: number;
  autoLabel: boolean;
  conf: number;
  imgsz?: number;
}

export const datasetApi = {
  list: () => request<{ datasets: DatasetSummary[]; running: string | null }>("/api/datasets"),
  get: (id: string) => request<Dataset>(`/api/datasets/${encodeURIComponent(id)}`),
  capture: (o: StartCaptureOptions) =>
    post<Dataset>("/api/datasets/capture", {
      name: o.name,
      corners: o.corners,
      pitch_x_mm: o.pitchX,
      pitch_y_mm: o.pitchY,
      speed: o.speed,
      settle_sec: o.settleSec,
      auto_label: o.autoLabel,
      conf: o.conf,
      imgsz: o.imgsz,
    }),
  stop: () => post("/api/datasets/capture/stop"),
  remove: (id: string) => request<{ success: boolean }>(`/api/datasets/${encodeURIComponent(id)}`, { method: "DELETE" }),
  labels: (id: string, file: string) =>
    request<{ file: string; boxes: LabelBox[]; classes: string[] }>(`/api/datasets/${encodeURIComponent(id)}/labels/${encodeURIComponent(file)}`),
  saveLabels: (id: string, file: string, boxes: LabelBox[]) =>
    request<DatasetImage>(`/api/datasets/${encodeURIComponent(id)}/labels/${encodeURIComponent(file)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ boxes }),
    }),
  removeImage: (id: string, file: string) =>
    request<{ success: boolean }>(`/api/datasets/${encodeURIComponent(id)}/images/${encodeURIComponent(file)}`, { method: "DELETE" }),
  imageUrl: (id: string, file: string) => `${API_BASE}/api/storage/datasets/${id}/images/${file}`,
  downloadUrl: (id: string, valRatio = 0.2) => `${API_BASE}/api/datasets/${encodeURIComponent(id)}/download?val_ratio=${valRatio}`,
};

export const errorMessage = (err: unknown) => (err instanceof Error ? err.message : String(err));
