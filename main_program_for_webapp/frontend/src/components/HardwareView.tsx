"use client";

import React, { useEffect, useState } from "react";
import { Activity, Cpu, Fan, Gauge, Lock, MemoryStick, Rocket, Thermometer, Zap } from "lucide-react";
import type { HardwareSnapshot } from "@/types";
import { api } from "@/lib/api";
import { Badge, Button, Card, CardHeader, Segmented, Slider, Spinner, Toggle, cx } from "./ui";
import { useToast } from "./Toast";

const POLL_MS = 1000;
const HISTORY = 60; // samples kept per line (one minute)

type Series = { cpu: number[][]; gpu: number[]; watts: number[] };

/** Live performance of the station computer, plus Jetson power mode, max clocks and fan. */
export function HardwareView({ isOperator }: { isOperator: boolean }) {
  const toast = useToast();
  const [hw, setHw] = useState<HardwareSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [series, setSeries] = useState<Series>({ cpu: [], gpu: [], watts: [] });
  // Over-current counters when the page opened, to show whether they are still rising.
  const [ocStart, setOcStart] = useState<Record<string, number> | null>(null);

  const record = (d: HardwareSnapshot) => {
    setHw(d);
    setOcStart((s) => s ?? d.over_current ?? null);
    setSeries((s) => ({
      cpu: d.cpu.cores.map((c, i) => [...(s.cpu[i] ?? []), c.usage].slice(-HISTORY)),
      gpu: [...s.gpu, d.gpu?.usage ?? 0].slice(-HISTORY),
      watts: [...s.watts, d.power_rails?.[0]?.watts ?? 0].slice(-HISTORY),
    }));
  };

  // Poll once a second while the page is visible.
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    let first = true;
    const tick = async () => {
      if (first || !document.hidden) {
        first = false;
        try {
          const d = await api.hardware.get();
          if (!alive) return;
          setError(null);
          record(d);
        } catch (err) {
          if (alive) setError(err instanceof Error ? err.message : String(err));
        }
      }
      if (alive) timer = setTimeout(tick, POLL_MS);
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, []);

  if (!hw) {
    return (
      <div className="h-full grid place-items-center text-sm text-muted">
        {error ? `อ่านข้อมูลเครื่องไม่สำเร็จ: ${error}` : <Spinner className="size-6" />}
      </div>
    );
  }

  const jetson = hw.platform === "jetson";
  const mem = hw.memory;
  const input = hw.power_rails?.[0];
  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-6xl mx-auto p-4 md:p-6 flex flex-col gap-5">
        <div className="flex items-center gap-2 flex-wrap">
          <Badge tone={jetson ? "pass" : "neutral"}>{jetson ? "NVIDIA Jetson" : "คอมพิวเตอร์ทั่วไป"}</Badge>
          {hw.model && <span className="text-sm text-muted truncate">{hw.model}</span>}
          <span className="ml-auto flex items-center gap-1.5 text-xs text-muted">
            <Activity className="size-3.5 text-pass" /> อัปเดตทุก 1 วินาที
          </span>
        </div>

        {/* ── Summary ── */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Kpi icon={Cpu} label="CPU" value={`${hw.cpu.usage.toFixed(0)}%`} hint={`${hw.cpu.cores.length} คอร์ · load ${hw.cpu.load[0]}`} pct={hw.cpu.usage} />
          {hw.gpu ? (
            <Kpi icon={Gauge} label="GPU" value={`${hw.gpu.usage?.toFixed(0) ?? "–"}%`} hint={`${hw.gpu.mhz} / ${hw.gpu.max_mhz} MHz`} pct={hw.gpu.usage ?? 0} />
          ) : (
            <Kpi icon={Gauge} label="GPU" value="–" hint="อ่านได้บน Jetson" pct={0} />
          )}
          <Kpi icon={MemoryStick} label="RAM" value={`${((mem.used_mb / mem.total_mb) * 100).toFixed(0)}%`} hint={`${gb(mem.used_mb)} / ${gb(mem.total_mb)} GB`} pct={(mem.used_mb / mem.total_mb) * 100} />
          <Kpi
            icon={Thermometer}
            label="ร้อนสุด"
            value={hw.temperatures.length ? `${Math.max(...hw.temperatures.map((t) => t.c)).toFixed(0)}°C` : "–"}
            hint={hw.temperatures.length ? (hw.temperatures.reduce((a, b) => (b.c > a.c ? b : a)).name) : "ไม่มีเซนเซอร์"}
            pct={hw.temperatures.length ? Math.max(...hw.temperatures.map((t) => t.c)) : 0}
            tone={tempTone(hw.temperatures.length ? Math.max(...hw.temperatures.map((t) => t.c)) : 0)}
          />
        </div>

        {/* ── CPU cores ── */}
        <Card>
          <CardHeader icon={Cpu} title="CPU แต่ละคอร์" subtitle="การใช้งาน (%) และความถี่ปัจจุบัน · กราฟย้อนหลัง 1 นาที" />
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 p-4">
            {hw.cpu.cores.map((c, i) => (
              <div key={c.id} className="rounded-lg border border-line bg-surface-2 p-3 flex flex-col gap-1.5">
                <div className="flex items-baseline justify-between">
                  <span className="text-xs text-muted">คอร์ {c.id}</span>
                  <span className="text-lg font-semibold tabular">{c.usage.toFixed(0)}%</span>
                </div>
                <Spark values={series.cpu[i] ?? []} max={100} className="text-accent" />
                <div className="text-[11px] font-mono tabular text-muted">
                  {c.mhz ? `${c.mhz}${c.max_mhz ? ` / ${c.max_mhz}` : ""} MHz` : "–"}
                </div>
                {c.governor && <div className="text-[10px] text-subtle truncate">{c.governor}</div>}
              </div>
            ))}
          </div>
        </Card>

        <div className="grid md:grid-cols-2 gap-5">
          {hw.gpu && (
            <Card>
              <CardHeader icon={Gauge} title="GPU และหน่วยความจำ" />
              <div className="p-4 flex flex-col gap-3">
                <Spark values={series.gpu} max={100} className="text-pass h-14" />
                <Meter label="GPU" value={hw.gpu.usage ?? 0} text={`${hw.gpu.usage?.toFixed(0) ?? "–"}% · ${hw.gpu.mhz} MHz (สูงสุด ${hw.gpu.max_mhz})`} />
                {hw.emc && <Meter label="EMC (RAM bus)" value={(hw.emc.mhz / hw.emc.max_mhz) * 100} text={`${hw.emc.mhz} / ${hw.emc.max_mhz} MHz`} />}
                <Meter label="RAM" value={(mem.used_mb / mem.total_mb) * 100} text={`${gb(mem.used_mb)} / ${gb(mem.total_mb)} GB`} />
                <Meter
                  label="Swap"
                  value={mem.swap_total_mb ? (mem.swap_used_mb / mem.swap_total_mb) * 100 : 0}
                  text={mem.swap_total_mb ? `${gb(mem.swap_used_mb)} / ${gb(mem.swap_total_mb)} GB` : "ไม่มี swap — ถ้า RAM เต็มโปรแกรมจะถูกปิด (ดู INSTALL.md)"}
                  warn={!mem.swap_total_mb}
                />
              </div>
            </Card>
          )}

          <Card>
            <CardHeader icon={Thermometer} title="อุณหภูมิ" />
            <ul className="p-4 grid grid-cols-2 gap-2">
              {hw.temperatures.map((t) => (
                <li key={t.name} className="flex items-center justify-between rounded-lg bg-surface-2 px-3 py-2 text-sm">
                  <span className="text-muted">{t.name}</span>
                  <span className={cx("font-semibold tabular", { pass: "text-pass", review: "text-review", fail: "text-fail" }[tempTone(t.c)])}>{t.c.toFixed(1)}°C</span>
                </li>
              ))}
              {!hw.temperatures.length && <li className="col-span-2 text-xs text-muted">เครื่องนี้ไม่เปิดให้อ่านเซนเซอร์อุณหภูมิ</li>}
            </ul>
          </Card>

          {jetson && hw.power_rails && (
            <Card>
              <CardHeader icon={Zap} title="พลังงาน" subtitle={input ? `รวม ${input.watts.toFixed(1)} W` : undefined} />
              <div className="p-4 flex flex-col gap-3">
                <Spark values={series.watts} max={Math.max(15, ...series.watts)} className="text-review h-14" />
                {hw.power_rails.map((r) => (
                  <Meter
                    key={r.name}
                    label={r.name}
                    value={r.crit_amps ? (r.amps / r.crit_amps) * 100 : 0}
                    text={`${r.watts.toFixed(2)} W · ${r.volts} V × ${r.amps} A${r.crit_amps ? ` (เพดาน ${r.crit_amps} A)` : ""}`}
                    warn={!!r.crit_amps && r.amps / r.crit_amps > 0.85}
                  />
                ))}
                {hw.over_current && <OverCurrent now={hw.over_current} start={ocStart} />}
              </div>
            </Card>
          )}

          {jetson && hw.fan && (
            <Card>
              <CardHeader icon={Fan} title="พัดลม" subtitle={hw.fan.mode === "manual" ? `กำหนดเอง ${hw.fan.manual_percent}%` : `อัตโนมัติ · ${profileLabel(hw.fan.profile)}`} />
              <div className="p-4 flex items-center gap-4">
                <Fan className={cx("size-12 text-accent", (hw.fan.percent ?? 0) > 0 && "animate-spin")} style={{ animationDuration: `${Math.max(0.3, 3 - (hw.fan.percent ?? 0) / 40)}s` }} />
                <div className="flex flex-col">
                  <span className="text-2xl font-semibold tabular">{hw.fan.percent ?? "–"}%</span>
                  <span className="text-sm text-muted tabular">{hw.fan.rpm != null ? `${Math.round(hw.fan.rpm)} rpm` : "อ่านรอบไม่ได้"}</span>
                </div>
              </div>
            </Card>
          )}
        </div>

        {jetson ? (
          <JetsonControls hw={hw} isOperator={isOperator} onChange={record} toast={toast} />
        ) : (
          <p className="text-xs text-muted">การตั้งค่าโหมดพลังงาน ความถี่ และพัดลม ใช้ได้เมื่อสถานีรันบน NVIDIA Jetson</p>
        )}
      </div>
    </div>
  );
}

