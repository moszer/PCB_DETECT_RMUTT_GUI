"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import type * as T from "three";
import { Box, Home, RotateCcw } from "lucide-react";
import type { CustomPointRequest, MachineState, Verdict } from "@/types";
import { fovMm, pictureQuad, type StageCal } from "@/lib/three/boardMap";
import { getStageCal } from "@/lib/three/calibration";
import { addBoardSurface, makeLabel, makePin, surfaceBounds, type SurfaceItem } from "@/lib/three/boardSurface";
import { MACHINE, MACHINE_PARTS, loadMachine, type MachineGroup } from "@/lib/three/models";
import { createThreeStage, disposeObject, type ThreeStage } from "@/lib/three/stage";
import { cx } from "../ui";

export type PointStatus = Verdict | "pending" | "error";

/**
 * The CAD is real millimetres; positions from the controller are commanded mm. On this station
 * one commanded mm moves the gantry about 4.7 mm (38 mm commanded ≈ the ~180 mm the rails
 * allow), so the twin draws commanded mm that much larger. Pictures, points and the camera's
 * view are all in commanded mm, so they line up with each other exactly.
 */
const REAL_MM_PER_CMD = 4.7;

const STATUS_COLOR: Record<PointStatus, number> = {
  PASS: 0x22c55e,
  FAIL: 0xef4444,
  REVIEW: 0xf59e0b,
  ERROR: 0x8b5cf6,
  error: 0x8b5cf6,
  pending: 0x94a3b8,
};
const STATUS_LABEL: Record<PointStatus, string> = { PASS: "ผ่าน", FAIL: "ไม่ผ่าน", REVIEW: "ตรวจซ้ำ", ERROR: "ผิดพลาด", error: "ผิดพลาด", pending: "ยังไม่ตรวจ" };

type Covers = "ghost" | "hidden";

interface TwinProps {
  machine: MachineState | null;
  points: CustomPointRequest[];
  statuses: Array<PointStatus | null>;
  scanningIndex: number | null;
  selected: number | null;
  zoom: number;
  cameraResolution: [number, number] | null | undefined;
  onPickPoint?: (index: number) => void;
  className?: string;
}

type Latest = Omit<TwinProps, "className"> & { covers: Covers };

interface TwinApi {
  setPosition: (p: [number, number]) => void;
  setPins: (statuses: Array<PointStatus | null>, selected: number | null, scanning: number | null) => void;
  setHoming: (on: boolean) => void;
  setFov: (zoom: number) => void;
  setCovers: (c: Covers) => void;
  resetView: () => void;
}

/** A board's points as a signature: the scene is rebuilt only when places or pictures change. */
function signature(points: CustomPointRequest[], limits: [number, number] | undefined) {
  return JSON.stringify([limits, points.map((p) => [p.x_mm, p.y_mm, p.zoom, p.reference_image?.length ?? 0, p.reference_image?.slice(-24) ?? ""])]);
}

/**
 * Digital twin of the station from its CAD: frame, Y rails, the gantry (cross rail, sliders,
 * drive covers) and the camera head moving to the live position over the board, which lies on
 * the base with each point's taught picture. Scan points are pins coloured by their latest
 * result (the one being scanned blinks), with the scan path, the camera's view on the board and
 * the head lighting up while homing. Drawn only when something moves.
 */
