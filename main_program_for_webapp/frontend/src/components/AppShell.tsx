"use client";

import React, { useState } from "react";
import {
  BarChart3,
  BookMarked,
  Database,
  Cpu,
  Crosshair,
  Gauge,
  Eye,
  Image as ImageIcon,
  KeyRound,
  LogOut,
  Moon,
  OctagonX,
  ScanLine,
  Settings,
  ShieldCheck,
  Sun,
  Video,
  Volume2,
  VolumeX,
  Wifi,
  WifiOff,
  type LucideIcon,
} from "lucide-react";
import type { SystemStatus } from "@/types";
import { api, errorMessage } from "@/lib/api";
import { fileName, formatMm } from "@/lib/format";
import type { OperatorLease } from "@/hooks/useOperatorLease";
import { useSoundPrefs } from "@/hooks/useSound";
import { sfx } from "@/lib/sound";
import { Button, Checkbox, Field, Modal, StatusDot, TextInput, cx } from "./ui";
import { useToast } from "./Toast";
import { OpenOnPhoneButton } from "./RemoteAccess";

export type TabId = "aoi" | "inspect" | "dataset" | "references" | "history" | "hardware" | "settings";

export const NAV: Array<{ id: TabId; label: string; short: string; icon: LucideIcon; description: string }> = [
  { id: "aoi", label: "สแกน AOI", short: "AOI", icon: ScanLine, description: "มาร์คจุด สอนต้นแบบ และสแกนบอร์ดอัตโนมัติด้วยสเตจ XY" },
  { id: "inspect", label: "ตรวจภาพเดี่ยว", short: "ตรวจภาพ", icon: ImageIcon, description: "ตรวจจากกล้องสดหรืออัปโหลดภาพ เทียบกับโปรไฟล์อ้างอิง" },
  { id: "dataset", label: "ชุดข้อมูลเทรน", short: "ข้อมูล", icon: Database, description: "มาร์ค 4 มุมบอร์ด ถ่ายทั้งบอร์ดอัตโนมัติ แก้ label และดาวน์โหลดไปเทรนโมเดล" },
  { id: "references", label: "บอร์ด", short: "บอร์ด", icon: BookMarked, description: "บอร์ดที่สอนไว้: ภาพต้นแบบ ความพร้อมก่อนสแกน ประวัติและ yield ของแต่ละบอร์ด" },
  { id: "history", label: "ประวัติ & Yield", short: "ประวัติ", icon: BarChart3, description: "ผลการตรวจย้อนหลังและอัตราผ่านการผลิต" },
  { id: "hardware", label: "ประสิทธิภาพเครื่อง", short: "เครื่อง", icon: Gauge, description: "CPU/GPU แต่ละคอร์ อุณหภูมิ พลังงาน พัดลม และโหมดพลังงาน Jetson แบบสด" },
  { id: "settings", label: "ตั้งค่าสถานี", short: "ตั้งค่า", icon: Settings, description: "โมเดล ฮาร์ดแวร์ประมวลผล ขอบเขตสเตจ และข้อมูลสถานี" },
];

interface AppShellProps {
  tab: TabId;
  onTab: (tab: TabId) => void;
  status: SystemStatus | null;
  socketConnected: boolean;
  onRefreshStatus: () => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  lease: OperatorLease;
  children: React.ReactNode;
}

