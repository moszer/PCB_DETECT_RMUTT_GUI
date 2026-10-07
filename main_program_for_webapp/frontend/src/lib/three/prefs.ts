"use client";

import { useSyncExternalStore } from "react";

/**
 * Per-browser 3D preferences. `enabled` switches every 3D view to its 2D fallback (the station's
 * GPU is shared with inference, and some browsers have no WebGL); `decor` turns off only the
 * decorative ones (splash PCB, rotating empty-state boards).
 */
export interface ThreePrefs {
  enabled: boolean;
  decor: boolean;
}

const KEY = "pcb_3d_prefs";
const DEFAULTS: ThreePrefs = { enabled: true, decor: true };
const SERVER: ThreePrefs = { enabled: false, decor: false };
const listeners = new Set<() => void>();
let current: ThreePrefs | null = null;

function load(): ThreePrefs {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...DEFAULTS, ...JSON.parse(raw) } : DEFAULTS;
  } catch {
    return DEFAULTS;
  }
}

function snapshot(): ThreePrefs {
  if (!current) current = load();
  return current;
}

function subscribe(fn: () => void) {
  listeners.add(fn);
  const onStorage = (e: StorageEvent) => {
    if (e.key !== KEY) return;
    current = load();
    fn();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(fn);
    window.removeEventListener("storage", onStorage);
  };
}

export function setThreePrefs(patch: Partial<ThreePrefs>) {
  current = { ...snapshot(), ...patch };
  try {
    localStorage.setItem(KEY, JSON.stringify(current));
  } catch {
    // Kept in memory for this tab.
  }
  listeners.forEach((fn) => fn());
}

let webgl: boolean | null = null;
/** Whether this browser can make a WebGL context at all (checked once). */
export function webglAvailable(): boolean {
  if (webgl !== null) return webgl;
  try {
    const c = document.createElement("canvas");
    const gl = (c.getContext("webgl2") || c.getContext("webgl")) as WebGLRenderingContext | null;
    webgl = Boolean(gl);
    // Browsers allow only a few live contexts: give this test one back right away.
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
  } catch {
    webgl = false;
  }
  return webgl;
}

const reducedQuery = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null);

/** 3D settings plus what the browser allows: `use3d` for working views, `decor` for decoration. */
export function useThreePrefs() {
  const prefs = useSyncExternalStore(subscribe, snapshot, () => SERVER);
  const reduced = useSyncExternalStore(
    (fn) => {
      const q = reducedQuery();
      q?.addEventListener("change", fn);
      return () => q?.removeEventListener("change", fn);
    },
    () => Boolean(reducedQuery()?.matches),
    () => true
  );
  const gl = typeof window !== "undefined" && prefs.enabled && webglAvailable();
  return { ...prefs, use3d: gl, decor: gl && prefs.decor && !reduced, reducedMotion: reduced };
}
