"use client";

import type * as T from "three";
import { pictureQuad, type StageCal } from "./boardMap";
import { loadTexture, type ThreeStage } from "./stage";

/** One taught point with its reference picture (data URL or link), in stage mm. */
export interface SurfaceItem {
  x_mm: number;
  y_mm: number;
  zoom?: number;
  size: [number, number] | null;
  image: string | null;
}

export interface Bounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

export const PCB_GREEN = 0x1d5b3c;

/** Extent of every picture (or a camera view around each point without one). */
export function surfaceBounds(cal: StageCal | null, items: SurfaceItem[], fallback: [number, number]): Bounds {
  const b: Bounds = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity };
  for (const it of items) {
    const size = it.size ?? [fallback[0], fallback[1]];
    const corners = it.size ? pictureQuad(cal, it, size).corners : [[it.x_mm - fallback[0] / 2, it.y_mm - fallback[1] / 2], [it.x_mm + fallback[0] / 2, it.y_mm + fallback[1] / 2]];
    for (const [x, y] of corners) {
      b.minX = Math.min(b.minX, x);
      b.maxX = Math.max(b.maxX, x);
      b.minY = Math.min(b.minY, y);
      b.maxY = Math.max(b.maxY, y);
    }
  }
  if (!Number.isFinite(b.minX)) return { minX: -10, maxX: 10, minY: -10, maxY: 10 };
  return b;
}

/** A quad through four board points (TL, TR, BR, BL) with the picture's UVs (top row = v 0). */
export function quadGeometry(THREE: typeof T, corners: [number, number][], z: number) {
  const g = new THREE.BufferGeometry();
  const [tl, tr, br, bl] = corners;
  g.setAttribute("position", new THREE.Float32BufferAttribute([...tl, z, ...tr, z, ...br, z, ...bl, z], 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute([0, 0, 1, 0, 1, 1, 0, 1], 2));
  g.setAttribute("normal", new THREE.Float32BufferAttribute([0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1], 3));
  // Wound so the face points up whichever way the matrix turns the picture.
  const cross = (tr[0] - tl[0]) * (bl[1] - tl[1]) - (tr[1] - tl[1]) * (bl[0] - tl[0]);
  g.setIndex(cross < 0 ? [0, 3, 1, 1, 3, 2] : [0, 1, 3, 1, 2, 3]);
  return g;
}

/**
 * The board: a green plate under all pictures, each point's picture laid at its place
 * (loaded in the background, small), and a thin outline per picture. Returns the plate's
 * bounds; `group` gets everything.
 */
export function addBoardSurface(stage: ThreeStage, group: T.Group, cal: StageCal | null, items: SurfaceItem[], fallback: [number, number], opts: { margin?: number; maxSide?: number; outline?: number } = {}) {
  const { THREE } = stage;
  const b = surfaceBounds(cal, items, fallback);
  const m = opts.margin ?? Math.max(2, 0.06 * Math.max(b.maxX - b.minX, b.maxY - b.minY));
  const W = b.maxX - b.minX + 2 * m;
  const H = b.maxY - b.minY + 2 * m;
  const plate = new THREE.Mesh(
    new THREE.BoxGeometry(W, H, 1.6),
    new THREE.MeshStandardMaterial({ color: PCB_GREEN, roughness: 0.75, metalness: 0.05 })
  );
  plate.position.set((b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2, -0.8);
  group.add(plate);

  let alive = true;
  stage.onDispose(() => {
    alive = false;
  });
  items.forEach((it, i) => {
    const z = 0.02 + i * 0.004;
    // Only the picture's aspect matters (px per mm scales with its height), so a picture of
    // unknown size is placed once decoded.
    const outline = (size: [number, number]) => {
      const { corners } = pictureQuad(cal, it, size);
      group.add(
        new THREE.LineLoop(
          new THREE.BufferGeometry().setFromPoints(corners.map(([x, y]) => new THREE.Vector3(x, y, z + 0.01))),
          new THREE.LineBasicMaterial({ color: opts.outline ?? 0x9fb4c8, transparent: true, opacity: 0.55 })
        )
      );
      return corners;
    };
    if (!it.image) {
      if (it.size) outline(it.size);
      return;
    }
    void loadTexture(THREE, it.image, opts.maxSide ?? 512).then((tex) => {
      if (!tex) return;
      if (!alive) return tex.dispose();
      const img = tex.image as { width: number; height: number };
      const corners = outline(it.size ?? [img.width, img.height]);
      const mesh = new THREE.Mesh(quadGeometry(THREE, corners, z), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.9, metalness: 0 }));
      mesh.renderOrder = i;
      group.add(mesh);
      stage.invalidate();
    });
  });
  return { bounds: b, size: [W, H] as [number, number], center: [(b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2] as [number, number] };
}

/** A map pin (stem + head) whose head colour can be changed through `material`. */
export function makePin(THREE: typeof T, height: number, color: T.ColorRepresentation) {
  const g = new THREE.Group();
  const material = new THREE.MeshStandardMaterial({ color, roughness: 0.35, metalness: 0.1, emissive: color, emissiveIntensity: 0.25 });
  const head = new THREE.Mesh(new THREE.SphereGeometry(height * 0.22, 20, 14), material);
  head.position.z = height;
  const stem = new THREE.Mesh(
    new THREE.CylinderGeometry(height * 0.035, height * 0.01, height, 8),
    new THREE.MeshStandardMaterial({ color: 0xd8dee8, roughness: 0.4, metalness: 0.6 })
  );
  stem.rotation.x = Math.PI / 2;
  stem.position.z = height / 2;
  g.add(head, stem);
  return { group: g, head, material };
}

/** A text label drawn on a canvas, as a sprite that always faces the camera. */
export function makeLabel(THREE: typeof T, text: string, height: number, opts: { color?: string; background?: string } = {}) {
  const fontPx = 44;
  const c = document.createElement("canvas");
  const ctx = c.getContext("2d")!;
  ctx.font = `600 ${fontPx}px "IBM Plex Sans Thai", "Noto Sans Thai", system-ui, sans-serif`;
  const w = Math.ceil(ctx.measureText(text).width) + 28;
  c.width = w;
  c.height = fontPx + 22;
  ctx.font = `600 ${fontPx}px "IBM Plex Sans Thai", "Noto Sans Thai", system-ui, sans-serif`;
  ctx.fillStyle = opts.background ?? "rgba(15,23,42,0.78)";
  ctx.beginPath();
  ctx.roundRect(0, 0, c.width, c.height, 14);
  ctx.fill();
  ctx.fillStyle = opts.color ?? "#ffffff";
  ctx.textBaseline = "middle";
  ctx.fillText(text, 14, c.height / 2 + 2);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
  sprite.scale.set((height * c.width) / c.height, height, 1);
  sprite.renderOrder = 999;
  return sprite;
}
