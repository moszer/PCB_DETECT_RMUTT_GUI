"use client";

import React from "react";
import { Crosshair, Layers, Loader2, MapPin, Navigation, Play, Plus, Sparkles, Trash2 } from "lucide-react";
import type { CustomPointRequest } from "@/types";
import { formatMm } from "@/lib/format";
import { Badge, Button, EmptyState, SectionLabel, Segmented, cx } from "../ui";

interface PointsPanelProps {
  points: CustomPointRequest[];
  selected: number;
  onSelect: (index: number) => void;
  zoom: number;
  onZoom: (zoom: number) => void;
  onRename: (index: number, name: string) => void;
  onSetPointZoom: (index: number, zoom: number) => void;
  onMark: () => void;
  onMove: (index: number) => void;
  onEditReference: (index: number) => void;
  onDelete: (index: number) => void;
  onClear: () => void;
  onTeachAll: () => void;
  onStart: () => void;
  marking: boolean;
  movingIndex: number | null;
  teachProgress: { current: number; total: number } | null;
  canMove: boolean;
  scanning: boolean;
  frames: number | null;
  /** Point currently being scanned (pulses in the list). */
  scanningIndex?: number | null;
}

const ZOOMS = [1, 1.5, 2, 3, 4];

export function PointsPanel(p: PointsPanelProps) {
  const taught = p.points.filter((pt) => pt.expected_components?.length).length;
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <SectionLabel>ซูมสำหรับจุดใหม่</SectionLabel>
        <Segmented className="w-full" value={p.zoom} onChange={p.onZoom} options={ZOOMS.map((z) => ({ value: z, label: `${z}×` }))} />
        <Button variant="success" size="lg" icon={p.marking ? undefined : Plus} loading={p.marking} disabled={!p.canMove || p.scanning} onClick={p.onMark}>
          {p.marking ? "กำลังถ่ายต้นแบบ…" : "มาร์คตำแหน่งปัจจุบัน"}
        </Button>
        <p className="text-[11px] text-subtle leading-snug">จ๊อกสเตจไปยังบริเวณที่ต้องการตรวจแล้วกดมาร์ค ระบบจะบันทึกพิกัดและถ่ายภาพต้นแบบให้อัตโนมัติ</p>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <SectionLabel>
            จุดตรวจ ({p.points.length}) · มีต้นแบบ {taught}
          </SectionLabel>
          {p.points.length > 0 && (
            <button type="button" onClick={p.onClear} disabled={p.scanning} className="text-[11px] text-fail hover:underline cursor-pointer disabled:opacity-40">
              ลบทั้งหมด
            </button>
          )}
        </div>

        {p.points.length === 0 ? (
          <EmptyState icon={MapPin} title="ยังไม่มีจุดตรวจ" className="rounded-lg border border-dashed border-line py-8">
            เชื่อมต่อและ HOME สเตจ จ๊อกไปยังจุดที่ต้องการ แล้วกด “มาร์คตำแหน่งปัจจุบัน”
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
                      <Button size="sm" icon={moving ? undefined : Navigation} loading={moving} disabled={!p.canMove || p.scanning} onClick={() => p.onMove(i)}>
                        ไปที่จุด
                      </Button>
                      <Button size="sm" icon={Crosshair} disabled={p.scanning} onClick={() => p.onEditReference(i)}>
                        {parts ? "แก้ต้นแบบ" : "สอนต้นแบบ"}
                      </Button>
                      <select
                        aria-label="ซูมของจุด"
                        value={pt.zoom || 1}
                        disabled={p.scanning}
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
                        disabled={p.scanning}
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

      {p.points.length > 0 && (
        <div className="flex flex-col gap-2">
          <Button variant="primary" size="lg" icon={Play} disabled={!p.canMove || p.scanning} onClick={p.onStart}>
            เริ่มตรวจ {p.points.length} จุด
            {p.frames ? (
              <span className="inline-flex items-center gap-1 opacity-80 font-normal">
                · <Layers className="size-3.5" /> {p.frames}F
              </span>
            ) : null}
          </Button>
          <Button icon={p.teachProgress ? undefined : Sparkles} disabled={!p.canMove || p.scanning || !!p.teachProgress} onClick={p.onTeachAll}>
            {p.teachProgress ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                สอนต้นแบบ {p.teachProgress.current}/{p.teachProgress.total}
              </>
            ) : (
              "สอนต้นแบบทุกจุดอัตโนมัติ"
            )}
          </Button>
          {taught < p.points.length && (
            <p className="text-[11px] text-review">จุดที่ไม่มีต้นแบบจะได้ผลเป็น REVIEW (ตรวจจับอย่างเดียว)</p>
          )}
        </div>
      )}
    </div>
  );
}
