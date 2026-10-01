"use client";

import React, { useMemo, useState } from "react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Home, LocateFixed, Navigation, Play, Sparkles } from "lucide-react";
import type { MachineState, ReferenceSummary } from "@/types";
import { IMGSZ_OPTIONS, percent } from "@/lib/format";
import type { InspectionParams, SetParams } from "@/lib/params";
import { Button, Field, NumberInput, SectionLabel, Segmented, Select, Slider, Toggle, cx } from "../ui";

export interface GridPlan {
  originX: number;
  originY: number;
  pitchX: number;
  pitchY: number;
  columns: number;
  rows: number;
}

export interface MotionSettings {
  speed: number;
  settleSec: number;
  jogStep: number;
}

export const DEFAULT_GRID: GridPlan = { originX: 0, originY: 0, pitchX: 10, pitchY: 10, columns: 2, rows: 2 };
export const DEFAULT_MOTION: MotionSettings = { speed: 800, settleSec: 0.5, jogStep: 1 };

/* ── Jog ─────────────────────────────────────────────────── */

export function JogPanel({
  machine,
  motion,
  setMotion,
  disabled,
  onJog,
  onHome,
  onMoveTo,
}: {
  machine: MachineState | null;
  motion: MotionSettings;
  setMotion: (m: Partial<MotionSettings>) => void;
  disabled: boolean;
  onJog: (dx: number, dy: number) => void;
  onHome: () => void;
  onMoveTo: (x: number, y: number) => void;
}) {
  const [target, setTarget] = useState({ x: 0, y: 0 });
  const canMove = !disabled && Boolean(machine?.homed);
  const s = motion.jogStep;
  const pad = "size-14 rounded-xl border border-line bg-surface-2 grid place-items-center text-text hover:bg-surface-3 active:scale-95 transition cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed";
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <SectionLabel>ระยะต่อครั้ง</SectionLabel>
        <Segmented
          className="w-full"
          value={s}
          onChange={(jogStep) => setMotion({ jogStep })}
          options={[0.1, 0.5, 1, 5, 10].map((v) => ({ value: v, label: `${v}` }))}
        />
      </div>

      <div className="grid grid-cols-3 gap-2 w-fit mx-auto" aria-label="ปุ่มจ๊อกสเตจ">
        <span />
        <button type="button" className={pad} disabled={!canMove} onClick={() => onJog(0, s)} aria-label={`Y+ ${s} mm`}>
          <ArrowUp className="size-5" />
        </button>
        <span />
        <button type="button" className={pad} disabled={!canMove} onClick={() => onJog(-s, 0)} aria-label={`X- ${s} mm`}>
          <ArrowLeft className="size-5" />
        </button>
        <button type="button" className={cx(pad, "bg-accent-soft text-accent")} disabled={disabled || !machine?.connected} onClick={onHome} aria-label="HOME">
          <Home className="size-5" />
        </button>
        <button type="button" className={pad} disabled={!canMove} onClick={() => onJog(s, 0)} aria-label={`X+ ${s} mm`}>
          <ArrowRight className="size-5" />
        </button>
        <span />
        <button type="button" className={pad} disabled={!canMove} onClick={() => onJog(0, -s)} aria-label={`Y- ${s} mm`}>
          <ArrowDown className="size-5" />
        </button>
        <span />
      </div>
      {!machine?.homed && <p className="text-xs text-center text-review">เชื่อมต่อและ HOME สเตจก่อนจ๊อก</p>}

      <div className="flex flex-col gap-2">
        <SectionLabel>ไปยังตำแหน่ง</SectionLabel>
        <div className="grid grid-cols-2 gap-2">
          <NumberInput value={target.x} min={0} max={machine?.soft_limits_mm[0]} step={0.5} suffix="X mm" onChange={(x) => setTarget((t) => ({ ...t, x }))} />
          <NumberInput value={target.y} min={0} max={machine?.soft_limits_mm[1]} step={0.5} suffix="Y mm" onChange={(y) => setTarget((t) => ({ ...t, y }))} />
        </div>
        <Button icon={Navigation} disabled={!canMove} onClick={() => onMoveTo(target.x, target.y)}>
          เคลื่อนที่
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="ความเร็ว (step/s)">
          <NumberInput value={motion.speed} min={20} max={1500} step={50} onChange={(speed) => setMotion({ speed })} />
        </Field>
        <Field label="เวลานิ่งก่อนถ่าย">
          <NumberInput value={motion.settleSec} min={0} max={5} step={0.1} suffix="s" onChange={(settleSec) => setMotion({ settleSec })} />
        </Field>
      </div>
    </div>
  );
}

/* ── Grid scan ───────────────────────────────────────────── */

