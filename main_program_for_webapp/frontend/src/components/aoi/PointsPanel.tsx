"use client";

import React from "react";
import { Crosshair, MapPin, Navigation, Plus, Trash2 } from "lucide-react";
import type { CustomPointRequest } from "@/types";
import { formatMm } from "@/lib/format";
import { Badge, Button, EmptyState, SectionLabel, cx } from "../ui";

interface PointsPanelProps {
  points: CustomPointRequest[];
  selected: number;
  onSelect: (index: number) => void;
  /** Zoom new points are marked with (set on the live view). */
  zoom: number;
  onRename: (index: number, name: string) => void;
  onSetPointZoom: (index: number, zoom: number) => void;
  onMark: () => void;
  onMove: (index: number) => void;
  onEditReference: (index: number) => void;
  onDelete: (index: number) => void;
  onClear: () => void;
  marking: boolean;
  movingIndex: number | null;
  /** Why the stage can't be moved/marked right now (null when it can). */
  markReason: string | null;
  /** Editing points is off (scanning, or someone else controls the station). */
  locked: boolean;
  /** Point currently being scanned (highlighted in the list). */
  scanningIndex?: number | null;
  boardName: string;
}

const ZOOMS = [1, 1.5, 2, 3, 4];

export function PointsPanel(p: PointsPanelProps) {
  const taught = p.points.filter((pt) => pt.expected_components?.length).length;
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <Button
          variant="success"
          size="lg"
          icon={p.marking ? undefined : Plus}
          loading={p.marking}
          disabled={p.markReason !== null}
          reason={p.markReason}
          onClick={p.onMark}
          data-tour="mark"
        >
          {p.marking ? "กำลังถ่ายต้นแบบ…" : (p.markReason ?? "มาร์คตำแหน่งปัจจุบัน")}
          {!p.marking && p.markReason === null && <kbd className="ml-1 pointer-coarse:hidden px-1.5 rounded bg-white/20 text-[11px] font-mono font-normal">M</kbd>}
        </Button>
        <p className="text-xs leading-snug text-muted">
          จ๊อกสเตจบนภาพสดไปยังบริเวณที่ต้องการตรวจแล้วกดมาร์ค ระบบบันทึกพิกัดและถ่ายภาพต้นแบบ (ซูม {p.zoom}×) ลงบอร์ด “{p.boardName}” ให้อัตโนมัติ
        </p>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <SectionLabel>
            จุดตรวจ ({p.points.length}) · มีต้นแบบ {taught}
          </SectionLabel>
          {p.points.length > 0 && (
            <button type="button" onClick={p.onClear} disabled={p.locked} className="text-xs text-fail hover:underline cursor-pointer disabled:opacity-40">
              ลบทั้งหมด
            </button>
          )}
        </div>

        {p.points.length === 0 ? (
          <EmptyState icon={MapPin} title="ยังไม่มีจุดตรวจ" className="rounded-lg border border-dashed border-line py-8">
            จ๊อกไปยังจุดที่ต้องการ แล้วกด “มาร์คตำแหน่งปัจจุบัน” (หรือกด M)
          </EmptyState>
        ) : (
          <ul className="rounded-lg border border-line divide-y divide-line overflow-hidden">
            {p.points.map((pt, i) => {
              const active = i === p.selected;
              const parts = pt.expected_components?.length ?? 0;
              const moving = p.movingIndex === i;
              const live = p.scanningIndex === i;
              return (
                <li key={pt.id ?? i} className={cx("transition-colors animate-rise", active || live ? "bg-accent-soft" : "hover:bg-surface-2")}>
                  <div className="flex items-center gap-2 px-2.5 py-2 cursor-pointer" onClick={() => p.onSelect(i)}>
                    <span
                      className={cx(
                        "size-6 rounded-md grid place-items-center text-[11px] font-mono font-semibold shrink-0",
                        active || live ? "bg-accent text-on-accent" : "bg-surface-3 text-muted",
                        live && "animate-ring"
                      )}
                    >
                      {i + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      {active ? (
                        <input
                          aria-label="ชื่อจุด"
                          value={pt.name ?? ""}
                          disabled={p.locked}
                          onChange={(e) => p.onRename(i, e.target.value)}
                          onClick={(e) => e.stopPropagation()}
                          className="w-full bg-transparent text-sm font-medium focus:outline-none border-b border-transparent focus:border-accent"
                        />
                      ) : (
                        <div className="text-sm font-medium truncate">{pt.name || `จุด ${i + 1}`}</div>
                      )}
                      <div className="text-[11px] font-mono tabular text-muted">
                        {formatMm(pt.x_mm)}, {formatMm(pt.y_mm)} mm · {pt.zoom || 1}×
                      </div>
                    </div>
                    {parts ? <Badge tone="info">{parts} ชิ้น</Badge> : <Badge tone="review">ไม่มีต้นแบบ</Badge>}
                  </div>
                  {active && (
                    <div className="flex items-center gap-1 px-2.5 pb-2 flex-wrap">
                      <Button size="sm" icon={moving ? undefined : Navigation} loading={moving} disabled={p.markReason !== null} onClick={() => p.onMove(i)}>
                        ไปที่จุด
                      </Button>
                      <Button size="sm" icon={Crosshair} disabled={p.locked} onClick={() => p.onEditReference(i)}>
                        {parts ? "แก้ต้นแบบ" : "สอนต้นแบบ"}
                      </Button>
                      <select
                        aria-label="ซูมของจุด"
                        value={pt.zoom || 1}
                        disabled={p.locked}
                        onChange={(e) => p.onSetPointZoom(i, Number(e.target.value))}
                        className="h-8 rounded-md border border-line bg-surface px-1.5 text-xs cursor-pointer"
                      >
                        {ZOOMS.map((z) => (
                          <option key={z} value={z}>
                            {z}×
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        aria-label="ลบจุดนี้"
                        disabled={p.locked}
                        onClick={() => p.onDelete(i)}
                        className="ml-auto size-8 grid place-items-center rounded-md text-subtle hover:text-fail hover:bg-fail-soft cursor-pointer disabled:opacity-40"
                      >
                        <Trash2 className="size-4" />
                      </button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
