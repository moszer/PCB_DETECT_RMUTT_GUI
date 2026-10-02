"use client";

import React, { useEffect, useRef, useState } from "react";
import { Crosshair, RefreshCw, SlidersHorizontal, VideoOff } from "lucide-react";
import { API_BASE, api } from "@/lib/api";
import { CAMERA_PRESETS, formatMm, presetForCamera, type CameraShape } from "@/lib/format";
import type { CameraDevice } from "@/types";
import { Button, Field, IconButton, Select, StatusDot, cx } from "./ui";
import { useToast } from "./Toast";

export interface FeedHud {
  title: string;
  detail?: string;
  tone: "accent" | "review";
}

interface LiveCameraFeedProps {
  className?: string;
  /** Digital zoom preview (the same center crop the backend applies at capture time). */
  zoom?: number;
  onZoomChange?: (zoom: number) => void;
  stagePosition?: [number, number] | null;
  hud?: FeedHud | null;
  /** Disable camera switching (e.g. during a scan the backend rejects it anyway). */
  locked?: boolean;
  /** Changing this value plays a shutter flash (one per captured frame). */
  flashKey?: string | number | null;
  /** Sweep a scan line over the image while a scan is capturing. */
  scanning?: boolean;
}

const ZOOM_STEPS = [1, 1.5, 2, 3, 4];

/**
 * The single live camera view used across the app: MJPEG stream with an automatic
 * snapshot fallback, alignment reticle, zoom preview and the one camera-settings menu.
 */
