import type { StageCalibrationResult } from "@/types";

/**
 * Where the pictures of a board's points lie on the board, in stage mm.
 *
 * A board feature's position is the stage position that brings it under the image centre:
 * for a picture taken at stage P, the pixel q (from the image centre) is at P − M⁻¹·q, with M
 * the calibrated stage→image matrix (px per commanded mm, scaled to the picture's size and
 * zoom). With x right and y up this lays the pictures out the way the camera shows them, and
 * the points at their own stage coordinates.
 */
export type Mat2 = [[number, number], [number, number]];

/** Height of the full camera frame in commanded mm when there is no calibration yet. */
const DEFAULT_FOV_MM = 19;

export interface StageCal {
  m: Mat2;
  /** Image height the matrix was measured at. */
  h: number;
}

export function stageCal(last: StageCalibrationResult | null | undefined): StageCal | null {
  const m = last?.stage_to_image;
  const size = (last as { image_size?: [number, number] } | null | undefined)?.image_size;
  if (!m || m.length !== 2 || !size?.[1]) return null;
  const det = m[0][0] * m[1][1] - m[0][1] * m[1][0];
  return Math.abs(det) < 1e-6 ? null : { m: [[m[0][0], m[0][1]], [m[1][0], m[1][1]]], h: size[1] };
}

/** Image px per commanded mm for a picture `picH` px tall at digital zoom `zoom`. */
export function pictureMatrix(cal: StageCal | null, picH: number, zoom = 1): Mat2 {
  const z = Math.max(1, zoom || 1);
  if (!cal) {
    const ppm = (picH / DEFAULT_FOV_MM) * z;
    return [[-ppm, 0], [0, ppm]];
  }
  const k = (picH / cal.h) * z;
  return [[cal.m[0][0] * k, cal.m[0][1] * k], [cal.m[1][0] * k, cal.m[1][1] * k]];
}

function invert([[a, b], [c, d]]: Mat2): Mat2 {
  const det = a * d - b * c;
  return [[d / det, -b / det], [-c / det, a / det]];
}

/** Stage-mm position of pixel (u, v) of a picture of size w×h taken at (x, y). */
export function pixelToBoard(inv: Mat2, x: number, y: number, w: number, h: number, u: number, v: number): [number, number] {
  const qx = u - w / 2;
  const qy = v - h / 2;
  return [x - (inv[0][0] * qx + inv[0][1] * qy), y - (inv[1][0] * qx + inv[1][1] * qy)];
}

/** The picture's corners on the board: top-left, top-right, bottom-right, bottom-left. */
export function pictureQuad(cal: StageCal | null, p: { x_mm: number; y_mm: number; zoom?: number }, size: [number, number]) {
  const [w, h] = size;
  const inv = invert(pictureMatrix(cal, h, p.zoom));
  const at = (u: number, v: number) => pixelToBoard(inv, p.x_mm, p.y_mm, w, h, u, v);
  return { corners: [at(0, 0), at(w, 0), at(w, h), at(0, h)] as [number, number][], at };
}

/** The camera's view (full frame, zoom 1) in commanded mm: [width, height]. */
export function fovMm(cal: StageCal | null, frame: [number, number] | null | undefined, zoom = 1): [number, number] {
  const [w, h] = frame && frame[0] > 0 ? frame : [1, 1];
  const inv = invert(pictureMatrix(cal, h, zoom));
  const fw = Math.hypot(inv[0][0] * w, inv[1][0] * w);
  const fh = Math.hypot(inv[0][1] * h, inv[1][1] * h);
  return [fw, fh];
}
