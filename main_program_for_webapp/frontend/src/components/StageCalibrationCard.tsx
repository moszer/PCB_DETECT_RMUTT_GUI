"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Play, Ruler, Square, Wand2 } from "lucide-react";
import type { StageAxisCalibration, StageCalibrationResult, StageCalibrationStatus } from "@/types";
import { api } from "@/lib/api";
import { Button, Card, CardHeader, Field, NumberInput, Stat, Toggle, cx } from "./ui";
import { useToast } from "./Toast";

const um = (mm: number | undefined | null) => (mm === undefined || mm === null ? "–" : `${Math.round(mm * 1000)} µm`);

/** Position error along one axis: + pass and - pass (the gap between them is the backlash). */
function AxisErrorPlot({ axis, name }: { axis: StageAxisCalibration; name: string }) {
  const W = 260;
  const H = 120;
  const pad = { l: 34, r: 8, t: 8, b: 20 };
  const xs = axis.errors.map((e) => e[0]);
  const ys = axis.errors.map((e) => e[1] * 1000);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const lim = Math.max(5, ...ys.map(Math.abs)) * 1.15;
  const sx = (v: number) => pad.l + ((v - x0) / Math.max(1e-9, x1 - x0)) * (W - pad.l - pad.r);
  const sy = (v: number) => pad.t + (1 - (v + lim) / (2 * lim)) * (H - pad.t - pad.b);
  const series = (forward: boolean) =>
    axis.errors
      .filter((e) => e[2] === forward)
      .sort((a, b) => a[0] - b[0])
      .map((e) => [sx(e[0]), sy(e[1] * 1000)] as const);
  return (
    <div className="rounded-lg border border-line bg-surface-2 p-2">
      <div className="text-[11px] text-muted px-1">แกน {name} · ความคลาดเคลื่อนตามตำแหน่ง (µm)</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto">
        <line x1={pad.l} x2={W - pad.r} y1={sy(0)} y2={sy(0)} className="stroke-line-strong" strokeDasharray="3 3" />
        {[lim, -lim].map((v) => (
          <text key={v} x={pad.l - 4} y={sy(v * 0.87) + 3} textAnchor="end" className="fill-subtle text-[9px] font-mono">
            {Math.round(v * 0.87)}
          </text>
        ))}
        <text x={pad.l} y={H - 6} className="fill-subtle text-[9px] font-mono">{x0.toFixed(1)}</text>
        <text x={W - pad.r} y={H - 6} textAnchor="end" className="fill-subtle text-[9px] font-mono">{x1.toFixed(1)} mm</text>
        {([true, false] as const).map((fwd) => {
          const pts = series(fwd);
          return (
            <g key={String(fwd)} className={fwd ? "text-accent" : "text-review"}>
              <polyline points={pts.map((p) => p.join(",")).join(" ")} fill="none" stroke="currentColor" strokeWidth={1.5} />
              {pts.map(([x, y], i) => (
                <circle key={i} cx={x} cy={y} r={2.2} fill="currentColor" />
              ))}
            </g>
          );
        })}
      </svg>
      <div className="flex gap-3 px-1 text-[10px] text-muted">
        <span className="text-accent">● เดินทาง +</span>
        <span className="text-review">● เดินทาง −</span>
      </div>
    </div>
  );
}

