"use client";

import React, { useEffect, useRef, useState } from "react";
import type { DepthResult } from "@/types";
import { useElementSize } from "@/hooks/useElementSize";
import { heightColor, heightRange } from "./Depth3DView";

/** Where a w×h picture lands inside a box with object-contain. */
function fit(box: { width: number; height: number }, w: number, h: number) {
  const s = Math.min(box.width / w, box.height / h) || 0;
  return { left: (box.width - w * s) / 2, top: (box.height - h * s) / 2, width: w * s, height: h * s };
}

function Panel({
  title,
  aspect,
  children,
  cursor,
  onCursor,
  box,
}: {
  title: string;
  aspect: [number, number];
  children: React.ReactNode;
  cursor: [number, number] | null;
  onCursor: (uv: [number, number] | null) => void;
  box: DepthResult["box_in_roi"];
}) {
  const ref = useRef<HTMLDivElement>(null);
  const size = useElementSize(ref);
  const r = fit(size, aspect[0], aspect[1]);
  return (
    <div className="flex flex-col gap-1 min-w-0">
      <span className="text-[11px] text-muted">{title}</span>
      <div
        ref={ref}
        className="relative h-[400px] rounded-lg bg-viewport overflow-hidden cursor-crosshair"
        onPointerMove={(e) => {
          const b = ref.current!.getBoundingClientRect();
          const u = (e.clientX - b.left - r.left) / r.width;
          const v = (e.clientY - b.top - r.top) / r.height;
          onCursor(u >= 0 && u <= 1 && v >= 0 && v <= 1 ? [u, v] : null);
        }}
        onPointerLeave={() => onCursor(null)}
      >
        <div className="absolute" style={r}>
          {children}
          <div
            className="absolute border-2 border-amber-400/90 rounded-sm pointer-events-none"
            style={{ left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%` }}
          />
          {cursor && (
            <>
              <div className="absolute inset-y-0 w-px bg-white/70 pointer-events-none" style={{ left: `${cursor[0] * 100}%` }} />
              <div className="absolute inset-x-0 h-px bg-white/70 pointer-events-none" style={{ top: `${cursor[1] * 100}%` }} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Top-down view: the photo and the height map side by side, sharing a crosshair, with the
 * height under the pointer. Easier to read than the 3D view for "is it there / how tall".
 */
export function DepthMap2D({ data }: { data: DepthResult }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [cursor, setCursor] = useState<[number, number] | null>(null);
  const [lo, hi] = heightRange(data);
  const aspect: [number, number] = [data.roi_size_px[0], data.roi_size_px[1]];

  useEffect(() => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx) return;
    el.width = data.grid_w;
    el.height = data.grid_h;
    const img = ctx.createImageData(data.grid_w, data.grid_h);
    data.heights.forEach((h, i) => {
      const [r, g, b] = heightColor((h - lo) / (hi - lo || 1));
      img.data.set([r * 255, g * 255, b * 255, data.valid[i] ? 255 : 150], i * 4);
    });
    ctx.putImageData(img, 0, 0);
  }, [data, lo, hi]);

  const value = cursor
    ? data.heights[
        Math.min(data.grid_h - 1, Math.floor(cursor[1] * data.grid_h)) * data.grid_w + Math.min(data.grid_w - 1, Math.floor(cursor[0] * data.grid_w))
      ]
    : null;

  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-2">
        <Panel title="ภาพจริง" aspect={aspect} cursor={cursor} onCursor={setCursor} box={data.box_in_roi}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {data.texture && <img src={data.texture} alt="ภาพชิ้นส่วน" className="absolute inset-0 size-full" draggable={false} />}
        </Panel>
        <Panel title="แผนที่ความสูง (มองจากด้านบน)" aspect={aspect} cursor={cursor} onCursor={setCursor} box={data.box_in_roi}>
          <canvas ref={canvas} className="absolute inset-0 size-full" />
        </Panel>
      </div>
      <span className="h-6 text-xs text-muted flex items-center">
        {value !== null && value !== undefined ? (
          <span className="font-mono tabular text-text">สูง {value.toFixed(1)} mm</span>
        ) : (
          "ชี้บนภาพเพื่ออ่านความสูง · กรอบสีส้มคือชิ้นที่เลือก · ส่วนที่จางคือที่เติมจากรอบข้าง (วัดตรงไม่ได้)"
        )}
      </span>
    </div>
  );
}
