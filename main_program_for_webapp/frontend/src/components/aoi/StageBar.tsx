"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Home, Plug, PlugZap, Power, RefreshCw, Unplug } from "lucide-react";
import type { MachineState, SerialPort, StageErrorState } from "@/types";
import { api } from "@/lib/api";
import { formatMm } from "@/lib/format";
import { Badge, Button, IconButton, Select, StatusDot, cx } from "../ui";
import { useToast } from "../Toast";
import { sfx } from "@/lib/sound";

const STATUS_TEXT: Partial<Record<StageErrorState["status"], string>> = {
  needs_calibration: "calibrate ราง XY ก่อน (หน้าตั้งค่า) จึงจะวัดได้",
  no_texture: "ภาพไม่มีลายพอให้วัด",
  no_camera: "ต้องใช้กล้องจริง",
};

const tone = (um: number) => (um >= 150 ? "text-fail" : um >= 50 ? "text-review" : "text-pass");
const signed = (mm: number) => `${mm >= 0 ? "+" : "−"}${Math.abs(Math.round(mm * 1000))}`;

/** Live positioning error: the last move's X/Y error and a sparkline of the recent moves. */
function StageErrorReadout({ state }: { state: StageErrorState | null }) {
  if (!state) return null;
  const last = state.samples[state.samples.length - 1];
  if (!last) {
    const hint = STATUS_TEXT[state.status] ?? "ขยับสเตจเพื่อวัดความคลาดเคลื่อน";
    return <span className="text-[11px] text-subtle">คลาดเคลื่อน: {hint}</span>;
  }
  const recent = state.samples.slice(-30).map((s) => s.error_um);
  const top = Math.max(60, ...recent);
  const W = 72;
  const H = 20;
  const pts = recent.map((v, i) => `${(i / Math.max(1, recent.length - 1)) * W},${H - (v / top) * (H - 2) - 1}`).join(" ");
  const sum = state.summary;
  const title =
    `ล่าสุด: สั่ง ${last.move_mm[0].toFixed(2)}, ${last.move_mm[1].toFixed(2)} mm · คลาด X ${signed(last.error_mm[0])} Y ${signed(last.error_mm[1])} µm` +
    (sum.rms_um ? `\nRMS ${sum.n} ครั้ง: X ${sum.rms_um[0]} Y ${sum.rms_um[1]} µm · สูงสุด ${sum.max_um} µm` : "") +
    (STATUS_TEXT[state.status] ? `\n${STATUS_TEXT[state.status]}` : "");
  return (
    <div className="h-8 px-2.5 rounded-lg bg-surface-2 border border-line flex items-center gap-2 font-mono tabular text-xs" title={title}>
      <span className="text-subtle font-sans">คลาด</span>
      <span key={last.time} className={cx("animate-pop", tone(last.error_um))}>
        X {signed(last.error_mm[0])} · Y {signed(last.error_mm[1])}
      </span>
      <span className="text-subtle">µm</span>
      {recent.length > 1 && (
        <svg width={W} height={H} className="text-accent shrink-0" aria-hidden>
          <line x1={0} x2={W} y1={H - (50 / top) * (H - 2) - 1} y2={H - (50 / top) * (H - 2) - 1} className="stroke-review/50" strokeDasharray="2 2" />
          <polyline points={pts} fill="none" stroke="currentColor" strokeWidth={1.4} />
        </svg>
      )}
    </div>
  );
}

