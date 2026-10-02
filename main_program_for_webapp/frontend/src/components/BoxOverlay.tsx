"use client";

import React, { useMemo, useRef, useState } from "react";
import { useElementSize } from "@/hooks/useElementSize";
import { LABEL_FONT, LABEL_HEIGHT, layoutLabels, paintOrder, pickAt, type NBox } from "@/lib/labelLayout";
import { Segmented, cx } from "./ui";

export type LabelMode = "all" | "focus" | "none";

export interface OverlayBox {
  bbox: NBox;
  label: string;
  /** #rrggbb */
  color: string;
  dashed?: boolean;
}

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

/** Black text on light label backgrounds, white on dark ones. */
function textOn(hex: string) {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? "#000" : "#fff";
}

export function LabelModeSwitch({ value, onChange }: { value: LabelMode; onChange: (m: LabelMode) => void }) {
  return (
    <Segmented
      size="sm"
      value={value}
      onChange={onChange}
      options={[
        { value: "all", label: "ป้ายทั้งหมด" },
        { value: "focus", label: "เฉพาะที่เลือก" },
        { value: "none", label: "ซ่อนป้าย" },
      ]}
    />
  );
}

/**
 * Image with clickable boxes. Labels are auto-placed so they don't cover each other,
 * small boxes are painted above large ones, and clicking the same spot again cycles
 * through stacked boxes. Optional drag-to-draw.
 */
export function BoxOverlay({
  src,
  alt,
  boxes,
  selected,
  hovered = null,
  labelMode = "all",
  onSelect,
  drawing = false,
  onDraw,
  className,
}: {
  src: string;
  alt: string;
  boxes: OverlayBox[];
  selected: number | null;
  hovered?: number | null;
  labelMode?: LabelMode;
  onSelect?: (index: number | null) => void;
  drawing?: boolean;
  onDraw?: (bbox: NBox) => void;
  className?: string;
}) {
  const surface = useRef<HTMLDivElement>(null);
  const { width, height } = useElementSize(surface);
  const [draft, setDraft] = useState<NBox | null>(null);
  const down = useRef<{ x: number; y: number; px: number; py: number } | null>(null);

  const nboxes = useMemo(() => boxes.map((b) => b.bbox), [boxes]);
  const focus = useMemo(() => [selected, hovered].filter((i): i is number => i !== null && i < boxes.length), [selected, hovered, boxes.length]);
  const spots = useMemo(
    () => (labelMode === "none" ? [] : layoutLabels(nboxes, boxes.map((b) => b.label), width, height, focus)),
    [labelMode, nboxes, boxes, width, height, focus]
  );
  const order = paintOrder(nboxes, [hovered !== selected ? hovered : null, selected]);
  const hiddenCount = labelMode === "all" ? spots.filter((s, i) => s.hidden && !focus.includes(i)).length : 0;

  const point = (e: React.PointerEvent) => {
    const r = surface.current!.getBoundingClientRect();
    return { x: clamp01((e.clientX - r.left) / r.width), y: clamp01((e.clientY - r.top) / r.height), px: e.clientX, py: e.clientY };
  };

  return (
    <div className={cx("relative rounded-xl overflow-hidden bg-viewport border border-line", className)}>
      <div
        ref={surface}
        className={cx("relative select-none touch-none", drawing ? "cursor-crosshair" : "cursor-pointer")}
        onPointerDown={(e) => {
          down.current = point(e);
          if (drawing) {
            surface.current!.setPointerCapture(e.pointerId);
            setDraft([down.current.x, down.current.y, down.current.x, down.current.y]);
          }
        }}
        onPointerMove={(e) => {
          if (!drawing || !down.current) return;
          const p = point(e);
          setDraft([down.current.x, down.current.y, p.x, p.y]);
        }}
        onPointerUp={(e) => {
          const start = down.current;
          down.current = null;
          if (!start) return;
          const p = point(e);
          if (drawing) {
            setDraft(null);
            const bbox: NBox = [Math.min(start.x, p.x), Math.min(start.y, p.y), Math.max(start.x, p.x), Math.max(start.y, p.y)];
            if (bbox[2] - bbox[0] > 0.004 && bbox[3] - bbox[1] > 0.004) onDraw?.(bbox);
          } else if (Math.hypot(p.px - start.px, p.py - start.py) < 5) {
            onSelect?.(pickAt(nboxes, p.x, p.y, selected));
          }
        }}
        onPointerCancel={() => {
          down.current = null;
          setDraft(null);
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt={alt} draggable={false} className="w-full block pointer-events-none" />

        {order.map((i) => {
          const b = boxes[i];
          const [x1, y1, x2, y2] = b.bbox;
          const active = i === selected || i === hovered;
          return (
            <div
              key={i}
              className="absolute pointer-events-none"
              style={{
                left: `${x1 * 100}%`,
                top: `${y1 * 100}%`,
                width: `${(x2 - x1) * 100}%`,
                height: `${(y2 - y1) * 100}%`,
                border: `${i === selected ? 3 : 2}px ${b.dashed ? "dashed" : "solid"} ${b.color}`,
                background: `${b.color}${active ? "40" : "14"}`,
                boxShadow: i === selected ? "0 0 0 1px #fff" : undefined,
              }}
            />
          );
        })}

        {/* Labels in their own layer above every box. */}
        {spots.map((s, i) => {
          const visible = labelMode === "all" ? !s.hidden || focus.includes(i) : labelMode === "focus" && focus.includes(i);
          if (!visible || !s.width) return null;
          const b = boxes[i];
          return (
            <span
              key={i}
              className="absolute pointer-events-none whitespace-nowrap rounded-sm px-1"
              style={{
                left: s.left,
                top: s.top,
                height: LABEL_HEIGHT,
                lineHeight: `${LABEL_HEIGHT}px`,
                font: LABEL_FONT,
                background: b.color,
                color: textOn(b.color),
                outline: focus.includes(i) ? "1px solid #fff" : undefined,
                zIndex: focus.includes(i) ? 3 : 2,
              }}
            >
              {b.label}
            </span>
          );
        })}

        {draft && (
          <div
            className="absolute border-2 border-dashed border-white pointer-events-none"
            style={{
              left: `${Math.min(draft[0], draft[2]) * 100}%`,
              top: `${Math.min(draft[1], draft[3]) * 100}%`,
              width: `${Math.abs(draft[2] - draft[0]) * 100}%`,
              height: `${Math.abs(draft[3] - draft[1]) * 100}%`,
            }}
          />
        )}
      </div>
      {hiddenCount > 0 && (
        <span className="absolute bottom-2 right-2 h-6 px-2 rounded-md bg-black/65 text-[11px] text-white flex items-center pointer-events-none">
          ซ่อน {hiddenCount} ป้ายที่ทับกัน — คลิกกรอบหรือชี้รายการเพื่อดู
        </span>
      )}
    </div>
  );
}
