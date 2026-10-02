/**
 * Placement of box labels over an image so they don't cover each other.
 *
 * Boxes are normalized [x1, y1, x2, y2]; layout happens in container pixels because
 * text has a fixed pixel size. Each label tries a few anchor positions around its box
 * and takes the first one that collides with no already-placed label. Labels with no
 * free spot are reported as hidden (shown only when their box is selected/hovered).
 */

export type NBox = [number, number, number, number];

export interface LabelSpot {
  left: number;
  top: number;
  width: number;
  hidden: boolean;
}

export const LABEL_FONT = "600 10px ui-monospace, SFMono-Regular, Menlo, monospace";
export const LABEL_HEIGHT = 15;
const PAD_X = 4;

let measureCtx: CanvasRenderingContext2D | null = null;
export function labelWidth(text: string) {
  if (typeof document === "undefined") return text.length * 6.5 + PAD_X * 2;
  measureCtx ??= document.createElement("canvas").getContext("2d");
  if (!measureCtx) return text.length * 6.5 + PAD_X * 2;
  measureCtx.font = LABEL_FONT;
  return Math.ceil(measureCtx.measureText(text).width) + PAD_X * 2;
}

type Rect = { l: number; t: number; r: number; b: number };
const overlap = (a: Rect, b: Rect) => Math.max(0, Math.min(a.r, b.r) - Math.max(a.l, b.l)) * Math.max(0, Math.min(a.b, b.b) - Math.max(a.t, b.t));

/**
 * @param priority indices placed first (e.g. the selected box) — they always win a spot.
 */
export function layoutLabels(
  boxes: NBox[],
  texts: string[],
  width: number,
  height: number,
  priority: number[] = []
): LabelSpot[] {
  const spots: LabelSpot[] = boxes.map(() => ({ left: 0, top: 0, width: 0, hidden: true }));
  if (!width || !height) return spots;
  const area = (b: NBox) => (b[2] - b[0]) * (b[3] - b[1]);
  // Priority first, then small boxes (they're the ones that get lost), then the rest.
  const order = boxes.map((_, i) => i).sort((a, b) => {
    const pa = priority.includes(a) ? 0 : 1;
    const pb = priority.includes(b) ? 0 : 1;
    return pa - pb || area(boxes[a]) - area(boxes[b]);
  });
  const placed: Rect[] = [];
  const h = LABEL_HEIGHT;
  for (const i of order) {
    const [x1, y1, x2, y2] = boxes[i];
    const L = x1 * width, T = y1 * height, R = x2 * width, B = y2 * height;
    const w = labelWidth(texts[i]);
    const candidates: Array<[number, number]> = [
      [L, T - h], // above, left-aligned (classic)
      [R - w, T - h], // above, right-aligned
      [L, B], // below
      [L, T], // inside top-left
      [R - w, B], // below, right-aligned
      [L, B - h], // inside bottom-left
      [R, T], // right side
      [L - w, T], // left side
    ];
    let best: { rect: Rect; cost: number } | null = null;
    for (const [cl, ct] of candidates) {
      const l = Math.min(Math.max(0, cl), width - w);
      const t = Math.min(Math.max(0, ct), height - h);
      const rect = { l, t, r: l + w, b: t + h };
      const cost = placed.reduce((sum, p) => sum + overlap(rect, p), 0);
      if (!best || cost < best.cost) best = { rect, cost };
      if (cost === 0) break;
    }
    const forced = priority.includes(i);
    // Accept a free spot; a priority label is always shown even if it has to overlap.
    if (best && (best.cost === 0 || forced)) {
      placed.push(best.rect);
      spots[i] = { left: best.rect.l, top: best.rect.t, width: w, hidden: false };
    } else if (best) {
      spots[i] = { left: best.rect.l, top: best.rect.t, width: w, hidden: true };
    }
  }
  return spots;
}

/** Paint order: big boxes first so small ones stay visible and clickable; `top` last. */
export function paintOrder(boxes: NBox[], top: Array<number | null | undefined> = []) {
  const area = (b: NBox) => (b[2] - b[0]) * (b[3] - b[1]);
  const pinned = top.filter((i): i is number => i !== null && i !== undefined);
  return boxes
    .map((_, i) => i)
    .filter((i) => !pinned.includes(i))
    .sort((a, b) => area(boxes[b]) - area(boxes[a]))
    .concat(pinned.filter((i) => i < boxes.length));
}

/**
 * Boxes containing a point, smallest first. Clicking the same spot again moves to the
 * next one, so boxes hidden underneath others can still be selected.
 */
export function pickAt(boxes: NBox[], x: number, y: number, current: number | null): number | null {
  const area = (b: NBox) => (b[2] - b[0]) * (b[3] - b[1]);
  const hits = boxes
    .map((b, i) => ({ i, b }))
    .filter(({ b }) => x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3])
    .sort((a, b) => area(a.b) - area(b.b))
    .map(({ i }) => i);
  if (!hits.length) return null;
  const at = current === null ? -1 : hits.indexOf(current);
  return at === -1 ? hits[0] : hits[(at + 1) % hits.length];
}

/* ── Overlapping boxes (likely duplicate / nested labels) ───────────────── */

/** Highlight for overlapping boxes — distinct from every class / status color in the app. */
export const OVERLAP_COLOR = "#ff2bd6";

/**
 * Pairs of boxes that overlap enough to be suspicious: IoU ≥ `iou` (two boxes on the same
 * part) or ≥ `contain` of the smaller box inside the larger one (a box nested in another).
 * Neighbouring parts that merely touch are not reported.
 */
export function overlappingPairs(boxes: NBox[], { iou = 0.3, contain = 0.7 } = {}) {
  const area = (b: NBox) => Math.max(0, b[2] - b[0]) * Math.max(0, b[3] - b[1]);
  const pairs: Array<[number, number]> = [];
  for (let i = 0; i < boxes.length; i++) {
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i], b = boxes[j];
      const inter = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
      if (!inter) continue;
      const aa = area(a), ab = area(b);
      if (inter / (aa + ab - inter) >= iou || inter / Math.min(aa, ab) >= contain) pairs.push([i, j]);
    }
  }
  const flagged = new Set(pairs.flat());
  return { pairs, flagged };
}

/** Boxes whose center lies inside a marquee rectangle (center rule: grazing a big box doesn't grab it). */
export function boxesInRect(boxes: NBox[], rect: NBox): number[] {
  const [l, t, r, b] = [Math.min(rect[0], rect[2]), Math.min(rect[1], rect[3]), Math.max(rect[0], rect[2]), Math.max(rect[1], rect[3])];
  return boxes
    .map((bx, i) => ({ i, cx: (bx[0] + bx[2]) / 2, cy: (bx[1] + bx[3]) / 2 }))
    .filter(({ cx, cy }) => cx >= l && cx <= r && cy >= t && cy <= b)
    .map(({ i }) => i);
}
