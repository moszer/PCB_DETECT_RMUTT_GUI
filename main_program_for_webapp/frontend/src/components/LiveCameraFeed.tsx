"use client";

import React, { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Crosshair, RefreshCw, SlidersHorizontal, VideoOff } from "lucide-react";
import { API_BASE, api } from "@/lib/api";
import { formatMm } from "@/lib/format";
import type { CameraShape } from "@/lib/cameraFormat";
import { Button, IconButton, StatusDot, cx } from "./ui";
import { CameraFormatPanel } from "./CameraFormatPanel";

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
  /** Sweep a scan line over the image while a scan is capturing. */
  scanning?: boolean;
  /** Extra controls drawn over the image (e.g. the AOI jog pad). */
  children?: React.ReactNode;
}

const ZOOM_STEPS = [1, 1.5, 2, 3, 4];

/*
 * Page visibility as an external store. The snapshot is -1 while the tab is hidden and a
 * new number each time it becomes visible again, so the stream restarts fresh after the
 * tab (or the Mac) has been idle.
 */
let visibleEpoch = 0;
function subscribeVisibility(onChange: () => void) {
  const handler = () => {
    if (!document.hidden) visibleEpoch++;
    onChange();
  };
  document.addEventListener("visibilitychange", handler);
  return () => document.removeEventListener("visibilitychange", handler);
}
const visibilitySnapshot = () => (document.hidden ? -1 : visibleEpoch);
const serverVisibility = () => 0;

/**
 * MJPEG <img> that really closes its connection. Chromium keeps a multipart image request
 * running after the element is removed, so every remount leaked a stream; browsers allow
 * only 6 connections per host, and once leaked streams filled them every API call hung.
 */
function MjpegImage({ src, onFail, ...rest }: { src: string; onFail: () => void } & Omit<React.ImgHTMLAttributes<HTMLImageElement>, "src">) {
  const ref = useRef<HTMLImageElement>(null);
  const fail = useRef(onFail);
  useEffect(() => {
    fail.current = onFail;
  });
  useEffect(() => {
    const img = ref.current;
    if (!img) return;
    const onError = () => fail.current();
    img.addEventListener("error", onError);
    img.src = src;
    return () => {
      img.removeEventListener("error", onError);
      img.removeAttribute("src"); // aborts the in-flight multipart request
      img.src = "data:,";
    };
  }, [src]);
  // eslint-disable-next-line @next/next/no-img-element, jsx-a11y/alt-text
  return <img ref={ref} {...rest} />;
}

/**
 * The single live camera view used across the app: MJPEG stream with an automatic
 * snapshot fallback, alignment reticle, zoom preview and the one camera-settings menu.
 */
export function LiveCameraFeed({ className, zoom = 1, onZoomChange, stagePosition, hud, locked, scanning, children }: LiveCameraFeedProps) {
  const [mode, setMode] = useState<"stream" | "snapshot">("stream");
  const [streamKey, setStreamKey] = useState(() => Date.now());
  const [snapshotUrl, setSnapshotUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [reticle, setReticle] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [info, setInfo] = useState<(CameraShape & { fps: number; mock: boolean }) | null>(null);
  // No stream while the tab is in the background: it would hold one of the browser's
  // 6 connections to this host for nothing.
  const visible = useSyncExternalStore(subscribeVisibility, visibilitySnapshot, serverVisibility);

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
      if (document.hidden) {
        timer = setTimeout(next, 1000);
        return;
      }
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
  const streamSrc = visible >= 0 ? `${API_BASE}/api/camera/stream?t=${streamKey}-${visible}` : null;
  const imgClass = "absolute inset-0 size-full object-contain transition-transform duration-300 ease-out pointer-events-none";

  return (
    <div className={cx("relative overflow-hidden rounded-xl bg-viewport border border-line select-none", className)}>
      {mode === "stream" ? (
        streamSrc && (
          <MjpegImage
            src={streamSrc}
            alt="ภาพสดจากกล้อง"
            onFail={() => setMode("snapshot")}
            style={{ transform: zoomed ? `scale(${zoom})` : undefined }}
            className={imgClass}
          />
        )
      ) : snapshotUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={snapshotUrl} alt="ภาพสดจากกล้อง" style={{ transform: zoomed ? `scale(${zoom})` : undefined }} className={imgClass} />
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
        <CameraFormatPanel className="absolute top-12 right-3 z-10" locked={locked} onClose={() => setSettingsOpen(false)} onApplied={reload} />
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

      {children}

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
                  "h-7 pointer-coarse:h-10 px-2 pointer-coarse:px-3 rounded-md text-[11px] font-mono cursor-pointer",
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
