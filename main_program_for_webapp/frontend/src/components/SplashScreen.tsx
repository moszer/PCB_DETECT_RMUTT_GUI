"use client";

import React, { useEffect, useState } from "react";
import { AlertTriangle, Check, Loader2, Minus } from "lucide-react";
import { api } from "@/lib/api";
import type { SystemStatus } from "@/types";
import { Button, cx } from "./ui";
import { DecorPcb } from "./three/DecorPcb";

type StepState = "wait" | "ok" | "warn" | "fail";
interface Step {
  label: string;
  state: StepState;
  detail?: string;
}

const MIN_SHOW_MS = 1600;
const GIVE_UP_MS = 12_000;

/**
 * Start-up screen with the RMUTT logo. It checks the station while the app loads underneath:
 * backend reachable, YOLO model, camera and stage. Only the backend is required to continue.
 */
export function SplashScreen({ onDone }: { onDone: () => void }) {
  const [steps, setSteps] = useState<Step[]>([
    { label: "เชื่อมต่อเซิร์ฟเวอร์", state: "wait" },
    { label: "โมเดล AI ตรวจจับชิ้นส่วน", state: "wait" },
    { label: "กล้องและสเตจ XY", state: "wait" },
  ]);
  const [failed, setFailed] = useState(false);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    let alive = true;
    const started = Date.now();
    const finish = () => {
      const wait = Math.max(0, MIN_SHOW_MS - (Date.now() - started));
      setTimeout(() => {
        if (!alive) return;
        setLeaving(true);
        setTimeout(() => alive && onDone(), 450);
      }, wait);
    };
    const set = (i: number, step: Partial<Step>) => setSteps((all) => all.map((s, k) => (k === i ? { ...s, ...step } : s)));

    const attempt = async () => {
      let status: SystemStatus | null = null;
      while (alive && !status) {
        try {
          status = await api.getStatus();
        } catch {
          if (Date.now() - started > GIVE_UP_MS) {
            set(0, { state: "fail", detail: "ติดต่อ backend ไม่ได้" });
            setFailed(true);
            return;
          }
          await new Promise((r) => setTimeout(r, 800));
        }
      }
      if (!alive || !status) return;
      set(0, { state: "ok" });
      await new Promise((r) => setTimeout(r, 250));
      set(1, status.model_loaded ? { state: "ok", detail: status.active_device } : { state: "warn", detail: "ยังไม่ได้โหลด — เลือกได้ในหน้าตั้งค่า" });
      await new Promise((r) => setTimeout(r, 250));
      const cam = status.camera_active ? "กล้องพร้อม" : "กล้องจะเปิดเมื่อใช้งาน";
      const stage = status.machine?.connected ? (status.machine.homed ? "สเตจพร้อม" : "สเตจยังไม่ HOME") : "สเตจยังไม่เชื่อมต่อ";
      set(2, { state: status.machine?.connected ? "ok" : "warn", detail: `${cam} · ${stage}` });
      finish();
    };
    attempt();
    return () => {
      alive = false;
    };
  }, [onDone]);

  const done = steps.filter((s) => s.state !== "wait").length;

  return (
    <div
      className={cx(
        "fixed inset-0 z-[100] grid place-items-center bg-bg transition-opacity duration-500",
        leaving ? "opacity-0 pointer-events-none" : "opacity-100"
      )}
      role="status"
      aria-live="polite"
    >
      <div className="absolute inset-0 pointer-events-none splash-glow" aria-hidden />
      {/* A circuit board assembling itself behind the logo (2D splash when 3D is off). */}
      <div className="absolute inset-x-0 top-1/2 -translate-y-[62%] flex justify-center opacity-45 pointer-events-none" aria-hidden>
        <DecorPcb variant="assemble" className="w-[min(96vw,760px)] h-[min(62vh,460px)]" />
      </div>
      <div className="relative flex flex-col items-center gap-6 px-6 text-center max-w-md w-full">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/rmutt-logo.png" alt="ตรามหาวิทยาลัยเทคโนโลยีราชมงคลธัญบุรี" className="h-44 sm:h-52 w-auto drop-shadow-xl splash-logo" draggable={false} />

        <div className="flex flex-col gap-1 splash-rise" style={{ animationDelay: "250ms" }}>
          <h1 className="text-lg sm:text-xl font-semibold text-text">มหาวิทยาลัยเทคโนโลยีราชมงคลธัญบุรี</h1>
          <p className="text-xs sm:text-sm text-muted tracking-wide">Rajamangala University of Technology Thanyaburi</p>
        </div>

        <div className="flex flex-col items-center gap-1 splash-rise" style={{ animationDelay: "450ms" }}>
          <span className="text-sm font-semibold text-accent">RMUTT AOI · PCB Inspection Station</span>
          <span className="text-[11px] text-subtle">ระบบตรวจสอบแผงวงจรอัตโนมัติด้วย AI</span>
        </div>

        <div className="w-full flex flex-col gap-3 splash-rise" style={{ animationDelay: "600ms" }}>
          <div className="h-1 rounded-full bg-surface-3 overflow-hidden">
            <div className="h-full rounded-full bg-accent transition-[width] duration-500 ease-out" style={{ width: `${Math.max(8, (done / steps.length) * 100)}%` }} />
          </div>
          <ul className="flex flex-col gap-1.5 text-left">
            {steps.map((s) => (
              <li key={s.label} className="flex items-center gap-2 text-xs">
                <span className="size-4 grid place-items-center shrink-0">
                  {s.state === "wait" ? (
                    <Loader2 className="size-3.5 animate-spin text-accent" />
                  ) : s.state === "ok" ? (
                    <Check className="size-3.5 text-pass" />
                  ) : s.state === "warn" ? (
                    <Minus className="size-3.5 text-review" />
                  ) : (
                    <AlertTriangle className="size-3.5 text-fail" />
                  )}
                </span>
                <span className={s.state === "wait" ? "text-muted" : "text-text"}>{s.label}</span>
                {s.detail && <span className={cx("ml-auto truncate", s.state === "fail" ? "text-fail" : "text-subtle")}>{s.detail}</span>}
              </li>
            ))}
          </ul>
          {failed && (
            <div className="flex flex-col items-center gap-2 pt-1">
              <p className="text-xs text-fail">เชื่อมต่อ backend ไม่ได้ — ตรวจว่ารัน ./run_web.sh อยู่</p>
              <div className="flex gap-2">
                <Button size="sm" onClick={() => window.location.reload()}>
                  ลองใหม่
                </Button>
                <Button size="sm" variant="ghost" onClick={onDone}>
                  เข้าใช้งานต่อ
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
