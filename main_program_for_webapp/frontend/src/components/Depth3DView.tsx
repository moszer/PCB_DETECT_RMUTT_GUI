"use client";

import React, { useEffect, useRef, useState } from "react";
import type { DepthResult } from "@/types";
import { cx } from "./ui";

export type DepthColorMode = "photo" | "height";

/** Blue → cyan → green → yellow → red. */
export function heightColor(t: number): [number, number, number] {
  const stops: Array<[number, number, number]> = [
    [0.19, 0.25, 0.85],
    [0.1, 0.75, 0.95],
    [0.2, 0.85, 0.35],
    [0.98, 0.85, 0.2],
    [0.95, 0.25, 0.2],
  ];
  const x = Math.min(1, Math.max(0, t)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(x));
  const f = x - i;
  return [0, 1, 2].map((k) => stops[i][k] + (stops[i + 1][k] - stops[i][k]) * f) as [number, number, number];
}

/** Robust display range (2nd–98th percentile, always including the board level). */
export function heightRange(data: DepthResult): [number, number] {
  const sorted = [...data.heights].sort((a, b) => a - b);
  const lo = Math.min(0, sorted[Math.floor(sorted.length * 0.02)] ?? 0);
  const hi = Math.max(1, sorted[Math.floor(sorted.length * 0.98)] ?? 1);
  return [lo, hi];
}

export const HEIGHT_GRADIENT = `linear-gradient(to right, ${[0, 0.25, 0.5, 0.75, 1]
  .map((t) => `rgb(${heightColor(t).map((c) => Math.round(c * 255)).join(",")})`)
  .join(", ")})`;

interface ViewApi {
  setExaggeration: (v: number) => void;
  setMode: (m: DepthColorMode) => void;
}

/**
 * Interactive height map of one part (drag to orbit, scroll to zoom). Real proportions in
 * mm, heights optionally exaggerated; the part's box is outlined in amber.
 */
