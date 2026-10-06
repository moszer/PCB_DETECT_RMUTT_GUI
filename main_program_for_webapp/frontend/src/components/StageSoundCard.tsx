"use client";

import React, { useEffect, useState } from "react";
import { Music } from "lucide-react";
import { api } from "@/lib/api";
import { Button, Card, CardHeader, Toggle } from "./ui";
import { useToast } from "./Toast";

const TUNES = [
  { id: "test", label: "ทดสอบ" },
  { id: "pass", label: "PASS" },
  { id: "fail", label: "FAIL" },
  { id: "done", label: "เสร็จ" },
] as const;

/** The stage motors buzz short tunes: scan PASS/FAIL, HOME and calibration done. */
export function StageSoundCard({ isOperator }: { isOperator: boolean }) {
  const toast = useToast();
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    api.getSettings().then((s) => setEnabled(s.stage_sound_enabled ?? true)).catch(() => undefined);
  }, []);

  const toggle = async (v: boolean) => {
    setEnabled(v);
    try {
      await api.updateSettings({ stage_sound_enabled: v });
    } catch (err) {
      setEnabled(!v);
      toast.error("บันทึกไม่สำเร็จ", err);
    }
  };

  const play = async (tune: (typeof TUNES)[number]["id"]) => {
    setBusy(tune);
    try {
      await api.beep(tune);
    } catch (err) {
      toast.error("เล่นเสียงไม่ได้", err);
    } finally {
      setTimeout(() => setBusy(null), 600);
    }
  };

  return (
    <Card>
      <CardHeader
        icon={Music}
        title="เสียงจากตัวเครื่อง (มอเตอร์)"
        subtitle="มอเตอร์สเตจส่งเสียงสั้นๆ แทน buzzer — ได้ยินที่เครื่องแม้ไม่ได้เปิดหน้าเว็บ · ไม่ทำให้ตำแหน่งหรือ HOME เสีย"
      />
      <div className="p-4 flex flex-col gap-3">
        <Toggle
          checked={enabled}
          onChange={toggle}
          disabled={!isOperator}
          label="ส่งเสียงเมื่อสแกนเสร็จ (PASS / FAIL) · HOME เสร็จ · calibrate เสร็จ"
          description="เล่นเฉพาะตอนสเตจว่าง ไม่ทำให้การเคลื่อนที่ช้าลง"
        />
        <div className="flex flex-wrap gap-2">
          {TUNES.map((t) => (
            <Button key={t.id} size="sm" variant="secondary" loading={busy === t.id} disabled={!isOperator || !enabled || !!busy} onClick={() => play(t.id)}>
              {t.label}
            </Button>
          ))}
        </div>
        <p className="text-[11px] text-subtle">ต้องเชื่อมต่อสเตจ และใช้เฟิร์มแวร์ที่รองรับเสียง (firmware/cnc รุ่นที่มีคำสั่ง TONE)</p>
      </div>
    </Card>
  );
}
