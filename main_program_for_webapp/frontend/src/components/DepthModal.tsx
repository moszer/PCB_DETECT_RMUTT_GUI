"use client";

import React, { useEffect, useState } from "react";
import { Box, RefreshCw } from "lucide-react";
import type { DepthResult } from "@/types";
import { api, errorMessage } from "@/lib/api";
import { Depth3DView, HEIGHT_GRADIENT, heightRange, type DepthColorMode } from "./Depth3DView";
import { DepthMap2D } from "./DepthMap2D";
import { Button, Modal, Segmented, Spinner, Stat } from "./ui";

export interface DepthTarget {
  x_mm: number;
  y_mm: number;
  zoom: number;
  /** Normalized box in the inspection image. */
  bbox: [number, number, number, number];
  name: string;
}

const EXAGGERATION = [1, 2, 5, 10];

/** 3D height view of one part (motion stereo: the stage moves aside, shoots, and returns). */
export function DepthModal({ target, onClose }: { target: DepthTarget; onClose: () => void }) {
  const [nonce, setNonce] = useState(0);
  const [result, setResult] = useState<{ key: string; data?: DepthResult; error?: string } | null>(null);
  const [exaggeration, setExaggeration] = useState(1);
  const [mode, setMode] = useState<DepthColorMode>("height");
  const [view, setView] = useState<"2d" | "3d">("2d");

  const key = `${target.x_mm}:${target.y_mm}:${target.zoom}:${target.bbox.join(",")}:${nonce}`;
  useEffect(() => {
    let live = true;
    api
      .measureDepth({ x_mm: target.x_mm, y_mm: target.y_mm, zoom: target.zoom, bbox: target.bbox, recapture: nonce > 0 })
      .then((data) => live && setResult({ key, data }))
      .catch((err) => live && setResult({ key, error: errorMessage(err) }));
    return () => {
      live = false;
    };
  }, [key, target, nonce]);

  const current = result?.key === key ? result : null;
  const data = current?.data;
  const range = data ? heightRange(data) : null;

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={
        <>
          <Box className="size-4 text-accent" />
          ความสูง 3D · {target.name}
        </>
      }
      subtitle="ถ่าย 2 ภาพโดยเลื่อนสเตจไปด้านข้าง แล้วคำนวณความสูงจากการเลื่อนของภาพ (ค่าคร่าวๆ)"
    >
      {!current ? (
        <div className="h-[440px] grid place-items-center text-center">
          <div className="flex flex-col items-center gap-3 text-sm text-muted">
            <Spinner className="size-6" />
            กำลังเลื่อนสเตจไปที่จุดนี้และถ่าย 2 ภาพ…
            <span className="text-xs text-subtle">บอร์ดต้องวางอยู่ตำแหน่งเดิมกับตอนสแกน</span>
          </div>
        </div>
      ) : current.error ? (
        <div className="h-[440px] grid place-items-center text-center">
          <div className="flex flex-col items-center gap-3 max-w-md">
            <p className="text-sm text-fail">{current.error}</p>
            <Button icon={RefreshCw} onClick={() => setNonce((n) => n + 1)}>
              ลองใหม่
            </Button>
          </div>
        </div>
      ) : (
        data && (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px]">
            {view === "2d" ? <DepthMap2D data={data} /> : <Depth3DView data={data} exaggeration={exaggeration} mode={mode} className="h-[440px]" />}
            <div className="flex flex-col gap-3 min-w-0">
              <div className="grid grid-cols-2 gap-2">
                <Stat label="สูงสุดในกรอบ" value={data.stats.max_mm !== null ? `${data.stats.max_mm.toFixed(1)} mm` : "–"} />
                <Stat label="ค่ากลางในกรอบ" value={data.stats.median_mm !== null ? `${data.stats.median_mm.toFixed(1)} mm` : "–"} />
              </div>
              <p className="text-[11px] text-muted -mt-1">
                วัดได้โดยตรง {Math.round(data.stats.box_valid_ratio * 100)}% ของกรอบ — ที่เหลือเติมจากรอบข้าง
                {data.stats.box_valid_ratio < 0.5 && <span className="text-review"> (ผิวเรียบ/สะท้อนแสง ค่าอาจคลาดเคลื่อน)</span>}
              </p>

              <div className="flex flex-col gap-1.5">
                <span className="text-xs text-muted">มุมมอง</span>
                <Segmented
                  size="sm"
                  value={view}
                  onChange={setView}
                  options={[
                    { value: "2d", label: "แผนที่ 2D" },
                    { value: "3d", label: "3D หมุนได้" },
                  ]}
                />
              </div>

              {view === "2d" && range && (
                <div className="flex flex-col gap-0.5">
                  <div className="h-2 rounded-full" style={{ background: HEIGHT_GRADIENT }} />
                  <div className="flex justify-between text-[10px] font-mono text-muted">
                    <span>{range[0].toFixed(1)}</span>
                    <span>{range[1].toFixed(1)} mm</span>
                  </div>
                </div>
              )}

              <div className={view === "3d" ? "flex flex-col gap-1.5" : "hidden"}>
                <span className="text-xs text-muted">สี</span>
                <Segmented
                  size="sm"
                  value={mode}
                  onChange={setMode}
                  options={[
                    { value: "photo", label: "ภาพจริง" },
                    { value: "height", label: "ตามความสูง" },
                  ]}
                />
                {mode === "height" && range && (
                  <div className="flex flex-col gap-0.5">
                    <div className="h-2 rounded-full" style={{ background: HEIGHT_GRADIENT }} />
                    <div className="flex justify-between text-[10px] font-mono text-muted">
                      <span>{range[0].toFixed(1)}</span>
                      <span>{range[1].toFixed(1)} mm</span>
                    </div>
                  </div>
                )}
              </div>

              <div className={view === "3d" ? "flex flex-col gap-1.5" : "hidden"}>
                <span className="text-xs text-muted">ขยายความสูง</span>
                <Segmented size="sm" value={exaggeration} onChange={setExaggeration} options={EXAGGERATION.map((v) => ({ value: v, label: `×${v}` }))} />
              </div>

              <div className="mt-auto flex flex-col gap-2">
                <p className="text-[11px] text-subtle leading-relaxed">
                  ความสูงเทียบกับผิวบอร์ดรอบชิ้น · อิงระยะเลนส์ถึงบอร์ด {data.camera_distance_mm} mm (แก้ได้ในหน้าตั้งค่า) · ถ่ายเมื่อ{" "}
                  {Math.round(data.captured_ago_sec)} วินาทีที่แล้ว
                </p>
                <Button size="sm" icon={RefreshCw} onClick={() => setNonce((n) => n + 1)}>
                  ถ่ายใหม่
                </Button>
              </div>
            </div>
          </div>
        )
      )}
    </Modal>
  );
}
