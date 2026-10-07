"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, Box, Download, Grid3x3, Map as MapIcon, Play, Ruler, Square, Wand2 } from "lucide-react";
import type { StageAxisCalibration, StageCalibrationResult, StageCalibrationStatus, StageMapResult } from "@/types";
import { API_BASE, api } from "@/lib/api";
import { Button, Card, CardHeader, Field, NumberInput, Segmented, Stat, Toggle, buttonClasses, cx } from "./ui";
import { useToast } from "./Toast";
import { useThreePrefs } from "@/lib/three/prefs";
import { goodBadHex } from "@/lib/three/colors";
import { RAIL_GOOD_UM, RailMap3D, nodeText } from "./three/RailMap3D";

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

/** Top view of the map: one cell per node coloured by its error, an arrow for its direction. */
function RailMap2D({ map }: { map: StageMapResult }) {
  const [cols, rows] = map.grid;
  const cell = 44;
  const W = cols * cell;
  const H = rows * cell;
  const worst = Math.max(RAIL_GOOD_UM * 2, map.max_um ?? 0);
  return (
    <div className="rounded-lg border border-line bg-surface-2 p-2 overflow-x-auto">
      <svg viewBox={`-28 -8 ${W + 36} ${H + 30}`} className="w-full max-w-xl h-auto mx-auto">
        {map.nodes.map((n) => {
          const x = n.col * cell;
          const y = (rows - 1 - n.row) * cell;
          const e = n.err_mm;
          const len = e && n.err_um ? Math.min(cell * 0.42, 6 + (n.err_um / worst) * cell * 0.36) : 0;
          const ang = e ? Math.atan2(-e[1], e[0]) : 0;
          return (
            <g key={`${n.col}-${n.row}`}>
              <title>{nodeText(n)}</title>
              <rect x={x + 1} y={y + 1} width={cell - 2} height={cell - 2} rx={5} fill={n.measured ? goodBadHex((n.err_um ?? 0) / worst) : "#475569"} opacity={0.85} />
              <text x={x + cell / 2} y={y + cell - 6} textAnchor="middle" className="fill-black/70 text-[9px] font-mono">
                {n.measured ? Math.round(n.err_um ?? 0) : "–"}
              </text>
              {len > 0 && (
                <line
                  x1={x + cell / 2}
                  y1={y + cell / 2 - 4}
                  x2={x + cell / 2 + Math.cos(ang) * len}
                  y2={y + cell / 2 - 4 + Math.sin(ang) * len}
                  stroke="white"
                  strokeWidth={1.6}
                  markerEnd="url(#railArrow)"
                />
              )}
            </g>
          );
        })}
        <defs>
          <marker id="railArrow" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="4" markerHeight="4" orient="auto">
            <path d="M0,0 L6,3 L0,6 z" fill="white" />
          </marker>
        </defs>
        <text x={W / 2} y={H + 18} textAnchor="middle" className="fill-subtle text-[10px]">
          X {map.xs[0]?.toFixed(1)} → {map.xs[map.xs.length - 1]?.toFixed(1)} mm (ตัวเลข = µm)
        </text>
        <text x={-10} y={H / 2} textAnchor="middle" transform={`rotate(-90 -10 ${H / 2})`} className="fill-subtle text-[10px]">
          Y {map.ys[0]?.toFixed(1)} → {map.ys[map.ys.length - 1]?.toFixed(1)} mm
        </text>
      </svg>
    </div>
  );
}

