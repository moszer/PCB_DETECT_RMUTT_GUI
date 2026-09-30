"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Building2, Check, Cpu, Crosshair, HardDriveUpload, Layers, Save } from "lucide-react";
import type { ComputeDevice, ModelFile } from "@/types";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { Badge, Button, Card, CardHeader, Field, NumberInput, Spinner, TextInput, cx } from "./ui";
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

  // Model
  const [models, setModels] = useState<ModelFile[]>([]);
  const [currentModel, setCurrentModel] = useState("");
  const [loadingModel, setLoadingModel] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const loadModels = useCallback(
    () =>
      api.listModels().then((res) => {
        setModels(res.models);
        setCurrentModel(res.current_model);
      }),
    []
  );

  useEffect(() => {
    Promise.all([api.getSettings(), api.getDevices(), api.listModels()])
      .then(([s, d, m]) => {
        setModels(m.models);
        setCurrentModel(m.current_model);
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

  const chooseModel = async (path: string) => {
    setLoadingModel(path);
    try {
      const res = await api.setModel(path);
      setCurrentModel(res.model_path);
      toast.success("โหลดโมเดลแล้ว", res.device);
      onRefreshStatus();
    } catch (err) {
      toast.error("โหลดโมเดลไม่สำเร็จ — ยังใช้โมเดลเดิม", err);
    } finally {
      setLoadingModel(null);
    }
  };

  const upload = async (file: File | undefined) => {
    if (!file) return;
    if (!file.name.endsWith(".pt")) return toast.warning("รองรับเฉพาะไฟล์ .pt");
    setUploading(true);
    try {
      const res = await api.uploadModel(file);
      await loadModels();
      toast.success("อัปโหลดและโหลดโมเดลแล้ว", `${res.filename} · ${res.size_mb} MB`);
      onRefreshStatus();
    } catch (err) {
      toast.error("อัปโหลดโมเดลไม่สำเร็จ", err);
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
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
        <Card>
          <CardHeader icon={Layers} title="โมเดล YOLO" subtitle="คลิกเพื่อโหลดโมเดล — หากโหลดไม่สำเร็จระบบจะใช้โมเดลเดิมต่อ" actions={
            <Button size="sm" icon={HardDriveUpload} loading={uploading} onClick={() => fileInput.current?.click()}>
              อัปโหลด .pt
            </Button>
          } />
          <input ref={fileInput} type="file" accept=".pt" className="hidden" onChange={(e) => upload(e.target.files?.[0])} />
          <ul className="divide-y divide-line">
            {models.map((m) => {
              const active = m.path === currentModel;
              return (
                <li key={m.path}>
                  <button
                    type="button"
                    disabled={active || !!loadingModel}
                    onClick={() => chooseModel(m.path)}
                    className={cx("w-full flex items-center gap-3 px-4 py-3 text-left transition-colors", active ? "bg-accent-soft" : "hover:bg-surface-2 cursor-pointer")}
                  >
                    <span className={cx("size-4 rounded-full border-2 grid place-items-center shrink-0", active ? "border-accent bg-accent" : "border-line-strong")}>
                      {active && <Check className="size-2.5 text-on-accent" strokeWidth={4} />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium truncate">{m.filename}</span>
                      <span className="block text-[11px] text-subtle font-mono truncate">{m.path}</span>
                    </span>
                    <span className="text-xs text-muted font-mono tabular shrink-0">{m.size_mb} MB</span>
                    {m.modified_at && <span className="hidden sm:block text-[11px] text-subtle shrink-0">{formatDateTime(m.modified_at)}</span>}
                    {loadingModel === m.path && <Spinner />}
                    {active && <Badge tone="accent">ใช้งานอยู่</Badge>}
                  </button>
                </li>
              );
            })}
            {!models.length && <li className="px-4 py-6 text-sm text-muted text-center">ไม่พบไฟล์ .pt ในโฟลเดอร์โปรเจกต์</li>}
          </ul>
        </Card>

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
