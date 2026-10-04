"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Camera,
  Columns2,
  Grid3x3,
  HelpCircle,
  Home,
  Image as ImageIcon,
  MapPin,
  Move,
  SlidersHorizontal,
  UserRound,
  Video,
  Wrench,
} from "lucide-react";
import type { AOIPointResult, AOIRunReport, CustomPointRequest, InspectionResult, PointFrames, ReferenceSummary, ScanProgressEvent, SystemStatus } from "@/types";
import { API_BASE, api, errorMessage } from "@/lib/api";
import { captureInspection } from "@/lib/capture-inspection";
import type { ExpectedComponent } from "@/lib/board-inspection";
import { formatMm, refsOfType } from "@/lib/format";
import type { InspectionParams, SetParams } from "@/lib/params";
import { usePersistentState } from "@/hooks/usePersistentState";
import { useElementSize } from "@/hooks/useElementSize";
import { sfx } from "@/lib/sound";
import { LiveCameraFeed, type FeedHud } from "../LiveCameraFeed";
import PointReferenceModal from "../PointReferenceModal";
import { PointResultModal } from "../PointResultModal";
import { Tour, type TourStep } from "../Tour";
import { Button, IconButton, Segmented, cx } from "../ui";
import { useToast } from "../Toast";
import { StageBar } from "./StageBar";
import { PointsPanel } from "./PointsPanel";
import { PointSets, type ActiveBoard } from "./PointSets";
import { DEFAULT_GRID, DEFAULT_MOTION, GridPanel, JogPanel, ParamsPanel, type GridPlan, type MotionSettings } from "./panels";
import { OutputView, type OutputItem, type PendingFrame } from "./ScanResults";
import { ScanDock } from "./ScanDock";
import { JogOverlay } from "./JogOverlay";
import { WorkflowSteps, type StepKey, type WorkflowStep } from "./WorkflowSteps";
import { OperatorPanel } from "./OperatorPanel";
import { ShortcutHelp } from "./ShortcutHelp";

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
  pointFrames: PointFrames | null;
  references: ReferenceSummary[];
  params: InspectionParams;
  setParams: SetParams;
  onRefreshStatus: () => void;
  /** Another operator holds the station: everything that changes it is locked. */
  viewOnly: boolean;
  /** The splash screen is gone, so the first-visit tour may start. */
  introReady: boolean;
}

type PanelTab = "points" | "grid" | "jog" | "params";
type ViewMode = "live" | "output" | "split";
type WorkMode = "engineer" | "operator";

const POINTS_KEY = "pcb_aoi_points";
const VIEW_GAP = 12;
const ZOOMS = [1, 1.5, 2, 3, 4];
const ARROWS: Record<string, [number, number]> = { ArrowUp: [0, 1], ArrowDown: [0, -1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] };

/**
 * Size the camera/result cards to the camera's aspect ratio, as large as the area allows:
 * side by side or stacked, whichever gives the bigger picture (no letterbox bars).
 */
function fitViewers(width: number, height: number, count: number, ratio: number) {
  const gaps = VIEW_GAP * (count - 1);
  const rowW = Math.min((width - gaps) / count, height * ratio);
  const colW = Math.min(width, ((height - gaps) / count) * ratio);
  const row = count === 1 || rowW >= colW;
  const w = Math.max(160, Math.floor(row ? rowW : colW));
  return { row, w, h: Math.floor(w / ratio), total: row ? w * count + gaps : w };
}
const stripImages = (points: CustomPointRequest[]) => points.map((p) => ({ ...p, reference_image: undefined }));

const PROGRESS_TITLE: Partial<Record<ScanProgressEvent["event"], string>> = {
  point_start: "กำลังเคลื่อนไปยังจุดตรวจ",
  point_capturing: "รอภาพนิ่งและถ่ายภาพ",
  point_frame: "กำลังตรวจหลายเฟรม",
  point_complete: "ตรวจจุดเสร็จ",
};

