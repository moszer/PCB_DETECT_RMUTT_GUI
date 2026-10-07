"use client";

import type * as THREE_NS from "three";
import type { OrbitControls as OrbitControlsType } from "three/examples/jsm/controls/OrbitControls.js";

export type Three = typeof THREE_NS;

/**
 * A three.js view that only draws when something changed: on demand (`invalidate`), while an
 * animation callback asks for more frames, or while the orbit controls are still gliding.
 * Nothing is drawn while the tab is hidden or the view is scrolled out of sight, so an idle
 * view costs the station's GPU (shared with inference) nothing.
 */
export interface ThreeStage {
  THREE: Three;
  scene: THREE_NS.Scene;
  camera: THREE_NS.PerspectiveCamera;
  renderer: THREE_NS.WebGLRenderer;
  controls: OrbitControlsType | null;
  canvas: HTMLCanvasElement;
  /** Draw one more frame. */
  invalidate: () => void;
  /** Run `fn` every frame until it returns false (or the returned stop function is called). */
  animate: (fn: (time: number, dt: number) => boolean | void) => () => void;
  /** Run when the view is disposed (textures, listeners). */
  onDispose: (fn: () => void) => void;
  dispose: () => void;
}

export interface StageOptions {
  controls?: boolean;
  fov?: number;
  /** Cap for continuous animation (decorative views run slower). */
  maxFps?: number;
  /** Lower resolution for small or decorative views. */
  pixelRatio?: number;
  /** Ignore pointer input (decorative views). */
  passive?: boolean;
}

let threePromise: Promise<{ THREE: Three; OrbitControls: typeof OrbitControlsType }> | null = null;
/** three.js is ~600 kB: loaded the first time a 3D view opens, then shared. */
export function loadThree() {
  if (!threePromise) {
    threePromise = Promise.all([import("three"), import("three/examples/jsm/controls/OrbitControls.js")]).then(([THREE, c]) => ({
      THREE,
      OrbitControls: c.OrbitControls,
    }));
  }
  return threePromise;
}

export async function createThreeStage(host: HTMLElement, opts: StageOptions = {}): Promise<ThreeStage | null> {
  const { THREE, OrbitControls } = await loadThree();
  let renderer: THREE_NS.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
  } catch {
    return null;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, opts.pixelRatio ?? 1.75));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const canvas = renderer.domElement;
  canvas.style.display = "block";
  canvas.style.width = "100%";
  canvas.style.height = "100%";
  if (opts.passive) canvas.style.pointerEvents = "none";
  host.appendChild(canvas);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(opts.fov ?? 38, 1, 1, 5000);
  camera.up.set(0, 0, 1);
  const controls = opts.controls ? new OrbitControls(camera, canvas) : null;
  if (controls) {
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
  }

  const tickers = new Set<(time: number, dt: number) => boolean | void>();
  const disposers: Array<() => void> = [];
  let pending = 0;
  let visible = !document.hidden;
  let inView = true;
  let last = performance.now();
  let lastDraw = 0;
  let disposed = false;
  const minGap = opts.maxFps ? 1000 / opts.maxFps : 0;

  const frame = (now: number) => {
    pending = 0;
    if (disposed || !visible) return;
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    // Out of sight, animations pause; a requested redraw still happens (it is one frame).
    const animating = inView && tickers.size > 0;
    if (animating && now - lastDraw < minGap) {
      schedule();
      return;
    }
    let more = false;
    if (inView) {
      for (const fn of [...tickers]) {
        if (fn(now / 1000, dt) === false) tickers.delete(fn);
        else more = true;
      }
    }
    const gliding = controls ? controls.update() : false;
    renderer.render(scene, camera);
    lastDraw = now;
    if (more || gliding) schedule();
  };
  function schedule() {
    if (!pending && !disposed) pending = requestAnimationFrame(frame);
  }
  const invalidate = () => schedule();

  const resize = () => {
    const w = host.clientWidth || 1;
    const h = host.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    invalidate();
  };
  resize();
  const ro = new ResizeObserver(resize);
  ro.observe(host);
  const io = new IntersectionObserver(([entry]) => {
    inView = entry?.isIntersecting ?? true;
    if (inView) {
      last = performance.now();
      invalidate();
    }
  });
  io.observe(host);
  const onVisibility = () => {
    visible = !document.hidden;
    if (visible) {
      last = performance.now();
      invalidate();
    }
  };
  document.addEventListener("visibilitychange", onVisibility);
  controls?.addEventListener("change", invalidate);

  const dispose = () => {
    if (disposed) return;
    disposed = true;
    cancelAnimationFrame(pending);
    ro.disconnect();
    io.disconnect();
    document.removeEventListener("visibilitychange", onVisibility);
    controls?.removeEventListener("change", invalidate);
    controls?.dispose();
    disposers.forEach((fn) => fn());
    disposeObject(scene);
    renderer.dispose();
    renderer.forceContextLoss();
    canvas.remove();
  };

  return {
    THREE,
    scene,
    camera,
    renderer,
    controls,
    canvas,
    invalidate,
    animate: (fn) => {
      tickers.add(fn);
      last = performance.now();
      schedule();
      return () => {
        tickers.delete(fn);
      };
    },
    onDispose: (fn) => disposers.push(fn),
    dispose,
  };
}

/** Free the GPU memory of everything under `root` (geometries, materials, their textures). */
export function disposeObject(root: THREE_NS.Object3D) {
  root.traverse((obj) => {
    const mesh = obj as THREE_NS.Mesh;
    mesh.geometry?.dispose();
    const mats = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : [];
    for (const m of mats) {
      for (const v of Object.values(m)) if (v && typeof v === "object" && "isTexture" in v) (v as THREE_NS.Texture).dispose();
      m.dispose();
    }
  });
}

/**
 * A picture as a small texture: decoded at most `maxSide` px wide first, so a 4K reference
 * image (data URL or link) costs a few hundred kB of GPU memory instead of 60 MB.
 */
export async function loadTexture(THREE: Three, src: string, maxSide = 512): Promise<THREE_NS.Texture | null> {
  try {
    const blob = await (await fetch(src)).blob();
    const probe = await createImageBitmap(blob);
    const k = Math.min(1, maxSide / Math.max(probe.width, probe.height));
    const bmp = k < 1 ? await createImageBitmap(blob, { resizeWidth: Math.round(probe.width * k), resizeHeight: Math.round(probe.height * k), resizeQuality: "high" }) : probe;
    if (bmp !== probe) probe.close();
    const tex = new THREE.Texture(bmp);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.flipY = false;
    tex.needsUpdate = true;
    const close = tex.dispose.bind(tex);
    tex.dispose = () => {
      close();
      bmp.close();
    };
    return tex;
  } catch {
    return null;
  }
}

/** Colour of a value 0..1 on green → amber → red. */
export function goodBadColor(THREE: Three, t: number): THREE_NS.Color {
  const c = new THREE.Color();
  const x = Math.min(1, Math.max(0, t));
  return x < 0.5 ? c.setRGB(0.13 + x * 1.7, 0.72, 0.36 - x * 0.4) : c.setRGB(0.98, 0.72 - (x - 0.5) * 1.1, 0.16);
}
