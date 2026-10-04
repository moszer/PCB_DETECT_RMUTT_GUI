"use client";

import React, { useEffect, useRef, useState } from "react";
import { Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import { cx } from "./ui";

const MIN = 1;
const STEP = 1.25;
const PAN_START_PX = 6; // more than BoxOverlay's 5 px click tolerance, so a pan never clicks

type View = { s: number; x: number; y: number };

/**
 * Zoom and pan any content (an image with boxes): mouse wheel or pinch to zoom around the
 * pointer, drag to pan once zoomed in, double-click / double-tap to toggle 2.5×, and
 * +/−/fit buttons. With `panWithDrag` off (drawing or marquee selection), pan with the
 * middle mouse button, Space + drag, or two fingers.
 */
export function ZoomPan({
  children,
  className,
  max = 8,
  panWithDrag = true,
}: {
  children: React.ReactNode;
  className?: string;
  max?: number;
  panWithDrag?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<View>({ s: 1, x: 0, y: 0 });
  const viewRef = useRef(view);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const gesture = useRef<{ startX: number; startY: number; vx: number; vy: number; panning: boolean; dist: number; s: number; mid: { x: number; y: number } } | null>(null);
  const space = useRef(false);
  const lastTap = useRef(0);

  useEffect(() => {
    viewRef.current = view;
  });

  // Keep the content covering the frame (no empty margins when zoomed).
  const clamp = (v: View): View => {
    const el = box.current;
    if (!el) return v;
    const s = Math.min(max, Math.max(MIN, v.s));
    const w = el.clientWidth;
    const h = el.clientHeight;
    return { s, x: Math.min(0, Math.max(w * (1 - s), v.x)), y: Math.min(0, Math.max(h * (1 - s), v.y)) };
  };

  /** Zoom to scale `s` (or by `factor` of the current scale) keeping (px, py) still. */
  const zoomAt = (s: number | { factor: number }, px: number, py: number) =>
    setView((v) => {
      const next = Math.min(max, Math.max(MIN, typeof s === "number" ? s : v.s * s.factor));
      return clamp({ s: next, x: px - ((px - v.x) * next) / v.s, y: py - ((py - v.y) * next) / v.s });
    });

  const local = (clientX: number, clientY: number) => {
    const r = box.current!.getBoundingClientRect();
    return { x: clientX - r.left, y: clientY - r.top };
  };

  // Native wheel listener: React's is passive, so it could not stop the page from scrolling.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      const zoomingOutAtFit = e.deltaY > 0 && viewRef.current.s <= MIN;
      if (zoomingOutAtFit) return; // let the page scroll
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const factor = Math.exp(-Math.max(-60, Math.min(60, e.deltaY)) * 0.006);
      const v = viewRef.current;
      const next = Math.min(max, Math.max(MIN, v.s * factor));
      const px = e.clientX - r.left;
      const py = e.clientY - r.top;
      setView(clampWith(el, max, { s: next, x: px - ((px - v.x) * next) / v.s, y: py - ((py - v.y) * next) / v.s }));
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.code === "Space" && !(e.target as HTMLElement)?.closest("input, textarea")) space.current = e.type === "keydown";
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKey);
    return () => {
      el.removeEventListener("wheel", onWheel);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKey);
    };
  }, [max]);

  const onPointerDown = (e: React.PointerEvent) => {
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const pts = [...pointers.current.values()];
    const v = viewRef.current;
    if (pts.length === 1) {
      gesture.current = { startX: e.clientX, startY: e.clientY, vx: v.x, vy: v.y, panning: false, dist: 0, s: v.s, mid: { x: 0, y: 0 } };
      if (e.button === 1 || space.current) {
        e.preventDefault();
        gesture.current.panning = true;
        e.stopPropagation(); // not a click on the content
      }
      // Double-tap (touch) / double-click: toggle 2.5×.
      const now = Date.now();
      if (now - lastTap.current < 300) {
        const p = local(e.clientX, e.clientY);
        zoomAt(v.s > 1.05 ? 1 : 2.5, p.x, p.y);
        lastTap.current = 0;
      } else lastTap.current = now;
    } else if (pts.length === 2) {
      const mid = local((pts[0].x + pts[1].x) / 2, (pts[0].y + pts[1].y) / 2);
      gesture.current = { startX: 0, startY: 0, vx: v.x, vy: v.y, panning: true, dist: Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y), s: v.s, mid };
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const g = gesture.current;
    if (!g || !pointers.current.has(e.pointerId)) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const pts = [...pointers.current.values()];
    if (pts.length === 2 && g.dist) {
      const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      const mid = local((pts[0].x + pts[1].x) / 2, (pts[0].y + pts[1].y) / 2);
      const next = Math.min(max, Math.max(MIN, (g.s * dist) / g.dist));
      // Zoom around the starting midpoint, then follow the fingers.
      setView(clamp({ s: next, x: g.mid.x - ((g.mid.x - g.vx) * next) / g.s + (mid.x - g.mid.x), y: g.mid.y - ((g.mid.y - g.vy) * next) / g.s + (mid.y - g.mid.y) }));
      return;
    }
    if (pts.length !== 1) return;
    const dx = e.clientX - g.startX;
    const dy = e.clientY - g.startY;
    if (!g.panning && panWithDrag && viewRef.current.s > MIN && Math.hypot(dx, dy) > PAN_START_PX) g.panning = true;
    if (g.panning) setView(clamp({ s: viewRef.current.s, x: g.vx + dx, y: g.vy + dy }));
  };

  const onPointerEnd = (e: React.PointerEvent) => {
    pointers.current.delete(e.pointerId);
    const rest = [...pointers.current.values()];
    if (!rest.length) gesture.current = null;
    else if (rest.length === 1) {
      const v = viewRef.current;
      gesture.current = { startX: rest[0].x, startY: rest[0].y, vx: v.x, vy: v.y, panning: true, dist: 0, s: v.s, mid: { x: 0, y: 0 } };
    }
  };

  const center = () => {
    const el = box.current;
    return el ? { x: el.clientWidth / 2, y: el.clientHeight / 2 } : { x: 0, y: 0 };
  };
  const zoomed = view.s > MIN + 0.01;

  return (
    <div
      ref={box}
      className={cx("relative overflow-hidden", zoomed ? "touch-none" : "touch-pan-x touch-pan-y", className)}
      onPointerDownCapture={onPointerDown}
      onPointerMoveCapture={onPointerMove}
      onPointerUpCapture={onPointerEnd}
      onPointerCancelCapture={onPointerEnd}
      onAuxClick={(e) => e.preventDefault()}
    >
      <div
        className="origin-top-left will-change-transform"
        style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})` }}
      >
        {children}
      </div>

      <div className="absolute bottom-2 right-2 z-10 flex items-center gap-0.5 rounded-lg bg-black/60 backdrop-blur p-0.5 text-white" onPointerDownCapture={(e) => e.stopPropagation()}>
        <ZoomButton label="ซูมออก" disabled={!zoomed} onClick={() => zoomAt({ factor: 1 / STEP }, center().x, center().y)}>
          <ZoomOut className="size-4" />
        </ZoomButton>
        <button
          type="button"
          onClick={() => setView({ s: 1, x: 0, y: 0 })}
          title="พอดีกรอบ"
          className="h-7 pointer-coarse:h-9 min-w-12 px-1.5 rounded-md text-[11px] font-mono tabular hover:bg-white/15 cursor-pointer"
        >
          {Math.round(view.s * 100)}%
        </button>
        <ZoomButton label="ซูมเข้า" disabled={view.s >= max} onClick={() => zoomAt({ factor: STEP }, center().x, center().y)}>
          <ZoomIn className="size-4" />
        </ZoomButton>
        {zoomed && (
          <ZoomButton label="พอดีกรอบ" onClick={() => setView({ s: 1, x: 0, y: 0 })}>
            <Maximize2 className="size-3.5" />
          </ZoomButton>
        )}
      </div>
    </div>
  );
}

function clampWith(el: HTMLElement, max: number, v: View): View {
  const s = Math.min(max, Math.max(MIN, v.s));
  return { s, x: Math.min(0, Math.max(el.clientWidth * (1 - s), v.x)), y: Math.min(0, Math.max(el.clientHeight * (1 - s), v.y)) };
}

function ZoomButton({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="size-7 pointer-coarse:size-9 grid place-items-center rounded-md hover:bg-white/15 cursor-pointer disabled:opacity-40 disabled:cursor-default"
    >
      {children}
    </button>
  );
}
