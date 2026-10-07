"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import type * as T from "three";
import { Home, RotateCcw } from "lucide-react";
import type { CustomPointRequest, MachineState, Verdict } from "@/types";
import { fovMm, pictureQuad, type StageCal } from "@/lib/three/boardMap";
import { getStageCal } from "@/lib/three/calibration";
import { addBoardSurface, makeLabel, makePin, surfaceBounds, type SurfaceItem } from "@/lib/three/boardSurface";
import { loadStageParts } from "@/lib/three/models";
import { createThreeStage, disposeObject, type ThreeStage } from "@/lib/three/stage";
import { cx } from "../ui";

export type PointStatus = Verdict | "pending" | "error";

/**
 * The CAD parts are real millimetres; positions from the controller are commanded mm. On this
 * station one commanded mm moves the rack-and-pinion about 4.7 mm (38 mm commanded ≈ the
 * rail's ~180 mm of travel), so the twin draws commanded mm that much larger. Pictures, points
 * and the camera's view are all in commanded mm, so they line up with each other exactly.
 */
const REAL_MM_PER_CMD = 4.7;
const CAMERA_HEIGHT = 200;

const STATUS_COLOR: Record<PointStatus, number> = {
  PASS: 0x22c55e,
  FAIL: 0xef4444,
  REVIEW: 0xf59e0b,
  ERROR: 0x8b5cf6,
  error: 0x8b5cf6,
  pending: 0x94a3b8,
};

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

interface TwinApi {
  setPosition: (p: [number, number], immediate?: boolean) => void;
  setPins: (statuses: Array<PointStatus | null>, selected: number | null, scanning: number | null) => void;
  setHoming: (on: boolean) => void;
  setFov: (zoom: number) => void;
  resetView: () => void;
}

/** A board's points as a signature: the scene is rebuilt only when places or pictures change. */
function signature(points: CustomPointRequest[], limits: [number, number] | undefined) {
  return JSON.stringify([limits, points.map((p) => [p.x_mm, p.y_mm, p.zoom, p.reference_image?.length ?? 0, p.reference_image?.slice(-24) ?? ""])]);
}

/**
 * Digital twin of the XY stage: the CAD carriage, racks, pinions and mount; the board (with each
 * point's taught picture) riding on it to the live position; scan points as pins coloured by
 * their latest result (the one being scanned blinks), the scan path, the camera and its view on
 * the board, and the limit switches lighting up while homing. Drawn only when something moves.
 */
