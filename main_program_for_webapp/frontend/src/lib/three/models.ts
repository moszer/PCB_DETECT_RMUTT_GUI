"use client";

import type * as T from "three";
import type { Three } from "./stage";

export type StagePart = "carriage" | "rail" | "pinion" | "mount";
const PARTS: StagePart[] = ["carriage", "rail", "pinion", "mount"];

let cache: Promise<Record<StagePart, T.BufferGeometry> | null> | null = null;

/**
 * The XY stage's CAD parts (converted from the STEP files, simplified, mm, Z up), loaded once:
 * carriage, 250 mm rack rail, 14-tooth pinion and the rail mount. Null if the file is missing.
 */
export function loadStageParts(THREE: Three): Promise<Record<StagePart, T.BufferGeometry> | null> {
  if (!cache) {
    cache = import("three/examples/jsm/loaders/GLTFLoader.js")
      .then(({ GLTFLoader }) => new GLTFLoader().loadAsync("/models/stage.glb"))
      .then((gltf) => {
        const out: Partial<Record<StagePart, T.BufferGeometry>> = {};
        gltf.scene.updateMatrixWorld(true);
        gltf.scene.traverse((o) => {
          const mesh = o as T.Mesh;
          if (!mesh.isMesh) return;
          // Quantized files name the node above the mesh (the mesh itself gets "mesh_N").
          let node: T.Object3D | null = mesh;
          while (node && !PARTS.includes(node.name as StagePart)) node = node.parent;
          if (!node) return;
          const name = node.name as StagePart;
          const g = mesh.geometry.clone();
          // The file is quantized (16-bit, KHR_mesh_quantization): back to floats before the
          // node's dequantizing transform is baked in, or the mm values would clip.
          for (const [key, attr] of Object.entries(g.attributes)) {
            const a = attr as T.BufferAttribute;
            if (a.array instanceof Float32Array && !(a as unknown as { isInterleavedBufferAttribute?: boolean }).isInterleavedBufferAttribute) continue;
            const buf = new Float32Array(a.count * a.itemSize);
            const get = [a.getX, a.getY, a.getZ, a.getW];
            for (let i = 0; i < a.count; i++) for (let c = 0; c < a.itemSize; c++) buf[i * a.itemSize + c] = get[c].call(a, i);
            g.setAttribute(key, new THREE.BufferAttribute(buf, a.itemSize));
          }
          g.applyMatrix4(mesh.matrixWorld);
          if (!g.getAttribute("normal")) g.computeVertexNormals();
          out[name] = g;
        });
        return out.carriage && out.rail && out.pinion && out.mount ? (out as Record<StagePart, T.BufferGeometry>) : null;
      })
      .catch(() => {
        cache = null;
        return null;
      });
  }
  return cache;
}
