"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Home, Plug, PlugZap, Power, RefreshCw, Unplug } from "lucide-react";
import type { MachineState, SerialPort } from "@/types";
import { api } from "@/lib/api";
import { formatMm } from "@/lib/format";
import { Badge, Button, IconButton, Select, StatusDot } from "../ui";
import { useToast } from "../Toast";

/** Stage connection, homing and position readout across the top of the AOI screen. */
export function StageBar({ machine, scanning, onChange }: { machine: MachineState | null; scanning: boolean; onChange: () => void }) {
  const [ports, setPorts] = useState<SerialPort[]>([]);
  const [port, setPort] = useState("");
  const [busy, setBusy] = useState<"connect" | "home" | null>(null);
  const toast = useToast();
  const connected = Boolean(machine?.connected);

  const refreshPorts = useCallback(() => {
    api
      .listPorts()
      .then((res) => {
        setPorts(res.ports);
        setPort((current) => current || res.ports.find((p) => p.is_usb)?.device || res.ports[0]?.device || "");
      })
      .catch((err) => toast.error("อ่านรายการพอร์ตไม่สำเร็จ", err));
  }, [toast]);

  useEffect(() => {
    refreshPorts();
  }, [refreshPorts]);

  const run = async (kind: "connect" | "home", action: () => Promise<unknown>, failTitle: string) => {
    setBusy(kind);
    try {
      await action();
    } catch (err) {
      toast.error(failTitle, err);
    } finally {
      setBusy(null);
      onChange();
    }
  };

  const disconnect = async () => {
    try {
      await api.disconnectMachine();
    } catch (err) {
      toast.error("ตัดการเชื่อมต่อไม่สำเร็จ", err);
    }
    onChange();
  };

  const motorsOff = async () => {
    try {
      await api.motorsOff();
      toast.info("ปิดมอเตอร์แล้ว", "ต้องสั่ง HOME ใหม่ก่อนเคลื่อนที่");
    } catch (err) {
      toast.error("ปิดมอเตอร์ไม่สำเร็จ", err);
    }
    onChange();
  };

  return (
    <div className="flex items-center gap-2 flex-wrap px-4 py-2.5 border-b border-line bg-surface">
      <div className="flex items-center gap-2 mr-1">
        <StatusDot tone={!connected ? "neutral" : machine?.homed ? "pass" : "review"} pulse={machine?.is_moving} />
        <span className="text-sm font-medium">สเตจ XY</span>
        {connected && <Badge tone={machine?.mode === "serial" ? "accent" : "review"}>{machine?.mode === "serial" ? "Serial" : "จำลอง"}</Badge>}
      </div>

      {!connected ? (
        <>
          <Select value={port} onChange={(e) => setPort(e.target.value)} className="w-56! h-8! text-xs" aria-label="พอร์ตอนุกรม">
            {ports.map((p) => (
              <option key={p.device} value={p.device}>
                {p.device}
                {p.is_usb ? " · USB" : ""}
              </option>
            ))}
            {!ports.length && <option value="">ไม่พบพอร์ต</option>}
          </Select>
          <IconButton icon={RefreshCw} label="รีเฟรชพอร์ต" size="sm" onClick={refreshPorts} />
          <Button
            size="sm"
            variant="primary"
            icon={Plug}
            loading={busy === "connect"}
            disabled={!port}
            onClick={() => run("connect", () => api.connectMachine("serial", port), "เชื่อมต่อสเตจไม่สำเร็จ")}
          >
            เชื่อมต่อ
          </Button>
          <Button
            size="sm"
            variant="ghost"
            icon={PlugZap}
            loading={busy === "connect"}
            onClick={() => run("connect", () => api.connectMachine("simulation"), "เปิดสเตจจำลองไม่สำเร็จ")}
            title="ทดลองใช้งานโดยไม่ต่อฮาร์ดแวร์"
          >
            จำลอง
          </Button>
        </>
      ) : (
        <>
          <Button
            size="sm"
            variant={machine?.homed ? "secondary" : "primary"}
            icon={Home}
            loading={busy === "home"}
            disabled={scanning || machine?.is_moving}
            onClick={() => run("home", api.homeMachine, "HOME ไม่สำเร็จ")}
          >
            HOME
          </Button>
          <div className="h-8 px-3 rounded-lg bg-surface-2 border border-line flex items-center gap-3 font-mono tabular text-xs">
            <span>
              <span className="text-subtle">X</span> {formatMm(machine?.position_mm[0])}
            </span>
            <span>
              <span className="text-subtle">Y</span> {formatMm(machine?.position_mm[1])}
            </span>
            <span className="text-subtle">mm</span>
          </div>
          {!machine?.homed && <span className="text-xs text-review">ต้อง HOME ก่อนเคลื่อนที่</span>}
          <div className="ml-auto flex items-center gap-1">
            <Button size="sm" variant="ghost" icon={Power} disabled={scanning} onClick={motorsOff}>
              ปิดมอเตอร์
            </Button>
            <Button size="sm" variant="ghost" icon={Unplug} onClick={disconnect}>
              ตัดการเชื่อมต่อ
            </Button>
          </div>
        </>
      )}
      {machine?.last_error && <span className="basis-full text-xs text-fail truncate">⚠ {machine.last_error}</span>}
    </div>
  );
}
