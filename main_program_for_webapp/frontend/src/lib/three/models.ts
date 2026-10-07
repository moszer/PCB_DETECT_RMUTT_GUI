"use client";

import type * as T from "three";

/**
 * The whole station from its CAD (full_machine_pcb_detect.step, tessellated by FreeCAD at
 * 0.18 mm, meshopt-compressed: 5.7 MB → 0.65 MB). Units mm, web convention Y up, origin at the
 * middle of the base: X across, Z front (+) to back (−).
 *
 * It is a gantry: the two Y rails and the frame are fixed, the cross rail with its sliders and
 * drive covers moves along Y (toward the back = −Z), and the camera head moves along X on it.
 * The board lies still on the base plate (top at Y = 5).
 */
export type MachineGroup = "rails" | "gantry" | "head" | "top" | "enclosure" | "base" | "frame";

export const MACHINE_PARTS: Record<string, { title: string; group: MachineGroup }> = {
  "part-00": { title: "รางแกน Y ขวา", group: "rails" },
  "part-01": { title: "รางแกน Y ซ้าย", group: "rails" },
  "part-02": { title: "รางขวางแกน X", group: "gantry" },
  "part-03": { title: "ชุดเลื่อนฝั่งซ้าย", group: "gantry" },
  "part-04": { title: "ชุดเลื่อนฝั่งขวา", group: "gantry" },
  "part-05": { title: "ฝาครอบชุดขับขวา", group: "gantry" },
  "part-06": { title: "ฝาครอบหัวเลื่อน", group: "head" },
  "part-07": { title: "ฝาครอบชุดขับซ้าย", group: "gantry" },
  "part-08": { title: "แผ่นสี่เหลี่ยมด้านบน", group: "top" },
  "part-09": { title: "แผ่นบนเครื่อง", group: "top" },
  "part-10": { title: "แผงหลัง", group: "enclosure" },
  "part-11": { title: "แผงหน้า", group: "enclosure" },
  "part-12": { title: "แผงขวา", group: "enclosure" },
  "part-13": { title: "แผงซ้าย", group: "enclosure" },
  "part-14": { title: "แผ่นฐาน", group: "base" },
  "part-15": { title: "กรอบฐานด้านใน", group: "base" },
  "part-16": { title: "เสามุมหน้าขวา", group: "frame" },
  "part-17": { title: "เสามุมหลังขวา", group: "frame" },
  "part-18": { title: "เสามุมหลังซ้าย", group: "frame" },
  "part-19": { title: "เสามุมหน้าซ้าย", group: "frame" },
  "part-20": { title: "คานหน้ารองราง", group: "frame" },
  "part-21": { title: "คานหลังรองราง", group: "frame" },
  "part-22": { title: "ขายึดรางซ้ายหน้า", group: "frame" },
  "part-23": { title: "ขายึดรางซ้ายหลัง", group: "frame" },
  "part-24": { title: "ขายึดรางขวาหลัง", group: "frame" },
  "part-25": { title: "ขายึดรางขวาหน้า", group: "frame" },
  "part-26": { title: "ชุดหัวเลื่อนด้านใน", group: "head" },
};

/** Where things are in the CAD assembly (web coordinates, mm). */
export const MACHINE = {
  /** Camera head centre in the assembly, taken as the HOME position (front left). */
  headX: -103,
  headZ: 94,
  /** Bottom of the camera head, where the lens looks down from. */
  lensY: 146,
  /** Top of the base plate, where the board lies. */
  baseTopY: 5,
};

let cache: Promise<T.Object3D | null> | null = null;

/** The machine's scene (loaded once; every call returns a copy sharing the geometry). */
export async function loadMachine(): Promise<T.Object3D | null> {
  if (!cache) {
    cache = Promise.all([import("three/examples/jsm/loaders/GLTFLoader.js"), import("three/examples/jsm/libs/meshopt_decoder.module.js")])
      .then(([{ GLTFLoader }, { MeshoptDecoder }]) => {
        const loader = new GLTFLoader();
        loader.setMeshoptDecoder(MeshoptDecoder);
        return loader.loadAsync("/models/machine.glb");
      })
      .then((gltf) => (gltf.scene.getObjectByName("part-02") ? gltf.scene : null))
      .catch(() => {
        cache = null;
        return null;
      });
  }
  const scene = await cache;
  return scene ? scene.clone(true) : null;
}
