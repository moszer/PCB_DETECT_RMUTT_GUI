"use client";

import React, { useEffect, useState } from "react";
import { Check, RotateCcw, ScanLine, Wand2 } from "lucide-react";
import { API_BASE, api, request } from "@/lib/api";
import { Button, Card, CardHeader, Field, NumberInput, Spinner } from "./ui";
import { useToast } from "./Toast";

/** Straighten a camera mounted a little turned: every frame (live view too) is rotated by the angle. */
export function StraightenCard({ isOperator }: { isOperator: boolean }) {
  const toast = useToast();
  const [saved, setSaved] = useState<number | null>(null);
  const [angle, setAngle] = useState(0);
  const [detecting, setDetecting] = useState(false);
  const [nonce, setNonce] = useState(0);
  const [loaded, setLoaded] = useState<string | null>(null);

  useEffect(() => {
    api
      .getSettings()
      .then((s) => {
        setSaved(s.camera_rotate_deg ?? 0);
        setAngle(s.camera_rotate_deg ?? 0);
      })
      .catch(() => setSaved(0));
  }, []);

  // The preview is the raw picture turned by the angle being tried, with level guide lines.
  const [shownAngle, setShownAngle] = useState(0);
  useEffect(() => {
    const id = window.setTimeout(() => setShownAngle(angle), 350);
    return () => window.clearTimeout(id);
  }, [angle]);
  const preview = `${API_BASE}/api/camera/straighten/preview?angle=${shownAngle}&t=${nonce}`;

  const detect = async () => {
    setDetecting(true);
    try {
      const res = await request<{ angle_deg: number }>("/api/camera/straighten/detect");
      setAngle(res.angle_deg);
      setNonce((n) => n + 1);
      toast.info(`ตรวจได้ ${res.angle_deg >= 0 ? "+" : ""}${res.angle_deg.toFixed(2)}°`, "ดูเส้นในภาพตัวอย่างว่าขนานกับแนวบอร์ดไหม แล้วกด “ใช้มุมนี้”");
    } catch (err) {
      toast.error("ตรวจจับมุมไม่สำเร็จ", err);
    } finally {
      setDetecting(false);
    }
  };

  const apply = async (value: number) => {
    try {
      await api.updateSettings({ camera_rotate_deg: value });
      setSaved(value);
      setAngle(value);
      toast.success(value ? `หมุนภาพกล้อง ${value >= 0 ? "+" : ""}${value.toFixed(2)}° แล้ว` : "เลิกหมุนภาพกล้องแล้ว");
    } catch (err) {
      toast.error("บันทึกไม่สำเร็จ", err);
    }
  };

  return (
    <Card>
      <CardHeader
        icon={ScanLine}
        title="หมุนภาพกล้องให้ตรง"
        subtitle="กล้องติดเอียงเล็กน้อยทำให้บอร์ดดูเอียงในภาพ — หมุนภาพทุกเฟรม (ภาพสด ถ่ายต้นแบบ สแกน 3D) ให้แนวบอร์ดขนานกับขอบภาพ"
      />
      <div className="p-4 grid gap-4 md:grid-cols-[minmax(0,1fr)_240px]">
        <div className="relative aspect-square rounded-lg overflow-hidden bg-viewport">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            key={preview}
            src={preview}
            alt="ภาพกล้องที่หมุนแล้ว พร้อมเส้นแนวระดับ"
            className="absolute inset-0 size-full object-contain"
            onLoad={() => setLoaded(preview)}
            onError={() => setLoaded(preview)}
          />
          {loaded !== preview && (
            <div className="absolute inset-0 grid place-items-center">
              <Spinner className="size-5" />
            </div>
          )}
        </div>
        <div className="flex flex-col gap-3">
          <Field label="มุมหมุน" hint="+ = ทวนเข็มนาฬิกา · เทียบเส้นสีเหลืองกับขอบชิ้น/ลายวงจร">
            <NumberInput value={angle} min={-15} max={15} step={0.05} suffix="°" onChange={setAngle} />
          </Field>
          <Button icon={Wand2} onClick={detect} loading={detecting}>
            ตรวจจับอัตโนมัติ
          </Button>
          <Button variant="primary" icon={Check} disabled={!isOperator || saved === angle} onClick={() => apply(angle)}>
            ใช้มุมนี้
          </Button>
          {saved !== 0 && saved !== null && (
            <Button variant="ghost" icon={RotateCcw} disabled={!isOperator} onClick={() => apply(0)}>
              เลิกหมุน (ตอนนี้ {saved.toFixed(2)}°)
            </Button>
          )}
          <p className="text-[11px] text-muted leading-relaxed">
            หลังเปลี่ยนมุม ภาพต้นแบบที่สอนไว้ก่อนหน้าถ่ายที่มุมเดิม — ควรสอนต้นแบบใหม่ (ระหว่างนี้ “ชดเชยการวางบอร์ด” จะหมุนภาพให้ตรงต้นแบบเดิมให้) · ผล calibrate รางปรับตามมุมให้อัตโนมัติ
          </p>
          <p className="text-[11px] text-subtle">ถ้าทำได้ หมุนตัวกล้องให้ตรงจริงดีที่สุด (ไม่ต้องหมุนภาพ ภาพคมกว่า)</p>
        </div>
      </div>
    </Card>
  );
}