export function StageTwin3D({ machine, points, statuses, scanningIndex, selected, zoom, cameraResolution, onPickPoint, className }: TwinProps) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<TwinApi | null>(null);
  const [cal, setCal] = useState<StageCal | null | undefined>(undefined);
  const [failed, setFailed] = useState(false);
  const limits = machine?.soft_limits_mm;
  const sig = useMemo(() => signature(points, limits), [points, limits]);
  const homing = Boolean(machine?.connected && machine.is_moving && !machine.homed);
  const latest = useRef({ machine, points, statuses, scanningIndex, selected, zoom, cameraResolution, onPickPoint, homing });
  useEffect(() => {
    latest.current = { machine, points, statuses, scanningIndex, selected, zoom, cameraResolution, onPickPoint, homing };
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
      const parts = await loadStageParts(stage.THREE);
      if (disposed) return;
      view.current = buildTwin(stage, parts, cal, latest);
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

  const counts = useMemo(() => {
    const c = { PASS: 0, FAIL: 0, REVIEW: 0 } as Record<string, number>;
    for (const s of statuses) if (s && s in c) c[s]++;
    return c;
  }, [statuses]);

  return (
    <div className={cx("relative rounded-xl overflow-hidden border border-line bg-viewport", className)}>
      <div ref={host} className="absolute inset-0 cursor-grab active:cursor-grabbing" />
      {failed && <p className="absolute inset-0 grid place-items-center text-sm text-white/60">เบราว์เซอร์นี้แสดง 3D (WebGL) ไม่ได้</p>}
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
      <button
        type="button"
        onClick={() => view.current?.resetView()}
        className="absolute top-2 right-2 size-7 rounded-md bg-black/60 text-white grid place-items-center hover:bg-black/80"
        title="มุมมองเริ่มต้น"
      >
        <RotateCcw className="size-3.5" />
      </button>
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

function buildTwin(
  stage: ThreeStage,
  parts: Awaited<ReturnType<typeof loadStageParts>>,
  cal: StageCal | null,
  props: React.RefObject<{
    machine: MachineState | null;
    points: CustomPointRequest[];
    statuses: Array<PointStatus | null>;
    scanningIndex: number | null;
    selected: number | null;
    zoom: number;
    cameraResolution: [number, number] | null | undefined;
    onPickPoint?: (i: number) => void;
  }>
): TwinApi {
  const init = props.current;
  const { THREE, scene, camera, controls, invalidate } = stage;
  const k = REAL_MM_PER_CMD;
  const [Lx, Ly] = init.machine?.soft_limits_mm ?? [38, 38];
  const frame: [number, number] = init.cameraResolution && init.cameraResolution[0] > 0 ? init.cameraResolution : [3840, 3840];
  const fov = fovMm(cal, frame, 1);

  const items: SurfaceItem[] = init.points.map((p) => ({ x_mm: p.x_mm, y_mm: p.y_mm, zoom: p.zoom, size: null, image: p.reference_image ?? null }));
  // Picture sizes are only known once decoded; until then a camera view around each point.
  const b = items.length ? surfaceBounds(cal, items, fov) : { minX: -fov[0] / 2, maxX: Lx + fov[0] / 2, minY: -fov[1] / 2, maxY: Ly + fov[1] / 2 };
  const dc: [number, number] = [(b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2];

  // ── materials ──
  const alu = new THREE.MeshStandardMaterial({ color: 0xb9c2cf, metalness: 0.65, roughness: 0.35 });
  const plastic = new THREE.MeshStandardMaterial({ color: 0x3b82f6, metalness: 0.05, roughness: 0.55 });
  const dark = new THREE.MeshStandardMaterial({ color: 0x3f4654, metalness: 0.3, roughness: 0.6 });
  const nylon = new THREE.MeshStandardMaterial({ color: 0xf1f5f9, metalness: 0, roughness: 0.5 });
  const sw = new THREE.MeshStandardMaterial({ color: 0x7f1d1d, emissive: 0xef4444, emissiveIntensity: 0.15, roughness: 0.5 });

  const root = new THREE.Group();
  scene.add(root);
  scene.add(new THREE.HemisphereLight(0xe6eeff, 0x202633, 1.15));
  const sun = new THREE.DirectionalLight(0xffffff, 2.0);
  sun.position.set(-300, -400, 700);
  scene.add(sun);
  const fill = new THREE.DirectionalLight(0x9db8ff, 0.7);
  fill.position.set(400, 300, 200);
  scene.add(fill);

  // ── moving stages: X carries the Y axis, Y carries the bed and the board ──
  const xStage = new THREE.Group();
  const yStage = new THREE.Group();
  xStage.add(yStage);
  root.add(xStage);

  const board = new THREE.Group();
  board.scale.set(k, k, 1);
  yStage.add(board);
  const surface = addBoardSurface(stage, board, cal, items, fov, { maxSide: 384, margin: 3 });
  const [bw, bh] = surface.size;

  const bed = new THREE.Mesh(new THREE.BoxGeometry(bw * k + 16, bh * k + 16, 4.4), alu);
  bed.position.set(dc[0] * k, dc[1] * k, -1.6 - 2.2);
  yStage.add(bed);

  const cx0 = dc[0] * k;
  const cy0 = dc[1] * k;
  const travelX = Lx * k;
  const travelY = Ly * k;
  const yRail0 = cy0 - travelY - 40;
  const yMid = yRail0 + 125;
  const xRail0 = cx0 - travelX - 45;

  if (parts) {
    const add = (g: T.BufferGeometry, mat: T.Material, parent: T.Object3D, x: number, y: number, z: number, rz = 0) => {
      const m = new THREE.Mesh(g, mat);
      m.position.set(x, y, z);
      m.rotation.z = rz;
      parent.add(m);
      return m;
    };
    // Y axis: carriage under the bed, riding a rack rail fixed on the X carriage.
    add(parts.carriage, plastic, yStage, cx0, cy0, -16.6, Math.PI / 2);
    add(parts.rail, alu, xStage, cx0, yRail0, -29.1);
    // X axis: carriage under the Y rail, riding the X rack rail on the fixed mount.
    add(parts.carriage, plastic, xStage, cx0, yMid, -39.7);
    add(parts.rail, alu, root, xRail0, yMid, -52.2, -Math.PI / 2);
    add(parts.mount, dark, root, xRail0 + 125 - 169.5, yMid - 3.5, -80.2);
  } else {
    // No CAD file: plain bars in their place.
    const bar = (w: number, h: number, d: number, mat: T.Material, parent: T.Object3D, x: number, y: number, z: number) => {
      const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
      m.position.set(x, y, z);
      parent.add(m);
    };
    bar(33, 45, 10.6, plastic, yStage, cx0, cy0, -11.3);
    bar(28, 250, 12.5, alu, xStage, cx0, yRail0 + 125, -22.85);
    bar(45, 33, 10.6, plastic, xStage, cx0, yMid, -34.4);
    bar(250, 28, 12.5, alu, root, xRail0 + 125, yMid, -45.95);
    bar(383, 33, 23, dark, root, xRail0 + 125, yMid, -63.7);
  }

  // Pinions turn with the travel (14 teeth, ~7.2 mm pitch radius).
  const pinion = (parent: T.Object3D, x: number, y: number, z: number, axis: "x" | "y") => {
    const g = new THREE.Group();
    const m = parts ? new THREE.Mesh(parts.pinion, nylon) : new THREE.Mesh(new THREE.CylinderGeometry(7.2, 7.2, 6.5, 14).rotateX(Math.PI / 2), nylon);
    m.position.z = -3.25;
    if (axis === "y") m.rotation.x = Math.PI / 2;
    else m.rotation.y = Math.PI / 2;
    g.add(m);
    g.position.set(x, y, z);
    parent.add(g);
    return g;
  };
  const pinionX = pinion(xStage, cx0, yMid - 22, -46, "y");
  const pinionY = pinion(yStage, cx0 + 22, cy0, -22.8, "x");

  // Limit switches at the HOME end of each axis.
  const swGeo = new THREE.BoxGeometry(8, 12, 8);
  const swX = new THREE.Mesh(swGeo, sw);
  swX.position.set(cx0 + 30, yMid, -44);
  root.add(swX);
  const swY = new THREE.Mesh(swGeo, sw);
  swY.position.set(cx0, cy0 + 30, -22.8);
  xStage.add(swY);

  // Base plate.
  const base = new THREE.Mesh(
    new THREE.BoxGeometry(travelX + 260, travelY + 300, 6),
    new THREE.MeshStandardMaterial({ color: 0x1e2430, roughness: 0.9 })
  );
  base.position.set(cx0 - travelX / 2, cy0 - travelY / 2, -84);
  root.add(base);

  // ── camera (fixed) on a post behind the stage ──
  const postY = b.maxY * k + 70;
  const post = new THREE.Mesh(new THREE.BoxGeometry(20, 20, CAMERA_HEIGHT + 115), dark);
  post.position.set(0, postY, (CAMERA_HEIGHT + 115) / 2 - 84);
  const arm = new THREE.Mesh(new THREE.BoxGeometry(20, postY, 14), dark);
  arm.position.set(0, postY / 2, CAMERA_HEIGHT + 28);
  const body = new THREE.Mesh(new THREE.BoxGeometry(34, 34, 26), new THREE.MeshStandardMaterial({ color: 0x111827, roughness: 0.4, metalness: 0.3 }));
  body.position.set(0, 0, CAMERA_HEIGHT + 20);
  const lens = new THREE.Mesh(new THREE.CylinderGeometry(9, 10, 14, 28).rotateX(Math.PI / 2), new THREE.MeshStandardMaterial({ color: 0x0b0f17, roughness: 0.2, metalness: 0.6 }));
  lens.position.set(0, 0, CAMERA_HEIGHT);
  root.add(post, arm, body, lens);

  // The camera's view on the board: frustum lines and a translucent rectangle.
  const fovGroup = new THREE.Group();
  root.add(fovGroup);
  const setFov = (z: number) => {
    fovGroup.children.forEach((c) => disposeObject(c));
    fovGroup.clear();
    const { corners } = pictureQuad(cal, { x_mm: 0, y_mm: 0, zoom: z }, frame);
    const pts = corners.map(([x, y]) => new THREE.Vector3(x * k, y * k, 0.6));
    const fill = new THREE.Mesh(
      new THREE.ShapeGeometry(new THREE.Shape(pts.map((p) => new THREE.Vector2(p.x, p.y)))),
      new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.28, depthWrite: false, side: THREE.DoubleSide })
    );
    fill.position.z = 0.6;
    const outline = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: 0xe0f2fe }));
    const apex = new THREE.Vector3(0, 0, CAMERA_HEIGHT - 7);
    const rays = new THREE.LineSegments(
      new THREE.BufferGeometry().setFromPoints(pts.flatMap((p) => [apex, p])),
      new THREE.LineBasicMaterial({ color: 0x93c5fd, transparent: true, opacity: 0.45 })
    );
    fovGroup.add(fill, outline, rays);
    invalidate();
  };
  setFov(init.zoom);

  // ── scan points: pins, numbers and the path between them ──
  const pinH = Math.max(14, Math.min(40, Math.max(bw, bh) * k * 0.09));
  const pins = init.points.map((p, i) => {
    const pin = makePin(THREE, pinH, STATUS_COLOR.pending);
    pin.group.position.set(p.x_mm * k, p.y_mm * k, 0);
    pin.head.userData.index = i;
    const label = makeLabel(THREE, String(i + 1), pinH * 0.42);
    label.position.set(0, 0, pinH * 1.5);
    pin.group.add(label);
    yStage.add(pin.group);
    return pin;
  });
  if (init.points.length > 1) {
    const path = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(init.points.map((p) => new THREE.Vector3(p.x_mm * k, p.y_mm * k, 0.8))),
      new THREE.LineDashedMaterial({ color: 0xfbbf24, dashSize: 6, gapSize: 4 })
    );
    path.computeLineDistances();
    yStage.add(path);
  }

  let blinkStop: (() => void) | null = null;
  const setPins = (statuses: Array<PointStatus | null>, selected: number | null, scanning: number | null) => {
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

  // ── live position, eased; the pinions turn with it ──
  const target = new THREE.Vector2(...(init.machine?.position_mm ?? [0, 0]));
  const now = target.clone();
  const apply = () => {
    xStage.position.x = -now.x * k;
    yStage.position.y = -now.y * k;
    pinionX.rotation.y = (now.x * k) / 7.2;
    pinionY.rotation.x = (-now.y * k) / 7.2;
  };
  apply();
  let gliding = false;
  const setPosition = (p: [number, number], immediate = false) => {
    target.set(p[0], p[1]);
    if (immediate) {
      now.copy(target);
      apply();
      return invalidate();
    }
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
    sw.emissiveIntensity = 0.15;
    if (on) homeStop = stage.animate((t) => void (sw.emissiveIntensity = 0.2 + 1.3 * (0.5 + 0.5 * Math.sin(t * 9))));
    invalidate();
  };

  // ── view ──
  const center = new THREE.Vector3(cx0 - travelX / 2, cy0 - travelY / 2, 30);
  const span = Math.max(travelX, travelY) + Math.max(bw, bh) * k;
  const resetView = () => {
    camera.near = 2;
    camera.far = span * 20;
    camera.updateProjectionMatrix();
    camera.position.set(center.x + span * 0.6, center.y - span * 1.25, center.z + span * 1.05);
    controls?.target.copy(center);
    controls?.update();
    invalidate();
  };
  if (controls) {
    controls.maxPolarAngle = Math.PI * 0.495;
    controls.minDistance = 60;
    controls.maxDistance = span * 4;
  }
  resetView();

  // Click a pin to select its point (a drag orbits instead).
  const ray = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  let down: [number, number] | null = null;
  const onDown = (e: PointerEvent) => void (down = [e.clientX, e.clientY]);
  const onUp = (e: PointerEvent) => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
    const r = stage.canvas.getBoundingClientRect();
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hit = ray.intersectObjects(pins.map((p) => p.head))[0];
    if (hit) props.current.onPickPoint?.(hit.object.userData.index as number);
  };
  stage.canvas.addEventListener("pointerdown", onDown);
  stage.canvas.addEventListener("pointerup", onUp);
  stage.onDispose(() => {
    stage.canvas.removeEventListener("pointerdown", onDown);
    stage.canvas.removeEventListener("pointerup", onUp);
  });

  return { setPosition, setPins, setHoming, setFov, resetView };
}
