"use client";

import React, { useCallback, useEffect, useState } from "react";
import { AppShell, type TabId } from "@/components/AppShell";
import { ToastProvider } from "@/components/Toast";
import { InspectionView } from "@/components/InspectionView";
import { AOIScanView } from "@/components/aoi/AOIScanView";
import { ReferencesView } from "@/components/ReferencesView";
import { HistoryView } from "@/components/HistoryView";
import { SettingsView } from "@/components/SettingsView";
import { useStationSocket } from "@/hooks/useStationSocket";
import { useIsClient, usePersistentState } from "@/hooks/usePersistentState";
import { api } from "@/lib/api";
import { DEFAULT_PARAMS, type InspectionParams } from "@/lib/params";
import type { AOIRunReport, ReferenceSummary, SystemStatus } from "@/types";

export default function Home() {
  // Everything below reads browser storage while initializing, so render it client-side only.
  const isClient = useIsClient();
  return isClient ? <Station /> : <div className="h-dvh bg-bg" />;
}

function Station() {
  const [tab, setTab] = usePersistentState<TabId>("pcb_tab", "aoi");
  const [theme, setTheme] = useState<"light" | "dark">(() => (document.documentElement.dataset.theme === "light" ? "light" : "dark"));
  const [params, setParamsState] = usePersistentState<InspectionParams>("pcb_params", DEFAULT_PARAMS, { merge: true });
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [polledScan, setPolledScan] = useState<AOIRunReport | null>(null);
  const [references, setReferences] = useState<ReferenceSummary[]>([]);
  const { connected, machineState, scanProgress } = useStationSocket();

  const setParams = useCallback(
    (update: Partial<InspectionParams>) => setParamsState((p) => ({ ...p, ...update })),
    [setParamsState]
  );

  const refreshStatus = useCallback(() => {
    api
      .getStatus()
      .then((s) => {
        setStatus(s);
        if (s.active_scan) return api.getScanStatus().then((scan) => setPolledScan("id" in scan ? scan : null));
      })
      .catch(() => undefined); // Backend unreachable; the socket indicator shows the link state.
  }, []);

  const refreshReferences = useCallback(() => {
    api
      .listReferences()
      .then(setReferences)
      .catch(() => undefined); // Keep the last list.
  }, []);

  useEffect(() => {
    refreshStatus();
    refreshReferences();
    const timer = setInterval(refreshStatus, 5000);
    return () => clearInterval(timer);
  }, [refreshStatus, refreshReferences]);

  // A finished golden scan creates a new reference profile.
  useEffect(() => {
    if (scanProgress?.event === "complete") {
      refreshReferences();
      refreshStatus();
    }
  }, [scanProgress, refreshReferences, refreshStatus]);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("pcb_theme", next);
    } catch {
      // Theme just won't persist.
    }
  };

  const liveStatus: SystemStatus | null = status ? { ...status, machine: machineState ?? status.machine } : null;
  const activeReport = scanProgress?.report ?? polledScan;

  return (
    <ToastProvider>
      <AppShell
        tab={tab}
        onTab={setTab}
        status={liveStatus}
        socketConnected={connected}
        onRefreshStatus={refreshStatus}
        theme={theme}
        onToggleTheme={toggleTheme}
      >
        {tab === "aoi" && (
          <AOIScanView
            status={liveStatus}
            report={activeReport}
            progress={scanProgress}
            references={references}
            params={params}
            setParams={setParams}
            onRefreshStatus={refreshStatus}
          />
        )}
        {tab === "inspect" && <InspectionView references={references} params={params} setParams={setParams} status={liveStatus} />}
        {tab === "references" && <ReferencesView references={references} onRefresh={refreshReferences} />}
        {tab === "history" && <HistoryView />}
        {tab === "settings" && <SettingsView onRefreshStatus={refreshStatus} />}
      </AppShell>
    </ToastProvider>
  );
}