export function AppShell({ tab, onTab, status, socketConnected, onRefreshStatus, theme, onToggleTheme, lease, children }: AppShellProps) {
  const current = NAV.find((n) => n.id === tab)!;
  const [askControl, setAskControl] = useState(false);
  return (
    <div className="h-dvh flex bg-bg text-text">
      {/* Sidebar (md+) */}
      <aside className="hidden md:flex w-[76px] xl:w-60 shrink-0 flex-col border-r border-line bg-surface">
        <div className="h-14 flex items-center gap-2.5 px-4 border-b border-line">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/rmutt-logo.png" alt="RMUTT" className="h-10 w-auto shrink-0 drop-shadow" draggable={false} />
          <div className="hidden xl:block min-w-0">
            <div className="text-sm font-semibold leading-tight">RMUTT AOI</div>
            <div className="text-[11px] text-muted leading-tight truncate">PCB Inspection Station</div>
          </div>
        </div>
        <nav className="flex-1 p-2 flex flex-col gap-0.5">
          {NAV.map((item) => {
            const active = item.id === tab;
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => onTab(item.id)}
                aria-current={active ? "page" : undefined}
                title={item.label}
                className={cx(
                  "flex items-center gap-3 rounded-lg px-3 h-10 text-sm transition-colors cursor-pointer",
                  "justify-center xl:justify-start",
                  active ? "bg-accent-soft text-accent font-semibold" : "text-muted hover:bg-surface-2 hover:text-text"
                )}
              >
                <Icon className="size-[18px] shrink-0" />
                <span className="hidden xl:inline truncate">{item.label}</span>
              </button>
            );
          })}
        </nav>
        <SystemHealth status={status} socketConnected={socketConnected} />
      </aside>

      <div className="flex-1 min-w-0 flex flex-col">
        <header className="h-14 shrink-0 flex items-center gap-3 px-4 border-b border-line bg-surface">
          <div className="min-w-0 flex-1">
            <h1 className="text-[15px] font-semibold leading-tight truncate">{current.label}</h1>
            <p className="hidden sm:block text-[11px] text-muted leading-tight truncate">{current.description}</p>
          </div>
          <StatusChips status={status} />
          <OperatorControl status={status} lease={lease} open={askControl} setOpen={setAskControl} />
          <OpenOnPhoneButton />
          <SoundToggle />
          <button
            type="button"
            onClick={onToggleTheme}
            aria-label={theme === "dark" ? "เปลี่ยนเป็นธีมสว่าง" : "เปลี่ยนเป็นธีมมืด"}
            title="สลับธีม"
            className="size-9 grid place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-text cursor-pointer"
          >
            {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </button>
          <EmergencyStop onDone={onRefreshStatus} />
        </header>

        {lease.controlled && !lease.isMine && (
          <ViewOnlyBanner name={status?.control_lease.operator_name} ip={status?.control_lease.client_ip} onRequest={() => setAskControl(true)} />
        )}
        <main className="flex-1 min-h-0 overflow-hidden pb-16 md:pb-0">{children}</main>
      </div>

      {/* Bottom nav (mobile / tablet portrait) */}
      <nav className="md:hidden fixed bottom-0 inset-x-0 z-40 h-16 grid grid-cols-7 border-t border-line bg-surface">
        {NAV.map((item) => {
          const active = item.id === tab;
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onTab(item.id)}
              className={cx("flex flex-col items-center justify-center gap-1 text-[10px] sm:text-[11px] cursor-pointer", active ? "text-accent font-semibold" : "text-muted")}
            >
              <Icon className="size-5" />
              {item.short}
            </button>
          );
        })}
      </nav>
    </div>
  );
}

function SoundToggle() {
  const { enabled } = useSoundPrefs();
  return (
    <button
      type="button"
      onClick={() => sfx.setEnabled(!enabled)}
      aria-label={enabled ? "ปิดเสียงเอฟเฟกต์" : "เปิดเสียงเอฟเฟกต์"}
      aria-pressed={enabled}
      title={enabled ? "เสียงเอฟเฟกต์: เปิด" : "เสียงเอฟเฟกต์: ปิด"}
      className="size-9 grid place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-text cursor-pointer"
    >
      {enabled ? <Volume2 className="size-4" /> : <VolumeX className="size-4" />}
    </button>
  );
}

function StatusChips({ status }: { status: SystemStatus | null }) {
  if (!status) return null;
  const m = status.machine;
  const chips = [
    {
      icon: Cpu,
      tone: status.model_loaded ? "pass" : "fail",
      label: status.model_loaded ? status.active_device : "ไม่มีโมเดล",
      title: status.model_loaded ? `โมเดล: ${fileName(status.model_path)}` : "ยังไม่ได้โหลดโมเดล YOLO",
    },
    {
      icon: Video,
      tone: !status.camera_active ? "neutral" : status.camera_is_mock ? "review" : "pass",
      label: !status.camera_active
        ? "กล้องปิด"
        : status.camera_is_mock
          ? "กล้องจำลอง"
          : `${status.camera_resolution?.[1] ?? ""}p · ${Math.round(status.camera_fps)}fps`,
      title: status.camera_is_mock ? "ไม่พบกล้องจริง — ใช้ภาพจำลอง (ผลตรวจจะเป็น REVIEW)" : "สถานะกล้อง",
    },
    {
      icon: Crosshair,
      tone: !m.connected ? "neutral" : m.homed ? "pass" : "review",
      label: !m.connected ? "สเตจไม่เชื่อมต่อ" : !m.homed ? "ยังไม่ HOME" : m.is_moving ? "กำลังเคลื่อนที่" : m.mode === "serial" ? "สเตจพร้อม" : "สเตจจำลอง",
      title: m.connected ? `สเตจ ${m.mode === "serial" ? m.port : "จำลอง"} · ${formatMm(m.position_mm[0])}, ${formatMm(m.position_mm[1])} mm` : "สเตจ XY",
    },
  ] as const;
  return (
    <div className="hidden lg:flex items-center gap-1.5">
      {chips.map((c) => (
        <span
          key={c.title}
          title={c.title}
          className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg border border-line bg-surface-2 text-xs text-muted"
        >
          <StatusDot tone={c.tone} />
          <c.icon className="size-3.5" />
          <span className="font-mono tabular text-text max-w-[150px] truncate">{c.label}</span>
        </span>
      ))}
    </div>
  );
}

function SystemHealth({ status, socketConnected }: { status: SystemStatus | null; socketConnected: boolean }) {
  return (
    <div className="border-t border-line p-3 hidden xl:flex flex-col gap-1.5 text-[11px] text-muted">
      <div className="flex items-center gap-2">
        {socketConnected ? <Wifi className="size-3.5 text-pass" /> : <WifiOff className="size-3.5 text-review" />}
        {socketConnected ? "เชื่อมต่อเรียลไทม์" : "กำลังเชื่อมต่อใหม่…"}
      </div>
      {status && (
        <div className="truncate" title={status.model_path}>
          โมเดล: <span className="text-text">{status.model_loaded ? fileName(status.model_path) : "–"}</span>
        </div>
      )}
    </div>
  );
}