export function GridPanel({
  grid,
  setGrid,
  machine,
  references,
  referenceId,
  setReferenceId,
  disabled,
  onStart,
}: {
  grid: GridPlan;
  setGrid: (g: Partial<GridPlan>) => void;
  machine: MachineState | null;
  references: ReferenceSummary[];
  referenceId: string;
  setReferenceId: (id: string) => void;
  disabled: boolean;
  onStart: (golden: boolean) => void;
}) {
  const total = grid.columns * grid.rows;
  const limits = machine?.soft_limits_mm ?? [38, 38];
  const path = useMemo(() => {
    const pts: Array<[number, number]> = [];
    for (let r = 0; r < grid.rows; r++) {
      for (let i = 0; i < grid.columns; i++) {
        const c = r % 2 === 0 ? i : grid.columns - 1 - i;
        pts.push([grid.originX + c * grid.pitchX, grid.originY + r * grid.pitchY]);
      }
    }
    return pts;
  }, [grid]);
  const outOfRange = path.some(([x, y]) => x < 0 || y < 0 || x > limits[0] || y > limits[1]);
  const tooMany = total > 400;
  const invalid = outOfRange || tooMany;

  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-3">
        <Field
          label="จุดเริ่ม X / Y (mm)"
          className="col-span-2"
          aside={
            <button
              type="button"
              className="text-[11px] text-accent hover:underline cursor-pointer disabled:opacity-40"
              disabled={!machine?.connected}
              onClick={() => machine && setGrid({ originX: machine.position_mm[0], originY: machine.position_mm[1] })}
            >
              <LocateFixed className="inline size-3 mr-1" />
              ใช้ตำแหน่งปัจจุบัน
            </button>
          }
        >
          <div className="grid grid-cols-2 gap-2">
            <NumberInput value={grid.originX} min={0} step={0.5} suffix="X" onChange={(originX) => setGrid({ originX })} />
            <NumberInput value={grid.originY} min={0} step={0.5} suffix="Y" onChange={(originY) => setGrid({ originY })} />
          </div>
        </Field>
        <Field label="ระยะห่าง X">
          <NumberInput value={grid.pitchX} min={0.5} step={0.5} suffix="mm" onChange={(pitchX) => setGrid({ pitchX })} />
        </Field>
        <Field label="ระยะห่าง Y">
          <NumberInput value={grid.pitchY} min={0.5} step={0.5} suffix="mm" onChange={(pitchY) => setGrid({ pitchY })} />
        </Field>
        <Field label="คอลัมน์">
          <NumberInput value={grid.columns} min={1} max={100} step={1} onChange={(v) => setGrid({ columns: Math.round(v) })} />
        </Field>
        <Field label="แถว">
          <NumberInput value={grid.rows} min={1} max={100} step={1} onChange={(v) => setGrid({ rows: Math.round(v) })} />
        </Field>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <SectionLabel>เส้นทางสแกน · {total} จุด</SectionLabel>
          <span className="text-[11px] text-subtle font-mono">
            พื้นที่ {limits[0]}×{limits[1]} mm
          </span>
        </div>
        <PathPreview path={path} limits={limits} />
        {outOfRange && <p className="text-xs text-fail">บางจุดเกินขอบเขตการเคลื่อนที่ — ลดจุดเริ่ม ระยะห่าง หรือจำนวนจุด</p>}
        {tooMany && <p className="text-xs text-fail">สแกนได้สูงสุด 400 จุดต่อรอบ</p>}
      </div>

      <Field label="โปรไฟล์ตารางอ้างอิง" hint={references.length ? "ต้องสร้างจากการสแกนต้นแบบด้วยตารางเดียวกัน" : "ยังไม่มี — กด “สแกนบอร์ดต้นแบบ” เพื่อสร้าง"}>
        <Select value={referenceId} onChange={(e) => setReferenceId(e.target.value)}>
          <option value="">ไม่เทียบ (ผลเป็น REVIEW)</option>
          {references.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name} · {r.points_count} จุด
            </option>
          ))}
        </Select>
      </Field>

      <div className="flex flex-col gap-2">
        <Button variant="primary" size="lg" icon={Play} disabled={disabled || invalid} onClick={() => onStart(false)}>
          เริ่มสแกนตาราง ({total} จุด)
        </Button>
        <Button icon={Sparkles} disabled={disabled || invalid} onClick={() => onStart(true)}>
          สแกนบอร์ดต้นแบบ → สร้างโปรไฟล์
        </Button>
      </div>
    </div>
  );
}