function JetsonControls({
  hw,
  isOperator,
  onChange,
  toast,
}: {
  hw: HardwareSnapshot;
  isOperator: boolean;
  onChange: (d: HardwareSnapshot) => void;
  toast: ReturnType<typeof useToast>;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [fanPct, setFanPct] = useState(hw.fan?.manual_percent ?? 60);
  const lock = !hw.control_available ? "ยังไม่ได้เปิดสิทธิ์ควบคุมพลังงานบน Jetson" : !isOperator ? "ขอสิทธิ์ควบคุมก่อน" : null;

  const run = async (key: string, task: () => Promise<{ hardware: HardwareSnapshot }>, done: string) => {
    setBusy(key);
    try {
      const res = await task();
      if (res.hardware?.cpu) onChange(res.hardware);
      toast.success(done);
    } catch (err) {
      toast.error("เปลี่ยนการตั้งค่าไม่สำเร็จ", err);
    } finally {
      setBusy(null);
    }
  };

  const modes = hw.power_mode?.modes ?? [];
  const fanMode = hw.fan?.mode === "manual" ? "manual" : (hw.fan?.profile ?? "quiet");
  return (
    <Card>
      <CardHeader icon={Rocket} title="ตั้งค่าพลังงานและพัดลม (Jetson)" subtitle="มีผลทันที · ต้องมีสิทธิ์ควบคุมสถานี" />
      <div className="p-4 flex flex-col gap-6">
        {(!hw.control_available || hw.helper_outdated) && (
          <div className="rounded-lg border border-review/50 bg-review-soft p-3 text-sm flex flex-col gap-1.5">
            <span className="font-semibold text-review flex items-center gap-1.5">
              <Lock className="size-4" /> {hw.helper_outdated ? "ตัวช่วยควบคุมพลังงานต้องอัปเดต (ต้องใช้ sudo บน Jetson)" : "เปิดสิทธิ์ครั้งเดียว (ต้องใช้ sudo บน Jetson)"}
            </span>
            <code className="font-mono text-xs bg-surface rounded px-2 py-1 select-all break-all">cd ~/Desktop/PCB_DETECT_RMUTT_GUI/main_program_for_webapp && sudo ./scripts/jetson/install-power-control.sh</code>
            <span className="text-xs text-muted">ติดตั้งตัวช่วยที่รับเฉพาะคำสั่งเปลี่ยนโหมดพลังงาน ความถี่ และพัดลมเท่านั้น จากนั้นรีเฟรชหน้านี้</span>
          </div>
        )}

        <section className="flex flex-col gap-2">
          <h4 className="text-sm font-semibold">โหมดพลังงาน (nvpmodel)</h4>
          <div className="flex flex-wrap gap-2">
            {modes.map((m) => {
              const active = hw.power_mode?.current === m.id;
              return (
                <Button
                  key={m.id}
                  variant={active ? "primary" : "secondary"}
                  loading={busy === `mode-${m.id}`}
                  disabled={!!busy || active || lock !== null}
                  reason={active ? null : lock}
                  onClick={() => {
                    if (window.confirm(`เปลี่ยนโหมดพลังงานเป็น ${m.name}?`)) run(`mode-${m.id}`, () => api.hardware.powerMode(m.id), `ใช้โหมด ${m.name} แล้ว`);
                  }}
                >
                  {m.name}
                </Button>
              );
            })}
          </div>
          <p className="text-xs text-muted">
            โหมดสูงเร็วกว่าแต่กินไฟมากกว่า ถ้าเห็นเตือน <em>over-current</em> บ่อย หรือใช้อะแดปเตอร์ไฟไม่ใช่ของแท้ ให้ใช้ 25W
          </p>
        </section>

        <section className="flex flex-col gap-2">
          <Toggle
            label="ล็อกความถี่สูงสุด (jetson_clocks)"
            description="ให้ CPU / GPU / หน่วยความจำวิ่งที่ความถี่สูงสุดของโหมดปัจจุบันตลอดเวลา ไม่ลดลงตอนว่าง — ตอบสนองไวขึ้นแต่ร้อนและกินไฟขึ้น พัดลมจะหมุนเต็มที่"
            checked={!!hw.clocks_max}
            disabled={!!busy || lock !== null}
            onChange={(on) => run("clocks", () => api.hardware.clocks(on), on ? "ล็อกความถี่สูงสุดแล้ว" : "กลับเป็นความถี่อัตโนมัติแล้ว")}
          />
          <p className="text-xs text-muted">
            Jetson ไม่รองรับการโอเวอร์คล็อกเกินสเปกที่ NVIDIA กำหนด — แรงสุดที่ทำได้อย่างปลอดภัยคือโหมด MAXN_SUPER ร่วมกับการล็อกความถี่สูงสุด
          </p>
        </section>

        <section className="flex flex-col gap-3">
          <h4 className="text-sm font-semibold">พัดลม</h4>
          <Segmented
            className="self-start"
            value={fanMode}
            disabled={!!busy || lock !== null}
            onChange={(m) => {
              if (m !== "manual") run("fan", () => api.hardware.fan(m as "quiet" | "cool"), m === "cool" ? "พัดลมอัตโนมัติ: เน้นเย็น" : "พัดลมอัตโนมัติ: เน้นเงียบ");
              else run("fan", () => api.hardware.fan("manual", fanPct), `พัดลมคงที่ ${fanPct}%`);
            }}
            options={[
              { value: "quiet", label: "อัตโนมัติ · เงียบ" },
              { value: "cool", label: "อัตโนมัติ · เย็น" },
              { value: "manual", label: "กำหนดเอง" },
            ]}
          />
          {fanMode === "manual" && (
            <div className="flex items-end gap-3 flex-wrap">
              <div className="flex-1 min-w-48">
                <Slider label="ความเร็ว" value={fanPct} min={20} max={100} step={5} format={(v) => `${v}%`} disabled={lock !== null} onChange={setFanPct} />
              </div>
              <Button loading={busy === "fan-set"} disabled={!!busy || lock !== null} onClick={() => run("fan-set", () => api.hardware.fan("manual", fanPct), `พัดลมคงที่ ${fanPct}%`)}>
                ใช้ความเร็วนี้
              </Button>
            </div>
          )}
          <p className="text-xs text-muted">
            ความเร็วที่กำหนดเองคงอยู่จนกว่าจะเลือกโหมดอัตโนมัติ (รวมถึงหลังรีบูต) · ขั้นต่ำ 20% และถ้าอุณหภูมิถึง 85°C ระบบเร่งเป็น 100% ให้เพื่อความปลอดภัย (ยังอยู่ในโหมดกำหนดเอง ปรับลดเองได้ภายหลัง)
          </p>
        </section>
      </div>
    </Card>
  );
}

function OverCurrent({ now, start }: { now: Record<string, number>; start: Record<string, number> | null }) {
  const total = Object.values(now).reduce((a, b) => a + b, 0);
  const since = start ? Object.entries(now).reduce((a, [k, v]) => a + (v - (start[k] ?? v)), 0) : 0;
  return (
    <div className={cx("rounded-lg px-3 py-2 text-xs flex items-center gap-2", since > 0 ? "bg-fail-soft text-fail" : "bg-surface-2 text-muted")}>
      <Zap className="size-3.5 shrink-0" />
      <span>
        ไฟเกิน (over-current) ตั้งแต่เปิดเครื่อง <strong className="tabular">{total.toLocaleString()}</strong> ครั้ง
        {since > 0 ? ` · เพิ่มขึ้น ${since} ครั้งตั้งแต่เปิดหน้านี้ — ลดโหมดพลังงานหรือตรวจอะแดปเตอร์ไฟ` : " · ไม่เพิ่มขึ้นตั้งแต่เปิดหน้านี้"}
      </span>
    </div>
  );
}

function Kpi({ icon: Icon, label, value, hint, pct, tone }: { icon: typeof Cpu; label: string; value: string; hint: string; pct: number; tone?: "pass" | "review" | "fail" }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-3 flex flex-col gap-1">
      <span className="flex items-center gap-1.5 text-xs text-muted">
        <Icon className="size-3.5" /> {label}
      </span>
      <span className={cx("text-2xl font-semibold tabular", tone && { pass: "text-pass", review: "text-review", fail: "text-fail" }[tone])}>{value}</span>
      <div className="h-1 rounded-full bg-surface-3 overflow-hidden">
        <div className={cx("h-full transition-all duration-500", barTone(pct))} style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
      <span className="text-[11px] text-subtle truncate">{hint}</span>
    </div>
  );
}

