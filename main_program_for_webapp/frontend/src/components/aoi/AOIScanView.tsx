"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Camera, Columns2, Grid3x3, Image as ImageIcon, MapPin, Move, SlidersHorizontal, Video } from "lucide-react";
import type { AOIPointResult, AOIRunReport, CustomPointRequest, InspectionResult, ReferenceSummary, ScanProgressEvent, SystemStatus } from "@/types";
import { API_BASE, api, errorMessage } from "@/lib/api";
import { captureInspection } from "@/lib/capture-inspection";
import type { ExpectedComponent } from "@/lib/board-inspection";
import { formatMm, refsOfType } from "@/lib/format";
import type { InspectionParams, SetParams } from "@/lib/params";
import { usePersistentState } from "@/hooks/usePersistentState";
import { sfx } from "@/lib/sound";
import { LiveCameraFeed, type FeedHud } from "../LiveCameraFeed";
import PointReferenceModal from "../PointReferenceModal";
import { PointResultModal } from "../PointResultModal";
import { Button, Segmented } from "../ui";
import { useToast } from "../Toast";
import { StageBar } from "./StageBar";
import { PointsPanel } from "./PointsPanel";
import { DEFAULT_GRID, DEFAULT_MOTION, GridPanel, JogPanel, ParamsPanel, type GridPlan, type MotionSettings } from "./panels";
import { Filmstrip, OutputView, ScanStatusStrip, type OutputItem, type PendingFrame } from "./ScanResults";

/** One camera frame as an object URL (for the "analyzing" view); null if unavailable. */
async function grabFrame(): Promise<string | null> {
  try {
    const res = await fetch(`${API_BASE}/api/camera/snapshot?t=${Date.now()}`, { cache: "no-store" });
    return res.ok ? URL.createObjectURL(await res.blob()) : null;
  } catch {
    return null;
  }
}

interface AOIScanViewProps {
  status: SystemStatus | null;
  report: AOIRunReport | null;
  progress: ScanProgressEvent | null;
  references: ReferenceSummary[];
  params: InspectionParams;
  setParams: SetParams;
  onRefreshStatus: () => void;
}

type PanelTab = "points" | "grid" | "jog" | "params";
type ViewMode = "live" | "output" | "split";

const POINTS_KEY = "pcb_aoi_points";
const stripImages = (points: CustomPointRequest[]) => points.map((p) => ({ ...p, reference_image: undefined }));

const PROGRESS_TITLE: Partial<Record<ScanProgressEvent["event"], string>> = {
  point_start: "กำลังเคลื่อนไปยังจุดตรวจ",
  point_capturing: "รอภาพนิ่งและถ่ายภาพ",
  point_frame: "กำลังตรวจหลายเฟรม",
  point_complete: "ตรวจจุดเสร็จ",
};

