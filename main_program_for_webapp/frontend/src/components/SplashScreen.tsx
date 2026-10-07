"use client";

import React, { useEffect, useState } from "react";
import { AlertTriangle, Check, Loader2, Minus } from "lucide-react";
import { api } from "@/lib/api";
import type { SystemStatus } from "@/types";
import { Button, cx } from "./ui";

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
  const progress = Math.round((done / steps.length) * 100);

  return (
    <div
      className={cx("splash-screen fixed inset-0 z-[100] grid place-items-center transition-opacity duration-500", leaving ? "opacity-0 pointer-events-none" : "opacity-100")}
      role="status"
      aria-live="polite"
    >
      <svg className="splash-circuits" viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        <g id="splash-circuit-left" className="splash-circuit-side">
          <path d="M0 125h145l145 140h205l155 155" />
          <path d="M0 205h110l170 165h265l100 100" />
          <path d="M0 285h185l130 115h180l130 130" />
          <path d="M0 400h215l100 85h225l75 75" />
          <path d="M0 520h185l165 95h235" />
          <path d="M0 645h170l135-95h215l115-90" />
          <path d="M0 755h150l145-120h175l165-135" />
          <path d="M0 840h160l155-135h245l110-100" />
          <circle cx="495" cy="265" r="6" /><circle cx="545" cy="370" r="6" />
          <circle cx="495" cy="400" r="6" /><circle cx="540" cy="485" r="6" />
          <circle cx="585" cy="615" r="6" /><circle cx="520" cy="550" r="6" />
          <circle cx="470" cy="635" r="6" /><circle cx="560" cy="705" r="6" />
        </g>
        <use href="#splash-circuit-left" transform="translate(1600 0) scale(-1 1)" />
      </svg>
      <div className="relative flex w-full max-w-[860px] flex-col items-center px-6 py-8 text-center sm:px-10">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/rmutt-logo.png" alt="ตรามหาวิทยาลัยเทคโนโลยีราชมงคลธัญบุรี" className="splash-logo h-40 w-auto sm:h-52 lg:h-64" draggable={false} />

        <div className="splash-rise mt-5 flex flex-col items-center" style={{ animationDelay: "180ms" }}>
          <h1 className="splash-title">RMUTT AOI</h1>
          <p className="splash-kicker">PCB INSPECTION STATION</p>
          <p className="splash-university">มหาวิทยาลัยเทคโนโลยีราชมงคลธัญบุรี</p>
        </div>

        <div className="splash-rise mt-7 w-full sm:mt-10" style={{ animationDelay: "360ms" }}>
          <ul className="splash-steps">
            {steps.map((s) => (
              <li key={s.label} className="splash-step" title={s.detail}>
                <span className={cx("splash-step-icon", `splash-step-${s.state}`)}>
                  {s.state === "wait" ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : s.state === "ok" ? (
                    <Check className="size-4" />
                  ) : s.state === "warn" ? (
                    <Minus className="size-4" />
                  ) : (
                    <AlertTriangle className="size-4" />
                  )}
                </span>
                <span>{s.label}</span>
              </li>
            ))}
          </ul>
          <div className="splash-progress" role="progressbar" aria-label="ความคืบหน้าการเตรียมระบบ" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
            <div className="splash-progress-fill" style={{ width: `${progress}%` }} />
          </div>
          <p className="splash-message">{failed ? "ไม่สามารถเชื่อมต่อเซิร์ฟเวอร์ได้" : done === steps.length ? "เตรียมระบบเสร็จแล้ว" : "กำลังเตรียมระบบตรวจสอบแผงวงจร"}</p>
          {failed && (
            <div className="flex flex-col items-center gap-3 pt-4">
              <p className="text-xs text-red-600">ตรวจว่ารัน ./run_web.sh อยู่ แล้วลองใหม่</p>
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