function Meter({ label, value, text, warn }: { label: string; value: number; text: string; warn?: boolean }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="font-medium">{label}</span>
        <span className={cx("tabular text-right", warn ? "text-review" : "text-muted")}>{text}</span>
      </div>
      <div className="h-1.5 rounded-full bg-surface-3 overflow-hidden">
        <div className={cx("h-full transition-all duration-500", warn ? "bg-review" : barTone(value))} style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
      </div>
    </div>
  );
}

/** Minimal line chart of the last minute. */
function Spark({ values, max, className }: { values: number[]; max: number; className?: string }) {
  const w = 120;
  const h = 32;
  const pts = values.map((v, i) => `${(i / Math.max(1, HISTORY - 1)) * w},${h - (Math.min(v, max) / max) * (h - 2) - 1}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className={cx("w-full h-8", className)} aria-hidden>
      {values.length > 1 && (
        <>
          <polygon points={`0,${h} ${pts} ${((values.length - 1) / Math.max(1, HISTORY - 1)) * w},${h}`} fill="currentColor" opacity={0.15} />
          <polyline points={pts} fill="none" stroke="currentColor" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
        </>
      )}
    </svg>
  );
}

const gb = (mb: number) => (mb / 1024).toFixed(1);
const tempTone = (c: number): "pass" | "review" | "fail" => (c >= 80 ? "fail" : c >= 65 ? "review" : "pass");
const barTone = (pct: number) => (pct >= 90 ? "bg-fail" : pct >= 70 ? "bg-review" : "bg-accent");
const profileLabel = (p: string | null) => (p === "cool" ? "เน้นเย็น" : p === "quiet" ? "เน้นเงียบ" : (p ?? "–"));
