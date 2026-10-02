"use client";

import React, { useRef, useState } from "react";
import { ScanSearch } from "lucide-react";
import type { AOIPointResult, InspectionResult } from "@/types";
import { classColor } from "@/lib/format";
import { LABEL_FONT, LABEL_HEIGHT, layoutLabels, type NBox } from "@/lib/labelLayout";
import { useElementSize } from "@/hooks/useElementSize";

type Kind = "ok" | "fail" | "review" | "plain";

interface Mark {
  /** Image pixels [x1, y1, x2, y2]. */
  box: [number, number, number, number];
  kind: Kind;
  color: string;
  label: string;
  /** A missing reference point (no box): drawn as a ring with a cross. */
  point?: boolean;
}

const KIND_COLOR: Record<Exclude<Kind, "plain">, string> = { ok: "#22c55e", fail: "#ef4444", review: "#f59e0b" };

/** Black text on light label backgrounds, white on dark ones. */
function textOn(hex: string) {
  const n = parseInt(hex.slice(1), 16);
  return 0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255) > 150 ? "#000" : "#fff";
}

/** Draw timing: boxes reveal top-left → bottom-right within ~0.7 s whatever their count. */
const DRAW_MS = 380;
const SPREAD_MS = 650;
const MAX_STEP_MS = 18;

export type ResultSource = { kind: "point"; point: AOIPointResult } | { kind: "snap"; result: InspectionResult };

function marksOf(item: ResultSource, w: number, h: number): Mark[] {
  if (item.kind === "point" && item.point.component_eval?.length) {
    // Taught point: one slot per expected component (normalized boxes).
    return item.point.component_eval.map((c) => {
      const b = c.expected.box ?? c.expected.bbox ?? [0, 0, 0, 0];
      const kind: Kind = c.status === "confirmed" ? "ok" : c.status === "uncertain" ? "review" : "fail";
      const label =
        c.status === "wrong"
          ? `${c.expected.id} ผิด (${c.wrong_label ?? "?"})`
          : c.status === "missing"
            ? `${c.expected.id} หาย`
            : `${c.expected.id} ${c.expected.name}`;
      return { box: [b[0] * w, b[1] * h, b[2] * w, b[3] * h], kind, color: KIND_COLOR[kind as keyof typeof KIND_COLOR], label };
    });
  }
  const detections = item.kind === "point" ? item.point.detections : item.result.detections;
  // Without a reference every detection comes back EXTRA — that isn't a problem, just a box.
  const compared =
    item.kind === "snap" ? (item.result.reference_eval ?? []).length > 0 : detections.some((d) => d.status === "OK" || d.status === "WRONG");
  const marks: Mark[] = detections.map((d) => {
    const kind: Kind = !compared ? "plain" : d.status === "OK" ? "ok" : d.status === "WRONG" ? "fail" : d.status === "EXTRA" ? "review" : "plain";
    const color = kind === "plain" ? classColor(d.label) : KIND_COLOR[kind];
    const label = kind === "fail" ? `${d.label} ผิด` : kind === "review" ? `${d.label} เกิน` : `${d.label} ${Math.round(d.conf * 100)}%`;
    return { box: d.box, kind, color, label };
  });
  if (item.kind === "snap") {
    for (const e of item.result.reference_eval ?? []) {
      if (e.status !== "MISSING") continue;
      const r = e.ref.tolerance_px ?? Math.max(w, h) * 0.02;
      marks.push({ box: [e.ref.x - r, e.ref.y - r, e.ref.x + r, e.ref.y + r], kind: "fail", color: KIND_COLOR.fail, label: `${e.ref.label} หาย`, point: true });
    }
  }
  return marks;
}

/** Number of marks a result draws (independent of image size). */
function markCount(item: ResultSource) {
  if (item.kind === "point") return item.point.component_eval?.length || item.point.detections.length;
  return item.result.detections.length + (item.result.reference_eval ?? []).filter((e) => e.status === "MISSING").length;
}

/** When the box sweep of `item` finishes (the verdict badge / glow wait for it). */
export function revealDelay(item: ResultSource) {
  const clean = item.kind === "point" ? item.point.image_url : item.result.image_url;
  return clean ? revealMs(markCount(item)) : 0;
}