function Results({ r }: { r: StageCalibrationResult }) {
  const rep = r.repeatability;
  const backlashTone = (mm: number) => (mm > 0.05 ? "review" : "pass");
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Stat label="Backlash แกน X" value={um(r.x.backlash_mm)} tone={backlashTone(r.x.backlash_mm)} />
        <Stat label="Backlash แกน Y" value={um(r.y.backlash_mm)} tone={backlashTone(r.y.backlash_mm)} />
        <Stat
          label="กลับจุดเดิม (ทิศเดียวกัน)"
          value={um(Math.max(rep.plus?.rms_mm ?? 0, rep.minus?.rms_mm ?? 0))}
          hint="RMS ของการกลับมาจุดเดิมซ้ำ"
        />
        {rep.compensated ? (
          <Stat label="กลับจุดเดิมเมื่อชดเชยแล้ว" value={um(rep.compensated.worst_pair_mm)} tone="pass" hint="ห่างกันมากสุดระหว่างครั้ง" />
        ) : (
          <Stat
            label="ต่างกันตามทิศที่เข้า"
            value={rep.direction_gap_mm ? um(Math.hypot(...rep.direction_gap_mm)) : "–"}
            tone={rep.direction_gap_mm && Math.hypot(...rep.direction_gap_mm) > 0.05 ? "review" : undefined}
            hint="เข้าจาก + เทียบเข้าจาก −"
          />
        )}
      </div>
      <div className="grid sm:grid-cols-2 gap-2">
        <AxisErrorPlot axis={r.x} name="X" />
        <AxisErrorPlot axis={r.y} name="Y" />
      </div>
      <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1.5 text-xs">
        {[
          ["ความเป็นเชิงเส้น X / Y", `${um(r.x.linearity_mm)} / ${um(r.y.linearity_mm)}`],
          ["ความตรงของราง X / Y", `${um(r.x.straightness_mm)} / ${um(r.y.straightness_mm)}`],
          ["มุมฉากระหว่างแกน", `เพี้ยน ${r.squareness_deg.toFixed(3)}°`],
          ["กล้องเอียงเทียบแกน X", `${r.camera_rotation_deg.toFixed(2)}°`],
          ["สเกล Y เทียบ X", `${((r.xy_scale_ratio - 1) * 100).toFixed(2)}%`],
          ["ความละเอียดภาพ", `${r.x.px_per_mm.toFixed(1)} px/mm`],
          ...(r.x.scale_error_pct !== undefined && r.y.scale_error_pct !== undefined
            ? [
                ["สเกลจริง X / Y", `${r.x.scale_error_pct.toFixed(2)}% / ${r.y.scale_error_pct.toFixed(2)}%`],
                ["steps/mm ที่ควรเป็น X / Y", `${r.x.suggested_steps_per_mm} / ${r.y.suggested_steps_per_mm} (ตอนนี้ ${r.steps_per_mm})`],
              ]
            : []),
        ].map(([k, v]) => (
          <div key={k} className="min-w-0">
            <dt className="text-muted">{k}</dt>
            <dd className="font-mono tabular text-text">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="text-[11px] text-subtle">
        วัดเมื่อ {new Date(r.time * 1000).toLocaleString("th-TH")} · รอบจุด ({r.center_mm[0].toFixed(1)}, {r.center_mm[1].toFixed(1)}) mm ช่วง ±
        {r.range_mm} mm{r.approach_mm_during_test > 0 ? ` · ขณะวัดเปิดชดเชย ${r.approach_mm_during_test} mm` : ""}
        {!r.mm_per_px && " · สเกลจริงต้องใช้ checkerboard"}
      </p>
    </div>
  );
}

/** Camera-based accuracy test of the XY stage and its backlash compensation. */
export function StageCalibrationCard({ isOperator }: { isOperator: boolean }) {
  const toast = useToast();
  const [status, setStatus] = useState<StageCalibrationStatus | null>(null);
  const [approach, setApproach] = useState(0);
  const [useBoard, setUseBoard] = useState(false);
  const [cols, setCols] = useState(9);
  const [rows, setRows] = useState(6);
  const [squareMm, setSquareMm] = useState(2);
  const [busy, setBusy] = useState(false);

  // Toast once when a run this page watched finishes.
  const watched = useRef(false);
  const refresh = useCallback(
    () =>
      api
        .getStageCalibration()
        .then((s) => {
          if (s.state === "running") watched.current = true;
          else if (watched.current) {
            watched.current = false;
            if (s.state === "done") toast.success("Calibrate ราง XY เสร็จแล้ว");
            else if (s.state === "error") toast.error("Calibrate ไม่สำเร็จ", s.message);
          }
          setStatus(s);
        })
        .catch(() => {}),
    [toast]
  );
  useEffect(() => {
    refresh();
    api.getSettings().then((s) => setApproach(s.stage_approach_mm ?? 0)).catch(() => {});
  }, [refresh]);

  const running = status?.state === "running";
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(refresh, 1000);
    return () => window.clearInterval(id);
  }, [running, refresh]);

  const start = async () => {
    setBusy(true);
    try {
      const s = await api.startStageCalibration(useBoard ? { checkerboard_cols: cols, checkerboard_rows: rows, square_mm: squareMm } : {});
      watched.current = s.state === "running";
      setStatus(s);
    } catch (err) {
      toast.error("เริ่ม calibrate ไม่ได้", err);
    } finally {
      setBusy(false);
    }
  };

  const saveApproach = async (mm: number) => {
    try {
      await api.updateSettings({ stage_approach_mm: mm });
      setApproach(mm);
      toast.success(mm > 0 ? `เปิดชดเชย backlash ${mm} mm แล้ว` : "ปิดการชดเชย backlash แล้ว");
    } catch (err) {
      toast.error("บันทึกไม่สำเร็จ", err);
    }
  };

  const last = status?.last;
  const progress = running && status?.total ? Math.round(((status.step ?? 0) / status.total) * 100) : 0;

  return (
    <Card>
      <CardHeader
        icon={Ruler}
        title="Calibrate ความแม่นยำราง XY"
        subtitle="ใช้กล้องวัดว่าสเตจไปถึงตำแหน่งจริงแค่ไหน: backlash, ความเป็นเชิงเส้น, ความตรงของราง, มุมฉาก และการกลับจุดเดิม"
      />
      <div className="p-4 flex flex-col gap-4">
        <ol className="text-xs text-muted list-decimal pl-4 space-y-0.5">
          <li>วางบอร์ดที่มีลวดลาย (หรือ checkerboard) ไว้บนสเตจ ให้เต็มภาพกล้องและยึดไม่ให้ขยับ</li>
          <li>HOME แล้วเลื่อนสเตจไปกลางบอร์ดในหน้าสแกน — ระบบจะเดินทดสอบรอบตำแหน่งนี้ ±3 mm</li>
          <li>กดเริ่ม ใช้เวลาราว 1–2 นาที ระหว่างนั้นห้ามแตะเครื่อง</li>
        </ol>

        <div className="flex flex-col gap-2">
          <Toggle
            checked={useBoard}
            onChange={setUseBoard}
            label="ใช้ checkerboard วัดสเกลจริง"
            description="ถ้ามีแผ่นตารางหมากรุกที่รู้ขนาดช่อง จะได้ค่า steps/mm ที่ถูกต้องของแต่ละแกนด้วย"
          />
          {useBoard && (
            <div className="grid grid-cols-3 gap-3">
              <Field label="มุมด้านใน (แนวนอน)">
                <NumberInput value={cols} min={3} max={40} step={1} onChange={setCols} />
              </Field>
              <Field label="มุมด้านใน (แนวตั้ง)">
                <NumberInput value={rows} min={3} max={40} step={1} onChange={setRows} />
              </Field>
              <Field label="ขนาดช่อง">
                <NumberInput value={squareMm} min={0.1} max={50} step={0.1} suffix="mm" onChange={setSquareMm} />
              </Field>
            </div>
          )}
        </div>

        <div className="flex items-center gap-3">
          {running ? (
            <Button icon={Square} variant="danger" onClick={() => api.stopStageCalibration().then(setStatus).catch((e) => toast.error("หยุดไม่ได้", e))}>
              หยุด
            </Button>
          ) : (
            <Button icon={Play} variant="primary" onClick={start} disabled={!isOperator || busy}>
              เริ่ม calibrate
            </Button>
          )}
          {running && (
            <div className="flex-1 min-w-0">
              <div className="h-1.5 rounded-full bg-surface-2 overflow-hidden">
                <div className="h-full bg-accent transition-[width]" style={{ width: `${progress}%` }} />
              </div>
              <p className="text-[11px] text-muted mt-1 truncate">
                {progress}% · {status?.message}
              </p>
            </div>
          )}
          {!running && status?.state === "error" && <p className="text-xs text-fail min-w-0">{status.message}</p>}
          {!isOperator && <p className="text-xs text-muted">ต้องมีสิทธิ์ควบคุมสถานี</p>}
        </div>

        {last && <Results r={last} />}

        <div className={cx("rounded-lg border p-3 flex flex-col gap-2", approach > 0 ? "border-pass/40 bg-pass-soft" : "border-line")}>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-sm font-medium">ชดเชย backlash {approach > 0 ? `· เปิด ${approach} mm` : "· ปิด"}</div>
              <p className="text-[11px] text-muted mt-0.5">
                เวลาสแกน/วัด 3D ถ้าแกนไหนต้องถอยกลับ จะเลยเป้าไปก่อนแล้วเดินหน้าเข้าเป้าเสมอ ทำให้ตำแหน่งตรงกันทุกรอบ (ช้าลงเล็กน้อยเฉพาะจุดที่ถอยกลับ)
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <Field label="ระยะเลยเป้า" className="w-36">
              <NumberInput value={approach} min={0} max={3} step={0.05} suffix="mm" onChange={setApproach} />
            </Field>
            <Button size="sm" onClick={() => saveApproach(approach)} disabled={!isOperator}>
              บันทึก
            </Button>
            {last && (
              <Button size="sm" icon={Wand2} variant="primary" onClick={() => saveApproach(last.suggested_approach_mm)} disabled={!isOperator}>
                ใช้ค่าแนะนำ {last.suggested_approach_mm} mm
              </Button>
            )}
            {approach > 0 && (
              <Button size="sm" variant="ghost" onClick={() => saveApproach(0)} disabled={!isOperator}>
                ปิด
              </Button>
            )}
          </div>
          {approach > 0 && last && last.approach_mm_during_test === 0 && (
            <p className="text-[11px] text-review">กด calibrate อีกรอบเพื่อยืนยันว่าชดเชยแล้วกลับจุดเดิมได้ตรง</p>
          )}
        </div>
      </div>
    </Card>
  );
}