/** Someone else holds the station: say so, instead of leaving buttons silently refused. */
function ViewOnlyBanner({ name, ip, onRequest }: { name?: string | null; ip?: string | null; onRequest: () => void }) {
  return (
    <div className="shrink-0 flex items-center gap-2 px-4 py-1.5 border-b border-review/40 bg-review-soft text-review text-xs animate-rise">
      <Eye className="size-4 shrink-0" />
      <span className="min-w-0 truncate">
        <strong className="font-semibold">โหมดดูอย่างเดียว</strong> · สถานีถูกควบคุมโดย <strong className="font-semibold">{name || "ผู้อื่น"}</strong>
        {ip ? ` (${ip})` : ""} — คำสั่งเคลื่อนที่ สแกน และแก้ไขจะใช้ไม่ได้ (ปุ่ม STOP ใช้ได้เสมอ)
      </span>
      <button type="button" onClick={onRequest} className="ml-auto shrink-0 font-semibold underline underline-offset-2 hover:no-underline cursor-pointer">
        ขอสิทธิ์ควบคุม
      </button>
    </div>
  );
}

function OperatorControl({
  status,
  lease: { isMine, controlled, acquire, release },
  open,
  setOpen,
}: {
  status: SystemStatus | null;
  lease: OperatorLease;
  open: boolean;
  setOpen: (open: boolean) => void;
}) {
  const lease = status?.control_lease;
  const [name, setName] = useState("Operator");
  const [passcode, setPasscode] = useState("");
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await acquire(name.trim() || "Operator", passcode, force);
      setOpen(false);
      setPasscode("");
      setForce(false);
      toast.success("ได้รับสิทธิ์ควบคุมสถานีแล้ว");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {isMine ? (
        <Button
          size="sm"
          variant="secondary"
          icon={ShieldCheck}
          className="text-pass"
          title="คุณถือสิทธิ์ควบคุม — คลิกเพื่อคืนสิทธิ์"
          onClick={() => release().catch((err) => toast.error("คืนสิทธิ์ไม่สำเร็จ", err))}
        >
          <span className="hidden sm:inline max-w-[110px] truncate">{lease?.operator_name}</span>
          <LogOut className="size-3.5 text-muted" />
        </Button>
      ) : (
        <Button size="sm" variant={controlled ? "secondary" : "primary"} icon={KeyRound} onClick={() => setOpen(true)}>
          <span className="hidden sm:inline">{controlled ? `ควบคุมโดย ${lease?.operator_name}` : "ขอสิทธิ์ควบคุม"}</span>
        </Button>
      )}

      <Modal open={open} onClose={() => setOpen(false)} size="sm" title="ขอสิทธิ์ควบคุมสถานี" subtitle="ผู้ควบคุมได้ครั้งละหนึ่งคน ผู้อื่นดูได้อย่างเดียว (ปุ่ม STOP ใช้ได้ทุกคน)">
        <form onSubmit={submit} className="flex flex-col gap-4">
          <Field label="ชื่อผู้ควบคุม" htmlFor="op-name">
            <TextInput id="op-name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
          </Field>
          <Field label="รหัสผ่านสถานี" htmlFor="op-pass">
            <TextInput id="op-pass" type="password" value={passcode} onChange={(e) => setPasscode(e.target.value)} autoComplete="current-password" autoFocus />
          </Field>
          {controlled && (
            <Checkbox checked={force} onChange={setForce}>
              ยึดสิทธิ์จาก <strong>{lease?.operator_name}</strong> ({lease?.client_ip})
            </Checkbox>
          )}
          {error && <p className="text-sm text-fail">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              ยกเลิก
            </Button>
            <Button type="submit" variant="primary" loading={busy} disabled={controlled && !force}>
              ยืนยัน
            </Button>
          </div>
        </form>
      </Modal>
    </>
  );
}

function EmergencyStop({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const stop = async () => {
    sfx.alarm();
    setBusy(true);
    try {
      await api.stopEmergency();
      toast.warning("หยุดฉุกเฉินแล้ว", "สเตจหยุดและยกเลิกการสแกนที่กำลังทำงาน");
    } catch (err) {
      toast.error("ส่งคำสั่ง STOP ไม่สำเร็จ", err);
    } finally {
      setBusy(false);
      onDone();
    }
  };
  return (
    <button
      type="button"
      onClick={stop}
      disabled={busy}
      title="หยุดฉุกเฉิน: หยุดสเตจและยกเลิกการสแกนทันที (ใช้ได้ทุกเครื่อง)"
      className="h-10 px-4 rounded-lg bg-fail text-white font-bold text-sm tracking-wide inline-flex items-center gap-2 shadow-card hover:brightness-110 active:scale-[0.97] transition cursor-pointer disabled:opacity-70 ring-2 ring-fail/30"
    >
      <OctagonX className="size-[18px]" />
      STOP
    </button>
  );
}
