"use client";

import React, { useEffect, useState } from "react";
import { Building2, Check, Cpu, Crosshair, Save, Volume2 } from "lucide-react";
import type { ComputeDevice } from "@/types";
import { api } from "@/lib/api";
import { Button, Card, CardHeader, Field, NumberInput, Slider, Spinner, TextInput, Toggle, cx } from "./ui";
import { ModelPicker } from "./ModelPicker";
import { useSoundPrefs } from "@/hooks/useSound";
import { sfx } from "@/lib/sound";
import { useToast } from "./Toast";

export function SettingsView({ onRefreshStatus }: { onRefreshStatus: () => void }) {
  const toast = useToast();
  const [loaded, setLoaded] = useState(false);

  // Station metadata + safety bounds (saved together)
  const [stationName, setStationName] = useState("");
  const [operator, setOperator] = useState("");
  const [limitX, setLimitX] = useState(38);
  const [limitY, setLimitY] = useState(38);
  const [saving, setSaving] = useState(false);

  // Compute device
  const [devices, setDevices] = useState<ComputeDevice[]>([]);
  const [activeDevice, setActiveDevice] = useState("");
  const [preference, setPreference] = useState("auto");
  const [switchingDevice, setSwitchingDevice] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.getSettings(), api.getDevices()])
      .then(([s, d]) => {
        setStationName(s.station_name);
        setOperator(s.default_operator);
        setLimitX(s.soft_limit_x_mm);
        setLimitY(s.soft_limit_y_mm);
        setDevices(d.devices);
        setActiveDevice(d.current_device);
        setPreference(d.preference);
      })
      .catch((err) => toast.error("โหลดการตั้งค่าไม่สำเร็จ", err))
      .finally(() => setLoaded(true));
  }, [toast]);

  const save = async () => {
    setSaving(true);
    try {
      await api.updateSettings({ station_name: stationName, default_operator: operator, soft_limit_x_mm: limitX, soft_limit_y_mm: limitY });
      toast.success("บันทึกการตั้งค่าแล้ว");
      onRefreshStatus();
    } catch (err) {
      toast.error("บันทึกไม่สำเร็จ", err);
    } finally {
      setSaving(false);
    }
  };

  const chooseDevice = async (id: string) => {
    setSwitchingDevice(id);
    try {
      await api.setDevice(id);
      const d = await api.getDevices();
      setPreference(d.preference);
      setActiveDevice(d.current_device);
      toast.success("เปลี่ยนฮาร์ดแวร์ประมวลผลแล้ว", d.current_device);
      onRefreshStatus();
    } catch (err) {
      toast.error("เปลี่ยนฮาร์ดแวร์ไม่สำเร็จ", err);
    } finally {
      setSwitchingDevice(null);
    }
  };

  if (!loaded) {
    return (
      <div className="h-full grid place-items-center">
        <Spinner className="size-6" />
      </div>
    );
  }

  const deviceOptions: ComputeDevice[] = [
    { id: "auto", label: "อัตโนมัติ", available: true, detail: "เลือก GPU ที่มี (CUDA → Apple MPS → CPU)" },
    ...devices,
  ];

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto p-4 md:p-6 flex flex-col gap-5">
        <ModelPicker onRefreshStatus={onRefreshStatus} />

        <Card>
          <CardHeader icon={Cpu} title="ฮาร์ดแวร์ประมวลผล" subtitle={`กำลังใช้: ${activeDevice}`} />
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2 p-4">
            {deviceOptions.map((d) => {
              const active = preference === d.id;
              return (
                <button
                  key={d.id}
                  type="button"
                  disabled={!d.available || active || !!switchingDevice}
                  onClick={() => chooseDevice(d.id)}
                  className={cx(
                    "rounded-lg border p-3 text-left transition-colors",
                    active ? "border-accent bg-accent-soft" : "border-line hover:border-line-strong cursor-pointer",
                    !d.available && "opacity-40 cursor-not-allowed"
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">{d.label}</span>
                    {switchingDevice === d.id ? <Spinner /> : active && <Check className="size-4 text-accent" />}
                  </div>
                  <p className="text-[11px] text-muted mt-1 leading-snug">{d.detail}</p>
                </button>
              );
            })}
          </div>
        </Card>

        <Card>
          <CardHeader icon={Crosshair} title="ขอบเขตการเคลื่อนที่ของสเตจ" subtitle="Soft limit ป้องกันไม่ให้แกนวิ่งชนสุดระยะ — มีผลทันทีกับสเตจที่เชื่อมต่อ" />
          <div className="grid grid-cols-2 gap-4 p-4">
            <Field label="ระยะสูงสุดแกน X">
              <NumberInput value={limitX} min={1} max={1000} step={0.5} suffix="mm" onChange={setLimitX} />
            </Field>
            <Field label="ระยะสูงสุดแกน Y">
              <NumberInput value={limitY} min={1} max={1000} step={0.5} suffix="mm" onChange={setLimitY} />
            </Field>
          </div>
        </Card>

        <SoundCard />

        <Card>
          <CardHeader icon={Building2} title="ข้อมูลสถานี" />
          <div className="grid sm:grid-cols-2 gap-4 p-4">
            <Field label="ชื่อสถานี" htmlFor="station-name">
              <TextInput id="station-name" value={stationName} onChange={(e) => setStationName(e.target.value)} />
            </Field>
            <Field label="ชื่อผู้ควบคุมเริ่มต้น" htmlFor="default-operator">
              <TextInput id="default-operator" value={operator} onChange={(e) => setOperator(e.target.value)} />
            </Field>
          </div>
        </Card>

        <div className="flex justify-end sticky bottom-0 py-3 bg-bg/90 backdrop-blur">
          <Button variant="primary" size="lg" icon={Save} loading={saving} onClick={save}>
            บันทึกการตั้งค่า
          </Button>
        </div>
      </div>
    </div>
  );
}