const ENGINEER_TOUR: TourStep[] = [
  { target: "steps", title: "ขั้นตอนการทำงาน", body: "ทำตามลำดับ 1 → 4 วงกลมสีน้ำเงินคือขั้นปัจจุบัน และกล่องด้านล่างบอกว่าต้องทำอะไรต่อ กดที่ขั้นเพื่อไปยังส่วนนั้น" },
  { target: "board", title: "บอร์ด", body: "จุดตรวจทั้งหมดเก็บอยู่ในบอร์ด สร้างชื่อบอร์ดใหม่หรือเปิดบอร์ดที่บันทึกไว้ ทุกการแก้ไขบันทึกลงสถานีอัตโนมัติ" },
  { target: "stage", title: "สเตจ XY", body: "เชื่อมต่อพอร์ต (หรือกด “จำลอง” เพื่อทดลองโดยไม่ต่อเครื่อง) แล้วกด HOME ทุกครั้งก่อนเคลื่อนที่" },
  {
    target: "live",
    title: "ภาพสดและการจ๊อก",
    body: "ขยับสเตจด้วยปุ่มลูกศรบนภาพหรือบนคีย์บอร์ด (Shift = ×10) กดค้างเพื่อเคลื่อนต่อเนื่อง ปุ่มกลางเปลี่ยนระยะต่อครั้ง มุมขวาล่างเลือกซูม",
  },
  { target: "mark", title: "มาร์คจุดตรวจ", body: "กดปุ่มนี้ (หรือกด M) เพื่อบันทึกพิกัดปัจจุบันและถ่ายภาพต้นแบบของจุดนั้น ปุ่มจะบอกเหตุผลถ้ายังกดไม่ได้" },
  { target: "dock", title: "เริ่มสแกน", body: "ปุ่มเริ่มตรวจและภาพย่อของทุกจุดอยู่ตรงนี้ ระหว่างสแกนภาพย่อจะเปลี่ยนเป็นผล PASS/FAIL ทีละจุด กดภาพย่อเพื่อดูผล" },
  { target: "output", title: "ผลตรวจ", body: "แสดงผลล่าสุด คลิกเพื่อดูรายละเอียดทุกชิ้นส่วน ถ้ายังไม่มีผลจะแสดงการสแกนล่าสุดและสรุปของวันนี้" },
  { target: "mode", title: "โหมดผู้ใช้งาน / วิศวกร", body: "คนหน้าเครื่องใช้โหมดผู้ใช้งาน: เลือกบอร์ด → กดเริ่ม → อ่าน PASS/FAIL ตัวใหญ่ ส่วนการมาร์คจุดและตั้งค่าอยู่ในโหมดวิศวกร" },
  { target: "help", title: "คีย์ลัดและทัวร์", body: "กด ? หรือปุ่มนี้เพื่อดูคีย์ลัดทั้งหมด และเปิดทัวร์นี้อีกครั้งได้ทุกเมื่อ" },
];

const OPERATOR_TOUR: TourStep[] = [
  { target: "mode", title: "โหมดผู้ใช้งาน", body: "หน้าจอสำหรับคนหน้าเครื่อง มีแค่สิ่งที่ต้องใช้ตรวจบอร์ด สลับเป็นโหมดวิศวกรเพื่อมาร์คจุดหรือตั้งค่า" },
  { target: "board", title: "เลือกบอร์ด", body: "เลือกรุ่นบอร์ดที่จะตรวจจากรายการที่วิศวกรบันทึกไว้ แล้วกด “เปิด”" },
  { target: "operator", title: "เริ่มตรวจและอ่านผล", body: "วางบอร์ดแล้วกดปุ่มใหญ่ ผลรวมของบอร์ดแสดงเป็น PASS / FAIL ตัวใหญ่ตรงนี้" },
  { target: "dock", title: "ผลแต่ละจุด", body: "ภาพย่อของทุกจุดตรวจ กดเพื่อดูว่าชิ้นส่วนไหนไม่ผ่าน" },
  { target: "help", title: "ความช่วยเหลือ", body: "กด ? เพื่อดูคีย์ลัด และเปิดทัวร์นี้อีกครั้งได้" },
];

