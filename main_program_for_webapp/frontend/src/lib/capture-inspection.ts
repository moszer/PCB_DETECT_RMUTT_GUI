import { API_BASE, request } from "./api";
import type { InspectionResult } from "@/types";
import type { ExpectedComponent, InspectionFrame } from "./board-inspection";

/** Longest edge of the reference/frame previews kept in the browser. Boxes are normalized, so this only affects display size. */
const PREVIEW_MAX_EDGE = 1280;

async function previewDataUrl(bitmap: ImageBitmap): Promise<string> {
  const scale = Math.min(1, PREVIEW_MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.82);
}

/** One fresh camera frame, with the same crop/zoom used by AOI, and no history side effects. */
export async function captureInspection(zoom: number, confidence: number, imgsz: number, signal?: AbortSignal) {
  const snapshot = await fetch(`${API_BASE}/api/camera/snapshot?zoom=${zoom}&t=${Date.now()}`, { signal, cache: "no-store" });
  if (!snapshot.ok) throw new Error(`Camera snapshot failed (${snapshot.status})`);
  const timestampHeader = snapshot.headers.get("X-Frame-Timestamp");
  const timestamp = Number(timestampHeader);
  if (!timestampHeader || !Number.isFinite(timestamp)) throw new Error("Camera frame timestamp is missing");
  const simulation = snapshot.headers.get("X-Camera-Mock") === "true";
  const blob = await snapshot.blob();
  const bitmap = await createImageBitmap(blob);
  const width = bitmap.width;
  const height = bitmap.height;
  const image = await previewDataUrl(bitmap);
  bitmap.close();

  const data = new FormData();
  data.append("file", blob, "camera-frame.jpg");
  data.append("conf", String(confidence));
  data.append("imgsz", String(imgsz));
  data.append("persist", "false");
  const result = await request<InspectionResult>("/api/inspection/inspect-upload", { method: "POST", body: data, signal });
  signal?.throwIfAborted();

  const frame: InspectionFrame = {
    id: timestamp,
    capturedAt: Date.now(),
    context: "live_camera",
    width,
    height,
    image,
    boxes: result.detections.map((d) => ({ cls: d.id, name: d.label, conf: d.conf, bbox: d.box })),
  };
  const items: ExpectedComponent[] = result.detections
    .map((d, i) => ({
      id: `P${i + 1}`,
      name: d.label,
      bbox: d.box.map((v, axis) => Math.max(0, Math.min(1, v / (axis % 2 ? height : width)))) as ExpectedComponent["bbox"],
    }))
    .filter((d) => d.bbox[2] > d.bbox[0] && d.bbox[3] > d.bbox[1]);
  return { frame, items, timestamp, simulation };
}
