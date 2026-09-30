export interface ExpectedComponent {
  id: string;
  name: string;
  bbox: [number, number, number, number]; // [xmin, ymin, xmax, ymax] normalized 0..1
}

export interface DetectedBox {
  cls: number;
  name: string;
  conf: number;
  bbox: [number, number, number, number]; // [xmin, ymin, xmax, ymax] in source image pixels
  held?: boolean;
}

export interface InspectionFrame {
  id: number;
  capturedAt: number;
  context: string;
  width: number;
  height: number;
  image: string; // data URL or http URL
  boxes: DetectedBox[];
}

export interface RecordedInspectionFrame {
  id: number;
  frameIndex: number;
  capturedAt: number;
  image: string;
  width: number;
  height: number;
  boxes: DetectedBox[];
  matchedIndices: number[];
  unmatchedIndices: number[];
  matches: Array<{ expectedIndex: number; boxIndex: number; overlap: number }>;
}

export interface InspectionRound {
  startedAt: number;
  lastFrame: number;
  frames: number;
  hits: number[];
  status: 'running' | 'complete' | 'cancelled';
  capturedFrames?: RecordedInspectionFrame[];
  targetFrames?: number;
  passThreshold?: number;
}

export function boxIoU(
  boxA: { bbox: [number, number, number, number] },
  boxB: { bbox: [number, number, number, number] }
): number {
  const [aX1, aY1, aX2, aY2] = boxA.bbox;
  const [bX1, bY1, bX2, bY2] = boxB.bbox;

  const interX1 = Math.max(aX1, bX1);
  const interY1 = Math.max(aY1, bY1);
  const interX2 = Math.min(aX2, bX2);
  const interY2 = Math.min(aY2, bY2);

  const interArea = Math.max(0, interX2 - interX1) * Math.max(0, interY2 - interY1);
  const areaA = Math.max(0, aX2 - aX1) * Math.max(0, aY2 - aY1);
  const areaB = Math.max(0, bX2 - bX1) * Math.max(0, bY2 - bY1);
  const union = areaA + areaB - interArea;

  return union > 0 ? interArea / union : 0;
}

type Box = [number, number, number, number];
const center = (b: Box) => [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];

/**
 * Median whole-frame shift of the detections vs. the reference (normalized units).
 * Mirrors estimate_frame_offset() in backend/app/core/inspection.py — keep them in sync so
 * the dialog's dry run and the real scan judge a frame the same way.
 */
export function estimateFrameOffset(
  expected: ExpectedComponent[],
  boxes: Array<{ name: string; bbox: Box }>,
  maxShift = 0.08,
  minPairs = 3
): [number, number] {
  const dxs: number[] = [];
  const dys: number[] = [];
  for (const item of expected) {
    const [ex, ey] = center(item.bbox);
    const label = item.name.trim().toLowerCase();
    let best: [number, number, number] | null = null;
    for (const box of boxes) {
      if (box.name.trim().toLowerCase() !== label) continue;
      const [cx, cy] = center(box.bbox);
      const dist = Math.hypot(cx - ex, cy - ey);
      if (dist <= maxShift && (!best || dist < best[0])) best = [dist, cx - ex, cy - ey];
    }
    if (best) {
      dxs.push(best[1]);
      dys.push(best[2]);
    }
  }
  if (dxs.length < minPairs) return [0, 0];
  const median = (v: number[]) => v.sort((a, b) => a - b)[Math.floor(v.length / 2)];
  return [median(dxs), median(dys)];
}

export function newRound(
  count: number,
  startedAt: number,
  targetFrames: number = 10,
  passThreshold?: number
): InspectionRound {
  const target = Math.max(1, targetFrames || 10);
  const pass = passThreshold !== undefined ? Math.max(1, Math.min(target, passThreshold)) : Math.max(1, Math.ceil(target * 0.8));
  return {
    startedAt,
    lastFrame: -1,
    frames: 0,
    hits: Array(count).fill(0),
    status: 'running',
    capturedFrames: [],
    targetFrames: target,
    passThreshold: pass,
  };
}

