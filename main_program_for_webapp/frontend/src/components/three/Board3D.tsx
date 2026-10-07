"use client";

import React, { useEffect, useRef, useState } from "react";
import type * as T from "three";
import { RotateCcw } from "lucide-react";
import type { BoardDetail } from "@/types";
import { api } from "@/lib/api";
import { fovMm, pictureQuad, type StageCal } from "@/lib/three/boardMap";
import { getStageCal } from "@/lib/three/calibration";
import { addBoardSurface, makeLabel, makePin, type SurfaceItem } from "@/lib/three/boardSurface";
import { createThreeStage, goodBadColor, type ThreeStage } from "@/lib/three/stage";
import { cx } from "../ui";

interface Hover {
  x: number;
  y: number;
  text: string;
}

/**
 * The board in 3D at its stage coordinates (mm): every point's taught picture where it was
 * taken, a pin per point coloured by its yield (green = always passes … red = always fails,
 * grey = never scanned), and a raised red block over every taught part that has failed — the
 * taller, the more often. Click a pin to jump to the point; hover a block for its counts.
 */
export function Board3D({ board, onPickPoint, className }: { board: BoardDetail; onPickPoint?: (index: number) => void; className?: string }) {
  const host = useRef<HTMLDivElement>(null);
  const reset = useRef<(() => void) | null>(null);
  const pick = useRef(onPickPoint);
  const [cal, setCal] = useState<StageCal | null | undefined>(undefined);
  const [hover, setHover] = useState<Hover | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    pick.current = onPickPoint;
  });

  useEffect(() => {
    let alive = true;
    void getStageCal().then((c) => alive && setCal(c));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const el = host.current;
    if (!el || cal === undefined) return;
    let disposed = false;
    let stage: ThreeStage | null = null;
    void createThreeStage(el, { controls: true, fov: 32 }).then((s) => {
      if (!s) return setFailed(true);
      if (disposed) return s.dispose();
      stage = s;
      reset.current = buildBoard(s, board, cal, (i) => pick.current?.(i), setHover);
    });
    return () => {
      disposed = true;
      reset.current = null;
      stage?.dispose();
    };
  }, [board, cal]);

  const scanned = Object.keys(board.history.point_stats ?? {}).length > 0;
  return (
    <div className={cx("relative rounded-xl overflow-hidden bg-viewport", className)}>
      <div ref={host} className="absolute inset-0 cursor-grab active:cursor-grabbing" />
      {failed && <p className="absolute inset-0 grid place-items-center text-sm text-white/60">เบราว์เซอร์นี้แสดง 3D (WebGL) ไม่ได้</p>}
      {hover && (
        <div className="absolute z-10 pointer-events-none px-2 py-1 rounded-md bg-black/80 text-[11px] text-white whitespace-pre" style={{ left: hover.x + 12, top: hover.y + 12 }}>
          {hover.text}
        </div>
      )}
      <div className="absolute bottom-2 left-2 flex flex-wrap items-center gap-x-3 gap-y-1 px-2 py-1 rounded-md bg-black/60 text-[11px] text-white pointer-events-none max-w-[calc(100%-1rem)]">
        <span className="flex items-center gap-1.5">
          หมุด = yield ของจุด
          <span className="h-2 w-16 rounded-full" style={{ background: "linear-gradient(to right, #22c55e, #f5b82e, #f43f2a)" }} />
          <span className="text-white/70">100% → 0%</span>
        </span>
        <span className="flex items-center gap-1">
          <span className="size-2 rounded-sm bg-[#ef4444]" /> ชิ้นที่เคยผิด (สูง = ผิดบ่อย)
        </span>
        {!scanned && <span className="text-white/70">ยังไม่เคยสแกน — หมุดเป็นสีเทา</span>}
        {cal === null && <span className="text-white/70">ยังไม่ calibrate: ตำแหน่งภาพเป็นค่าประมาณ</span>}
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

function buildBoard(stage: ThreeStage, board: BoardDetail, cal: StageCal | null, onPick: (i: number) => void, setHover: (h: Hover | null) => void) {
  const { THREE, scene, camera, controls, invalidate, canvas } = stage;
  const fallback = fovMm(cal, [16, 9]);
  const items: SurfaceItem[] = board.points.map((p) => ({
    x_mm: p.x_mm,
    y_mm: p.y_mm,
    zoom: p.zoom,
    size: p.reference_size,
    image: p.has_reference ? api.boards.thumb(board.id, p.index, 480, board.updated_at, false) : null,
  }));
  const group = new THREE.Group();
  scene.add(group);
  const surface = addBoardSurface(stage, group, cal, items, fallback, { maxSide: 480 });
  const [W, H] = surface.size;
  const span = Math.max(W, H);

  scene.add(new THREE.HemisphereLight(0xe6eeff, 0x202633, 1.2));
  const sun = new THREE.DirectionalLight(0xffffff, 1.8);
  sun.position.set(-span, -span, span * 2);
  scene.add(sun);

  // ── yield pins ──
  const stats = board.history.point_stats ?? {};
  const pinH = span * 0.07;
  const heads: T.Mesh[] = [];
  board.points.forEach((p) => {
    const st = stats[p.id];
    const y = st && st.scans ? st.pass / st.scans : null;
    const color = y === null ? new THREE.Color(0x94a3b8) : goodBadColor(THREE, 1 - y);
    const pin = makePin(THREE, pinH, color);
    pin.group.position.set(p.x_mm, p.y_mm, 0);
    pin.head.userData = { index: p.index, text: `${p.index + 1}. ${p.name}\n${st ? `ผ่าน ${st.pass}/${st.scans} รอบ (${Math.round((y ?? 0) * 100)}%)` : "ยังไม่เคยสแกน"}` };
    heads.push(pin.head);
    const label = makeLabel(THREE, y === null ? `${p.index + 1}` : `${p.index + 1} · ${Math.round(y * 100)}%`, pinH * 0.36);
    label.position.set(0, 0, pinH * 1.45);
    pin.group.add(label);
    group.add(pin.group);
  });

  // ── failure heatmap: a block over every part that has failed ──
  const fails = board.history.part_fails ?? [];
  const most = Math.max(1, ...fails.map((f) => f.missing + f.wrong));
  const blocks: T.Mesh[] = [];
  const blockGeo = new THREE.BoxGeometry(1, 1, 1);
  blockGeo.translate(0, 0, 0.5);
  const spotGeo = new THREE.PlaneGeometry(2, 2);
  const spotTex = radialTexture(THREE);
  for (const f of fails) {
    const p = board.points.find((q) => q.id === f.point_id);
    const part = p?.parts?.find((c) => c.id === f.part_id);
    if (!p || !part || !p.reference_size) continue;
    const [w, h] = p.reference_size;
    const { at } = pictureQuad(cal, p, p.reference_size);
    const [x1, y1, x2, y2] = part.bbox;
    const c = [at(x1 * w, y1 * h), at(x2 * w, y1 * h), at(x2 * w, y2 * h), at(x1 * w, y2 * h)];
    const xs = c.map((v) => v[0]);
    const ys = c.map((v) => v[1]);
    const n = f.missing + f.wrong;
    const t = n / most;
    const mesh = new THREE.Mesh(
      blockGeo,
      new THREE.MeshStandardMaterial({ color: goodBadColor(THREE, 0.55 + 0.45 * t), transparent: true, opacity: 0.55 + 0.3 * t, roughness: 0.5, emissive: 0x7f1d1d, emissiveIntensity: 0.25 })
    );
    // Small parts (an 0402 resistor is well under a millimetre here) still get a visible block.
    const minSide = span * 0.012;
    const mx = (Math.max(...xs) + Math.min(...xs)) / 2;
    const my = (Math.max(...ys) + Math.min(...ys)) / 2;
    mesh.scale.set(Math.max(minSide, Math.max(...xs) - Math.min(...xs)), Math.max(minSide, Math.max(...ys) - Math.min(...ys)), span * (0.02 + 0.1 * t));
    mesh.position.set(mx, my, 0.05);
    // A glowing spot around it: the heatmap seen from above.
    const spot = new THREE.Mesh(
      spotGeo,
      new THREE.MeshBasicMaterial({ map: spotTex, color: 0xff3b30, transparent: true, opacity: 0.45 + 0.45 * t, depthWrite: false, blending: THREE.AdditiveBlending })
    );
    const r = span * (0.03 + 0.05 * t);
    spot.scale.set(r, r, 1);
    spot.position.set(mx, my, 0.3);
    group.add(spot);
    mesh.userData = {
      index: p.index,
      text: `${part.name} (${part.id}) · จุด ${p.index + 1}\nผิด ${n} ครั้ง: ขาด ${f.missing} · ผิดชนิด ${f.wrong}`,
    };
    blocks.push(mesh);
    group.add(mesh);
  }

  // ── view ──
  const [cx0, cy0] = surface.center;
  const resetView = () => {
    camera.near = span / 200;
    camera.far = span * 30;
    camera.updateProjectionMatrix();
    camera.position.set(cx0 + span * 0.15, cy0 - span * 0.95, span * 1.05);
    controls?.target.set(cx0, cy0, 0);
    controls?.update();
    invalidate();
  };
  if (controls) {
    controls.maxPolarAngle = Math.PI * 0.49;
    controls.minDistance = span * 0.15;
    controls.maxDistance = span * 5;
  }
  resetView();

  // ── pointer: hover text, click a pin or block to go to its point ──
  const ray = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  const targets = [...heads, ...blocks];
  const hit = (e: PointerEvent) => {
    const r = canvas.getBoundingClientRect();
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    return { obj: ray.intersectObjects(targets)[0]?.object, r };
  };
  let down: [number, number] | null = null;
  let last = "";
  const onMove = (e: PointerEvent) => {
    if (e.buttons) return;
    const { obj, r } = hit(e);
    const text = (obj?.userData.text as string) ?? "";
    if (!text) {
      if (last) setHover(null);
      last = "";
      canvas.style.cursor = "";
      return;
    }
    last = text;
    canvas.style.cursor = "pointer";
    setHover({ x: e.clientX - r.left, y: e.clientY - r.top, text });
  };
  const onDown = (e: PointerEvent) => void (down = [e.clientX, e.clientY]);
  const onUp = (e: PointerEvent) => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
    const { obj } = hit(e);
    if (obj) onPick(obj.userData.index as number);
  };
  const onLeave = () => setHover(null);
  canvas.addEventListener("pointermove", onMove);
  canvas.addEventListener("pointerdown", onDown);
  canvas.addEventListener("pointerup", onUp);
  canvas.addEventListener("pointerleave", onLeave);
  stage.onDispose(() => {
    canvas.removeEventListener("pointermove", onMove);
    canvas.removeEventListener("pointerdown", onDown);
    canvas.removeEventListener("pointerup", onUp);
    canvas.removeEventListener("pointerleave", onLeave);
  });
  return resetView;
}

/** A soft round spot (white centre fading to clear) for the heatmap glow. */
function radialTexture(THREE: typeof T) {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const ctx = c.getContext("2d")!;
  const g = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.4, "rgba(255,255,255,0.55)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(c);
}
