"use client";

import React from "react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Lock, Minimize2, Move } from "lucide-react";
import { useHoldRepeat } from "@/hooks/useHoldRepeat";
import { cx } from "../ui";

export const JOG_STEPS = [0.1, 0.5, 1, 5, 10];

/**
 * Compact jog pad drawn over the live camera, so the stage can be nudged while looking
 * at the board (no trip to the "เคลื่อนที่" tab). Hold a button to keep moving; the
 * center chip cycles the step size.
 */
export function JogOverlay({
  step,
  onStep,
  onJog,
  reason,
  collapsed,
  onCollapsed,
}: {
  step: number;
  onStep: (step: number) => void;
  /** Resolves false when the move failed, which stops a held button. */
  onJog: (dx: number, dy: number) => Promise<boolean>;
  /** Why jogging is unavailable right now (null when it is). */
  reason: string | null;
  collapsed: boolean;
  onCollapsed: (collapsed: boolean) => void;
}) {
  const hold = useHoldRepeat();
  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => onCollapsed(false)}
        title="แสดงปุ่มจ๊อก"
        className="absolute left-3 bottom-12 size-9 pointer-coarse:size-12 grid place-items-center rounded-lg bg-black/55 backdrop-blur text-white/80 hover:text-white cursor-pointer"
      >
        <Move className="size-4" />
      </button>
    );
  }
  const off = reason !== null;
  const btn = cx(
    "size-9 pointer-coarse:size-12 grid place-items-center rounded-md text-white transition touch-none",
    off ? "opacity-35 cursor-not-allowed" : "bg-white/10 hover:bg-white/25 active:bg-white/35 active:scale-95 cursor-pointer"
  );
  const pad = (dx: number, dy: number, Icon: typeof ArrowUp, label: string) => (
    <button
      type="button"
      className={btn}
      disabled={off}
      aria-label={`${label} ${step} mm`}
      title={off ? reason : `${label} ${step} mm`}
      {...hold(() => onJog(dx * step, dy * step))}
    >
      <Icon className="size-4" />
    </button>
  );
  const nextStep = JOG_STEPS[(JOG_STEPS.indexOf(step) + 1) % JOG_STEPS.length] ?? 1;
  return (
    <div className="absolute left-3 bottom-12 rounded-xl bg-black/55 backdrop-blur p-1.5 text-white flex flex-col gap-1 animate-fade" aria-label="จ๊อกสเตจ">
      <div className="flex items-center justify-between px-0.5 text-[10px] text-white/70">
        <span className="flex items-center gap-1 min-w-0 max-w-28 pointer-coarse:max-w-36">
          {off ? <Lock className="size-3 shrink-0" /> : <Move className="size-3 shrink-0" />}
          <span className="truncate">{off ? reason : "จ๊อก · ปุ่มลูกศร"}</span>
        </span>
        <button
          type="button"
          onClick={() => onCollapsed(true)}
          title="ซ่อนปุ่มจ๊อก"
          className="size-5 grid place-items-center rounded hover:bg-white/15 cursor-pointer"
        >
          <Minimize2 className="size-3" />
        </button>
      </div>
      <div className="grid grid-cols-3 gap-1">
        <span />
        {pad(0, 1, ArrowUp, "Y+")}
        <span />
        {pad(-1, 0, ArrowLeft, "X-")}
        <button
          type="button"
          onClick={() => onStep(nextStep)}
          title={`ระยะต่อครั้ง ${step} mm — คลิกเพื่อเปลี่ยน (Shift+ลูกศร = ×10)`}
          className="size-9 pointer-coarse:size-12 rounded-md bg-white/15 hover:bg-white/25 font-mono text-[11px] font-semibold leading-none cursor-pointer flex flex-col items-center justify-center"
        >
          {step}
          <span className="text-[9px] font-normal text-white/60">mm</span>
        </button>
        {pad(1, 0, ArrowRight, "X+")}
        <span />
        {pad(0, -1, ArrowDown, "Y-")}
        <span />
      </div>
    </div>
  );
}
