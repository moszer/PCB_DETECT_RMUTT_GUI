"use client";

import type * as T from "three";

/** Small deterministic random numbers, so the decorative board is the same on every visit. */
function rng(seed: number) {
  let s = seed >>> 0 || 1;
  return () => {
    s ^= s << 13;
    s ^= s >>> 17;
    s ^= s << 5;
    return (s >>> 0) / 4294967296;
  };
}

export interface PcbParts {
  group: T.Group;
  /** Each placed part (for the drop-in animation): its mesh index, resting z and delay 0..1. */
  parts: Array<{ mesh: T.InstancedMesh; index: number; z: number; delay: number; matrix: T.Matrix4 }>;
  size: [number, number];
}

/**
 * A stylised PCB (mm): green board with gold traces and pads, ICs, SMD resistors/capacitors,
 * a connector and an electrolytic cap. Parts are instanced (a handful of draw calls).
 */
export function buildPcb(THREE: typeof T, opts: { seed?: number; width?: number; height?: number } = {}): PcbParts {
  const W = opts.width ?? 80;
  const H = opts.height ?? 54;
  const rand = rng(opts.seed ?? 7);
  const group = new THREE.Group();
  const parts: PcbParts["parts"] = [];

  const board = new THREE.Mesh(
    new THREE.BoxGeometry(W, H, 1.6),
    new THREE.MeshStandardMaterial({ color: 0x15603c, roughness: 0.55, metalness: 0.08 })
  );
  board.position.z = -0.8;
  group.add(board);

  // Traces: Manhattan runs between random points, gold.
  const gold = new THREE.MeshStandardMaterial({ color: 0xd4a640, roughness: 0.3, metalness: 0.85 });
  const traceGeo = new THREE.BoxGeometry(1, 1, 0.08);
  const traces = new THREE.InstancedMesh(traceGeo, gold, 160);
  const m = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const v = new THREE.Vector3();
  const s = new THREE.Vector3();
  let n = 0;
  const addTrace = (x1: number, y1: number, x2: number, y2: number, w = 0.45) => {
    if (n >= 160) return;
    const len = Math.hypot(x2 - x1, y2 - y1);
    if (len < 0.5) return;
    q.setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.atan2(y2 - y1, x2 - x1));
    m.compose(v.set((x1 + x2) / 2, (y1 + y2) / 2, 0.04), q, s.set(len + w, w, 1));
    traces.setMatrixAt(n++, m);
  };
  for (let i = 0; i < 46; i++) {
    const x1 = (rand() - 0.5) * W * 0.9;
    const y1 = (rand() - 0.5) * H * 0.9;
    const x2 = (rand() - 0.5) * W * 0.9;
    const y2 = (rand() - 0.5) * H * 0.9;
    const mid = rand() > 0.5;
    addTrace(x1, y1, mid ? x2 : x1, mid ? y1 : y2);
    addTrace(mid ? x2 : x1, mid ? y1 : y2, x2, y2);
  }
  traces.count = n;
  group.add(traces);

  // Mounting holes.
  const ringGeo = new THREE.RingGeometry(1.4, 2.4, 24);
  for (const [x, y] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
    const ring = new THREE.Mesh(ringGeo, gold);
    ring.position.set(x * (W / 2 - 4), y * (H / 2 - 4), 0.02);
    group.add(ring);
  }

  const place = (mesh: T.InstancedMesh, i: number, x: number, y: number, z: number, rot: number, sc: [number, number, number]) => {
    q.setFromAxisAngle(new THREE.Vector3(0, 0, 1), rot);
    const mat = new THREE.Matrix4().compose(new THREE.Vector3(x, y, z), q.clone(), new THREE.Vector3(...sc));
    mesh.setMatrixAt(i, mat);
    parts.push({ mesh, index: i, z, delay: rand(), matrix: mat });
  };

  const box = new THREE.BoxGeometry(1, 1, 1);
  // ICs.
  const icMat = new THREE.MeshStandardMaterial({ color: 0x1a1d22, roughness: 0.6, metalness: 0.1 });
  const ics = new THREE.InstancedMesh(box, icMat, 4);
  const icSpots: Array<[number, number, number, number]> = [
    [-W * 0.18, H * 0.12, 14, 14],
    [W * 0.2, H * 0.18, 10, 6],
    [W * 0.24, -H * 0.2, 7, 7],
    [-W * 0.3, -H * 0.24, 9, 5],
  ];
  icSpots.forEach(([x, y, w, h], i) => place(ics, i, x, y, 0.9, 0, [w, h, 1.8]));
  group.add(ics);

  // IC pins (silver) along the long sides of each IC.
  const pinMat = new THREE.MeshStandardMaterial({ color: 0xc9ced6, roughness: 0.3, metalness: 0.9 });
  const pins = new THREE.InstancedMesh(box, pinMat, 160);
  let pn = 0;
  for (const [x, y, w, h] of icSpots) {
    const count = Math.max(3, Math.floor(w / 1.3));
    for (let k = 0; k < count && pn < 158; k++) {
      const px = x - w / 2 + (k + 0.5) * (w / count);
      for (const side of [-1, 1]) {
        m.compose(v.set(px, y + side * (h / 2 + 0.6), 0.25), new THREE.Quaternion(), s.set(0.45, 1.3, 0.35));
        pins.setMatrixAt(pn++, m);
      }
    }
  }
  pins.count = pn;
  group.add(pins);

  // SMD resistors and capacitors.
  const chipCount = 26;
  const resMat = new THREE.MeshStandardMaterial({ color: 0x23262b, roughness: 0.5 });
  const capMat = new THREE.MeshStandardMaterial({ color: 0xb98a5a, roughness: 0.6 });
  const res = new THREE.InstancedMesh(box, resMat, chipCount);
  const caps = new THREE.InstancedMesh(box, capMat, chipCount);
  let ri = 0;
  let ci = 0;
  for (let i = 0; i < chipCount * 2; i++) {
    const x = (rand() - 0.5) * W * 0.86;
    const y = (rand() - 0.5) * H * 0.86;
    if (icSpots.some(([ix, iy, w, h]) => Math.abs(x - ix) < w / 2 + 2.5 && Math.abs(y - iy) < h / 2 + 2.5)) continue;
    const rot = rand() > 0.5 ? 0 : Math.PI / 2;
    if (rand() > 0.5 && ri < chipCount) place(res, ri++, x, y, 0.35, rot, [2.4, 1.25, 0.7]);
    else if (ci < chipCount) place(caps, ci++, x, y, 0.45, rot, [2.0, 1.25, 0.9]);
  }
  res.count = ri;
  caps.count = ci;
  group.add(res, caps);

  // Header connector and an electrolytic capacitor.
  const hdr = new THREE.InstancedMesh(box, new THREE.MeshStandardMaterial({ color: 0x111316, roughness: 0.7 }), 1);
  place(hdr, 0, 0, -H / 2 + 4, 1.25, 0, [W * 0.36, 2.6, 2.5]);
  group.add(hdr);
  const elec = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.5, 0.5, 1, 28).rotateX(Math.PI / 2), new THREE.MeshStandardMaterial({ color: 0x2b4fa8, roughness: 0.35, metalness: 0.2 }), 2);
  place(elec, 0, W * 0.36, H * 0.28, 3, 0, [6.3, 6.3, 6]);
  place(elec, 1, -W * 0.38, H * 0.3, 2.2, 0, [4.4, 4.4, 4.4]);
  group.add(elec);

  return { group, parts, size: [W, H] };
}

/** Standard three-point lighting for small product shots. */
export function addStudioLights(THREE: typeof T, scene: T.Scene, span: number) {
  scene.add(new THREE.HemisphereLight(0xdfe8ff, 0x1a2233, 1.1));
  const key = new THREE.DirectionalLight(0xffffff, 2.2);
  key.position.set(-span, -span * 0.8, span * 1.6);
  const rim = new THREE.DirectionalLight(0x8fb4ff, 1.1);
  rim.position.set(span, span, span * 0.6);
  scene.add(key, rim);
}