function RailMapResults({ map }: { map: StageMapResult }) {
  const { use3d } = useThreePrefs();
  const [view, setView] = useState<"3d" | "2d">("3d");
  const show3d = use3d && view === "3d";
  const worstNode = map.nodes.filter((n) => n.measured).sort((a, b) => (b.err_um ?? 0) - (a.err_um ?? 0))[0];
  const bl = map.backlash_mean_mm;
  const quality = map.quality ?? ((map.noise_um ?? 999) <= 8 ? "good" : (map.noise_um ?? 999) <= 25 ? "fair" : "poor");
  return (
    <div className="flex flex-col gap-3">
      {quality !== "good" && (
        <div
          className={cx(
            "rounded-lg border px-3 py-2 text-xs flex items-start gap-1.5",
            quality === "poor" ? "border-fail/40 bg-fail-soft text-fail" : "border-review/40 bg-review-soft text-review"
          )}
        >
          <AlertTriangle className="size-3.5 shrink-0 mt-0.5" />
          <span>
            {quality === "poor" ? (
              <>
                <strong>ผลนี้เชื่อถือไม่ได้</strong> — ภาพแต่ละคู่ไม่ลงกันถึง ±{map.noise_um} µm (ควรได้ไม่กี่ µm) ตัวเลขด้านล่างจึงมาจากการวัด ไม่ใช่จากราง
                มักเกิดจากวัดบนบอร์ดที่มีชิ้นส่วนสูง หรือบางจุดอยู่นอกแผ่น — วัดใหม่บนแผ่นลายจุดที่พิมพ์วางราบ
              </>
            ) : (
              <>ผลพอใช้ — ภาพแต่ละคู่ไม่ลงกัน ±{map.noise_um} µm ความคลาดเคลื่อนที่น้อยกว่านี้แยกจากการวัดไม่ได้ วัดบนแผ่นลายจุดจะแม่นกว่า</>
            )}
          </span>
        </div>
      )}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Stat label="คลาดเคลื่อนเฉลี่ย (RMS)" value={map.rms_um !== null ? `${map.rms_um} µm` : "–"} tone={(map.rms_um ?? 0) > RAIL_GOOD_UM ? "review" : "pass"} />
        <Stat
          label="แย่สุด"
          value={map.max_um !== null ? `${map.max_um} µm` : "–"}
          tone={(map.max_um ?? 0) > RAIL_GOOD_UM * 2 ? "review" : undefined}
          hint={worstNode ? `ที่ (${worstNode.x_mm.toFixed(1)}, ${worstNode.y_mm.toFixed(1)}) mm` : undefined}
        />
        <Stat label="Backlash เฉลี่ย X / Y" value={bl ? `${Math.round(Math.abs(bl[0]) * 1000)} / ${Math.round(Math.abs(bl[1]) * 1000)} µm` : "–"} />
        <Stat label="สัญญาณรบกวนการวัด" value={map.noise_um !== null ? `±${map.noise_um} µm` : "–"} hint="ค่าที่ต่ำกว่านี้แยกไม่ออกจากความคลาดเคลื่อนของการวัด" />
      </div>
      {use3d && (
        <Segmented
          size="sm"
          className="self-start"
          value={view}
          onChange={setView}
          options={[
            { value: "3d", label: "พื้นผิว 3D", icon: Box },
            { value: "2d", label: "ตาราง", icon: Grid3x3 },
          ]}
        />
      )}
      {show3d ? <RailMap3D map={map} className="h-[380px]" /> : <RailMap2D map={map} />}
      <p className="text-[11px] text-subtle">
        วัดเมื่อ {new Date(map.time * 1000).toLocaleString("th-TH")} · {map.grid[0]}×{map.grid[1]} จุด · ความคลาดเคลื่อนคือส่วนที่เหลือหลังหักเส้นตรงที่ดีที่สุดของทั้งราง (สเกลและมุมรวมของแกนแก้ได้ด้วย steps/mm และการหมุนภาพ ส่วนนี้คือความไม่สม่ำเสมอของรางและเฟือง)
        {map.failed_edges > 0 && ` · จับคู่ภาพไม่ได้ ${map.failed_edges} คู่`}
        {(map.rejected_edges ?? 0) > 0 && ` · ตัดคู่ที่ไม่ลงกันกับจุดอื่น ${map.rejected_edges} คู่`}
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
  const [density, setDensity] = useState(5);
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

  const start = async (mode: "axes" | "map" = "axes") => {
    setBusy(true);
    try {
      const s = await api.startStageCalibration(
        mode === "map" ? { mode, density } : useBoard ? { checkerboard_cols: cols, checkerboard_rows: rows, square_mm: squareMm } : {}
      );
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
  const lastMap = status?.last_map;
  const progress = running && status?.total ? Math.round(((status.step ?? 0) / status.total) * 100) : 0;
  const mapRunning = running && status?.mode === "map";
  const axesRunning = running && !mapRunning;
  const progressBar = (
    <div className="flex-1 min-w-0">
      <div className="h-1.5 rounded-full bg-surface-2 overflow-hidden">
        <div className="h-full bg-accent transition-[width]" style={{ width: `${progress}%` }} />
      </div>
      <p className="text-[11px] text-muted mt-1 truncate">
        {progress}% · {status?.message}
      </p>
    </div>
  );
  const stopButton = (
    <Button icon={Square} variant="danger" onClick={() => api.stopStageCalibration().then(setStatus).catch((e) => toast.error("หยุดไม่ได้", e))}>
      หยุด
    </Button>
  );

  return (
    <Card>
      <CardHeader
        icon={Ruler}
        title="Calibrate ความแม่นยำราง XY"
        subtitle="ใช้กล้องวัดว่าสเตจไปถึงตำแหน่งจริงแค่ไหน: backlash, ความเป็นเชิงเส้น, ความตรงของราง, มุมฉาก และการกลับจุดเดิม"
      />
      <div className="p-4 flex flex-col gap-4">
        <ol className="text-xs text-muted list-decimal pl-4 space-y-0.5">
          <li>
            วางแผ่นลายจุดที่พิมพ์ไว้ (ด้านล่าง) หรือ checkerboard ให้ราบบนฐาน เต็มภาพกล้อง และติดเทปไม่ให้ขยับ — บอร์ดที่มีชิ้นส่วนสูงใช้ได้แต่ค่าจะเพี้ยน
            (กล้องเลื่อน ชิ้นที่สูงจะเลื่อนในภาพต่างจากผิวบอร์ด)
          </li>
          <li>HOME แล้วเลื่อนสเตจไปกลางแผ่นในหน้าสแกน — ระบบจะเดินทดสอบรอบตำแหน่งนี้ ±2 mm</li>
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
              <div className="col-span-3 flex flex-wrap items-center gap-2 text-[11px] text-muted">
                <a
                  className={buttonClasses("secondary", "sm")}
                  href={`${API_BASE}/api/aoi/calibration/checkerboard.png?cols=${cols}&rows=${rows}&square_mm=${squareMm}`}
                  download
                >
                  <Download className="size-3.5" /> ดาวน์โหลด checkerboard สำหรับพิมพ์
                </a>
                <span>
                  {cols + 1}×{rows + 1} ช่อง ({((cols + 1) * squareMm).toFixed(0)}×{((rows + 1) * squareMm).toFixed(0)} mm) · พิมพ์ขนาดจริง 100% แล้ววัดช่องด้วยไม้บรรทัด
                  ใส่ค่าที่วัดได้ในช่อง “ขนาดช่อง” · วางให้ราบ ทั้งแผ่นอยู่ในภาพกล้อง
                </span>
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center gap-3">
          {axesRunning ? (
            stopButton
          ) : (
            <Button icon={Play} variant="primary" onClick={() => start("axes")} disabled={!isOperator || busy || running}>
              เริ่ม calibrate
            </Button>
          )}
          {axesRunning && progressBar}
          {!running && status?.state === "error" && status.mode !== "map" && <p className="text-xs text-fail min-w-0">{status.message}</p>}
          {!isOperator && <p className="text-xs text-muted">ต้องมีสิทธิ์ควบคุมสถานี</p>}
        </div>

        {last && <Results r={last} />}

        {/* ── whole-travel map ── */}
        <div className="rounded-lg border border-line p-3 flex flex-col gap-3">
          <div className="flex items-start gap-2">
            <MapIcon className="size-4 text-accent mt-0.5 shrink-0" />
            <div className="min-w-0">
              <div className="text-sm font-medium">แผนที่ความแม่นยำทั้งราง</div>
              <p className="text-[11px] text-muted mt-0.5">
                เดินเป็นตารางทั่วทั้งระยะเคลื่อนที่ ถ่ายภาพทุกจุดแล้วต่อภาพจุดข้างเคียงกัน (เหมือนต่อภาพพาโนรามา) เพื่อหาว่าแต่ละตำแหน่งบนรางไปถึงจริงคลาดไปเท่าไหร่ และ backlash
                ที่แต่ละจุด — ต้อง calibrate แบบด้านบนก่อน ใช้เวลาราว 3–8 นาที
              </p>
              <p className="text-[11px] text-review mt-1">
                ต้องวัดบนแผ่นลายจุดที่พิมพ์วางราบให้คลุมทุกที่ที่กล้องเห็นตลอดระยะเดิน (A3 หรือ A4 สองแผ่นต่อกัน) — บนบอร์ดจริงชิ้นส่วนที่สูงทำให้ภาพไม่ลงกัน
                (parallax) และลายซ้ำๆ อย่าง checkerboard จับคู่ผิดช่องได้ จุดที่อยู่นอกแผ่นจะถูกตัดทิ้งอัตโนมัติ
              </p>
              <div className="flex flex-wrap gap-1.5 mt-2">
                {(["a3", "a4"] as const).map((paper) => (
                  <a key={paper} className={buttonClasses("secondary", "sm")} href={`${API_BASE}/api/aoi/calibration/speckle.pdf?paper=${paper}`} download>
                    <Download className="size-3.5" /> แผ่นลายจุด {paper.toUpperCase()} (PDF)
                  </a>
                ))}
                <span className="text-[11px] text-subtle self-center">พิมพ์ขนาดจริง 100% · ห้ามย่อให้พอดีหน้า</span>
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Segmented
              size="sm"
              value={density}
              onChange={setDensity}
              options={[
                { value: 5, label: "5×5 (เร็ว)" },
                { value: 7, label: "7×7" },
                { value: 9, label: "9×9 (ละเอียด)" },
              ]}
            />
            {mapRunning ? (
              stopButton
            ) : (
              <Button
                icon={Play}
                onClick={() => start("map")}
                disabled={!isOperator || busy || running || !last}
                title={!last ? "ต้อง calibrate แบบปกติก่อน" : undefined}
              >
                วัดทั้งราง
              </Button>
            )}
            {mapRunning && progressBar}
            {!running && status?.state === "error" && status.mode === "map" && <p className="text-xs text-fail min-w-0">{status.message}</p>}
          </div>
          {lastMap && <RailMapResults map={lastMap} />}
        </div>

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