/** Top-down view of the stage travel area with a scan path (and optionally a marked outline). */
export function PathPreview({
  path,
  limits,
  outline,
}: {
  path: Array<[number, number]>;
  limits: [number, number];
  outline?: Array<[number, number]>;
}) {
  const W = 300;
  const H = Math.max(120, Math.min(220, (W * limits[1]) / limits[0]));
  const sx = (x: number) => 10 + (x / limits[0]) * (W - 20);
  const sy = (y: number) => H - 10 - (y / limits[1]) * (H - 20);
  const d = path.map(([x, y], i) => `${i ? "L" : "M"}${sx(x)} ${sy(y)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded-lg bg-surface-2 border border-line">
      <rect x={10} y={10} width={W - 20} height={H - 20} fill="none" stroke="var(--line-strong)" strokeDasharray="4 4" />
      {outline && outline.length > 1 && (
        <polygon
          points={outline.map(([x, y]) => `${sx(x)},${sy(y)}`).join(" ")}
          fill="var(--pass)"
          fillOpacity={0.08}
          stroke="var(--pass)"
          strokeDasharray="5 3"
        />
      )}
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth={1.5} strokeOpacity={0.6} />
      {path.slice(0, 400).map(([x, y], i) => {
        const bad = x < 0 || y < 0 || x > limits[0] || y > limits[1];
        return <circle key={i} cx={sx(x)} cy={sy(y)} r={path.length > 60 ? 1.8 : 3} fill={bad ? "var(--fail)" : i === 0 ? "var(--pass)" : "var(--accent)"} />;
      })}
    </svg>
  );
}

/* ── Inspection parameters ───────────────────────────────── */

export function ParamsPanel({ params, setParams, disabled }: { params: InspectionParams; setParams: SetParams; disabled: boolean }) {
  const passFrames = Math.max(1, Math.ceil(params.targetFrames * params.passRatio));
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-4">
        <SectionLabel>โมเดลตรวจจับ</SectionLabel>
        <Slider label="ความมั่นใจขั้นต่ำ" value={params.conf} min={0.01} max={1} step={0.01} format={percent} disabled={disabled} onChange={(conf) => setParams({ conf })} />
        <Field label="ขนาดภาพเข้าโมเดล (imgsz)" hint="ค่าสูงตรวจชิ้นเล็กได้ดีขึ้นแต่ช้าลง">
          <Select value={params.imgsz} disabled={disabled} onChange={(e) => setParams({ imgsz: Number(e.target.value) })}>
            {IMGSZ_OPTIONS.map((v) => (
              <option key={v} value={v}>
                {v} px{v === 1280 ? " (แนะนำ)" : ""}
              </option>
            ))}
          </Select>
        </Field>
      </div>

      <div className="flex flex-col gap-4">
        <SectionLabel>ความครบของชิ้นส่วน</SectionLabel>
        <Toggle
          label="ตรวจหลายเฟรมต่อจุด"
          description="ลดผลผิดพลาดจากเฟรมเดียว — ยืนยันชิ้นส่วนเมื่อพบซ้ำตามเกณฑ์"
          checked={params.multiframeEnabled}
          disabled={disabled}
          onChange={(multiframeEnabled) => setParams({ multiframeEnabled })}
        />
        {params.multiframeEnabled && (
          <>
            <Field label="จำนวนเฟรมต่อจุด" hint="1–50 เฟรม (เฟรมมากขึ้นแม่นขึ้นแต่ใช้เวลานานขึ้น)">
              <div className="flex gap-2">
                <NumberInput
                  className="w-28 shrink-0"
                  value={params.targetFrames}
                  min={1}
                  max={50}
                  step={1}
                  suffix="เฟรม"
                  disabled={disabled}
                  onChange={(v) => setParams({ targetFrames: Math.round(v) })}
                />
                <Segmented
                  className="flex-1"
                  size="sm"
                  disabled={disabled}
                  value={params.targetFrames}
                  onChange={(targetFrames) => setParams({ targetFrames })}
                  options={[3, 5, 10, 20, 50].map((v) => ({ value: v, label: `${v}` }))}
                />
              </div>
            </Field>
            <Slider
              label="เกณฑ์ผ่าน"
              value={params.passRatio}
              min={0.01}
              max={1}
              step={0.01}
              disabled={disabled}
              format={(v) => `${percent(v)} · ≥ ${passFrames}/${params.targetFrames}`}
              onChange={(passRatio) => setParams({ passRatio })}
            />
          </>
        )}
      </div>

      <div className="flex flex-col gap-4">
        <SectionLabel>การเทียบตำแหน่ง (โปรไฟล์ตาราง)</SectionLabel>
        <Slider
          label="ระยะจับคู่สูงสุด"
          value={params.matchDist}
          min={1}
          max={500}
          step={1}
          disabled={disabled}
          format={(v) => `${v} px`}
          onChange={(matchDist) => setParams({ matchDist })}
        />
        <Toggle
          label="ไม่ผ่านเมื่อพบชิ้นเกิน"
          checked={params.failOnExtra}
          disabled={disabled}
          onChange={(failOnExtra) => setParams({ failOnExtra })}
        />
      </div>
    </div>
  );
}
