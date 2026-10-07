"use client";

import React, { useEffect, useRef, useState } from "react";
import type * as T from "three";
import { RotateCcw } from "lucide-react";
import type { StageMapNode, StageMapResult } from "@/types";
import { makeLabel } from "@/lib/three/boardSurface";
import { createThreeStage, goodBadColor, type ThreeStage } from "@/lib/three/stage";
import { cx } from "../ui";

/** Errors up to this are green; the colour scale stretches further only for worse rails. */
export const RAIL_GOOD_UM = 20;

export function nodeText(n: StageMapNode) {
  if (!n.measured || !n.err_mm) return `(${n.x_mm.toFixed(1)}, ${n.y_mm.toFixed(1)}) mm\nวัดไม่ได้`;
  const lines = [
    `(${n.x_mm.toFixed(1)}, ${n.y_mm.toFixed(1)}) mm`,
    `คลาดเคลื่อน ${n.err_um} µm (X ${Math.round(n.err_mm[0] * 1000)} · Y ${Math.round(n.err_mm[1] * 1000)})`,
  ];
  if (n.backlash_mm) lines.push(`backlash X ${Math.round(n.backlash_mm[0] * 1000)} · Y ${Math.round(n.backlash_mm[1] * 1000)} µm`);
  if (n.scale_x_pct !== null || n.scale_y_pct !== null)
    lines.push(`ระยะเดินจริง X ${n.scale_x_pct !== null ? `${n.scale_x_pct > 0 ? "+" : ""}${n.scale_x_pct.toFixed(2)}%` : "–"} · Y ${n.scale_y_pct !== null ? `${n.scale_y_pct > 0 ? "+" : ""}${n.scale_y_pct.toFixed(2)}%` : "–"}`);
  return lines.join("\n");
}

/**
 * The whole-travel accuracy map as a surface over the stage's X/Y: height and colour are how
 * far the stage really stops from where it was told (after the best straight-line fit), with an
 * arrow per node pointing the way it is off. Hover a node for its numbers.
 */
export function RailMap3D({ map, className }: { map: StageMapResult; className?: string }) {
  const host = useRef<HTMLDivElement>(null);
  const reset = useRef<(() => void) | null>(null);
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let disposed = false;
    let stage: ThreeStage | null = null;
    void createThreeStage(el, { controls: true, fov: 34 }).then((s) => {
      if (!s) return setFailed(true);
      if (disposed) return s.dispose();
      stage = s;
      reset.current = buildMap(s, map, setHover);
    });
    return () => {
      disposed = true;
      stage?.dispose();
    };
  }, [map]);

  const worst = Math.max(RAIL_GOOD_UM * 2, map.max_um ?? 0);
  return (
    <div className={cx("relative rounded-xl overflow-hidden bg-viewport", className)}>
      <div ref={host} className="absolute inset-0 cursor-grab active:cursor-grabbing" />
      {failed && <p className="absolute inset-0 grid place-items-center text-sm text-white/60">เบราว์เซอร์นี้แสดง 3D (WebGL) ไม่ได้</p>}
      {hover && (
        <div className="absolute z-10 pointer-events-none px-2 py-1 rounded-md bg-black/80 text-[11px] text-white whitespace-pre font-mono" style={{ left: hover.x + 12, top: hover.y + 12 }}>
          {hover.text}
        </div>
      )}
      <div className="absolute bottom-2 left-2 flex items-center gap-2 px-2 py-1 rounded-md bg-black/60 text-[11px] text-white pointer-events-none">
        <span>0</span>
        <span className="h-2 w-20 rounded-full" style={{ background: "linear-gradient(to right, #22c55e, #f5b82e, #f43f2a)" }} />
        <span>{Math.round(worst)} µm</span>
        <span className="text-white/60">· ความสูงขยายให้เห็น · ลูกศร = ทิศที่คลาด</span>
      </div>
      <button
        type="button"
        onClick={() => reset.current?.()}
        className="absolute top-2 right-2 size-7 rounded-md bg-black/60 text-white grid place-items-center hover:bg-black/80"
        title="มุมมองเริ่มต้น"
      >
        <RotateCcw className="size-3.5" />
      </button>
    </div>
  );
}

