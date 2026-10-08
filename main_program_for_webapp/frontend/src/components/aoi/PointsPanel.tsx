"use client";

import React, { useState } from "react";
import { Crosshair, LocateFixed, MapPin, Move, Navigation, Plus, Trash2 } from "lucide-react";
import type { CustomPointRequest } from "@/types";
import { formatMm } from "@/lib/format";
import { Badge, Button, EmptyState, NumberInput, SectionLabel, cx } from "../ui";

interface PointsPanelProps {
  points: CustomPointRequest[];
  selected: number;
  onSelect: (index: number) => void;
  /** Zoom new points are marked with (set on the live view). */
  zoom: number;
  onRename: (index: number, name: string) => void;
  onSetPointZoom: (index: number, zoom: number) => void;
  /** Move a point to new stage coordinates (mm). */
  onSetPosition: (index: number, x: number, y: number) => void;
  /** Live stage position (mm), to take over as a point's position; null when not connected. */
  stagePosition: [number, number] | null;
  /** Travel limits (mm). */
  limits: [number, number];
  /** Point the stage is travelling to right now (go-to or a scan's move), and where it is. */
  travelIndex?: number | null;
  livePosition?: [number, number] | null;
  /** Point just reached (a short "arrived" flash). */
  arrivedIndex?: number | null;
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
  const [editing, setEditing] = useState<number | null>(null);
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
          <EmptyState pcb icon={MapPin} title="ยังไม่มีจุดตรวจ" className="rounded-lg border border-dashed border-line py-8">
            จ๊อกไปยังจุดที่ต้องการ แล้วกด “มาร์คตำแหน่งปัจจุบัน” (หรือกด M)
          </EmptyState>
        ) : (
          <ul className="rounded-lg border border-line divide-y divide-line overflow-hidden">
            {p.points.map((pt, i) => {
              const active = i === p.selected;
              const parts = pt.expected_components?.length ?? 0;
              const moving = p.movingIndex === i;
              const live = p.scanningIndex === i;
              const travelling = p.travelIndex === i && !!p.livePosition;
              const arrived = p.arrivedIndex === i;
              return (
                <li
                  key={pt.id ?? i}
                  className={cx(
                    "relative transition-colors",
                    active || live ? "bg-accent-soft" : "hover:bg-surface-2",
                    arrived ? "animate-arrive" : "animate-rise"
                  )}
                >
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
                    {arrived ? (
                      <Badge tone="pass">ถึงแล้ว</Badge>
                    ) : parts ? (
                      <Badge tone="info">{parts} ชิ้น</Badge>
                    ) : (
                      <Badge tone="review">ไม่มีต้นแบบ</Badge>
                    )}
                  </div>
                  {travelling && <TravelIndicator target={[pt.x_mm, pt.y_mm]} position={p.livePosition!} />}
                  {active && (
                    <div className="flex items-center gap-1 px-2.5 pb-2 flex-wrap">
                      <Button size="sm" icon={moving ? undefined : Navigation} loading={moving} disabled={p.markReason !== null} onClick={() => p.onMove(i)}>
                        ไปที่จุด
                      </Button>
                      <Button size="sm" icon={Crosshair} disabled={p.locked} onClick={() => p.onEditReference(i)}>
                        {parts ? "แก้ต้นแบบ" : "สอนต้นแบบ"}
                      </Button>
                      <Button size="sm" icon={Move} variant={editing === i ? "primary" : "secondary"} disabled={p.locked} onClick={() => setEditing(editing === i ? null : i)}>
                        แก้ตำแหน่ง
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
                  {active && editing === i && (
                    <PositionEditor
                      key={`${pt.x_mm},${pt.y_mm}`}
                      point={pt}
                      limits={p.limits}
                      stagePosition={p.stagePosition}
                      hasReference={!!pt.reference_image || parts > 0}
                      onSave={(x, y) => {
                        p.onSetPosition(i, x, y);
                        setEditing(null);
                      }}
                      onCancel={() => setEditing(null)}
                    />
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

/**
 * New coordinates for a point: typed, or the stage's current position (jog there on the live
 * view first). The reference picture was taken at the old place, so a big move asks for a
 * new one.
 */
function PositionEditor({
  point,
  limits,
  stagePosition,
  hasReference,
  onSave,
  onCancel,
}: {
  point: CustomPointRequest;
  limits: [number, number];
  stagePosition: [number, number] | null;
  hasReference: boolean;
  onSave: (x: number, y: number) => void;
  onCancel: () => void;
}) {
  const [x, setX] = useState(point.x_mm);
  const [y, setY] = useState(point.y_mm);
  const moved = Math.hypot(x - point.x_mm, y - point.y_mm);
  const inside = x >= 0 && y >= 0 && x <= limits[0] && y <= limits[1];
  return (
    <div className="mx-2.5 mb-2.5 rounded-lg border border-line bg-surface p-2.5 flex flex-col gap-2" onClick={(e) => e.stopPropagation()}>
      <div className="grid grid-cols-2 gap-2">
        <NumberInput value={x} min={0} max={limits[0]} step={0.1} suffix="X mm" onChange={setX} aria-label="ตำแหน่ง X" />
        <NumberInput value={y} min={0} max={limits[1]} step={0.1} suffix="Y mm" onChange={setY} aria-label="ตำแหน่ง Y" />
      </div>
      {stagePosition && (
        <Button
          size="sm"
          variant="ghost"
          icon={LocateFixed}
          onClick={() => {
            setX(Math.round(stagePosition[0] * 100) / 100);
            setY(Math.round(stagePosition[1] * 100) / 100);
          }}
        >
          ใช้ตำแหน่งสเตจตอนนี้ ({formatMm(stagePosition[0])}, {formatMm(stagePosition[1])})
        </Button>
      )}
      {!inside && <p className="text-[11px] text-fail">อยู่นอกระยะเคลื่อนที่ (0–{limits[0]} × 0–{limits[1]} mm)</p>}
      {inside && hasReference && moved >= 1 && (
        <p className="text-[11px] text-review">
          ย้าย {moved.toFixed(1)} mm — ภาพต้นแบบและกรอบชิ้นส่วนถ่ายที่ตำแหน่งเดิม หลังบันทึกให้กด “ไปที่จุด” แล้ว “แก้ต้นแบบ” ถ่ายใหม่
        </p>
      )}
      <div className="flex gap-1.5 justify-end">
        <Button size="sm" variant="ghost" onClick={onCancel}>
          ยกเลิก
        </Button>
        <Button size="sm" variant="primary" disabled={!inside || moved < 0.005} onClick={() => onSave(Math.round(x * 100) / 100, Math.round(y * 100) / 100)}>
          บันทึกตำแหน่ง
        </Button>
      </div>
    </div>
  );
}

/**
 * The stage on its way to this point: how far it has come (from where it was when the move
 * started) with a moving shimmer, the distance still to go, and a pulsing marker.
 */
function TravelIndicator({ target, position }: { target: [number, number]; position: [number, number] }) {
  // Where the move started: the position when this indicator appeared.
  const [from] = useState<[number, number]>(position);
  const total = Math.hypot(target[0] - from[0], target[1] - from[1]);
  const left = Math.hypot(target[0] - position[0], target[1] - position[1]);
  const done = total > 0.01 ? Math.min(1, Math.max(0, 1 - left / total)) : 1;
  return (
    <div className="px-2.5 pb-2" aria-live="polite">
      <div className="flex items-center gap-2 text-[11px] text-accent font-medium mb-1">
        <span className="relative flex size-2.5">
          <span className="absolute inline-flex size-full rounded-full bg-accent opacity-60 animate-ping" />
          <span className="relative inline-flex size-2.5 rounded-full bg-accent" />
        </span>
        <Navigation className="size-3 animate-travel" />
        <span>กำลังไปที่จุดนี้</span>
        <span className="ml-auto font-mono tabular text-muted">เหลือ {formatMm(left)} mm</span>
      </div>
      <div className="h-1.5 rounded-full bg-surface-3 overflow-hidden">
        <div className="h-full rounded-full bg-accent bg-stripes animate-stripes transition-[width] duration-300 ease-linear" style={{ width: `${Math.max(4, done * 100)}%` }} />
      </div>
    </div>
  );
}
