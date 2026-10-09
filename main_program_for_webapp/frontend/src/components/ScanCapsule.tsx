"use client";

import React from "react";
import { Check, TriangleAlert, X } from "lucide-react";
import { cx } from "./ui";

/** What the machine is doing at a scan point, in the order it happens. */
export type ScanPhase = "align" | "move" | "settle" | "analyze" | "pass" | "fail" | "review";

/**
 * Floating glass status capsule over a camera picture (Dynamic-Island-like). Each phase has its
 * own icon; a new phase or title pops in, so the capsule seems to morph between states.
 */
export function ScanCapsule({ phase, title, detail, top }: { phase: ScanPhase; title: string; detail?: string; /** px from the top (default under the HUD pills) */ top?: number }) {
  return (
    <div
      className={cx("scan-capsule pointer-events-none", phase === "pass" && "is-pass", phase === "fail" && "is-fail", phase === "review" && "is-review")}
      style={top !== undefined ? { top } : undefined}
      role="status"
      aria-live="polite"
    >
      <div key={`${phase}:${title}`} className="scan-capsule-body">
        <PhaseIcon phase={phase} />
        <span className={cx("font-semibold whitespace-nowrap", phase === "analyze" && "scan-capsule-shimmer")}>{title}</span>
        {detail && <span className="min-w-0 truncate text-white/70 font-medium">{detail}</span>}
      </div>
    </div>
  );
}

function PhaseIcon({ phase }: { phase: ScanPhase }) {
  if (phase === "pass") return <Check className="size-4 shrink-0 text-emerald-300" strokeWidth={3} aria-hidden="true" />;
  if (phase === "review") return <TriangleAlert className="size-4 shrink-0 text-amber-300" strokeWidth={2.5} aria-hidden="true" />;
  if (phase === "fail") return <X className="size-4 shrink-0 text-red-300" strokeWidth={3} aria-hidden="true" />;
  if (phase === "settle")
    return (
      <svg className="size-4 shrink-0 scan-capsule-ring" viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="9" fill="none" stroke="rgb(255 255 255 / 0.25)" strokeWidth="3" />
        <circle cx="12" cy="12" r="9" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeDasharray="57" transform="rotate(-90 12 12)" />
      </svg>
    );
  if (phase === "analyze") return <span className="scan-capsule-orb shrink-0" aria-hidden="true" />;
  return <span className="scan-capsule-spin shrink-0" aria-hidden="true" />;
}

/**
 * Picture effects for a scan point (inside a rounded, overflow-hidden picture box):
 * focus brackets closing in while the stage settles, a flash when the frame is taken,
 * and the rainbow light with a soft sweep while the AI analyses.
 */
export function ScanEffects({ phase }: { phase: "settle" | "analyze" | null }) {
  if (!phase) return null;
  return (
    <div className="absolute inset-0 rounded-[inherit] pointer-events-none" aria-hidden="true">
      {phase === "settle" && (
        <svg className="scan-focus" viewBox="0 0 100 100" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round">
          <path vectorEffect="non-scaling-stroke" d="M2 18V8a6 6 0 0 1 6-6h10M82 2h10a6 6 0 0 1 6 6v10M98 82v10a6 6 0 0 1-6 6H82M18 98H8a6 6 0 0 1-6-6V82" />
        </svg>
      )}
      {phase === "analyze" && (
        <>
          <span className="scan-flash" />
          <span className="scan-sweep" />
          <span className="scan-edge">
            <span />
          </span>
          <span className="scan-ring" />
        </>
      )}
    </div>
  );
}