function buildMap(stage: ThreeStage, map: StageMapResult, setHover: (h: { x: number; y: number; text: string } | null) => void) {
  const { THREE, scene, camera, controls, invalidate, canvas } = stage;
  const [cols, rows] = map.grid;
  const xs = map.xs;
  const ys = map.ys;
  const spanX = (xs[xs.length - 1] ?? 1) - (xs[0] ?? 0) || 1;
  const spanY = (ys[ys.length - 1] ?? 1) - (ys[0] ?? 0) || 1;
  const span = Math.max(spanX, spanY);
  const cx0 = (xs[0] + xs[xs.length - 1]) / 2;
  const cy0 = (ys[0] + ys[ys.length - 1]) / 2;
  const worst = Math.max(RAIL_GOOD_UM * 2, map.max_um ?? 0);
  const zPerUm = (span * 0.28) / worst;

  const grid: (StageMapNode | undefined)[] = new Array(cols * rows);
  for (const n of map.nodes) grid[n.row * cols + n.col] = n;

  // ── surface ──
  const pos = new Float32Array(cols * rows * 3);
  const col = new Float32Array(cols * rows * 3);
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const i = r * cols + c;
      const n = grid[i];
      const z = n?.err_um !== null && n?.err_um !== undefined ? n.err_um * zPerUm : 0;
      pos.set([xs[c] - cx0, ys[r] - cy0, z], i * 3);
      const color = n?.measured ? goodBadColor(THREE, (n.err_um ?? 0) / worst) : new THREE.Color(0x475569);
      col.set([color.r, color.g, color.b], i * 3);
    }
  }
  const index: number[] = [];
  for (let r = 0; r < rows - 1; r++) {
    for (let c = 0; c < cols - 1; c++) {
      const a = r * cols + c;
      index.push(a, a + 1, a + cols, a + 1, a + cols + 1, a + cols);
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
  geo.setIndex(index);
  geo.computeVertexNormals();
  const surface = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.55, metalness: 0.05, side: THREE.DoubleSide, transparent: true, opacity: 0.92 }));
  scene.add(surface);
  scene.add(new THREE.LineSegments(new THREE.WireframeGeometry(geo), new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.18 })));

  // Floor: the travel area with a 5 mm grid, and axis names.
  const floor = new THREE.GridHelper(Math.ceil(span / 5) * 5 + 10, Math.ceil(span / 5) + 2, 0x64748b, 0x334155);
  floor.rotation.x = Math.PI / 2;
  floor.position.z = -0.2;
  scene.add(floor);
  const lx = makeLabel(THREE, "X (mm)", span * 0.045);
  lx.position.set(spanX / 2 + span * 0.12, -spanY / 2, 0);
  const ly = makeLabel(THREE, "Y (mm)", span * 0.045);
  ly.position.set(-spanX / 2, spanY / 2 + span * 0.1, 0);
  scene.add(lx, ly);

  // ── nodes: a dot on the surface, a stem to the floor, an arrow for the error direction ──
  const dotGeo = new THREE.SphereGeometry(span * 0.012, 14, 10);
  const dots: T.Mesh[] = [];
  const stems: number[] = [];
  const arrowLen = span * 0.07;
  for (let i = 0; i < grid.length; i++) {
    const n = grid[i];
    if (!n) continue;
    const x = pos[i * 3];
    const y = pos[i * 3 + 1];
    const z = pos[i * 3 + 2];
    const color = n.measured ? goodBadColor(THREE, (n.err_um ?? 0) / worst) : new THREE.Color(0x64748b);
    const dot = new THREE.Mesh(dotGeo, new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.35 }));
    dot.position.set(x, y, z);
    dot.userData.text = nodeText(n);
    dots.push(dot);
    scene.add(dot);
    stems.push(x, y, 0, x, y, z);
    if (n.err_mm && n.err_um) {
      const dir = new THREE.Vector3(n.err_mm[0], n.err_mm[1], 0).normalize();
      const len = arrowLen * Math.min(1.6, 0.4 + n.err_um / worst);
      scene.add(new THREE.ArrowHelper(dir, new THREE.Vector3(x, y, z + span * 0.004), len, 0xffffff, len * 0.35, len * 0.22));
    }
  }
  scene.add(new THREE.LineSegments(new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(stems, 3)), new THREE.LineBasicMaterial({ color: 0x94a3b8, transparent: true, opacity: 0.5 })));

  scene.add(new THREE.HemisphereLight(0xe6eeff, 0x202633, 1.2));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(-span, -span, span * 2);
  scene.add(sun);

  const resetView = () => {
    camera.near = span / 100;
    camera.far = span * 40;
    camera.updateProjectionMatrix();
    camera.position.set(span * 0.5, -span * 1.25, span * 0.95);
    controls?.target.set(0, 0, span * 0.06);
    controls?.update();
    invalidate();
  };
  if (controls) {
    controls.minDistance = span * 0.3;
    controls.maxDistance = span * 6;
  }
  resetView();

  const ray = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  let last = "";
  const onMove = (e: PointerEvent) => {
    if (e.buttons) return;
    const r = canvas.getBoundingClientRect();
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const text = (ray.intersectObjects(dots)[0]?.object.userData.text as string) ?? "";
    if (!text) {
      if (last) setHover(null);
      last = "";
      return;
    }
    last = text;
    setHover({ x: e.clientX - r.left, y: e.clientY - r.top, text });
  };
  const onLeave = () => setHover(null);
  canvas.addEventListener("pointermove", onMove);
  canvas.addEventListener("pointerleave", onLeave);
  stage.onDispose(() => {
    canvas.removeEventListener("pointermove", onMove);
    canvas.removeEventListener("pointerleave", onLeave);
  });
  return resetView;
}
