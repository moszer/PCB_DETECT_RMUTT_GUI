"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";
import type { DatasetProgressEvent, MachineState, PointFrames, ScanProgressEvent, StageErrorSample, StageErrorState } from "@/types";

/**
 * Live machine state and scan progress over /ws/status.
 * On disconnect the last known values are kept (the page falls back to polling)
 * so the UI doesn't flash "disconnected" on every network hiccup.
 */
export function useStationSocket() {
  const [connected, setConnected] = useState(false);
  const [machineState, setMachineState] = useState<MachineState | null>(null);
  const [scanProgress, setScanProgress] = useState<ScanProgressEvent | null>(null);
  const [datasetProgress, setDatasetProgress] = useState<DatasetProgressEvent | null>(null);
  // Frames of the point being scanned (progress events only carry the latest one).
  const [pointFrames, setPointFrames] = useState<PointFrames | null>(null);
  // Positioning error of each move, measured live with the camera.
  const [stageError, setStageError] = useState<StageErrorState | null>(null);

  useEffect(() => {
    let disposed = false;
    let socket: WebSocket | null = null;
    let ping: ReturnType<typeof setInterval> | undefined;
    let retry: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (disposed) return;
      const url = new URL(`${API_BASE}/ws/status`, window.location.origin);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(url);
      socket = ws;

      ws.onopen = () => {
        setConnected(true);
        clearInterval(ping);
        ping = setInterval(() => ws.readyState === WebSocket.OPEN && ws.send("ping"), 5000);
      };
      ws.onmessage = (event) => {
        if (event.data === "pong") return;
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "machine_state") setMachineState(msg.data);
          else if (msg.type === "scan_progress") {
            const ev = msg.data as ScanProgressEvent;
            setScanProgress(ev);
            if (ev.point_index !== undefined && (ev.event === "point_start" || ev.event === "point_capturing" || ev.event === "point_frame")) {
              const key = `${ev.run_id}:${ev.point_index}`;
              setPointFrames((prev) => {
                const base = prev?.key === key ? prev : { key, pointIndex: ev.point_index!, target: ev.target_frames ?? 1, frames: [] };
                if (ev.event !== "point_frame") return base;
                const frame = { index: ev.frame_index ?? base.frames.length + 1, preview: ev.preview ?? null, boxes: ev.boxes ?? [] };
                return { ...base, target: ev.target_frames ?? base.target, frames: [...base.frames.filter((f) => f.index !== frame.index), frame] };
              });
            }
          }
          else if (msg.type === "dataset_progress") setDatasetProgress(msg.data);
          else if (msg.type === "stage_error") {
            const ev = msg.data as { event: string; status?: StageErrorState["status"]; sample?: StageErrorSample } & Partial<StageErrorState>;
            setStageError((prev) => {
              if (ev.event === "snapshot") return { status: ev.status ?? "idle", samples: ev.samples ?? [], summary: ev.summary ?? { n: 0 } };
              const base: StageErrorState = prev ?? { status: "idle", samples: [], summary: { n: 0 } };
              if (ev.event === "reset") return { ...base, samples: [], summary: { n: 0 } };
              if (ev.event === "status" && ev.status) return { ...base, status: ev.status };
              if (ev.event === "sample" && ev.sample) {
                return { status: "measuring", samples: [...base.samples, ev.sample].slice(-60), summary: ev.summary ?? base.summary };
              }
              return base;
            });
          }
        } catch {
          // Ignore malformed frames.
        }
      };
      ws.onclose = () => {
        clearInterval(ping);
        if (disposed) return;
        setConnected(false);
        retry = setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();
    };

    connect();
    return () => {
      disposed = true;
      clearInterval(ping);
      clearTimeout(retry);
      socket?.close();
    };
  }, []);

  return { connected, machineState, scanProgress, datasetProgress, pointFrames, stageError };
}
