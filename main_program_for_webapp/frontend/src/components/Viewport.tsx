"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ImageOff, Maximize, ZoomIn, ZoomOut } from "lucide-react";
import type { Detection, ReferenceEvaluation } from "@/types";
import { classColor } from "@/lib/format";
import { IconButton } from "./ui";

interface ViewportProps {
  imageUrl: string | null;
  detections?: Detection[];
  referenceEval?: ReferenceEvaluation[];
  selectedDetectionId?: number | null;
  onSelectDetection?: (det: Detection | null) => void;
  showLabels?: boolean;
}

const MIN_SCALE = 0.05;
const MAX_SCALE = 8;
const clampScale = (s: number) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, s));

/** Zoomable, pannable image with an SVG overlay of detections and reference markers. */
export function Viewport({
  imageUrl,
  detections = [],
  referenceEval = [],
  selectedDetectionId = null,
  onSelectDetection,
  showLabels = true,
}: ViewportProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loadedSize, setNatural] = useState({ url: "", width: 0, height: 0 });
  const natural = useMemo(
    () => (loadedSize.url === imageUrl ? loadedSize : { url: "", width: 0, height: 0 }),
    [loadedSize, imageUrl]
  );
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const gesture = useRef<{ dragX: number; dragY: number; pinchDist: number; pinchScale: number } | null>(null);
  const moved = useRef(false);

  const fitScale = useCallback((w: number, h: number) => {
    const el = containerRef.current;
    if (!el || !w || !h) return 1;
    return Math.min((el.clientWidth - 32) / w, (el.clientHeight - 32) / h, 1);
  }, []);

  const fit = useCallback(() => {
    setScale(fitScale(natural.width, natural.height));
    setOffset({ x: 0, y: 0 });
  }, [fitScale, natural]);

  // Wheel zoom around the cursor. Registered natively because React's onWheel is
  // passive, so preventDefault() there was ignored and the page scrolled too.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const cx = e.clientX - rect.left - rect.width / 2;
      const cy = e.clientY - rect.top - rect.height / 2;
      const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      setScale((prev) => {
        const next = clampScale(prev * factor);
        setOffset((o) => ({ x: cx - (cx - o.x) * (next / prev), y: cy - (cy - o.y) * (next / prev) }));
        return next;
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const onPointerDown = (e: React.PointerEvent) => {
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    moved.current = false;
    const pts = [...pointers.current.values()];
    if (pts.length === 1) {
      gesture.current = { dragX: e.clientX - offset.x, dragY: e.clientY - offset.y, pinchDist: 0, pinchScale: scale };
      setDragging(true);
    } else if (pts.length === 2 && gesture.current) {
      gesture.current.pinchDist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      gesture.current.pinchScale = scale;
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!pointers.current.has(e.pointerId) || !gesture.current) return;
    const prev = pointers.current.get(e.pointerId)!;
    if (Math.hypot(prev.x - e.clientX, prev.y - e.clientY) > 3) moved.current = true;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const pts = [...pointers.current.values()];
    if (pts.length === 1 && moved.current) {
      (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
      setOffset({ x: e.clientX - gesture.current.dragX, y: e.clientY - gesture.current.dragY });
    } else if (pts.length === 2 && gesture.current.pinchDist) {
      const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      setScale(clampScale(gesture.current.pinchScale * (dist / gesture.current.pinchDist)));
    }
  };

  const onPointerUp = (e: React.PointerEvent) => {
    pointers.current.delete(e.pointerId);
    const remaining = [...pointers.current.values()];
    if (remaining.length === 1 && gesture.current) {
      gesture.current.dragX = remaining[0].x - offset.x;
      gesture.current.dragY = remaining[0].y - offset.y;
      gesture.current.pinchDist = 0;
    }
    if (!remaining.length) {
      gesture.current = null;
      setDragging(false);
    }
  };

  // Overlay sizes scale with the image so labels stay readable at 720p and 4K alike.
  const unit = Math.max(natural.width, natural.height) / 1000 || 1;
  const font = Math.max(11, 13 * unit);
  const stroke = Math.max(1.5, 2 * unit);

  return (
    <div
      ref={containerRef}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onClick={() => !moved.current && onSelectDetection?.(null)}
      style={{ touchAction: "none" }}
      className={`relative size-full overflow-hidden rounded-xl bg-viewport border border-line grid place-items-center ${dragging ? "cursor-grabbing" : "cursor-grab"}`}
    >
      {imageUrl ? (
        <div
          style={{
            width: natural.width || undefined,
            height: natural.height || undefined,
            transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
            transition: dragging ? "none" : "transform 80ms ease-out",
            visibility: natural.width ? "visible" : "hidden",
          }}
          className="relative shrink-0"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={imageUrl}
            alt="ภาพ PCB"
            draggable={false}
            onLoad={(e) => {
              const { naturalWidth: w, naturalHeight: h } = e.currentTarget;
              setNatural({ url: imageUrl, width: w, height: h });
              setScale(fitScale(w, h));
              setOffset({ x: 0, y: 0 });
            }}
            className="block max-w-none pointer-events-none"
            style={{ width: natural.width || undefined, height: natural.height || undefined }}
          />
          {natural.width > 0 && (
            <svg viewBox={`0 0 ${natural.width} ${natural.height}`} className="absolute inset-0 size-full">
              {detections.map((det) => {
                const [x1, y1, x2, y2] = det.box;
                const color = classColor(det.label);
                const selected = selectedDetectionId === det.id;
                const text = `${det.label} ${Math.round(det.conf * 100)}%`;
                return (
                  <g
                    key={det.id}
                    className="cursor-pointer"
                    onClick={(e) => {
                      e.stopPropagation();
                      if (!moved.current) onSelectDetection?.(det);
                    }}
                  >
                    <rect
                      x={x1}
                      y={y1}
                      width={x2 - x1}
                      height={y2 - y1}
                      fill={color}
                      fillOpacity={selected ? 0.3 : 0.08}
                      stroke={selected ? "#ffffff" : color}
                      strokeWidth={selected ? stroke * 2 : stroke}
                    />
                    {showLabels && (
                      <>
                        <rect x={x1} y={Math.max(0, y1 - font * 1.5)} width={text.length * font * 0.62 + font * 0.6} height={font * 1.5} fill={color} rx={2} />
                        <text x={x1 + font * 0.3} y={Math.max(font * 1.1, y1 - font * 0.4)} fill="#fff" fontSize={font} fontWeight={600} fontFamily="ui-monospace, monospace">
                          {text}
                        </text>
                      </>
                    )}
                  </g>
                );
              })}
              {referenceEval.map((entry) => {
                const color = entry.status === "OK" ? "#22c55e" : "#ef4444";
                const r = 9 * unit + 4;
                const { x, y } = entry.ref;
                return (
                  <g key={entry.ref_index} pointerEvents="none">
                    <circle cx={x} cy={y} r={r} fill="none" stroke={color} strokeWidth={stroke * 1.2} />
                    <circle cx={x} cy={y} r={stroke} fill={color} />
                    {entry.status === "MISSING" && (
                      <path d={`M${x - r * 0.7} ${y - r * 0.7} L${x + r * 0.7} ${y + r * 0.7} M${x - r * 0.7} ${y + r * 0.7} L${x + r * 0.7} ${y - r * 0.7}`} stroke={color} strokeWidth={stroke * 1.2} />
                    )}
                  </g>
                );
              })}
            </svg>
          )}
        </div>
      ) : (
        <div className="flex flex-col items-center gap-2 text-white/50 text-sm">
          <ImageOff className="size-8" />
          ยังไม่มีภาพ
        </div>
      )}

      {imageUrl && natural.width > 0 && (
        <>
          <div
            className="absolute top-3 right-3 flex items-center gap-0.5 rounded-lg bg-black/55 backdrop-blur p-1 text-white"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
          >
            <IconButton size="sm" overlay icon={ZoomOut} label="ซูมออก" onClick={() => setScale((s) => clampScale(s / 1.3))} />
            <button
              type="button"
              title="ขนาดจริง 1:1"
              onClick={() => {
                setScale(1);
                setOffset({ x: 0, y: 0 });
              }}
              className="h-7 min-w-12 px-1.5 rounded-md text-[11px] font-mono tabular text-white/85 hover:bg-white/10 cursor-pointer"
            >
              {Math.round(scale * 100)}%
            </button>
            <IconButton size="sm" overlay icon={ZoomIn} label="ซูมเข้า" onClick={() => setScale((s) => clampScale(s * 1.3))} />
            <IconButton size="sm" overlay icon={Maximize} label="พอดีกรอบ" onClick={fit} />
          </div>
          <div className="absolute bottom-3 left-3 h-6 px-2 rounded-md bg-black/55 backdrop-blur text-[11px] font-mono tabular text-white/80 flex items-center pointer-events-none">
            {natural.width}×{natural.height}px
          </div>
        </>
      )}
    </div>
  );
}