const SOUND_PREVIEWS: Array<{ label: string; play: () => void }> = [
  { label: "ถ่ายภาพ", play: () => sfx.shutter() },
  { label: "แต่ละเฟรม", play: () => sfx.tick() },
  { label: "ผ่าน", play: () => sfx.pass() },
  { label: "ไม่ผ่าน", play: () => sfx.fail() },
  { label: "ตรวจซ้ำ", play: () => sfx.review() },
  { label: "สแกนครบ (ผ่าน)", play: () => sfx.complete("PASS") },
  { label: "สแกนครบ (ไม่ผ่าน)", play: () => sfx.complete("FAIL") },
  { label: "STOP", play: () => sfx.alarm() },
];

/** Sound preference is per browser (saved locally) and applies immediately — no Save needed. */
function SoundCard() {
  const { enabled, volume } = useSoundPrefs();
  return (
    <Card>
      <CardHeader icon={Volume2} title="เสียงเอฟเฟกต์" subtitle="ตั้งค่าเฉพาะเครื่องนี้ มีผลทันที" />
      <div className="flex flex-col gap-4 p-4">
        <Toggle
          label="เปิดเสียง"
          description="เสียงถ่ายภาพ เสียงแต่ละเฟรม เสียงผลผ่าน/ไม่ผ่าน และสัญญาณเมื่อสแกนจบหรือกด STOP"
          checked={enabled}
          onChange={(v) => sfx.setEnabled(v)}
        />
        <Slider
          label="ระดับเสียง"
          value={volume}
          min={0}
          max={1}
          step={0.05}
          disabled={!enabled}
          format={(v) => `${Math.round(v * 100)}%`}
          onChange={(v) => sfx.setVolume(v)}
        />
        <div className="flex flex-wrap gap-1.5">
          {SOUND_PREVIEWS.map((s) => (
            <Button key={s.label} size="sm" variant="ghost" disabled={!enabled} onClick={s.play}>
              ▶ {s.label}
            </Button>
          ))}
        </div>
      </div>
    </Card>
  );
}