function revealMs(n: number) {
  if (!n) return 0;
  const step = Math.min(MAX_STEP_MS, SPREAD_MS / n);
  return (n - 1) * step + DRAW_MS;
}

/**
 * Result image with boxes drawn in the browser so they can animate: each box traces its
 * outline in scan order, then OK slots flash a check and problems pulse red rings.
 * Falls back to the server-annotated image when the clean frame isn't available.
 */
export function AnimatedResult({ item }: { item: ResultSource }) {
  const clean = item.kind === "point" ? item.point.image_url : item.result.image_url;
  const annotated = item.kind === "point" ? item.point.annotated_url : item.result.annotated_url;
  const [natural, setNatural] = useState<{ src: string; w: number; h: number } | null>(null);
  const [broken, setBroken] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const size = useElementSize(box);

  const useClean = !!clean && broken !== clean;
  const src = useClean ? clean : annotated || "";
  const dims = natural?.src === src ? natural : null;

  const marks = useClean && dims ? marksOf(item, dims.w, dims.h) : [];
  const order = marks
    .map((m, i) => ({ m, i, key: m.box[0] / (dims?.w || 1) + m.box[1] / (dims?.h || 1) }))
    .sort((a, b) => a.key - b.key)
    .map(({ m }) => m);
  const step = order.length ? Math.min(MAX_STEP_MS, SPREAD_MS / order.length) : 0;
  const done = revealMs(order.length);

  // Map image pixels to screen pixels (object-contain inside the container).
  const scale = dims && size.width ? Math.min(size.width / dims.w, size.height / dims.h) : 0;
  const px = (v: number) => (scale ? v / scale : 0); // screen px -> image px
  const offX = dims ? (size.width - dims.w * scale) / 2 : 0;
  const offY = dims ? (size.height - dims.h * scale) / 2 : 0;

  // Labels: problems always; plain (no reference) results label every box that fits.
  const labelled = order.map((m) => m.kind === "fail" || m.kind === "review" || m.kind === "plain");
  const nboxes: NBox[] = dims ? order.map((m) => [m.box[0] / dims.w, m.box[1] / dims.h, m.box[2] / dims.w, m.box[3] / dims.h]) : [];
  const priority = order.map((m, i) => (m.kind === "fail" ? i : -1)).filter((i) => i >= 0);
  const spots = scale && dims ? layoutLabels(nboxes, order.map((m) => m.label), dims.w * scale, dims.h * scale, priority) : [];

  return (
    <div ref={box} className="absolute inset-0">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt="ภาพผลตรวจ"
        className="absolute inset-0 size-full object-contain"
        onLoad={(e) => {
          const img = e.currentTarget;
          setNatural({ src, w: img.naturalWidth, h: img.naturalHeight });
        }}
        onError={() => useClean && setBroken(clean)}
      />
      {dims && scale > 0 && (
        <svg viewBox={`0 0 ${dims.w} ${dims.h}`} preserveAspectRatio="xMidYMid meet" className="absolute inset-0 size-full pointer-events-none overflow-visible">
          {order.map((m, k) => {
            const delay = k * step;
            const [x1, y1, x2, y2] = m.box;
            const sw = px(m.kind === "fail" ? 3 : 2);
            if (m.point) {
              const r = (x2 - x1) / 2;
              const len = 2 * Math.PI * r;
              return (
                <g key={k}>
                  <circle
                    cx={(x1 + x2) / 2}
                    cy={(y1 + y2) / 2}
                    r={r}
                    fill="none"
                    stroke={m.color}
                    strokeWidth={sw}
                    strokeDasharray={len}
                    className="res-draw"
                    style={{ "--len": len, animationDelay: `${delay}ms` } as React.CSSProperties}
                  />
                  <path
                    d={`M${x1 + r * 0.5},${y1 + r * 0.5}L${x2 - r * 0.5},${y2 - r * 0.5}M${x1 + r * 0.5},${y2 - r * 0.5}L${x2 - r * 0.5},${y1 + r * 0.5}`}
                    stroke={m.color}
                    strokeWidth={sw}
                    className="res-fade"
                    style={{ animationDelay: `${delay + DRAW_MS * 0.6}ms` }}
                  />
                </g>
              );
            }
            const len = 2 * (x2 - x1 + (y2 - y1));
            return (
              <rect
                key={k}
                x={x1}
                y={y1}
                width={x2 - x1}
                height={y2 - y1}
                rx={px(2)}
                fill={m.color}
                stroke={m.color}
                strokeWidth={sw}
                strokeDasharray={len}
                strokeLinejoin="round"
                className="res-draw"
                style={{ "--len": len, animationDelay: `${delay}ms, ${delay + DRAW_MS * 0.6}ms` } as React.CSSProperties}
              />
            );
          })}

          {/* After the sweep: problems pulse, OK slots flash a check. */}
          {order.map((m, k) => {
            const [x1, y1, x2, y2] = m.box;
            const cxp = (x1 + x2) / 2;
            const cyp = (y1 + y2) / 2;
            if (m.kind === "fail") {
              const r = Math.max(Math.hypot(x2 - x1, y2 - y1) / 2, px(14));
              return (
                <circle
                  key={`p${k}`}
                  cx={cxp}
                  cy={cyp}
                  r={r}
                  fill="none"
                  stroke={KIND_COLOR.fail}
                  strokeWidth={px(3)}
                  className="res-ripple"
                  style={{ animationDelay: `${done + (k % 6) * 90}ms` }}
                />
              );
            }
            if (m.kind !== "ok") return null;
            const s = Math.min(px(9), (x2 - x1) * 0.35, (y2 - y1) * 0.35);
            if (s < px(4)) return null;
            return (
              <path
                key={`c${k}`}
                d={`M${cxp - s},${cyp}L${cxp - s * 0.3},${cyp + s * 0.7}L${cxp + s},${cyp - s * 0.6}`}
                fill="none"
                stroke="#fff"
                strokeWidth={px(2.5)}
                strokeLinecap="round"
                strokeLinejoin="round"
                className="res-tick"
                style={{ animationDelay: `${done + k * 6}ms` }}
              />
            );
          })}
        </svg>
      )}

      {/* Labels in screen space (fixed size), placed without overlapping. */}
      {spots.map((s, i) => {
        if (!labelled[i] || (s.hidden && !priority.includes(i)) || !s.width) return null;
        const m = order[i];
        return (
          <span
            key={i}
            className="absolute pointer-events-none whitespace-nowrap rounded-sm px-1 text-white res-fade"
            style={{
              left: offX + s.left,
              top: offY + s.top,
              height: LABEL_HEIGHT,
              lineHeight: `${LABEL_HEIGHT}px`,
              font: LABEL_FONT,
              background: m.color,
              color: textOn(m.color),
              animationDelay: `${m.kind === "plain" ? i * step + DRAW_MS : done}ms`,
            }}
          >
            {m.label}
          </span>
        );
      })}
    </div>
  );
}

/** The frozen frame being analyzed, with a sweep line — shown until the result arrives. */
export function AnalyzingFrame({ image, label }: { image: string | null; label: string }) {
  return (
    <div className="absolute inset-0 animate-fade">
      {image ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={image} alt="ภาพที่กำลังวิเคราะห์" className="absolute inset-0 size-full object-contain brightness-75 saturate-50" />
      ) : (
        <div className="absolute inset-0 bg-viewport" />
      )}
      <div className="absolute inset-0 res-grid pointer-events-none" />
      <div className="absolute inset-x-0 h-0.5 bg-cyan-300/90 shadow-[0_0_14px_3px_rgb(103_232_249/0.6)] animate-scanline pointer-events-none" />
      <div className="absolute inset-0 grid place-items-center pointer-events-none">
        <span className="h-8 px-3 rounded-full bg-black/65 backdrop-blur text-sm text-white flex items-center gap-2 animate-pop">
          <ScanSearch className="size-4 text-cyan-300 animate-pulse" />
          กำลังวิเคราะห์… <span className="text-white/60 text-xs">{label}</span>
        </span>
      </div>
    </div>
  );
}