/** Stage connection, homing and position readout across the top of the AOI screen. */
export function StageBar({
  machine,
  scanning,
  onChange,
  lockReason = null,
  stageError = null,
}: {
  machine: MachineState | null;
  scanning: boolean;
  onChange: () => void;
  /** Set while another operator holds the station: every control is locked with this reason. */
  lockReason?: string | null;
  /** Live, camera-measured positioning error of the moves. */
  stageError?: StageErrorState | null;
}) {
  const locked = lockReason !== null;
  const [ports, setPorts] = useState<SerialPort[]>([]);
  const [port, setPort] = useState("");
  const [busy, setBusy] = useState<"connect" | "home" | null>(null);
  const toast = useToast();
  const connected = Boolean(machine?.connected);

  const refreshPorts = useCallback(() => {
    api
      .listPorts()
      .then((res) => {
        setPorts(res.ports);
        setPort((current) => current || res.ports.find((p) => p.is_usb)?.device || res.ports[0]?.device || "");
      })
      .catch((err) => toast.error("อ่านรายการพอร์ตไม่สำเร็จ", err));
  }, [toast]);

  useEffect(() => {
    refreshPorts();
  }, [refreshPorts]);

  const run = async (kind: "connect" | "home", action: () => Promise<unknown>, failTitle: string) => {
    setBusy(kind);
    try {
      await action();
      sfx.ding();
    } catch (err) {
      toast.error(failTitle, err);
    } finally {
      setBusy(null);
      onChange();
    }
  };

  const disconnect = async () => {
    try {
      await api.disconnectMachine();
    } catch (err) {
      toast.error("ตัดการเชื่อมต่อไม่สำเร็จ", err);
    }
    onChange();
  };

  const motorsOff = async () => {
    try {
      await api.motorsOff();
      toast.info("ปิดมอเตอร์แล้ว", "ต้องสั่ง HOME ใหม่ก่อนเคลื่อนที่");
    } catch (err) {
      toast.error("ปิดมอเตอร์ไม่สำเร็จ", err);
    }
    onChange();
  };

  return (
    <div className="flex items-center gap-2 flex-wrap px-4 py-2.5 border-b border-line bg-surface" data-tour="stage">
      <div className="flex items-center gap-2 mr-1">
        <StatusDot tone={!connected ? "neutral" : machine?.homed ? "pass" : "review"} pulse={machine?.is_moving} />
        <span className="text-sm font-medium">สเตจ XY</span>
        {connected && <Badge tone={machine?.mode === "serial" ? "accent" : "review"}>{machine?.mode === "serial" ? "Serial" : "จำลอง"}</Badge>}
      </div>

      {!connected ? (
        <>
          <Select value={port} onChange={(e) => setPort(e.target.value)} className="w-56! h-8! text-xs" aria-label="พอร์ตอนุกรม">
            {ports.map((p) => (
              <option key={p.device} value={p.device}>
                {p.device}
                {p.is_usb ? " · USB" : ""}
              </option>
            ))}
            {!ports.length && <option value="">ไม่พบพอร์ต</option>}
          </Select>
          <IconButton icon={RefreshCw} label="รีเฟรชพอร์ต" size="sm" onClick={refreshPorts} />
          <Button
            size="sm"
            variant="primary"
            icon={Plug}
            loading={busy === "connect"}
            disabled={!port || locked}
            reason={lockReason}
            onClick={() => run("connect", () => api.connectMachine("serial", port), "เชื่อมต่อสเตจไม่สำเร็จ")}
          >
            เชื่อมต่อ
          </Button>
          <Button
            size="sm"
            variant="ghost"
            icon={PlugZap}
            loading={busy === "connect"}
            disabled={locked}
            onClick={() => run("connect", () => api.connectMachine("simulation"), "เปิดสเตจจำลองไม่สำเร็จ")}
            title="ทดลองใช้งานโดยไม่ต่อฮาร์ดแวร์"
          >
            จำลอง
          </Button>
        </>
      ) : (
        <>
          <Button
            size="sm"
            variant={machine?.homed ? "secondary" : "primary"}
            icon={Home}
            loading={busy === "home"}
            disabled={scanning || machine?.is_moving || locked}
            reason={lockReason}
            onClick={() =>
              run(
                "home",
                async () => {
                  const res = (await api.homeMachine()) as { state?: MachineState };
                  const info = res?.state?.home_info;
                  if (info) {
                    // steps → µm with the stage's 512 steps/mm
                    const um = (ax: "X" | "Y") => (info[ax] ? `${Math.round((info[ax].spread_steps / 512) * 1000)} µm` : "–");
                    const n = info.X?.touches ?? info.Y?.touches;
                    toast.info("HOME ละเอียดเสร็จ", `แตะ limit ${n} ครั้งต่อแกน · ต่างกัน X ${um("X")} · Y ${um("Y")}`);
                  }
                },
                "HOME ไม่สำเร็จ"
              )
            }
          >
            HOME
          </Button>
          {machine?.homed && machine.home_info && (
            <span
              className="text-[11px] text-subtle font-mono tabular"
              title="HOME แตะ limit ช้าๆ หลายครั้งแล้วใช้ค่าเฉลี่ย — ตัวเลขคือระยะที่จุดสัมผัสแต่ละครั้งต่างกัน (ความซ้ำของสวิตช์)"
            >
              ±{Math.round((Math.max(machine.home_info.X?.spread_steps ?? 0, machine.home_info.Y?.spread_steps ?? 0) / 512) * 1000)} µm
            </span>
          )}
          <div className="h-8 px-3 rounded-lg bg-surface-2 border border-line flex items-center gap-3 font-mono tabular text-xs">
            <span>
              <span className="text-subtle">X</span> {formatMm(machine?.position_mm[0])}
            </span>
            <span>
              <span className="text-subtle">Y</span> {formatMm(machine?.position_mm[1])}
            </span>
            <span className="text-subtle">mm</span>
          </div>
          {!machine?.homed && <span className="text-xs text-review font-medium">← กด HOME ก่อนเคลื่อนที่</span>}
          {machine?.homed && machine.mode === "serial" && <StageErrorReadout state={stageError} />}
          <div className="ml-auto flex items-center gap-1">
            <Button size="sm" variant="ghost" icon={Power} disabled={scanning || locked} onClick={motorsOff}>
              ปิดมอเตอร์
            </Button>
            <Button size="sm" variant="ghost" icon={Unplug} disabled={locked} onClick={disconnect}>
              ตัดการเชื่อมต่อ
            </Button>
          </div>
        </>
      )}
      {machine?.last_error && <span className="basis-full text-xs text-fail truncate">⚠ {machine.last_error}</span>}
    </div>
  );
}
