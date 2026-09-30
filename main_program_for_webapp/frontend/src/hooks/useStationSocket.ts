"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";
import type { MachineState, ScanProgressEvent } from "@/types";

/**
 * Live machine state and scan progress over /ws/status.
 * On disconnect the last known values are kept (the page falls back to polling)
 * so the UI doesn't flash "disconnected" on every network hiccup.
 */
export function useStationSocket() {
  const [connected, setConnected] = useState(false);
  const [machineState, setMachineState] = useState<MachineState | null>(null);
  const [scanProgress, setScanProgress] = useState<ScanProgressEvent | null>(null);

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
          else if (msg.type === "scan_progress") setScanProgress(msg.data);
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

  return { connected, machineState, scanProgress };
}