export function LiveCameraFeed({ className, zoom = 1, onZoomChange, stagePosition, hud, locked, flashKey, scanning }: LiveCameraFeedProps) {
  const [mode, setMode] = useState<"stream" | "snapshot">("stream");
  const [streamKey, setStreamKey] = useState(() => Date.now());
  const [snapshotUrl, setSnapshotUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [reticle, setReticle] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [info, setInfo] = useState<(CameraShape & { fps: number; mock: boolean }) | null>(null);

  useEffect(() => {
    api
      .listCameras()
      .then((res) =>
        setInfo({ resolution: res.resolution, capture_resolution: res.capture_resolution, output_mode: res.output_mode, fps: res.fps, mock: res.is_mock })
      )
      .catch(() => undefined); // Header status chip still reflects the camera.
  }, [streamKey]);

  // Snapshot fallback: one request per frame, displayed through an object URL
  // (the old loop downloaded every frame twice).
  useEffect(() => {
    if (mode !== "snapshot") return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    let current: string | null = null;
    const next = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/camera/snapshot?t=${Date.now()}`, { cache: "no-store" });
        if (!res.ok) throw new Error(String(res.status));
        const url = URL.createObjectURL(await res.blob());
        if (!active) return URL.revokeObjectURL(url);
        if (current) URL.revokeObjectURL(current);
        current = url;
        setSnapshotUrl(url);
        setFailed(false);
        timer = setTimeout(next, 80);
      } catch {
        if (!active) return;
        setFailed(true);
        timer = setTimeout(next, 1000);
      }
    };
    next();
    return () => {
      active = false;
      clearTimeout(timer);
      if (current) URL.revokeObjectURL(current);
    };
  }, [mode]);

  const reload = () => {
    setFailed(false);
    setMode("stream");
    setStreamKey(Date.now());
  };

  const zoomed = zoom > 1.01;
  const src = mode === "stream" ? `${API_BASE}/api/camera/stream?t=${streamKey}` : snapshotUrl;

  return (
    <div className={cx("relative overflow-hidden rounded-xl bg-viewport border border-line select-none", className)}>
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          key={mode === "stream" ? streamKey : "snapshot"}
          src={src}
          alt="ภาพสดจากกล้อง"
          onError={() => mode === "stream" && setMode("snapshot")}
          style={{ transform: zoomed ? `scale(${zoom})` : undefined }}
          className="absolute inset-0 size-full object-contain transition-transform duration-300 ease-out pointer-events-none"
        />
      ) : null}

      {failed && (
        <div className="absolute inset-0 grid place-items-center text-center text-white/70 text-sm">
          <div className="flex flex-col items-center gap-2">
            <VideoOff className="size-8" />
            ไม่ได้รับภาพจากกล้อง
            <Button size="sm" onClick={reload} icon={RefreshCw}>
              ลองใหม่
            </Button>
          </div>
        </div>
      )}

      {reticle && <Reticle zoomed={zoomed} />}

      {scanning && (
        <div className="absolute inset-x-0 h-0.5 bg-cyan-300/90 shadow-[0_0_14px_3px_rgb(103_232_249/0.6)] animate-scanline pointer-events-none" />
      )}
      {/* Remounting on a new key restarts the CSS animation: one flash per captured frame. */}
      {flashKey != null && <div key={flashKey} className="absolute inset-0 bg-white animate-flash pointer-events-none" />}

      {/* Top-left: source + resolution */}
      <div className="absolute top-3 left-3 flex items-center gap-1.5 flex-wrap max-w-[70%]">
        <HudPill>
          <StatusDot tone={failed ? "review" : "pass"} pulse={!failed} />
          {mode === "stream" ? "LIVE" : "SNAPSHOT"}
        </HudPill>
        {info && (
          <HudPill>
            <span className="font-mono tabular">
              {info.resolution[0]}×{info.resolution[1]}
            </span>
          </HudPill>
        )}
        {info?.mock && <HudPill className="text-amber-300">กล้องจำลอง</HudPill>}
        {info?.output_mode === "crop" && <HudPill className="text-cyan-300">1:1 crop</HudPill>}
        {zoomed && <HudPill className="text-amber-300 font-mono">ZOOM {zoom.toFixed(1)}×</HudPill>}
      </div>

      {/* Top-right: tools */}
      <div className="absolute top-3 right-3 flex items-center gap-1 rounded-lg bg-black/55 backdrop-blur p-1 text-white">
        <IconButton
          size="sm"
          icon={Crosshair}
          label="เป้าเล็ง"
          active={reticle}
          overlay
          onClick={() => setReticle((v) => !v)}
        />
        <IconButton
          size="sm"
          icon={SlidersHorizontal}
          label="ตั้งค่ากล้อง"
          overlay
          active={settingsOpen}
          onClick={() => setSettingsOpen((v) => !v)}
        />
        <IconButton size="sm" icon={RefreshCw} label="รีโหลดภาพ" overlay onClick={reload} />
      </div>

      {settingsOpen && (
        <CameraSettings
          locked={locked}
          current={info}
          onClose={() => setSettingsOpen(false)}
          onApplied={reload}
        />
      )}

      {hud && (
        <div
          key={hud.title}
          className={cx(
            "absolute top-14 left-3 right-3 sm:right-auto rounded-lg px-3 py-2 text-xs text-white backdrop-blur border animate-rise",
            hud.tone === "accent" ? "bg-blue-950/80 border-blue-400/50" : "bg-amber-950/80 border-amber-400/50"
          )}
        >
          <div className="font-semibold">{hud.title}</div>
          {hud.detail && <div className="text-white/75 font-mono tabular mt-0.5">{hud.detail}</div>}
        </div>
      )}

      {/* Bottom: stage position + zoom */}
      <div className="absolute bottom-3 left-3 right-3 flex items-end justify-between gap-2 pointer-events-none">
        {stagePosition !== undefined ? (
          <HudPill className="font-mono tabular">
            X {formatMm(stagePosition?.[0])} · Y {formatMm(stagePosition?.[1])} mm
          </HudPill>
        ) : (
          <span />
        )}
        {onZoomChange && (
          <div className="pointer-events-auto flex rounded-lg bg-black/55 backdrop-blur p-0.5">
            {ZOOM_STEPS.map((z) => (
              <button
                key={z}
                type="button"
                onClick={() => onZoomChange(z)}
                className={cx(
                  "h-7 px-2 rounded-md text-[11px] font-mono cursor-pointer",
                  Math.abs(zoom - z) < 0.05 ? "bg-white text-black font-bold" : "text-white/75 hover:text-white"
                )}
              >
                {z}×
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function HudPill({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1.5 h-6 px-2 rounded-md bg-black/55 backdrop-blur text-[11px] font-medium text-white", className)}>
      {children}
    </span>
  );
}

function Reticle({ zoomed }: { zoomed: boolean }) {
  const color = zoomed ? "border-amber-400/80" : "border-emerald-400/70";
  const line = zoomed ? "bg-amber-400/70" : "bg-emerald-400/60";
  return (
    <div className="absolute inset-0 pointer-events-none grid place-items-center">
      <div className={cx("absolute w-40 h-px", line)} />
      <div className={cx("absolute h-40 w-px", line)} />
      <div className={cx("absolute size-20 rounded-full border", color)} />
      <div className={cx("absolute size-1.5 rounded-full", zoomed ? "bg-amber-400" : "bg-emerald-400")} />
    </div>
  );
}

function CameraSettings({
  locked,
  current,
  onClose,
  onApplied,
}: {
  locked?: boolean;
  current?: CameraShape | null;
  onClose: () => void;
  onApplied: () => void;
}) {
  const [devices, setDevices] = useState<CameraDevice[]>([]);
  const [device, setDevice] = useState(0);
  const [preset, setPreset] = useState<string>(presetForCamera(current)?.id ?? "1080p");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .listCameras()
      .then((res) => {
        setDevices(res.devices);
        setDevice(res.current_index);
        const p = presetForCamera(res);
        if (p) setPreset(p.id);
      })
      .catch((err) => toast.error("อ่านรายการกล้องไม่สำเร็จ", err));
  }, [toast]);

  useEffect(() => {
    const onDown = (e: MouseEvent) => panel.current && !panel.current.contains(e.target as Node) && onClose();
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [onClose]);

  const apply = async () => {
    const p = CAMERA_PRESETS.find((x) => x.id === preset)!;
    setBusy(true);
    try {
      const res = await api.startCamera(device, p.width, p.height, p.output, p.mode);
      const cams = await api.listCameras();
      const cap = cams.capture_resolution;
      // The driver may silently deliver less than asked (e.g. 1080p instead of 4K).
      const short = cap && (cap[0] < p.width || cap[1] < p.height);
      if (res.is_mock) toast.warning("เปิดกล้องจริงไม่ได้ — ใช้ภาพจำลอง");
      else if (short) toast.warning("กล้องให้ความละเอียดต่ำกว่าที่ขอ", `ขอ ${p.width}×${p.height} ได้ ${cap[0]}×${cap[1]} — ภาพ ${res.resolution[0]}×${res.resolution[1]} จะซูมน้อยลง`);
      else toast.success("ตั้งค่ากล้องแล้ว", `${res.resolution[0]}×${res.resolution[1]}${cap ? ` (กล้องส่ง ${cap[0]}×${cap[1]})` : ""}`);
      onApplied();
      onClose();
    } catch (err) {
      toast.error("ตั้งค่ากล้องไม่สำเร็จ", err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div ref={panel} className="absolute top-12 right-3 z-10 w-72 rounded-xl border border-line bg-surface p-4 shadow-pop flex flex-col gap-3">
      <div className="text-sm font-semibold text-text">ตั้งค่ากล้อง</div>
      <Field label="อุปกรณ์กล้อง">
        <Select value={device} onChange={(e) => setDevice(Number(e.target.value))} disabled={locked}>
          {(devices.length ? devices : [{ index: 0, name: "Camera 0", active: false }]).map((d) => (
            <option key={d.index} value={d.index}>
              {d.name}
              {d.active ? " • ใช้งานอยู่" : ""}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="ขนาดภาพที่ถ่าย" hint="แบบสี่เหลี่ยมจัตุรัสจะตัดกลางภาพแล้วย่อ — ใช้กับภาพสด การตรวจ และการสแกนทั้งหมด">
        <Select value={preset} onChange={(e) => setPreset(e.target.value)} disabled={locked}>
          {CAMERA_PRESETS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </Select>
      </Field>
      {current?.capture_resolution && (
        <p className="text-[11px] text-subtle">
          กล้องส่งจริง {current.capture_resolution[0]}×{current.capture_resolution[1]} → ภาพที่ใช้ {current.resolution[0]}×{current.resolution[1]}
          {current.output_mode === "crop" ? " (ตัดกลาง 1:1)" : ""}
        </p>
      )}
      {preset === "4k_crop640" && (
        <p className="text-[11px] text-review">แบบ 1:1 เห็นพื้นที่แคบลงราว 3.4 เท่า (เหมือนซูม) — ต้องสอนต้นแบบใหม่และลดระยะห่างภาพตอนสแกน</p>
      )}
      {locked && <p className="text-[11px] text-review">เปลี่ยนกล้องไม่ได้ระหว่างสแกน</p>}
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onClose}>
          ปิด
        </Button>
        <Button size="sm" variant="primary" onClick={apply} loading={busy} disabled={locked}>
          ใช้ค่านี้
        </Button>
      </div>
    </div>
  );
}
