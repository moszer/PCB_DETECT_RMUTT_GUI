"use client";

import React, { useEffect, useState } from "react";
import { Box, Building2, Check, Cpu, Crosshair, RotateCw, Save, Vibrate, Volume2 } from "lucide-react";
import type { ComputeDevice } from "@/types";
import { api } from "@/lib/api";
import { Button, Card, CardHeader, Field, NumberInput, Segmented, Slider, Spinner, TextInput, Toggle, cx } from "./ui";
import { ModelPicker } from "./ModelPicker";
import { AIKeyPanel } from "./AIKeyPanel";
import { RemoteAccessPanel } from "./RemoteAccess";
import { StageCalibrationCard } from "./StageCalibrationCard";
import { StraightenCard } from "./StraightenCard";
import { useSoundPrefs } from "@/hooks/useSound";
import { sfx } from "@/lib/sound";
import { useToast } from "./Toast";

export function SettingsView({ onRefreshStatus, isOperator }: { onRefreshStatus: () => void; isOperator: boolean }) {
  const toast = useToast();
  const [loaded, setLoaded] = useState(false);

  // Station metadata + safety bounds (saved together)
  const [stationName, setStationName] = useState("");
  const [operator, setOperator] = useState("");
  const [limitX, setLimitX] = useState(38);
  const [limitY, setLimitY] = useState(38);
  const [depthDistance, setDepthDistance] = useState(200);
  const [depthBaseline, setDepthBaseline] = useState(6);
  const [depthViews, setDepthViews] = useState(4);
  const [stabilize, setStabilize] = useState(true);
  const [stabilizeWait, setStabilizeWait] = useState(2);
  const [stabilizePx, setStabilizePx] = useState(1.5);
  const [align, setAlign] = useState(true);
  const [alignDeg, setAlignDeg] = useState(10);
  const [alignMm, setAlignMm] = useState(8);
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
        setDepthDistance(s.depth_camera_distance_mm);
        setDepthBaseline(s.depth_baseline_mm);
        setDepthViews(s.depth_views ?? 4);
        setStabilize(s.stabilize_enabled ?? true);
        setStabilizeWait(s.stabilize_max_wait_sec ?? 2);
        setStabilizePx(s.stabilize_threshold_px ?? 1.5);
        setAlign(s.board_align_enabled ?? true);
        setAlignDeg(s.board_align_max_deg ?? 10);
        setAlignMm(s.board_align_max_mm ?? 8);
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
      await api.updateSettings({
        station_name: stationName,
        default_operator: operator,
        soft_limit_x_mm: limitX,
        soft_limit_y_mm: limitY,
        depth_camera_distance_mm: depthDistance,
        depth_baseline_mm: depthBaseline,
        depth_views: depthViews,
        stabilize_enabled: stabilize,
        stabilize_max_wait_sec: stabilizeWait,
        stabilize_threshold_px: stabilizePx,
        board_align_enabled: align,
        board_align_max_deg: alignDeg,
        board_align_max_mm: alignMm,
      });
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

        <AIKeyPanel isOperator={isOperator} />

        <RemoteAccessPanel isOperator={isOperator} />

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

        <StraightenCard isOperator={isOperator} />

        <StageCalibrationCard isOperator={isOperator} />

        <Card>
          <CardHeader
            icon={RotateCw}
            title="ชดเชยการวางบอร์ด"
            subtitle="ก่อนสแกน ถ่ายจุดที่สอนไว้ 2 จุดที่ห่างกันที่สุดเทียบกับภาพต้นแบบ หาว่าบอร์ดเอียง/เลื่อนเท่าไหร่ แล้วเลื่อนทุกจุดตามและหมุนภาพกลับให้ตรงกรอบ — ต้องมีภาพต้นแบบของจุด และ calibrate ราง XY แล้ว"
          />
          <div className="p-4 flex flex-col gap-4">
            <Toggle checked={align} onChange={setAlign} label="ชดเชยบอร์ดที่วางเอียงหรือเลื่อน" description="ถ้ายังไม่ได้ calibrate ราง จะจัดภาพแต่ละจุดให้ตรงต้นแบบอย่างเดียว (ไม่เลื่อนตำแหน่งสเตจ)" />
            <div className={cx("grid sm:grid-cols-2 gap-4", !align && "opacity-50 pointer-events-none")}>
              <Field label="เอียงได้ไม่เกิน" hint="เกินนี้จะหยุดสแกนและให้วางบอร์ดใหม่">
                <NumberInput value={alignDeg} min={0.5} max={45} step={0.5} suffix="°" onChange={setAlignDeg} />
              </Field>
              <Field label="เลื่อนได้ไม่เกิน" hint="ระยะห่างจากตำแหน่งตอนสอนจุด">
                <NumberInput value={alignMm} min={0.5} max={100} step={0.5} suffix="mm" onChange={setAlignMm} />
              </Field>
            </div>
          </div>
        </Card>

        <Card>
          <CardHeader
            icon={Vibrate}
            title="กันสั่นกล้อง"
            subtitle="หลังสเตจเคลื่อนที่ รอจนภาพนิ่งจริงก่อนถ่าย (เทียบภาพเฟรมต่อเฟรม) และถ่ายเฟรมที่สั่นใหม่ระหว่างตรวจหลายเฟรม — ใช้กับการสแกน 3D calibrate และเก็บ dataset"
          />
          <div className="p-4 flex flex-col gap-4">
            <Toggle checked={stabilize} onChange={setStabilize} label="รอภาพนิ่งก่อนถ่าย" description="เวลา settle ที่ตั้งในแผนสแกนเป็นเวลาขั้นต่ำ ถ้าภาพยังสั่นจะรอต่อจนนิ่ง" />
            <div className={cx("grid sm:grid-cols-2 gap-4", !stabilize && "opacity-50 pointer-events-none")}>
              <Field label="รอนานสุด" hint="ภาพไม่นิ่งภายในเวลานี้จะถ่ายต่อไปเลย">
                <NumberInput value={stabilizeWait} min={0.1} max={10} step={0.1} suffix="s" onChange={setStabilizeWait} />
              </Field>
              <Field label="ถือว่านิ่งเมื่อภาพขยับไม่เกิน" hint="px ของภาพเต็ม (1.5 px ≈ 11 µm ที่ 130 px/mm) — น้อยลง = นิ่งกว่าแต่รอนานขึ้น">
                <NumberInput value={stabilizePx} min={0.2} max={50} step={0.1} suffix="px" onChange={setStabilizePx} />
              </Field>
            </div>
          </div>
        </Card>

        <Card>
          <CardHeader
            icon={Box}
            title="วัดความสูง 3D"
            subtitle="ถ่ายภาพที่จุดนั้นแล้วเลื่อนสเตจไปรอบๆ ถ่ายเพิ่ม ของที่สูงกว่าจะเลื่อนในภาพมากกว่า — ใช้ดูว่าชิ้นมีอยู่ สูงเท่าไหร่ เอียงหรือยกไหม"
          />
          <div className="grid sm:grid-cols-2 gap-4 p-4">
            <Field label="ระยะจากเลนส์กล้องถึงผิวบอร์ด" hint="วัดด้วยไม้บรรทัดจากหน้าเลนส์ถึงผิวบอร์ด — ค่านี้ผิด ความสูงจะผิดตามสัดส่วน">
              <NumberInput value={depthDistance} min={20} max={2000} step={1} suffix="mm" onChange={setDepthDistance} />
            </Field>
            <Field label="ระยะเลื่อนสเตจแต่ละภาพ" hint="มากขึ้น = แม่นขึ้น แต่ชิ้นที่ขอบภาพอาจหลุดเฟรม (แนะนำ 4–8 mm)">
              <NumberInput value={depthBaseline} min={0.5} max={30} step={0.5} suffix="mm" onChange={setDepthBaseline} />
            </Field>
            <Field
              label="จำนวนทิศที่เลื่อนไปถ่าย"
              hint="1 = +X · 2 = ±X · 4 = ±X ±Y · 8 = เพิ่มแนวทแยง — หลายทิศละเอียดขึ้น รูโหว่น้อยลง และวัดผิวที่มีลายแนวเดียวได้ แต่ช้าลงราว 1 วินาทีต่อทิศ"
              className="sm:col-span-2"
            >
              <Segmented
                className="w-full max-w-md"
                value={depthViews}
                onChange={setDepthViews}
                options={[
                  { value: 1, label: "1 ทิศ" },
                  { value: 2, label: "2 ทิศ" },
                  { value: 4, label: "4 ทิศ (แนะนำ)" },
                  { value: 8, label: "8 ทิศ" },
                ]}
              />
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

        <div className="flex justify-end sticky bottom-0 py-3 pr-16 bg-bg/90 backdrop-blur">
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
  { label: "AI: เปิดหน้าต่าง", play: () => sfx.chatOpen() },
  { label: "AI: ส่งคำถาม", play: () => sfx.chatSend() },
  { label: "AI: อ่านข้อมูล", play: () => sfx.chatStep() },
  { label: "AI: ตอบเสร็จ", play: () => sfx.chatReply() },
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