export function AOIScanView({ status, report, progress, pointFrames, references, params, setParams, onRefreshStatus, viewOnly, introReady }: AOIScanViewProps) {
  const toast = useToast();
  const machine = status?.machine ?? null;
  const scanning = report?.status === "running";
  const canMove = Boolean(machine?.connected && machine.homed) && !viewOnly;

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
  // Board whose points are being edited (autosaved to the station); required before marking.
  const [board, setBoard] = usePersistentState<ActiveBoard>("pcb_aoi_board", null);
  const [grid, setGridState] = usePersistentState<GridPlan>("pcb_aoi_grid", DEFAULT_GRID, { merge: true });
  const [motion, setMotionState] = usePersistentState<MotionSettings>("pcb_aoi_motion", DEFAULT_MOTION, { merge: true });
  const [mode, setMode] = usePersistentState<WorkMode>("pcb_aoi_mode", "engineer");
  const [jogHidden, setJogHidden] = usePersistentState("pcb_aoi_jog_hidden", false);
  const [tourDone, setTourDone] = usePersistentState("pcb_aoi_tour_done", false);
  const setGrid = (g: Partial<GridPlan>) => setGridState((s) => ({ ...s, ...g }));
  const setMotion = (m: Partial<MotionSettings>) => setMotionState((s) => ({ ...s, ...m }));
  const operator = mode === "operator";

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
  const [helpOpen, setHelpOpen] = useState(false);
  const [tourManual, setTourManual] = useState(false);
  const shutter = () => sfx.shutter();
  const [pick, setPick] = useState<{ item: OutputItem; at: string | null } | null>(null);
  // Frozen frame shown in the output pane while a test snap / scan point is analyzed.
  const [snapPending, setSnapPending] = useState<PendingFrame | null>(null);
  const [scanFrame, setScanFrame] = useState<{ key: string; image: string } | null>(null);
  const [detail, setDetail] = useState<AOIPointResult | null>(null);
  const jogBusy = useRef(false);

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

  /* ── Why things are unavailable (shown on the buttons themselves) ── */

  const taught = points.filter((p) => p.expected_components?.length).length;
  const lockReason = viewOnly ? "ผู้อื่นกำลังควบคุมสถานี" : null;
  const stageReason =
    lockReason ??
    (scanning ? "กำลังสแกน" : !machine?.connected ? "เชื่อมต่อสเตจก่อน" : !machine.homed ? "กด HOME สเตจก่อน" : teachProgress ? "กำลังสอนต้นแบบ" : null);
  const markReason = !board ? "สร้างหรือเปิดบอร์ดก่อน" : stageReason;
  const startReason = lockReason ?? (!board ? "เปิดบอร์ดก่อน" : !points.length ? "มาร์คจุดตรวจก่อน" : stageReason);
  const panelDisabled = scanning || viewOnly;

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

  // The socket streams the new position, so a jog doesn't need a status refresh.
  const jog = async (dx: number, dy: number) => {
    try {
      await api.jogMachine(dx, dy, motion.speed);
      return true;
    } catch (err) {
      toast.error("จ๊อกไม่สำเร็จ", err);
      return false;
    }
  };

  const home = guarded("HOME ไม่สำเร็จ", async () => {
    await api.homeMachine();
    sfx.ding();
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
      const taughtPoints = [...points];
      for (let i = 0; i < points.length; i++) {
        setTeachProgress({ current: i + 1, total: points.length });
        await moveToPoint(i);
        await new Promise((r) => setTimeout(r, Math.max(300, motion.settleSec * 1000)));
        shutter();
        const captured = await captureInspection(points[i].zoom || 1, params.conf, params.imgsz);
        taughtPoints[i] = { ...points[i], reference_image: captured.frame.image, expected_components: captured.items };
      }
      setPoints(taughtPoints);
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

  /* ── Keyboard shortcuts (latest handlers via a ref; one listener) ── */

  const onKey = useRef<(e: KeyboardEvent) => void>(() => undefined);
  useEffect(() => {
    onKey.current = (e) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
      const target = e.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true'], [role='radiogroup']")) return;
      if (document.querySelector("[role='dialog']")) return; // modals and the tour own the keyboard
      // e.code, not e.key: the shortcuts must work with the Thai keyboard layout too.
      if (e.key === "?" || (e.code === "Slash" && e.shiftKey)) {
        e.preventDefault();
        setHelpOpen((v) => !v);
        return;
      }
      if (e.code === "Space") {
        if (target?.closest("button, a")) return; // Space presses the focused button
        e.preventDefault();
        if (!snapping && !scanning && !e.repeat) testSnap();
        return;
      }
      if (operator) return; // operators don't move the stage from the keyboard
      const dir = ARROWS[e.key];
      if (dir) {
        e.preventDefault();
        if (stageReason) {
          if (!e.repeat) toast.warning(stageReason);
          return;
        }
        if (jogBusy.current) return; // key repeat waits for the previous move
        const step = e.shiftKey ? Math.min(motion.jogStep * 10, 50) : motion.jogStep;
        jogBusy.current = true;
        jog(dir[0] * step, dir[1] * step).finally(() => (jogBusy.current = false));
        return;
      }
      if (e.repeat) return;
      if (e.code === "KeyM") {
        if (markReason) toast.warning(markReason);
        else if (!marking) markPoint();
      } else if (e.code === "KeyH") {
        if (lockReason || scanning || !machine?.connected) toast.warning(lockReason ?? (scanning ? "กำลังสแกน" : "เชื่อมต่อสเตจก่อน"));
        else home();
      } else if (/^Digit[1-5]$/.test(e.code) && !scanning) {
        setLiveZoom(ZOOMS[Number(e.code.slice(5)) - 1]);
      }
    };
  });
  useEffect(() => {
    const listener = (e: KeyboardEvent) => onKey.current(e);
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);

  /* ── Workflow steps ── */

  const scanDone = report?.status === "complete" && !report.is_golden_scan;
  const stepDone = [Boolean(board), Boolean(machine?.connected && machine.homed), points.length > 0 && taught === points.length, scanDone];
  const firstOpen = stepDone.findIndex((d) => !d);
  const stateOf = (i: number) => (stepDone[i] ? "done" : i === firstOpen ? "current" : "todo");
  const steps: WorkflowStep[] = [
    { key: "board", label: "บอร์ด", state: stateOf(0), hint: "ตั้งชื่อบอร์ดใหม่แล้วกด “สร้าง” หรือเปิดบอร์ดที่บันทึกไว้" },
    {
      key: "stage",
      label: "สเตจพร้อม",
      state: stateOf(1),
      hint: !machine?.connected
        ? "เลือกพอร์ตที่แถบด้านบนแล้วกด “เชื่อมต่อ” (หรือ “จำลอง” เพื่อทดลองโดยไม่ต่อเครื่อง)"
        : "กด HOME ที่แถบด้านบนเพื่อหาจุดศูนย์ของสเตจ",
    },
    {
      key: "points",
      label: "มาร์คจุด",
      state: stateOf(2),
      hint: points.length
        ? `${points.length - taught} จุดยังไม่มีต้นแบบ — กด “สอนต้นแบบ” ที่จุดนั้น หรือ “สอนต้นแบบทุกจุด” ใต้ภาพกล้อง`
        : "จ๊อกสเตจบนภาพสด (หรือปุ่มลูกศร) ไปยังจุดที่ต้องการ แล้วกด “มาร์คตำแหน่งปัจจุบัน” หรือกด M",
    },
    {
      key: "scan",
      label: "สแกน",
      state: stateOf(3),
      hint: scanning
        ? "กำลังสแกน… ผลแต่ละจุดขึ้นที่ภาพย่อใต้ภาพกล้อง"
        : scanDone
          ? "สแกนเสร็จแล้ว — วางบอร์ดชิ้นถัดไปแล้วกด “เริ่มตรวจ” อีกครั้ง"
          : "กด “เริ่มตรวจ” ใต้ภาพกล้อง",
    },
  ];
  const pickStep = (key: StepKey) => {
    if (key === "stage") setTab("jog");
    else setTab("points");
    if (key === "scan") {
      const btn = document.querySelector<HTMLButtonElement>('[data-tour="dock"] button');
      btn?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      btn?.focus();
    }
  };

  /* ── Camera HUD ── */

  const scanZoom = scanning ? progress?.zoom ?? 1 : liveZoom;
  const capturing = scanning && (progress?.event === "point_frame" || progress?.event === "point_capturing");
  const scanningIndex = scanning ? (progress?.point_index ?? null) : null;
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
          frames: pointFrames?.key === capturingKey ? pointFrames.frames : [],
          target: progress?.target_frames ?? (pointFrames?.key === capturingKey ? pointFrames.target : undefined),
          label: `จุด ${(progress?.point_index ?? 0) + 1}/${progress?.total_points ?? "?"}`,
          waiting: "รอภาพนิ่งและถ่ายภาพ",
        }
      : null);

  const showLive = viewMode !== "output";
  const showOutput = viewMode !== "live";

  // Viewer cards take the camera frame's aspect ratio (1:1 for a 2160x2160 crop).
  const viewArea = useRef<HTMLDivElement>(null);
  const dockRef = useRef<HTMLDivElement>(null);
  const area = useElementSize(viewArea);
  const dock = useElementSize(dockRef);
  const camRes = status?.camera_resolution;
  const ratio = camRes && camRes[0] > 0 && camRes[1] > 0 ? camRes[0] / camRes[1] : 1;
  const dockSpace = dock.height ? dock.height + VIEW_GAP : 0;
  // Below lg the page scrolls, so only the width limits the cards (full-width, stacked).
  const scrolls = typeof window !== "undefined" && window.innerWidth < 1024;
  const availH = scrolls ? Number.POSITIVE_INFINITY : Math.max(200, area.height - dockSpace);
  const fit = area.width > 0 && (scrolls || area.height > 0) ? fitViewers(area.width, availH, showLive && showOutput ? 2 : 1, ratio) : null;

  const tourOpen = tourManual || (introReady && !tourDone);
  const closeTour = () => {
    setTourManual(false);
    setTourDone(true);
  };

  return (
    <div className="h-full flex flex-col">
      <StageBar machine={machine} scanning={scanning} onChange={onRefreshStatus} lockReason={lockReason} />

      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[360px_minmax(0,1fr)] overflow-y-auto lg:overflow-hidden">
        {/* ── Left: tools ── */}
        <aside className="border-b lg:border-b-0 lg:border-r border-line bg-surface flex flex-col lg:min-h-0">
          <div className="p-3 border-b border-line flex flex-col gap-3">
            <div data-tour="mode">
              <Segmented
                className="w-full"
                value={mode}
                onChange={(m) => {
                  setMode(m);
                  if (m === "operator") setTab("points");
                }}
                options={[
                  { value: "operator", label: "ผู้ใช้งาน", icon: UserRound },
                  { value: "engineer", label: "วิศวกร", icon: Wrench },
                ]}
              />
            </div>
            {!operator && (
              <>
                <WorkflowSteps steps={steps} onPick={pickStep} />
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
              </>
            )}
          </div>
          <div className="flex-1 lg:overflow-y-auto p-4">
            {operator ? (
              <div className="flex flex-col gap-5">
                <PointSets
                  operator
                  points={points}
                  board={board}
                  onBoardChange={setBoard}
                  disabled={scanning || viewOnly}
                  onLoad={(loadedPoints) => {
                    setPoints(loadedPoints);
                    setSelected(0);
                    setLiveZoom(loadedPoints[0]?.zoom || 1);
                  }}
                />
                <OperatorPanel
                  report={report}
                  pointCount={points.length}
                  currentName={scanning ? (progress?.name ?? null) : null}
                  startReason={startReason}
                  onStart={startPointScan}
                  onStop={stopScan}
                />
              </div>
            ) : (
              <>
                {tab === "points" && (
                  <div className="flex flex-col gap-5">
                    <PointSets
                      points={points}
                      board={board}
                      onBoardChange={setBoard}
                      disabled={scanning || marking || teachProgress !== null || viewOnly}
                      onLoad={(loadedPoints) => {
                        setPoints(loadedPoints);
                        setSelected(0);
                        setLiveZoom(loadedPoints[0]?.zoom || 1);
                      }}
                    />
                    {board && !lockReason && machine?.connected && !machine.homed && <HomeFirst onHome={home} disabled={scanning || machine.is_moving} />}
                    {board && (
                      <PointsPanel
                        points={points}
                        selected={selected}
                        onSelect={(i) => {
                          setSelected(i);
                          setLiveZoom(points[i]?.zoom || 1);
                        }}
                        zoom={liveZoom}
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
                        marking={marking}
                        movingIndex={movingIndex}
                        markReason={markReason}
                        locked={panelDisabled}
                        scanningIndex={report?.plan.plan_mode === "custom" ? scanningIndex : null}
                        boardName={board.name}
                      />
                    )}
                  </div>
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
              </>
            )}
          </div>
        </aside>

        {/* ── Right: camera + results ── */}
        <section className="min-h-[560px] lg:min-h-0 p-3 flex flex-col gap-3">
          <div className="flex items-center gap-2 flex-wrap mx-auto w-full" style={fit ? { maxWidth: Math.max(fit.total, 480) } : undefined}>
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
            <div className="ml-auto flex items-center gap-1.5 relative">
              <span data-tour="help" data-help-toggle>
                <IconButton icon={HelpCircle} label="คีย์ลัดและทัวร์แนะนำ (?)" active={helpOpen} onClick={() => setHelpOpen((v) => !v)} />
              </span>
              {helpOpen && (
                <ShortcutHelp
                  operator={operator}
                  onClose={() => setHelpOpen(false)}
                  onTour={() => {
                    setHelpOpen(false);
                    setTourManual(true);
                  }}
                />
              )}
              <Button size="sm" icon={Camera} loading={snapping} disabled={scanning} onClick={testSnap} title="ถ่ายภาพและตรวจทันที (Space)">
                ถ่ายทดสอบ
                <kbd className="hidden sm:inline pointer-coarse:hidden px-1 rounded border border-line text-[10px] font-mono text-muted">Space</kbd>
              </Button>
            </div>
          </div>

          <div ref={viewArea} className="flex-1 min-h-0 flex flex-col items-center gap-3">
            <div className={cx("flex gap-3", fit ? (fit.row ? "flex-row" : "flex-col") : "w-full flex-col xl:flex-row")}>
              {showLive && (
                <div className="shrink-0" data-tour="live" style={fit ? { width: fit.w, height: fit.h } : { width: "100%", height: 420 }}>
                  <LiveCameraFeed
                    className="size-full"
                    zoom={scanZoom}
                    onZoomChange={scanning ? undefined : setLiveZoom}
                    stagePosition={machine?.connected ? machine.position_mm : undefined}
                    hud={hud}
                    scanning={capturing}
                    locked={scanning}
                  >
                    {!operator && !scanning && machine?.connected && (
                      <JogOverlay
                        step={motion.jogStep}
                        onStep={(jogStep) => setMotion({ jogStep })}
                        onJog={jog}
                        reason={stageReason}
                        collapsed={jogHidden}
                        onCollapsed={setJogHidden}
                      />
                    )}
                  </LiveCameraFeed>
                </div>
              )}
              {showOutput && (
                <div className="shrink-0" data-tour="output" style={fit ? { width: fit.w, height: fit.h } : { width: "100%", height: 420 }}>
                  <OutputView
                    item={output}
                    pending={pending}
                    onOpen={openOutput}
                    summaryKey={`${report?.id ?? ""}:${report?.status ?? ""}`}
                    onOpenPoint={setDetail}
                  />
                </div>
              )}
            </div>
            <div ref={dockRef} className="w-full" style={fit ? { maxWidth: Math.max(fit.total, 480) } : undefined}>
              <ScanDock
                points={points}
                report={report}
                scanningIndex={scanningIndex}
                activeIndex={output?.kind === "point" ? output.point.point_index : null}
                selected={selected}
                ratio={ratio}
                onStop={stopScan}
                onPickResult={(pt) => {
                  setOutput({ kind: "point", point: pt });
                  if (viewMode === "live") setViewMode("split");
                }}
                onPickPoint={(i) => {
                  setSelected(i);
                  setLiveZoom(points[i]?.zoom || 1);
                  if (!operator) setTab("points");
                }}
                actions={
                  operator
                    ? null
                    : {
                        boardName: board?.name ?? null,
                        onStart: startPointScan,
                        onTeachAll: teachAll,
                        startReason,
                        teachReason: stageReason,
                        teachProgress,
                        frames: params.multiframeEnabled ? params.targetFrames : null,
                      }
                }
              />
            </div>
          </div>
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
      {tourOpen && <Tour steps={operator ? OPERATOR_TOUR : ENGINEER_TOUR} onClose={closeTour} />}
    </div>
  );
}

/** Connected but not homed: the HOME button right where the operator is looking. */
function HomeFirst({ onHome, disabled }: { onHome: () => void; disabled: boolean }) {
  return (
    <div className="rounded-lg border border-review/50 bg-review-soft p-3 flex items-center gap-3">
      <p className="flex-1 text-xs text-text">
        <span className="block text-sm font-semibold text-review">สเตจยังไม่ HOME</span>
        ต้องหาจุดศูนย์ก่อนจ๊อกหรือมาร์คจุด (กด H ได้)
      </p>
      <Button size="sm" variant="primary" icon={Home} disabled={disabled} onClick={onHome}>
        HOME
      </Button>
    </div>
  );
}
