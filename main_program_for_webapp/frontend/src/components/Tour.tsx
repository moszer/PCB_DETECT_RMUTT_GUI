"use client";

import React, { useEffect, useState } from "react";
import { X } from "lucide-react";
import { Button } from "./ui";

export interface TourStep {
  /** `data-tour` value of the element to point at; missing elements get a centered card. */
  target: string;
  title: string;
  body: React.ReactNode;
}

type Box = { top: number; left: number; width: number; height: number };
const CARD_W = 340;
const PAD = 6;

/**
 * Step-by-step spotlight over the page. Mount it only while open (closing unmounts it,
 * so it restarts at step 1 next time). ←/→ or Enter to move, Esc to leave.
 */
export function Tour({ steps, onClose }: { steps: TourStep[]; onClose: () => void }) {
  const [index, setIndex] = useState(0);
  const [box, setBox] = useState<Box | null>(null);
  const step = steps[index];
  const last = index === steps.length - 1;

  // Follow the target: it can move as panels resize or the page scrolls.
  useEffect(() => {
    const el = document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`);
    el?.scrollIntoView({ block: "nearest", inline: "nearest" });
    let frame = 0;
    let prev = "";
    const measure = () => {
      const r = el?.getBoundingClientRect();
      const next = r && r.width > 0 ? { top: r.top, left: r.left, width: r.width, height: r.height } : null;
      const key = JSON.stringify(next);
      if (key !== prev) {
        prev = key;
        setBox(next);
      }
      frame = requestAnimationFrame(measure);
    };
    frame = requestAnimationFrame(measure);
    return () => cancelAnimationFrame(frame);
  }, [step.target]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" || e.key === "Enter") {
        if (e.key === "Enter" && (e.target as HTMLElement).closest("button")) return; // the button handles it
        e.preventDefault();
        if (index < steps.length - 1) setIndex(index + 1);
        else onClose();
      } else if (e.key === "ArrowLeft" && index > 0) setIndex(index - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, steps.length, onClose]);

  const vw = typeof window === "undefined" ? 1280 : window.innerWidth;
  const vh = typeof window === "undefined" ? 800 : window.innerHeight;
  const width = Math.min(CARD_W, vw - 24);
  let cardStyle: React.CSSProperties = { width, left: (vw - width) / 2, top: vh / 2 - 100 };
  if (box) {
    const below = box.top + box.height + PAD + 12;
    const roomBelow = vh - below > 200;
    const roomRight = vw - (box.left + box.width) > width + 24;
    if (roomBelow) cardStyle = { width, top: below, left: clamp(box.left, 12, vw - width - 12) };
    else if (box.top > 220) cardStyle = { width, bottom: vh - box.top + PAD + 12, left: clamp(box.left, 12, vw - width - 12) };
    else if (roomRight) cardStyle = { width, top: clamp(box.top, 12, vh - 240), left: box.left + box.width + PAD + 12 };
    else cardStyle = { width, top: clamp(box.top + 16, 12, vh - 240), left: clamp(box.left + 16, 12, vw - width - 12) };
  }

  return (
    <div className="fixed inset-0 z-[90]" role="dialog" aria-modal="true" aria-label="ทัวร์แนะนำการใช้งาน">
      {box ? (
        <div
          className="absolute rounded-xl ring-2 ring-accent transition-all duration-300 ease-out pointer-events-none"
          style={{
            top: box.top - PAD,
            left: box.left - PAD,
            width: box.width + PAD * 2,
            height: box.height + PAD * 2,
            boxShadow: "0 0 0 9999px rgb(0 0 0 / 0.62)",
          }}
        />
      ) : (
        <div className="absolute inset-0 bg-black/60" />
      )}
      <div key={index} className="absolute rounded-xl border border-line bg-surface shadow-pop p-4 flex flex-col gap-2 animate-rise" style={cardStyle}>
        <div className="flex items-start gap-2">
          <span className="text-xs font-mono text-accent mt-0.5">
            {index + 1}/{steps.length}
          </span>
          <h3 className="flex-1 text-sm font-semibold">{step.title}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="ปิดทัวร์"
            className="size-6 grid place-items-center rounded text-muted hover:bg-surface-2 cursor-pointer"
          >
            <X className="size-4" />
          </button>
        </div>
        <div className="text-sm text-muted leading-relaxed">{step.body}</div>
        <div className="flex items-center gap-2 pt-1">
          <div className="flex gap-1">
            {steps.map((s, i) => (
              <span key={s.target} className={i === index ? "h-1.5 w-4 rounded-full bg-accent" : "size-1.5 rounded-full bg-line-strong"} />
            ))}
          </div>
          <div className="ml-auto flex gap-1.5">
            {index > 0 && (
              <Button size="sm" variant="ghost" onClick={() => setIndex(index - 1)}>
                ย้อนกลับ
              </Button>
            )}
            <Button size="sm" variant="primary" autoFocus onClick={() => (last ? onClose() : setIndex(index + 1))}>
              {last ? "เริ่มใช้งาน" : "ถัดไป"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