export function Depth3DView({
  data,
  exaggeration,
  mode,
  className,
}: {
  data: DepthResult;
  exaggeration: number;
  mode: DepthColorMode;
  className?: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<ViewApi | null>(null);
  const latest = useRef({ exaggeration, mode });
  const [hover, setHover] = useState<number | null>(null);
  const [noWebgl, setNoWebgl] = useState(false);

  useEffect(() => {
    latest.current = { exaggeration, mode };
    view.current?.setExaggeration(exaggeration);
    view.current?.setMode(mode);
  }, [exaggeration, mode]);

  useEffect(() => {
    let disposed = false;
    let cleanup = () => {};
    (async () => {
      const THREE = await import("three");
      const { OrbitControls } = await import("three/examples/jsm/controls/OrbitControls.js");
      const el = host.current;
      if (disposed || !el) return;

      let renderer: InstanceType<typeof THREE.WebGLRenderer>;
      try {
        renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      } catch {
        setNoWebgl(true);
        return;
      }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      el.appendChild(renderer.domElement);
      renderer.domElement.style.display = "block";

      const { grid_w: gw, grid_h: gh } = data;
      const W = data.roi_size_px[0] * data.mm_per_px;
      const H = data.roi_size_px[1] * data.mm_per_px;
      const span = Math.max(W, H);
      const heights = Float32Array.from(data.heights);
      const [lo, hi] = heightRange(data);

      // Frame the whole part, tall ones included.
      const top = Math.max(0, hi) * latest.current.exaggeration;
      const reach = Math.max(span, top * 1.4);
      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(38, 1, reach / 100, reach * 50);
      camera.up.set(0, 0, 1);
      camera.position.set(0, -reach * 1.25, reach * 0.9 + top * 0.5);

      const geometry = new THREE.PlaneGeometry(W, H, gw - 1, gh - 1);
      const pos = geometry.attributes.position as InstanceType<typeof THREE.BufferAttribute>;
      const colors = new Float32Array(gw * gh * 3);
      for (let i = 0; i < gw * gh; i++) {
        const [r, g, b] = heightColor((heights[i] - lo) / (hi - lo || 1));
        colors.set([r, g, b], i * 3);
      }
      geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));

      const texture = data.texture ? new THREE.TextureLoader().load(data.texture) : null;
      if (texture) texture.colorSpace = THREE.SRGBColorSpace;
      const material = new THREE.MeshStandardMaterial({ roughness: 0.85, metalness: 0, side: THREE.DoubleSide });
      const mesh = new THREE.Mesh(geometry, material);
      scene.add(mesh);

      // The part's box, drawn just above its tallest point.
      const [bx1, by1, bx2, by2] = data.box_in_roi;
      const toX = (u: number) => -W / 2 + u * W;
      const toY = (v: number) => H / 2 - v * H;
      const outlineGeom = new THREE.BufferGeometry();
      const outline = new THREE.LineLoop(outlineGeom, new THREE.LineBasicMaterial({ color: 0xf59e0b }));
      scene.add(outline);

      scene.add(new THREE.AmbientLight(0xffffff, 0.8));
      const sun = new THREE.DirectionalLight(0xffffff, 1.6);
      sun.position.set(-span, -span * 0.6, span * 1.6);
      scene.add(sun);

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.target.set(0, 0, top * 0.35);
      controls.maxPolarAngle = Math.PI * 0.49;

      const setExaggeration = (k: number) => {
        let top = 0;
        for (let i = 0; i < gw * gh; i++) {
          // Clipped to the robust range: a few stray matches must not dwarf the part.
          const z = Math.min(hi, Math.max(lo, heights[i])) * k;
          pos.setZ(i, z);
          top = Math.max(top, z);
        }
        pos.needsUpdate = true;
        geometry.computeVertexNormals();
        const z = top + span * 0.01;
        outlineGeom.setFromPoints([
          new THREE.Vector3(toX(bx1), toY(by1), z),
          new THREE.Vector3(toX(bx2), toY(by1), z),
          new THREE.Vector3(toX(bx2), toY(by2), z),
          new THREE.Vector3(toX(bx1), toY(by2), z),
        ]);
      };
      const setMode = (m: DepthColorMode) => {
        const photo = m === "photo" && !!texture;
        material.map = photo ? texture : null;
        material.vertexColors = !photo;
        material.color.set(0xffffff);
        material.needsUpdate = true;
      };
      setExaggeration(latest.current.exaggeration);
      setMode(latest.current.mode);
      view.current = { setExaggeration, setMode };

      const resize = () => {
        const w = el.clientWidth || 1;
        const h = el.clientHeight || 1;
        renderer.setSize(w, h, false);
        renderer.domElement.style.width = "100%";
        renderer.domElement.style.height = "100%";
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
      };
      resize();
      const observer = new ResizeObserver(resize);
      observer.observe(el);

      // Height under the pointer.
      const raycaster = new THREE.Raycaster();
      const ndc = new THREE.Vector2();
      const onMove = (e: PointerEvent) => {
        const r = renderer.domElement.getBoundingClientRect();
        ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
        raycaster.setFromCamera(ndc, camera);
        const hit = raycaster.intersectObject(mesh)[0];
        if (!hit) return setHover(null);
        const col = Math.round(((hit.point.x + W / 2) / W) * (gw - 1));
        const row = Math.round(((H / 2 - hit.point.y) / H) * (gh - 1));
        const v = heights[Math.min(gh - 1, Math.max(0, row)) * gw + Math.min(gw - 1, Math.max(0, col))];
        setHover(Number.isFinite(v) ? v : null);
      };
      const onLeave = () => setHover(null);
      renderer.domElement.addEventListener("pointermove", onMove);
      renderer.domElement.addEventListener("pointerleave", onLeave);

      let frame = 0;
      const loop = () => {
        frame = requestAnimationFrame(loop);
        controls.update();
        renderer.render(scene, camera);
      };
      loop();

      cleanup = () => {
        cancelAnimationFrame(frame);
        observer.disconnect();
        renderer.domElement.removeEventListener("pointermove", onMove);
        renderer.domElement.removeEventListener("pointerleave", onLeave);
        controls.dispose();
        geometry.dispose();
        outlineGeom.dispose();
        material.dispose();
        texture?.dispose();
        renderer.dispose();
        renderer.domElement.remove();
        view.current = null;
      };
      if (disposed) cleanup();
    })();
    return () => {
      disposed = true;
      cleanup();
    };
  }, [data]);

  return (
    <div className={cx("relative rounded-xl overflow-hidden bg-viewport border border-line", className)}>
      <div ref={host} className="absolute inset-0 cursor-grab active:cursor-grabbing" />
      {noWebgl && <p className="absolute inset-0 grid place-items-center text-sm text-white/60">เบราว์เซอร์นี้แสดง 3D (WebGL) ไม่ได้</p>}
      <span className="absolute bottom-2 left-2 h-6 px-2 rounded-md bg-black/60 text-[11px] text-white flex items-center pointer-events-none">
        {hover !== null ? `สูง ${hover.toFixed(1)} mm` : "ลากเพื่อหมุน · เลื่อนลูกกลิ้งเพื่อซูม · ชี้เพื่ออ่านความสูง"}
      </span>
    </div>
  );
}