export function validateReference(items: ExpectedComponent[]): boolean {
  return (
    items.length > 0 &&
    new Set(items.map((i) => i.id.trim())).size === items.length &&
    items.every(
      (i) =>
        i.id.trim() !== '' &&
        i.name.trim() !== '' &&
        i.bbox.length === 4 &&
        i.bbox.every(Number.isFinite) &&
        i.bbox[0] >= 0 &&
        i.bbox[1] >= 0 &&
        i.bbox[2] <= 1 &&
        i.bbox[3] <= 1 &&
        i.bbox[2] > i.bbox[0] &&
        i.bbox[3] > i.bbox[1]
    )
  );
}

export function inspectFrame(
  round: InspectionRound,
  expected: ExpectedComponent[],
  frame: InspectionFrame,
  context: string,
  confidence: number
): InspectionRound {
  if (
    round.status !== 'running' ||
    frame.id <= round.lastFrame ||
    frame.capturedAt <= round.startedAt ||
    frame.context !== context ||
    !validateReference(expected) ||
    frame.width <= 0 ||
    frame.height <= 0
  ) {
    return round;
  }

  // Filter raw boxes by confidence
  const rawBoxes = frame.boxes.filter((b) => !b.held && b.conf >= confidence);

  // Normalize the API pixel coordinates to 0..1
  const boxes = rawBoxes.map((b) => {
    return {
      ...b,
      bbox: [
        b.bbox[0] / frame.width,
        b.bbox[1] / frame.height,
        b.bbox[2] / frame.width,
        b.bbox[3] / frame.height,
      ] as [number, number, number, number],
    };
  });

  // Compensate a uniform stage shift before matching (see estimateFrameOffset).
  const [dx, dy] = estimateFrameOffset(expected, boxes);
  const aligned = expected.map((item) => ({
    ...item,
    bbox: [item.bbox[0] + dx, item.bbox[1] + dy, item.bbox[2] + dx, item.bbox[3] + dy] as Box,
  }));

  // Calculate pairs with IoU >= 0.3 and exact normalized class name
  const pairs = aligned.flatMap((item, ei) =>
    boxes.flatMap((box, bi) => {
      const overlap = boxIoU({ bbox: item.bbox }, { bbox: box.bbox });
      const itemLabel = item.name.trim().toLowerCase();
      const boxLabel = box.name.trim().toLowerCase();
      const classMatch = !!itemLabel && itemLabel === boxLabel;
      return classMatch && overlap >= 0.3 ? [{ ei, bi, overlap }] : [];
    })
  ).sort((a, b) => b.overlap - a.overlap);

  const matched = new Set<number>();
  const used = new Set<number>();
  const matches: Array<{ expectedIndex: number; boxIndex: number; overlap: number }> = [];

  for (const p of pairs) {
    if (!matched.has(p.ei) && !used.has(p.bi)) {
      matched.add(p.ei);
      used.add(p.bi);
      matches.push({ expectedIndex: p.ei, boxIndex: p.bi, overlap: p.overlap });
    }
  }

  const targetFrames = round.targetFrames ?? 10;
  const frames = round.frames + 1;

  const recordedFrame: RecordedInspectionFrame = {
    id: frame.id,
    frameIndex: round.frames,
    capturedAt: frame.capturedAt,
    image: frame.image,
    width: frame.width,
    height: frame.height,
    boxes: rawBoxes,
    matchedIndices: Array.from(matched),
    unmatchedIndices: expected.map((_, i) => i).filter((i) => !matched.has(i)),
    matches,
  };

  const capturedFrames = [...(round.capturedFrames || []), recordedFrame];

  return {
    ...round,
    lastFrame: frame.id,
    frames,
    hits: round.hits.map((n, i) => n + (matched.has(i) ? 1 : 0)),
    status: frames >= targetFrames ? 'complete' : 'running',
    capturedFrames,
  };
}

export function slotStatus(
  hits: number,
  targetFrames: number = 10,
  passThreshold?: number
): 'confirmed' | 'uncertain' | 'suspect' {
  const target = Math.max(1, targetFrames);
  const pass = passThreshold !== undefined ? passThreshold : Math.max(1, Math.ceil(target * 0.8));
  const uncertain = Math.max(1, Math.floor(target * 0.4));
  return hits >= pass ? 'confirmed' : hits >= uncertain ? 'uncertain' : 'suspect';
}

export function boardComplete(round: InspectionRound | null): boolean {
  const target = round?.targetFrames ?? 10;
  return (
    !!round &&
    round.status === 'complete' &&
    round.frames === target &&
    round.hits.length > 0 &&
    round.hits.every((h) => slotStatus(h, target, round?.passThreshold) === 'confirmed')
  );
}
