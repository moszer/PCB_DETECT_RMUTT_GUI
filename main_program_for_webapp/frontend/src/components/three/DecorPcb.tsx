"use client";

import React, { useEffect, useRef, useState } from "react";
import { useThreePrefs } from "@/lib/three/prefs";
import { createThreeStage } from "@/lib/three/stage";
import { addStudioLights, buildPcb } from "@/lib/three/pcb";

/**
 * A decorative 3D circuit board. "assemble": the parts drop onto the board and it turns in
 * (start-up splash); "idle": it slowly turns (empty states). Shows `fallback` instead when
 * decorative 3D is off, WebGL is missing or the user prefers reduced motion. Animates at a
 * low frame rate and stops whenever it is off screen or the tab is hidden.
 */
export function DecorPcb({
  variant = "idle",
  className,
  fallback = null,
  seed,
}: {
  variant?: "assemble" | "idle";
  className?: string;
  fallback?: React.ReactNode;
  seed?: number;
}) {
  const { decor } = useThreePrefs();
  const host = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const el = host.current;
    if (!decor || !el) return;
    let disposed = false;
    let dispose = () => {};
    void createThreeStage(el, { passive: true, maxFps: variant === "assemble" ? 60 : 24, pixelRatio: 1.25, fov: 30 }).then((stage) => {
      if (!stage) return setFailed(true);
      if (disposed) return stage.dispose();
      dispose = stage.dispose;
      const { THREE, scene, camera } = stage;
      const pcb = buildPcb(THREE, { seed });
      const pivot = new THREE.Group();
      pivot.add(pcb.group);
      scene.add(pivot);
      addStudioLights(THREE, scene, 90);
      if (variant === "assemble") camera.position.set(0, -118, 86);
      else camera.position.set(0, -92, 66);
      camera.lookAt(0, 0, 0);
      camera.near = 5;
      camera.far = 800;
      camera.updateProjectionMatrix();

      const start = performance.now() / 1000;
      const drop = new THREE.Matrix4();
      const pos = new THREE.Vector3();
      const quat = new THREE.Quaternion();
      const scl = new THREE.Vector3();
      const ease = (t: number) => 1 - Math.pow(1 - Math.min(1, Math.max(0, t)), 3);
      stage.animate((now) => {
        const t = now - start;
        if (variant === "assemble") {
          // Board swings in, then every part falls into place with a little bounce.
          const k = ease(t / 0.9);
          pivot.rotation.set(-0.5 * (1 - k), 0, -0.9 * (1 - k) + t * 0.18);
          pivot.position.z = -30 * (1 - k);
          for (const p of pcb.parts) {
            const f = Math.min(1, Math.max(0, (t - 0.3 - p.delay * 0.6) / 0.35));
            p.matrix.decompose(pos, quat, scl);
            const bounce = f < 1 ? (1 - f) * (1 - f) * 40 - Math.sin(f * Math.PI) * 0.6 : 0;
            pos.z = p.z + bounce;
            drop.compose(pos, quat, f === 0 ? scl.clone().multiplyScalar(0.0001) : scl);
            p.mesh.setMatrixAt(p.index, drop);
          }
          for (const mesh of new Set(pcb.parts.map((p) => p.mesh))) mesh.instanceMatrix.needsUpdate = true;
        } else {
          pivot.rotation.set(0, 0, t * 0.25);
        }
        return true;
      });
      setReady(true);
    });
    return () => {
      disposed = true;
      dispose();
    };
  }, [decor, variant, seed]);

  if (!decor || failed) return <>{fallback}</>;
  return <div ref={host} aria-hidden className={`pointer-events-none transition-opacity duration-700 ${ready ? "opacity-100" : "opacity-0"} ${className ?? ""}`} />;
}
