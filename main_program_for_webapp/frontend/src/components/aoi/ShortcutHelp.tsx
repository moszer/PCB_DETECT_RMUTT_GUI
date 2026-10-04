"use client";

import React, { useEffect, useRef } from "react";
import { Compass, X } from "lucide-react";
import { Button } from "../ui";

export const SHORTCUTS: Array<[string, string]> = [
  ["← ↑ → ↓", "จ๊อกสเตจตามระยะที่เลือก"],
  ["Shift + ลูกศร", "จ๊อกระยะ ×10"],
  ["M", "มาร์คตำแหน่งปัจจุบัน"],
  ["Space", "ถ่ายทดสอบ"],
  ["H", "HOME สเตจ"],
  ["1 – 5", "ซูม 1× 1.5× 2× 3× 4×"],
  ["?", "เปิด/ปิดหน้านี้"],
];

/** Keyboard shortcut sheet for the AOI page, with a way back into the guided tour. */
export function ShortcutHelp({ onClose, onTour, operator }: { onClose: () => void; onTour: () => void; operator: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDown = (e: PointerEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node) && !(e.target as HTMLElement).closest("[data-help-toggle]")) onClose();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);
  const rows = operator ? SHORTCUTS.filter(([k]) => k === "Space" || k === "?") : SHORTCUTS;
  return (
    <div ref={ref} className="absolute right-0 top-10 z-30 w-80 rounded-xl border border-line bg-surface shadow-pop p-3 flex flex-col gap-2 animate-rise">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold">คีย์ลัด</span>
        <button
          type="button"
          onClick={onClose}
          aria-label="ปิด"
          className="size-6 grid place-items-center rounded text-muted hover:bg-surface-2 cursor-pointer"
        >
          <X className="size-4" />
        </button>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
        {rows.map(([key, what]) => (
          <React.Fragment key={key}>
            <dt>
              <kbd className="px-1.5 py-0.5 rounded border border-line-strong bg-surface-2 font-mono text-xs whitespace-nowrap">{key}</kbd>
            </dt>
            <dd className="text-muted">{what}</dd>
          </React.Fragment>
        ))}
      </dl>
      {operator && <p className="text-xs text-muted">โหมดผู้ใช้งานปิดคีย์ที่สั่งเคลื่อนที่ สลับเป็นโหมดวิศวกรเพื่อจ๊อกและมาร์คจุด</p>}
      <Button size="sm" icon={Compass} onClick={onTour} className="self-start">
        ดูทัวร์แนะนำอีกครั้ง
      </Button>
    </div>
  );
}
