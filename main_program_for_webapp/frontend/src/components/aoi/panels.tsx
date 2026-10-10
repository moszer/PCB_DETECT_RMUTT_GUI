"use client";

import React, { useState } from "react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Home, Navigation } from "lucide-react";
import type { MachineState } from "@/types";
import { IMGSZ_OPTIONS, percent } from "@/lib/format";
import type { InspectionParams, SetParams } from "@/lib/params";
import { useHoldRepeat } from "@/hooks/useHoldRepeat";
import { Button, Field, NumberInput, SectionLabel, Segmented, Select, Slider, Toggle, cx } from "../ui";

export interface MotionSettings {
  speed: number;
  settleSec: number;
  jogStep: number;
}

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
  /** Resolves false when the move failed (stops a held button). */
  onJog: (dx: number, dy: number) => Promise<boolean>;
  onHome: () => void;
  onMoveTo: (x: number, y: number) => void;
}) {
  const [target, setTarget] = useState({ x: 0, y: 0 });
  const hold = useHoldRepeat();
  const canMove = !disabled && Boolean(machine?.homed);
  const s = motion.jogStep;
  const pad = "size-14 pointer-coarse:size-18 rounded-xl border border-line bg-surface-2 grid place-items-center text-text hover:bg-surface-3 active:scale-95 transition cursor-pointer touch-none disabled:opacity-40 disabled:cursor-not-allowed";
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
        <button type="button" className={pad} disabled={!canMove} {...hold(() => onJog(0, s))} aria-label={`Y+ ${s} mm`}>
          <ArrowUp className="size-5" />
        </button>
        <span />
        <button type="button" className={pad} disabled={!canMove} {...hold(() => onJog(-s, 0))} aria-label={`X- ${s} mm`}>
          <ArrowLeft className="size-5" />
        </button>
        <button type="button" className={cx(pad, "bg-accent-soft text-accent")} disabled={disabled || !machine?.connected} onClick={onHome} aria-label="HOME">
          <Home className="size-5" />
        </button>
        <button type="button" className={pad} disabled={!canMove} {...hold(() => onJog(s, 0))} aria-label={`X+ ${s} mm`}>
          <ArrowRight className="size-5" />
        </button>
        <span />
        <button type="button" className={pad} disabled={!canMove} {...hold(() => onJog(0, -s))} aria-label={`Y- ${s} mm`}>
          <ArrowDown className="size-5" />
        </button>
        <span />
      </div>
      {!machine?.homed ? (
        <p className="text-xs text-center text-review">เชื่อมต่อและ HOME สเตจก่อนจ๊อก</p>
      ) : (
        <p className="text-xs text-center text-muted">กดค้างเพื่อเคลื่อนต่อเนื่อง · ใช้ปุ่มลูกศรบนคีย์บอร์ด หรือปุ่มจ๊อกบนภาพสดได้เช่นกัน</p>
      )}

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
        <SectionLabel>การเทียบตำแหน่งกับต้นแบบ</SectionLabel>
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
