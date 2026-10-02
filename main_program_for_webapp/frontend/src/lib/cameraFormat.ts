/**
 * Camera image format = what the camera captures + the size/way the frame is shaped for
 * everything downstream (live view, inspection, AOI scans, dataset capture).
 * Backend counterpart: CameraService.start(width, height, output_size, output_mode).
 */
import { api } from "./api";

export type CaptureId = "720p" | "1080p" | "4k";
export type OutputMode = "fit" | "crop";

export const CAPTURE_SIZES: Record<CaptureId, { label: string; size: [number, number] }> = {
  "720p": { label: "720p · 1280×720", size: [1280, 720] },
  "1080p": { label: "1080p · 1920×1080", size: [1920, 1080] },
  "4k": { label: "4K · 3840×2160", size: [3840, 2160] },
};

/** Common square sizes (YOLO-friendly); any custom W×H is also accepted. */
export const SQUARE_SIZES = [320, 416, 512, 640, 800, 960, 1024, 1080, 1280, 1600, 2160] as const;

export interface CameraFormat {
  capture: CaptureId;
  /** null = use the captured frame as-is. */
  output: [number, number] | null;
  mode: OutputMode;
}

export interface CameraShape {
  resolution: [number, number];
  capture_resolution?: [number, number];
  output_mode?: OutputMode;
}

export const DEFAULT_FORMAT: CameraFormat = { capture: "1080p", output: null, mode: "fit" };

/** Reconstruct the active format from /api/camera/devices. */
export function formatFromCamera(cam?: CameraShape | null): CameraFormat {
  if (!cam) return DEFAULT_FORMAT;
  const cap = cam.capture_resolution ?? cam.resolution;
  const capture =
    (Object.entries(CAPTURE_SIZES).find(([, c]) => c.size[0] === cap[0] && c.size[1] === cap[1])?.[0] as CaptureId) ??
    (cap[0] >= 3000 ? "4k" : cap[0] >= 1600 ? "1080p" : "720p");
  const same = cam.resolution[0] === cap[0] && cam.resolution[1] === cap[1];
  return { capture, output: same ? null : cam.resolution, mode: cam.output_mode ?? "fit" };
}

/**
 * How much narrower the 1:1 crop is than the "fit" view of the same output aspect
 * (>1 means a zoom). Below 1 the frame is too small and the backend falls back to fit.
 */
export function cropZoom(capture: [number, number], output: [number, number]) {
  return Math.min(capture[0] / output[0], capture[1] / output[1]);
}

export function formatLabel(f: CameraFormat, actualCapture?: [number, number]) {
  const cap = actualCapture ?? CAPTURE_SIZES[f.capture].size;
  if (!f.output) return `${cap[0]}×${cap[1]}`;
  const how = f.mode === "crop" ? `ตัด 1:1 ซูม ${cropZoom(cap, f.output).toFixed(1)}×` : "ย่อ";
  return `${f.output[0]}×${f.output[1]} · ${how}`;
}

export async function applyCameraFormat(deviceIndex: number, f: CameraFormat) {
  const [w, h] = CAPTURE_SIZES[f.capture].size;
  return api.startCamera(deviceIndex, w, h, f.output ?? undefined, f.mode);
}