export function AOIScanView({ status, report, progress, references, params, setParams, onRefreshStatus }: AOIScanViewProps) {
  const toast = useToast();
  const machine = status?.machine ?? null;
  const scanning = report?.status === "running";
  const canMove = Boolean(machine?.connected && machine.homed);

  // Persisted work: marked points survive a page reload (they used to be lost).
  // If localStorage is full, previews are dropped but the taught components are kept.
  const warnedQuota = useRef(false);
  const [points, setPoints] = usePersistentState<CustomPointRequest[]>(POINTS_KEY, [], {
    onWriteError: (value) => {
      try {
        localStorage.setItem(POINTS_KEY, JSON.stringify(stripImages(value)));
      } catch {
        // Nothing more we can do; points still live in memory.
      }
      if (!warnedQuota.current) {
        warnedQuota.current = true;
        toast.warning("พื้นที่เก็บในเบราว์เซอร์เต็ม", "บันทึกจุดและชิ้นส่วนต้นแบบแล้ว แต่ไม่ได้เก็บภาพตัวอย่าง");
      }
    },
  });
  const [grid, setGridState] = usePersistentState<GridPlan>("pcb_aoi_grid", DEFAULT_GRID, { merge: true });
  const [motion, setMotionState] = usePersistentState<MotionSettings>("pcb_aoi_motion", DEFAULT_MOTION, { merge: true });
  const setGrid = (g: Partial<GridPlan>) => setGridState((s) => ({ ...s, ...g }));
  const setMotion = (m: Partial<MotionSettings>) => setMotionState((s) => ({ ...s, ...m }));

  const [tab, setTab] = useState<PanelTab>("points");
  const [viewMode, setViewMode] = useState<ViewMode>("split");
  const [selectedRaw, setSelected] = useState(0);
  const [liveZoom, setLiveZoom] = useState(1);
  const [marking, setMarking] = useState(false);
  const [movingIndex, setMovingIndex] = useState<number | null>(null);
  const [teachProgress, setTeachProgress] = useState<{ current: number; total: number } | null>(null);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [pickedGridRef, setGridReferenceId] = useState("");
  const [snapping, setSnapping] = useState(false);
  const [localFlash, setLocalFlash] = useState<number | null>(null);
  const shutter = () => {
    sfx.shutter();
    setLocalFlash(Date.now());
  };
  const [pick, setPick] = useState<{ item: OutputItem; at: string | null } | null>(null);
  // Frozen frame shown in the output pane while a test snap / scan point is analyzed.
  const [snapPending, setSnapPending] = useState<PendingFrame | null>(null);
  const [scanFrame, setScanFrame] = useState<{ key: string; image: string } | null>(null);
  const [detail, setDetail] = useState<AOIPointResult | null>(null);

  const selected = Math.min(selectedRaw, Math.max(0, points.length - 1));
  const gridRefs = useMemo(() => refsOfType(references, "aoi_grid"), [references]);
  const gridReferenceId = gridRefs.some((r) => r.id === pickedGridRef) ? pickedGridRef : "";

  // The output pane follows the newest point result; a manual pick (filmstrip or test
  // snap) sticks until the next point finishes.
  const results = report?.results ?? [];
  const lastResult = results[results.length - 1];
  const lastKey = lastResult ? `${report?.id}:${lastResult.point_index}` : null;
  const output: OutputItem | null =
    pick && pick.at === lastKey ? pick.item : lastResult ? { kind: "point", point: lastResult } : (pick?.item ?? null);
  const setOutput = (item: OutputItem) => setPick({ item, at: lastKey });

  /* ── Motion ── */

  const moveTo = useCallback(
    async (x: number, y: number) => {
      await api.moveToPosition(x, y, motion.speed);
      onRefreshStatus();
    },
    [motion.speed, onRefreshStatus]
  );

  const moveToPoint = async (index: number) => {
    const pt = points[index];
    if (!pt) return;
    setSelected(index);
    setMovingIndex(index);
    setLiveZoom(pt.zoom || 1);
    try {
      await moveTo(pt.x_mm, pt.y_mm);
    } finally {
      setMovingIndex(null);
    }
  };

  const guarded = (title: string, action: () => Promise<unknown>) => async () => {
    try {
      await action();
    } catch (err) {
      toast.error(title, err);
    }
  };

  const jog = (dx: number, dy: number) =>
    guarded("จ๊อกไม่สำเร็จ", async () => {
      await api.jogMachine(dx, dy, motion.speed);
      onRefreshStatus();
    })();

  const home = guarded("HOME ไม่สำเร็จ", async () => {
    await api.homeMachine();
    onRefreshStatus();
  });

  /* ── Points ── */

  const updatePoint = (index: number, patch: Partial<CustomPointRequest>) =>
    setPoints((all) => all.map((p, i) => (i === index ? { ...p, ...patch } : p)));

  const markPoint = async () => {
    if (!machine) return;
    const [x, y] = machine.position_mm;
    setMarking(true);
    let reference: { image?: string; items?: ExpectedComponent[] } = {};
    try {
      shutter();
      const captured = await captureInspection(liveZoom, params.conf, params.imgsz);
      reference = { image: captured.frame.image, items: captured.items };
    } catch (err) {
      toast.warning("บันทึกจุดแล้ว แต่ถ่ายต้นแบบไม่สำเร็จ", errorMessage(err));
    } finally {
      setMarking(false);
    }
    const next: CustomPointRequest = {
      id: `pt_${Date.now()}`,
      name: `จุด ${points.length + 1}`,
      x_mm: Number(x.toFixed(2)),
      y_mm: Number(y.toFixed(2)),
      zoom: liveZoom,
      reference_image: reference.image,
      expected_components: reference.items,
    };
    setPoints((all) => [...all, next]);
    setSelected(points.length);
    if (reference.items) sfx.ding();
    if (reference.items) toast.success(`มาร์คจุดแล้ว · พบ ${reference.items.length} ชิ้น`, "ตรวจทานต้นแบบด้วยปุ่ม “แก้ต้นแบบ”");
  };

  const deletePoint = (index: number) => setPoints((all) => all.filter((_, i) => i !== index));

  const clearPoints = () => {
    if (window.confirm(`ลบจุดตรวจทั้งหมด ${points.length} จุด?`)) setPoints([]);
  };

  const saveReference = (index: number, image: string, items: ExpectedComponent[]) => {
    updatePoint(index, { reference_image: image, expected_components: items });
    toast.success("บันทึกต้นแบบแล้ว", `${items.length} ตำแหน่ง`);
  };

  const teachAll = async () => {
    setTeachProgress({ current: 0, total: points.length });
    try {
      const taught = [...points];
      for (let i = 0; i < points.length; i++) {
        setTeachProgress({ current: i + 1, total: points.length });
        await moveToPoint(i);
        await new Promise((r) => setTimeout(r, Math.max(300, motion.settleSec * 1000)));
        shutter();
        const captured = await captureInspection(points[i].zoom || 1, params.conf, params.imgsz);
        taught[i] = { ...points[i], reference_image: captured.frame.image, expected_components: captured.items };
      }
      setPoints(taught);
      sfx.pass();
      toast.success(`สอนต้นแบบครบ ${points.length} จุด`, "ตรวจทานกรอบและชื่อคลาสของแต่ละจุดก่อนใช้งานจริง");
    } catch (err) {
      toast.error("สอนต้นแบบไม่สำเร็จ", err);
    } finally {
      setTeachProgress(null);
    }
  };

  /* ── Scans ── */

  const startScan = async (plan: Parameters<typeof api.startScan>[0]["plan"], isGolden: boolean, referenceId?: string) => {
    try {
      setPick(null);
      await api.startScan({ ...params, plan, isGolden, referenceId });
      setViewMode("split");
      onRefreshStatus();
    } catch (err) {
      toast.error("เริ่มสแกนไม่สำเร็จ", err);
    }
  };

  const startPointScan = () =>
    startScan(
      {
        plan_mode: "custom",
        origin_x_mm: 0,
        origin_y_mm: 0,
        columns: points.length,
        rows: 1,
        pitch_x_mm: 10,
        pitch_y_mm: 10,
        speed: motion.speed,
        settle_sec: motion.settleSec,
        // The backend only needs the taught boxes; don't upload the preview images.
        custom_points: stripImages(points),
      },
      false
    );

  const startGridScan = (golden: boolean) =>
    startScan(
      {
        plan_mode: "grid",
        origin_x_mm: grid.originX,
        origin_y_mm: grid.originY,
        columns: grid.columns,
        rows: grid.rows,
        pitch_x_mm: grid.pitchX,
        pitch_y_mm: grid.pitchY,
        speed: motion.speed,
        settle_sec: motion.settleSec,
      },
      golden,
      golden ? undefined : gridReferenceId || undefined
    );

  const stopScan = guarded("หยุดสแกนไม่สำเร็จ", async () => {
    await api.stopScan();
    onRefreshStatus();
  });

  const testSnap = async () => {
    setSnapping(true);
    const key = `snap:${Date.now()}`;
    let frozen: string | null = null;
    setSnapPending({ key, image: null, label: "ถ่ายทดสอบ" });
    if (viewMode === "live") setViewMode("split");
    // The same moment the backend captures, for the "analyzing" view (best effort).
    grabFrame().then((url) => {
      frozen = url;
      if (url) setSnapPending((p) => (p?.key === key ? { ...p, image: url } : p));
    });
    try {
      shutter();
      const result: InspectionResult = await api.inspectLive({ ...params });
      sfx.verdict(result.verdict);
      setOutput({ kind: "snap", result });
      if (viewMode === "live") setViewMode("split");
    } catch (err) {
      toast.error("ถ่ายทดสอบไม่สำเร็จ", err);
    } finally {
      setSnapping(false);
      setSnapPending((p) => (p?.key === key ? null : p));
      // Let the pane swap to the result before dropping the frozen frame.
      setTimeout(() => frozen && URL.revokeObjectURL(frozen), 1000);
    }
  };

  const openOutput = () => {
    if (!output) return;
    if (output.kind === "point") return setDetail(output.point);
    const r = output.result;
    setDetail({
      point_index: 0,
      name: "ถ่ายทดสอบ",
      col: 0,
      row: 0,
      x_mm: machine?.position_mm[0] ?? 0,
      y_mm: machine?.position_mm[1] ?? 0,
      verdict: r.verdict,
      reason: r.reason,
      image_path: "",
      annotated_path: "",
      image_url: r.image_url || "",
      annotated_url: r.annotated_url || r.image_url || "",
      summary: r.summary,
      detections: r.detections,
      speed_ms: r.speed_ms,
    });
  };

  /* ── Camera HUD ── */

  const scanZoom = scanning ? progress?.zoom ?? 1 : liveZoom;
  const capturing = scanning && (progress?.event === "point_frame" || progress?.event === "point_capturing");
  const flashKey = capturing ? `${progress?.run_id}:${progress?.point_index}:${progress?.frame_index ?? "c"}` : localFlash;
  const scanningIndex = scanning && report?.plan.plan_mode === "custom" ? (progress?.point_index ?? null) : null;
  let hud: FeedHud | null = null;
  if (scanning && progress?.point_index !== undefined) {
    const frame = progress.event === "point_frame" ? ` · เฟรม ${progress.frame_index}/${progress.target_frames}` : "";
    hud = {
      tone: "accent",
      title: PROGRESS_TITLE[progress.event] ?? "กำลังสแกน",
      detail: `จุด ${progress.point_index + 1}/${progress.total_points} ${progress.name ?? ""}${
        progress.target_mm ? ` · ${formatMm(progress.target_mm[0])}, ${formatMm(progress.target_mm[1])} mm` : ""
      }${frame}`,
    };
  } else if (movingIndex !== null && points[movingIndex]) {
    const pt = points[movingIndex];
    hud = { tone: "review", title: `กำลังเคลื่อนไป ${pt.name}`, detail: `${formatMm(pt.x_mm)}, ${formatMm(pt.y_mm)} mm` };
  }

  // While a scan captures a point that has no result yet, show its frozen frame analyzing.
  const capturingKey =
    capturing && progress?.point_index !== undefined && !results.some((r) => r.point_index === progress.point_index)
      ? `${progress.run_id}:${progress.point_index}`
      : null;
  useEffect(() => {
    if (!capturingKey) return;
    let live = true;
    grabFrame().then((url) => {
      if (!url) return;
      if (!live) return URL.revokeObjectURL(url);
      setScanFrame((old) => {
        if (old) setTimeout(() => URL.revokeObjectURL(old.image), 1000);
        return { key: capturingKey, image: url };
      });
    });
    return () => {
      live = false;
    };
  }, [capturingKey]);
  const pending: PendingFrame | null =
    snapPending ??
    (capturingKey
      ? {
          key: capturingKey,
          image: scanFrame?.key === capturingKey ? scanFrame.image : null,
          label: `จุด ${(progress?.point_index ?? 0) + 1}/${progress?.total_points ?? "?"}`,
        }
      : null);

  const panelDisabled = scanning;
  const showLive = viewMode !== "output";
  const showOutput = viewMode !== "live";

  return (
    <div className="h-full flex flex-col">
      <StageBar machine={machine} scanning={scanning} onChange={onRefreshStatus} />

      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[360px_minmax(0,1fr)] overflow-y-auto lg:overflow-hidden">
        {/* ── Left: tools ── */}
        <aside className="border-b lg:border-b-0 lg:border-r border-line bg-surface flex flex-col lg:min-h-0">
          <div className="p-3 border-b border-line">
            <Segmented
              size="sm"
              className="w-full"
              value={tab}
              onChange={setTab}
              options={[
                { value: "points", label: "จุดตรวจ", icon: MapPin },
                { value: "grid", label: "ตาราง", icon: Grid3x3 },
                { value: "jog", label: "เคลื่อนที่", icon: Move },
                { value: "params", label: "ค่าตรวจ", icon: SlidersHorizontal },
              ]}
            />
          </div>
          <div className="flex-1 lg:overflow-y-auto p-4">
            {tab === "points" && (
              <PointsPanel
                points={points}
                selected={selected}
                onSelect={(i) => {
                  setSelected(i);
                  setLiveZoom(points[i]?.zoom || 1);
                }}
                zoom={liveZoom}
                onZoom={setLiveZoom}
                onRename={(i, name) => updatePoint(i, { name })}
                onSetPointZoom={(i, zoom) => {
                  updatePoint(i, { zoom });
                  setLiveZoom(zoom);
                }}
                onMark={markPoint}
                onMove={(i) => moveToPoint(i).catch((err) => toast.error("เคลื่อนที่ไม่สำเร็จ", err))}
                onEditReference={setEditingIndex}
                onDelete={deletePoint}
                onClear={clearPoints}
                onTeachAll={teachAll}
                onStart={startPointScan}
                marking={marking}
                movingIndex={movingIndex}
                teachProgress={teachProgress}
                canMove={canMove}
                scanning={scanning}
                frames={params.multiframeEnabled ? params.targetFrames : null}
                scanningIndex={scanningIndex}
              />
            )}
            {tab === "grid" && (
              <GridPanel
                grid={grid}
                setGrid={setGrid}
                machine={machine}
                references={gridRefs}
                referenceId={gridReferenceId}
                setReferenceId={setGridReferenceId}
                disabled={!canMove || panelDisabled}
                onStart={startGridScan}
              />
            )}
            {tab === "jog" && (
              <JogPanel
                machine={machine}
                motion={motion}
                setMotion={setMotion}
                disabled={panelDisabled}
                onJog={jog}
                onHome={home}
                onMoveTo={(x, y) => moveTo(x, y).catch((err) => toast.error("เคลื่อนที่ไม่สำเร็จ", err))}
              />
            )}
            {tab === "params" && <ParamsPanel params={params} setParams={setParams} disabled={panelDisabled} />}
          </div>
        </aside>

        {/* ── Right: camera + results ── */}
        <section className="min-h-[560px] lg:min-h-0 p-3 flex flex-col gap-3">
          {report && report.status !== "idle" && <ScanStatusStrip report={report} onStop={stopScan} />}

          <div className="flex items-center gap-2 flex-wrap">
            <Segmented
              size="sm"
              value={viewMode}
              onChange={setViewMode}
              options={[
                { value: "live", label: "ภาพสด", icon: Video },
                { value: "split", label: "คู่", icon: Columns2 },
                { value: "output", label: "ผลตรวจ", icon: ImageIcon },
              ]}
            />
            <Button size="sm" className="ml-auto" icon={Camera} loading={snapping} disabled={scanning} onClick={testSnap}>
              ถ่ายทดสอบ
            </Button>
          </div>

          <div className="flex-1 min-h-0 grid gap-3 grid-rows-[minmax(260px,1fr)] xl:grid-rows-1" style={{ gridTemplateColumns: showLive && showOutput ? "repeat(auto-fit, minmax(320px, 1fr))" : "1fr" }}>
            {showLive && (
              <LiveCameraFeed
                className="min-h-[260px]"
                zoom={scanZoom}
                onZoomChange={scanning ? undefined : setLiveZoom}
                stagePosition={machine?.connected ? machine.position_mm : undefined}
                hud={hud}
                flashKey={flashKey}
                scanning={capturing}
                locked={scanning}
              />
            )}
            {showOutput && (
              <div className="min-h-[260px]">
                <OutputView item={output} pending={pending} onOpen={openOutput} />
              </div>
            )}
          </div>

          <Filmstrip
            results={results}
            activeIndex={output?.kind === "point" ? output.point.point_index : null}
            onPick={(pt) => {
              setOutput({ kind: "point", point: pt });
              if (viewMode === "live") setViewMode("split");
            }}
          />
        </section>
      </div>

      {editingIndex !== null && points[editingIndex] && (
        <PointReferenceModal
          point={points[editingIndex]}
          pointIndex={editingIndex}
          params={params}
          onClose={() => setEditingIndex(null)}
          onSave={saveReference}
          onMoveToPoint={canMove ? () => moveToPoint(editingIndex) : undefined}
        />
      )}
      <PointResultModal point={detail} onClose={() => setDetail(null)} />
    </div>
  );
}