export function StageTwin3D({ machine, points, statuses, scanningIndex, selected, zoom, cameraResolution, onPickPoint, className }: TwinProps) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<TwinApi | null>(null);
  const [cal, setCal] = useState<StageCal | null | undefined>(undefined);
  const [failed, setFailed] = useState(false);
  const [covers, setCovers] = useState<Covers>("ghost");
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null);
  const limits = machine?.soft_limits_mm;
  const sig = useMemo(() => signature(points, limits), [points, limits]);
  const homing = Boolean(machine?.connected && machine.is_moving && !machine.homed);
  const latest = useRef<Latest>({ machine, points, statuses, scanningIndex, selected, zoom, cameraResolution, onPickPoint, covers });
  useEffect(() => {
    latest.current = { machine, points, statuses, scanningIndex, selected, zoom, cameraResolution, onPickPoint, covers };
  });

  useEffect(() => {
    let alive = true;
    void getStageCal().then((c) => alive && setCal(c));
    return () => {
      alive = false;
    };
  }, []);

  // Build (or rebuild when the board changes).
  useEffect(() => {
    const el = host.current;
    if (!el || cal === undefined) return;
    let disposed = false;
    let stage: ThreeStage | null = null;
    void (async () => {
      stage = await createThreeStage(el, { controls: true, fov: 34 });
      if (!stage) return setFailed(true);
      if (disposed) return stage.dispose();
      const model = await loadMachine();
      if (disposed) return;
      view.current = buildTwin(stage, model, cal, latest, setHover);
    })();
    return () => {
      disposed = true;
      view.current = null;
      stage?.dispose();
    };
  }, [cal, sig]);

  const pos = machine?.position_mm;
  useEffect(() => {
    if (pos) view.current?.setPosition(pos);
  }, [pos]);
  useEffect(() => {
    view.current?.setPins(statuses, selected, scanningIndex);
  }, [statuses, selected, scanningIndex]);
  useEffect(() => {
    view.current?.setHoming(homing);
  }, [homing]);
  useEffect(() => {
    view.current?.setFov(zoom);
  }, [zoom]);
  useEffect(() => {
    view.current?.setCovers(covers);
  }, [covers]);

  const counts = useMemo(() => {
    const c = { PASS: 0, FAIL: 0, REVIEW: 0 } as Record<string, number>;
    for (const s of statuses) if (s && s in c) c[s]++;
    return c;
  }, [statuses]);

  return (
    <div className={cx("relative rounded-xl overflow-hidden border border-line bg-viewport", className)}>
      <div ref={host} className="absolute inset-0 cursor-grab active:cursor-grabbing" />
      {failed && <p className="absolute inset-0 grid place-items-center text-sm text-white/60">เบราว์เซอร์นี้แสดง 3D (WebGL) ไม่ได้</p>}
      {hover && (
        <div className="absolute z-10 pointer-events-none px-2 py-1 rounded-md bg-black/80 text-[11px] text-white whitespace-pre" style={{ left: hover.x + 12, top: hover.y + 12 }}>
          {hover.text}
        </div>
      )}
      <div className="absolute top-2 left-2 flex flex-col gap-1 pointer-events-none">
        <span className="h-6 px-2 rounded-md bg-black/60 text-[11px] text-white flex items-center gap-1.5 font-mono tabular-nums">
          {machine?.connected ? `X ${machine.position_mm[0].toFixed(2)} · Y ${machine.position_mm[1].toFixed(2)} mm` : "สเตจยังไม่เชื่อมต่อ"}
        </span>
        {homing && (
          <span className="h-6 px-2 rounded-md bg-review text-[11px] font-semibold text-black flex items-center gap-1 animate-pulse">
            <Home className="size-3" /> กำลัง HOME — หาลิมิตสวิตช์
          </span>
        )}
        {cal === null && <span className="h-6 px-2 rounded-md bg-black/60 text-[11px] text-white/80 flex items-center">ยังไม่ calibrate — ขนาดภาพบนบอร์ดเป็นค่าประมาณ</span>}
      </div>
      <div className="absolute bottom-2 left-2 flex items-center gap-2 h-6 px-2 rounded-md bg-black/60 text-[11px] text-white pointer-events-none">
        <Legend color="#22c55e" label={`ผ่าน ${counts.PASS}`} />
        <Legend color="#ef4444" label={`ไม่ผ่าน ${counts.FAIL}`} />
        <Legend color="#f59e0b" label={`ตรวจซ้ำ ${counts.REVIEW}`} />
        <Legend color="#94a3b8" label="ยังไม่ตรวจ" />
        <span className="hidden sm:inline text-white/60">· กดหมุดเพื่อเลือกจุด</span>
      </div>
      <div className="absolute top-2 right-2 flex gap-1">
        <button
          type="button"
          onClick={() => setCovers((c) => (c === "ghost" ? "hidden" : "ghost"))}
          className={cx("h-7 px-2 rounded-md text-white text-[11px] flex items-center gap-1 hover:bg-black/80", covers === "hidden" ? "bg-accent/80" : "bg-black/60")}
          title="ฝาครอบและแผ่นบน: โปร่งใส / ซ่อน"
        >
          <Box className="size-3.5" /> {covers === "ghost" ? "ฝาครอบโปร่ง" : "ซ่อนฝาครอบ"}
        </button>
        <button
          type="button"
          onClick={() => view.current?.resetView()}
          className="size-7 rounded-md bg-black/60 text-white grid place-items-center hover:bg-black/80"
          title="มุมมองเริ่มต้น"
        >
          <RotateCcw className="size-3.5" />
        </button>
      </div>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className="size-2 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}

/*
 * Frames: the CAD is Y-up ("web"); the scene is Z-up. The machine is turned so that
 * web (x, y, z) → scene (x, −z, y): front of the machine toward −y, height up.
 *
 * Stage positions: HOME (0, 0) is the head's place in the assembly (front left). +X moves the
 * head right, +Y moves the gantry toward the back — the way the camera image moves (the
 * stage→image matrix: +X shifts the picture left, +Y shifts it down). A board point d (stage
 * mm, see boardMap) is under the camera when the stage is at d, so it lies at
 * HOME + k·d on the base.
 */
function buildTwin(
  stage: ThreeStage,
  model: T.Object3D | null,
  cal: StageCal | null,
  props: React.RefObject<Latest>,
  setHover: (h: { x: number; y: number; text: string } | null) => void
): TwinApi {
  const init = props.current;
  const { THREE, scene, camera, controls, invalidate, canvas } = stage;
  const k = REAL_MM_PER_CMD;
  const [Lx, Ly] = init.machine?.soft_limits_mm ?? [38, 38];
  const frame: [number, number] = init.cameraResolution && init.cameraResolution[0] > 0 ? init.cameraResolution : [3840, 3840];
  const fov = fovMm(cal, frame, 1);
  const homeX = MACHINE.headX;
  const homeY = -MACHINE.headZ;
  const boardZ = MACHINE.baseTopY + 1.6;

  scene.add(new THREE.HemisphereLight(0xe6eeff, 0x202633, 1.15));
  for (const [x, y, z, power] of [
    [300, -450, 700, 1.9],
    [-500, 100, 250, 1.0],
    [150, 500, 100, 0.8],
  ]) {
    const l = new THREE.DirectionalLight(0xffffff, power);
    l.position.set(x, y, z);
    scene.add(l);
  }

  // ── the machine ──
  const machine = new THREE.Group();
  machine.rotation.x = Math.PI / 2;
  scene.add(machine);
  const moving: Array<{ node: T.Object3D; base: T.Vector3; group: MachineGroup }> = [];
  const covers: T.Material[] = [];
  const headMats: T.MeshStandardMaterial[] = [];
  const partMeshes: T.Mesh[] = [];
  if (model) {
    machine.add(model);
    model.traverse((o) => {
      const part = MACHINE_PARTS[o.name];
      if (!part) return;
      if (part.group === "gantry" || part.group === "head") moving.push({ node: o, base: o.position.clone(), group: part.group });
      o.traverse((m) => {
        const mesh = m as T.Mesh;
        if (!mesh.isMesh) return;
        const mat = (mesh.material as T.MeshStandardMaterial).clone();
        mesh.material = mat;
        mesh.userData.title = part.title;
        partMeshes.push(mesh);
        if (part.group === "enclosure" || part.group === "top") covers.push(mat);
        if (part.group === "head") headMats.push(mat);
      });
    });
  }
  const setCovers = (c: Covers) => {
    for (const m of covers) {
      m.transparent = true;
      m.opacity = 0.1;
      m.depthWrite = false;
      m.visible = c === "ghost";
    }
    invalidate();
  };
  setCovers(init.covers);

  // ── the board on the base: taught pictures, pins and the scan path ──
  const items: SurfaceItem[] = init.points.map((p) => ({ x_mm: p.x_mm, y_mm: p.y_mm, zoom: p.zoom, size: null, image: p.reference_image ?? null }));
  const b = items.length ? surfaceBounds(cal, items, fov) : { minX: 0, maxX: Lx, minY: 0, maxY: Ly };
  const board = new THREE.Group();
  board.position.set(homeX, homeY, boardZ);
  board.scale.set(k, k, 1);
  scene.add(board);
  if (items.length) addBoardSurface(stage, board, cal, items, fov, { maxSide: 384, margin: 3 });
  const span = Math.max(b.maxX - b.minX, b.maxY - b.minY) * k;

  // Where the camera can look: the travel, drawn on the base.
  const travel = new THREE.LineLoop(
    new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(homeX, homeY, MACHINE.baseTopY + 0.3),
      new THREE.Vector3(homeX + Lx * k, homeY, MACHINE.baseTopY + 0.3),
      new THREE.Vector3(homeX + Lx * k, homeY + Ly * k, MACHINE.baseTopY + 0.3),
      new THREE.Vector3(homeX, homeY + Ly * k, MACHINE.baseTopY + 0.3),
    ]),
    new THREE.LineDashedMaterial({ color: 0x64748b, dashSize: 6, gapSize: 5 })
  );
  travel.computeLineDistances();
  scene.add(travel);
  const homeMark = makeLabel(THREE, "HOME", 7);
  homeMark.position.set(homeX - 8, homeY - 8, MACHINE.baseTopY + 4);
  scene.add(homeMark);

  const pinsGroup = new THREE.Group();
  pinsGroup.position.set(homeX, homeY, boardZ);
  scene.add(pinsGroup);
  const pinH = Math.max(14, Math.min(30, (span || 100) * 0.08));
  const pins = init.points.map((p, i) => {
    const pin = makePin(THREE, pinH, STATUS_COLOR.pending);
    pin.group.position.set(p.x_mm * k, p.y_mm * k, 0);
    pin.head.userData.index = i;
    const label = makeLabel(THREE, String(i + 1), pinH * 0.42);
    label.position.set(0, 0, pinH * 1.5);
    pin.group.add(label);
    pinsGroup.add(pin.group);
    return pin;
  });
  if (init.points.length > 1) {
    const path = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(init.points.map((p) => new THREE.Vector3(p.x_mm * k, p.y_mm * k, 0.8))),
      new THREE.LineDashedMaterial({ color: 0xfbbf24, dashSize: 6, gapSize: 4 })
    );
    path.computeLineDistances();
    pinsGroup.add(path);
  }

  // ── the camera's view: moves with the head ──
  const camGroup = new THREE.Group();
  scene.add(camGroup);
  const setFov = (z: number) => {
    camGroup.children.forEach((c) => disposeObject(c));
    camGroup.clear();
    const { corners } = pictureQuad(cal, { x_mm: 0, y_mm: 0, zoom: z }, frame);
    const pts = corners.map(([x, y]) => new THREE.Vector3(homeX + x * k, homeY + y * k, boardZ + 0.6));
    const fill = new THREE.Mesh(
      new THREE.ShapeGeometry(new THREE.Shape(pts.map((p) => new THREE.Vector2(p.x, p.y)))),
      new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.28, depthWrite: false, side: THREE.DoubleSide })
    );
    fill.position.z = boardZ + 0.6;
    const outline = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: 0xe0f2fe }));
    const apex = new THREE.Vector3(homeX, homeY, MACHINE.lensY);
    const rays = new THREE.LineSegments(
      new THREE.BufferGeometry().setFromPoints(pts.flatMap((p) => [apex, p])),
      new THREE.LineBasicMaterial({ color: 0x93c5fd, transparent: true, opacity: 0.5 })
    );
    camGroup.add(fill, outline, rays);
    invalidate();
  };
  setFov(init.zoom);

  let blinkStop: (() => void) | null = null;
  let pinStatus: Array<PointStatus | null> = init.statuses;
  const setPins = (statuses: Array<PointStatus | null>, selected: number | null, scanning: number | null) => {
    pinStatus = statuses;
    pins.forEach((pin, i) => {
      const c = STATUS_COLOR[statuses[i] ?? "pending"] ?? STATUS_COLOR.pending;
      pin.material.color.setHex(c);
      pin.material.emissive.setHex(c);
      pin.material.emissiveIntensity = 0.25;
      pin.group.scale.setScalar(i === selected ? 1.35 : 1);
    });
    blinkStop?.();
    blinkStop = null;
    const live = scanning !== null ? pins[scanning] : undefined;
    if (live) {
      live.material.color.setHex(0x38bdf8);
      live.material.emissive.setHex(0x38bdf8);
      blinkStop = stage.animate((t) => {
        live.material.emissiveIntensity = 0.3 + 0.7 * (0.5 + 0.5 * Math.sin(t * 7));
        live.group.scale.setScalar(1.25 + 0.15 * Math.sin(t * 7));
      });
    }
    invalidate();
  };
  setPins(init.statuses, init.selected, init.scanningIndex);

  // ── live position, eased ──
  const target = new THREE.Vector2(...(init.machine?.position_mm ?? [0, 0]));
  const now = target.clone();
  const apply = () => {
    const dx = now.x * k;
    const dy = now.y * k;
    // Web offsets (the machine group turns them): +X right, +Y toward the back (−Z).
    for (const m of moving) m.node.position.set(m.base.x + (m.group === "head" ? dx : 0), m.base.y, m.base.z - dy);
    camGroup.position.set(dx, dy, 0);
  };
  apply();
  let gliding = false;
  const setPosition = (p: [number, number]) => {
    target.set(p[0], p[1]);
    if (gliding) return;
    gliding = true;
    stage.animate((_t, dt) => {
      now.lerp(target, 1 - Math.exp(-dt * 9));
      if (now.distanceTo(target) < 0.005) now.copy(target);
      apply();
      gliding = !now.equals(target);
      return gliding;
    });
  };

  let homeStop: (() => void) | null = null;
  const setHoming = (on: boolean) => {
    homeStop?.();
    homeStop = null;
    for (const m of headMats) m.emissive.setHex(on ? 0xf59e0b : 0x000000);
    if (on)
      homeStop = stage.animate((t) => {
        for (const m of headMats) m.emissiveIntensity = 0.15 + 0.6 * (0.5 + 0.5 * Math.sin(t * 9));
      });
    invalidate();
  };

  // ── view ──
  const center = new THREE.Vector3(homeX + (Lx * k) / 2, homeY + (Ly * k) / 2, 70);
  const reach = 520;
  const resetView = () => {
    camera.near = 2;
    camera.far = 8000;
    camera.updateProjectionMatrix();
    camera.position.set(center.x + reach * 0.55, center.y - reach * 1.05, center.z + reach * 0.8);
    controls?.target.copy(center);
    controls?.update();
    invalidate();
  };
  if (controls) {
    controls.maxPolarAngle = Math.PI * 0.6;
    controls.minDistance = 40;
    controls.maxDistance = 2400;
  }
  resetView();

  // Pins: click to select the point; hover a pin or a part for its name.
  const ray = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  const heads = pins.map((p) => p.head);
  const pick = (e: PointerEvent) => {
    const r = canvas.getBoundingClientRect();
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const pin = ray.intersectObjects(heads)[0]?.object;
    if (pin) return { r, pin, text: pinText(pin.userData.index as number) };
    const part = ray.intersectObjects(partMeshes.filter((m) => (m.material as T.Material).visible && (m.material as T.Material).opacity > 0.2))[0]?.object;
    return { r, pin: null, text: (part?.userData.title as string) ?? "" };
  };
  const pinText = (i: number) => {
    const p = props.current.points[i];
    const s = pinStatus[i] ?? "pending";
    return `จุด ${i + 1}${p?.name ? ` · ${p.name}` : ""}\n${p ? `(${p.x_mm.toFixed(2)}, ${p.y_mm.toFixed(2)}) mm · ` : ""}${STATUS_LABEL[s]}`;
  };
  let down: [number, number] | null = null;
  let last = "";
  const onDown = (e: PointerEvent) => void (down = [e.clientX, e.clientY]);
  const onUp = (e: PointerEvent) => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
    const { pin } = pick(e);
    if (pin) props.current.onPickPoint?.(pin.userData.index as number);
  };
  const onMove = (e: PointerEvent) => {
    if (e.buttons) return;
    const { r, text } = pick(e);
    if (!text) {
      if (last) setHover(null);
      last = "";
      return;
    }
    last = text;
    setHover({ x: e.clientX - r.left, y: e.clientY - r.top, text });
  };
  const onLeave = () => setHover(null);
  canvas.addEventListener("pointerdown", onDown);
  canvas.addEventListener("pointerup", onUp);
  canvas.addEventListener("pointermove", onMove);
  canvas.addEventListener("pointerleave", onLeave);
  stage.onDispose(() => {
    canvas.removeEventListener("pointerdown", onDown);
    canvas.removeEventListener("pointerup", onUp);
    canvas.removeEventListener("pointermove", onMove);
    canvas.removeEventListener("pointerleave", onLeave);
  });

  return { setPosition, setPins, setHoming, setFov, setCovers, resetView };
}
