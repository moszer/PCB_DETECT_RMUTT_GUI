"use client";

import React, { useEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Camera,
  CheckCircle2,
  Database,
  Download,
  FolderOpen,
  Home,
  ImageIcon,
  Navigation,
  Play,
  Square,
  Trash2,
  X,
} from "lucide-react";
import type { Dataset, DatasetImage, DatasetProgressEvent, DatasetSummary, SystemStatus } from "@/types";
import { api, datasetApi } from "@/lib/api";
import { formatDateTime, formatMm, percent } from "@/lib/format";
import type { InspectionParams } from "@/lib/params";
import { usePersistentState } from "@/hooks/usePersistentState";
import { LiveCameraFeed, type FeedHud } from "../LiveCameraFeed";
import { StageBar } from "../aoi/StageBar";
import { DEFAULT_MOTION, PathPreview, type MotionSettings } from "../aoi/panels";
import { Badge, Button, Card, EmptyState, Field, NumberInput, SectionLabel, Segmented, Select, Spinner, TextInput, Toggle, buttonClasses, cx } from "../ui";
import { useToast } from "../Toast";
import { LabelEditor } from "./LabelEditor";

interface Props {
  status: SystemStatus | null;
  progress: DatasetProgressEvent | null;
  params: InspectionParams;
  onRefreshStatus: () => void;
}

type Corner = [number, number] | null;

interface CaptureSetup {
  name: string;
  corners: Corner[];
  pitchX: number;
  pitchY: number;
  autoLabel: boolean;
}

const DEFAULT_SETUP: CaptureSetup = { name: "", corners: [null, null, null, null], pitchX: 5, pitchY: 5, autoLabel: true };
const MAX_IMAGES = 400;

/** Mirror of plan_board_points() in backend/app/services/dataset_service.py (preview only). */
function planPreview(corners: Array<[number, number]>, pitchX: number, pitchY: number) {
  const xs = corners.map((c) => c[0]);
  const ys = corners.map((c) => c[1]);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const cols = Math.max(1, Math.ceil((maxX - minX) / pitchX) + 1);
  const rows = Math.max(1, Math.ceil((maxY - minY) / pitchY) + 1);
  const stepX = cols > 1 ? (maxX - minX) / (cols - 1) : 0;
  const stepY = rows > 1 ? (maxY - minY) / (rows - 1) : 0;
  const path: Array<[number, number]> = [];
  if (cols * rows <= MAX_IMAGES) {
    for (let r = 0; r < rows; r++)
      for (let i = 0; i < cols; i++) {
        const c = r % 2 === 0 ? i : cols - 1 - i;
        path.push([minX + c * stepX, minY + r * stepY]);
      }
  }
  return { cols, rows, stepX, stepY, path, size: [maxX - minX, maxY - minY] as const };
}

export function DatasetView({ status, progress, params, onRefreshStatus }: Props) {
  const [mode, setMode] = useState<"capture" | "library">("capture");
  const [openId, setOpenId] = useState<string | null>(null);
  const running = progress?.dataset.status === "capturing";

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-3 px-4 py-2.5 border-b border-line bg-surface flex-wrap">
        <Segmented
          value={mode}
          onChange={setMode}
          options={[
            { value: "capture", label: "ถ่ายชุดข้อมูล", icon: Camera },
            { value: "library", label: "ชุดข้อมูล & label", icon: Database },
          ]}
        />
        <p className="text-xs text-muted hidden md:block">
          {mode === "capture"
            ? "เล็งเป้ากลางภาพไปที่มุมบอร์ดทีละมุมแล้วกดมาร์คให้ครบ 4 มุม ระบบจะถ่ายทั่วทั้งบอร์ดอัตโนมัติ"
            : "ตรวจและแก้ label แล้วดาวน์โหลดเป็นชุดข้อมูล YOLO สำหรับเทรนต่อ"}
        </p>
      </div>
      <div className="flex-1 min-h-0">
        {mode === "capture" ? (
          <CaptureMode
            status={status}
            progress={progress}
            running={running}
            params={params}
            onRefreshStatus={onRefreshStatus}
            onOpen={(id) => {
              setOpenId(id);
              setMode("library");
            }}
          />
        ) : (
          <LibraryMode progress={progress} openId={openId} onOpenId={setOpenId} />
        )}
      </div>
    </div>
  );
}

/* ── Capture ─────────────────────────────────────────────── */

function CaptureMode({
  status,
  progress,
  running,
  params,
  onRefreshStatus,
  onOpen,
}: {
  status: SystemStatus | null;
  progress: DatasetProgressEvent | null;
  running: boolean;
  params: InspectionParams;
  onRefreshStatus: () => void;
  onOpen: (id: string) => void;
}) {
  const toast = useToast();
  const machine = status?.machine ?? null;
  const canMove = Boolean(machine?.connected && machine.homed) && !running;
  const [setup, setSetupState] = usePersistentState<CaptureSetup>("pcb_dataset_setup", DEFAULT_SETUP, { merge: true });
  const [motion, setMotionState] = usePersistentState<MotionSettings>("pcb_aoi_motion", DEFAULT_MOTION, { merge: true });
  const setSetup = (s: Partial<CaptureSetup>) => setSetupState((v) => ({ ...v, ...s }));
  const [starting, setStarting] = useState(false);
  const [recent, setRecent] = useState<{ id: string; images: DatasetImage[] } | null>(null);

  const marked = setup.corners.filter((c): c is [number, number] => !!c);
  const plan = marked.length === 4 ? planPreview(marked, setup.pitchX, setup.pitchY) : null;
  const tooMany = plan ? plan.cols * plan.rows > MAX_IMAGES : false;

  // Thumbnails of the frames captured so far in the active/last job.
  const capturedKey = progress ? `${progress.dataset.id}:${progress.dataset.captured}:${progress.event}` : null;
  useEffect(() => {
    if (!progress || !capturedKey) return;
    let current = true;
    datasetApi
      .get(progress.dataset.id)
      .then((d) => current && setRecent({ id: d.id, images: d.images }))
      .catch(() => undefined);
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [capturedKey]);

  const markCorner = (i: number) => {
    if (!machine) return;
    const corners = [...setup.corners];
    corners[i] = [Number(machine.position_mm[0].toFixed(2)), Number(machine.position_mm[1].toFixed(2))];
    setSetup({ corners });
  };

  const moveTo = async (c: [number, number]) => {
    try {
      await api.moveToPosition(c[0], c[1], motion.speed);
      onRefreshStatus();
    } catch (err) {
      toast.error("เคลื่อนที่ไม่สำเร็จ", err);
    }
  };

  const jog = async (dx: number, dy: number) => {
    try {
      await api.jogMachine(dx, dy, motion.speed);
      onRefreshStatus();
    } catch (err) {
      toast.error("จ๊อกไม่สำเร็จ", err);
    }
  };

  const start = async () => {
    if (marked.length !== 4) return;
    setStarting(true);
    try {
      await datasetApi.capture({
        name: setup.name,
        corners: marked,
        pitchX: setup.pitchX,
        pitchY: setup.pitchY,
        speed: motion.speed,
        settleSec: motion.settleSec,
        autoLabel: setup.autoLabel,
        conf: params.conf,
        imgsz: params.imgsz,
      });
    } catch (err) {
      toast.error("เริ่มถ่ายไม่สำเร็จ", err);
    } finally {
      setStarting(false);
    }
  };

  const stop = async () => {
    try {
      await datasetApi.stop();
    } catch (err) {
      toast.error("หยุดไม่สำเร็จ", err);
    }
  };

  const s = motion.jogStep;
  const pad =
    "size-11 rounded-lg border border-line bg-surface-2 grid place-items-center hover:bg-surface-3 active:scale-95 transition cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed";

  let hud: FeedHud | null = null;
  if (running && progress) {
    hud = {
      tone: "accent",
      title: progress.event === "moving" ? "กำลังเคลื่อนไปตำแหน่งถัดไป" : "ถ่ายภาพชุดข้อมูล",
      detail: `ภาพ ${progress.dataset.captured}/${progress.dataset.planned}${progress.target_mm ? ` · ${formatMm(progress.target_mm[0])}, ${formatMm(progress.target_mm[1])} mm` : ""}`,
    };
  }
  const flashKey = progress?.event === "captured" ? `${progress.dataset.id}:${progress.dataset.captured}` : null;

  return (
    <div className="h-full flex flex-col">
      <StageBar machine={machine} scanning={running} onChange={onRefreshStatus} />
      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[360px_minmax(0,1fr)] overflow-y-auto lg:overflow-hidden">
        <aside className="border-b lg:border-b-0 lg:border-r border-line bg-surface lg:overflow-y-auto p-4 flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <SectionLabel>1 · เล็งเป้าไปที่มุมบอร์ด</SectionLabel>
            <div className="flex items-center gap-3">
              <div className="grid grid-cols-3 gap-1.5 w-fit" aria-label="ปุ่มจ๊อก">
                <span />
                <button type="button" className={pad} disabled={!canMove} onClick={() => jog(0, s)} aria-label="Y+">
                  <ArrowUp className="size-4" />
                </button>
                <span />
                <button type="button" className={pad} disabled={!canMove} onClick={() => jog(-s, 0)} aria-label="X-">
                  <ArrowLeft className="size-4" />
                </button>
                <button
                  type="button"
                  className={cx(pad, "bg-accent-soft text-accent")}
                  disabled={running || !machine?.connected}
                  onClick={() => api.homeMachine().then(onRefreshStatus).catch((err) => toast.error("HOME ไม่สำเร็จ", err))}
                  aria-label="HOME"
                >
                  <Home className="size-4" />
                </button>
                <button type="button" className={pad} disabled={!canMove} onClick={() => jog(s, 0)} aria-label="X+">
                  <ArrowRight className="size-4" />
                </button>
                <span />
                <button type="button" className={pad} disabled={!canMove} onClick={() => jog(0, -s)} aria-label="Y-">
                  <ArrowDown className="size-4" />
                </button>
                <span />
              </div>
              <div className="flex-1 flex flex-col gap-1.5">
                <span className="text-[11px] text-muted">ระยะต่อครั้ง (mm)</span>
                <Segmented
                  size="sm"
                  className="w-full"
                  value={s}
                  onChange={(jogStep) => setMotionState((m) => ({ ...m, jogStep }))}
                  options={[0.1, 1, 5, 10].map((v) => ({ value: v, label: `${v}` }))}
                />
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <SectionLabel>2 · มาร์คมุมบอร์ด ({marked.length}/4)</SectionLabel>
              {marked.length > 0 && (
                <button type="button" disabled={running} className="text-[11px] text-fail hover:underline cursor-pointer disabled:opacity-40" onClick={() => setSetup({ corners: [null, null, null, null] })}>
                  ล้างทั้งหมด
                </button>
              )}
            </div>
            <ul className="rounded-lg border border-line divide-y divide-line">
              {setup.corners.map((c, i) => (
                <li key={i} className={cx("flex items-center gap-2 px-2.5 py-2", c && "animate-fade")}>
                  <span className={cx("size-6 rounded-md grid place-items-center text-[11px] font-mono font-semibold shrink-0", c ? "bg-pass text-white" : "bg-surface-3 text-muted")}>
                    {c ? <CheckCircle2 className="size-3.5" /> : i + 1}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm">มุม {i + 1}</div>
                    <div className="text-[11px] font-mono tabular text-muted">{c ? `${formatMm(c[0])}, ${formatMm(c[1])} mm` : "ยังไม่มาร์ค"}</div>
                  </div>
                  {c && (
                    <Button size="sm" variant="ghost" icon={Navigation} disabled={!canMove} onClick={() => moveTo(c)} title="ไปที่มุมนี้" />
                  )}
                  {c && (
                    <Button
                      size="sm"
                      variant="ghost"
                      icon={X}
                      disabled={running}
                      title="ลบมุมนี้"
                      onClick={() => setSetup({ corners: setup.corners.map((v, j) => (j === i ? null : v)) })}
                    />
                  )}
                  <Button size="sm" variant={c ? "secondary" : "primary"} disabled={!machine?.homed || running} onClick={() => markCorner(i)}>
                    {c ? "มาร์คใหม่" : "มาร์ค"}
                  </Button>
                </li>
              ))}
            </ul>
            <p className="text-[11px] text-subtle">จ๊อกจนเป้ากลางภาพทับมุมบอร์ด แล้วกด “มาร์ค” · ลำดับมุมใดก็ได้</p>
          </div>

          <div className="flex flex-col gap-3">
            <SectionLabel>3 · ตั้งค่าการถ่าย</SectionLabel>
            <Field label="ชื่อชุดข้อมูล" htmlFor="ds-name">
              <TextInput id="ds-name" placeholder="เช่น บอร์ด ASTRON รุ่น A" value={setup.name} disabled={running} onChange={(e) => setSetup({ name: e.target.value })} />
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="ระยะห่างภาพ X" hint="ควรเล็กกว่าความกว้างภาพเพื่อให้ภาพซ้อนกัน">
                <NumberInput value={setup.pitchX} min={0.5} max={100} step={0.5} suffix="mm" disabled={running} onChange={(pitchX) => setSetup({ pitchX })} />
              </Field>
              <Field label="ระยะห่างภาพ Y">
                <NumberInput value={setup.pitchY} min={0.5} max={100} step={0.5} suffix="mm" disabled={running} onChange={(pitchY) => setSetup({ pitchY })} />
              </Field>
              <Field label="เวลานิ่งก่อนถ่าย">
                <NumberInput value={motion.settleSec} min={0} max={10} step={0.1} suffix="s" disabled={running} onChange={(settleSec) => setMotionState((m) => ({ ...m, settleSec }))} />
              </Field>
              <Field label="ความเร็ว (step/s)">
                <NumberInput value={motion.speed} min={20} max={1500} step={50} disabled={running} onChange={(speed) => setMotionState((m) => ({ ...m, speed }))} />
              </Field>
            </div>
            <Toggle
              label="ใส่ label อัตโนมัติด้วยโมเดล"
              description={`ใช้โมเดลปัจจุบันตีกรอบให้ก่อน (ความมั่นใจ ≥ ${percent(params.conf)}, imgsz ${params.imgsz}) แล้วค่อยแก้ทีหลัง`}
              checked={setup.autoLabel}
              disabled={running}
              onChange={(autoLabel) => setSetup({ autoLabel })}
            />
            {plan && (
              <div className="flex flex-col gap-1.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted">
                    บอร์ด {plan.size[0].toFixed(1)} × {plan.size[1].toFixed(1)} mm
                  </span>
                  <span className={cx("font-semibold", tooMany ? "text-fail" : "text-text")}>
                    {plan.cols} × {plan.rows} = {plan.cols * plan.rows} ภาพ
                  </span>
                </div>
                <PathPreview path={plan.path} limits={machine?.soft_limits_mm ?? [38, 38]} outline={marked} />
                {tooMany && <p className="text-xs text-fail">เกิน {MAX_IMAGES} ภาพ — เพิ่มระยะห่างภาพ</p>}
              </div>
            )}
          </div>

          <div className="mt-auto flex flex-col gap-2">
            {running ? (
              <Button variant="danger" size="lg" icon={Square} onClick={stop}>
                หยุดถ่าย ({progress?.dataset.captured}/{progress?.dataset.planned})
              </Button>
            ) : (
              <Button variant="primary" size="lg" icon={Play} loading={starting} disabled={!plan || tooMany || !canMove} onClick={start}>
                {plan ? `เริ่มถ่ายอัตโนมัติ ${plan.cols * plan.rows} ภาพ` : "มาร์คให้ครบ 4 มุมก่อน"}
              </Button>
            )}
            {!machine?.homed && <p className="text-xs text-review text-center">เชื่อมต่อและ HOME สเตจก่อน</p>}
          </div>
        </aside>

        <section className="min-h-[520px] lg:min-h-0 p-3 flex flex-col gap-3">
          {progress && <CaptureProgress progress={progress} running={running} onOpen={() => onOpen(progress.dataset.id)} />}
          <LiveCameraFeed
            className="flex-1 min-h-[300px]"
            stagePosition={machine?.connected ? machine.position_mm : undefined}
            hud={hud}
            flashKey={flashKey}
            scanning={running}
            locked={running}
          />
          {recent && recent.images.length > 0 && progress?.dataset.id === recent.id && (
            <div className="flex gap-2 overflow-x-auto pb-1 shrink-0">
              {recent.images.slice(-30).map((img) => (
                <div key={img.file} className="relative h-16 aspect-video shrink-0 rounded-md overflow-hidden bg-viewport animate-rise">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={datasetApi.imageUrl(recent.id, img.file)} alt={img.file} className="size-full object-cover" loading="lazy" />
                  <span className="absolute bottom-0 inset-x-0 bg-black/60 text-[9px] text-white px-1 truncate">
                    {img.file.replace(".jpg", "")} · {img.boxes} กรอบ
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function CaptureProgress({ progress, running, onOpen }: { progress: DatasetProgressEvent; running: boolean; onOpen: () => void }) {
  const d = progress.dataset;
  const ratio = d.planned ? d.captured / d.planned : 0;
  const tone = d.status === "complete" ? "pass" : d.status === "capturing" ? "accent" : d.status === "aborted" ? "review" : "fail";
  const label = { capturing: "กำลังถ่าย", complete: "ถ่ายครบแล้ว", aborted: "หยุดแล้ว", error: "ผิดพลาด" }[d.status];
  return (
    <div className="rounded-xl border border-line bg-surface px-3.5 py-2.5 flex flex-col gap-2 shrink-0">
      <div className="flex items-center gap-2 flex-wrap text-sm">
        <Badge tone={tone}>{label}</Badge>
        <span className="font-medium truncate">{d.name}</span>
        <span className="font-mono tabular text-xs text-muted">
          {d.captured}/{d.planned} ภาพ
        </span>
        {!running && d.captured > 0 && (
          <Button size="sm" className="ml-auto" icon={FolderOpen} onClick={onOpen}>
            เปิดเพื่อแก้ label
          </Button>
        )}
      </div>
      <div className="h-1.5 rounded-full bg-surface-3 overflow-hidden">
        <div
          className={cx("h-full transition-all duration-500 ease-out", running ? "bg-accent bg-stripes animate-stripes" : d.status === "complete" ? "bg-pass" : "bg-review")}
          style={{ width: `${ratio * 100}%` }}
        />
      </div>
      {d.error && <p className="text-xs text-fail">{d.error}</p>}
    </div>
  );
}

/* ── Library ─────────────────────────────────────────────── */

function LibraryMode({ progress, openId, onOpenId }: { progress: DatasetProgressEvent | null; openId: string | null; onOpenId: (id: string | null) => void }) {
  const toast = useToast();
  const [list, setList] = useState<DatasetSummary[] | null>(null);
  const [reload, setReload] = useState(0);
  const listKey = `${reload}:${progress?.event === "captured" ? "" : progress?.event}:${progress?.dataset.id}`;

  useEffect(() => {
    datasetApi
      .list()
      .then((res) => setList(res.datasets))
      .catch((err) => toast.error("โหลดรายการชุดข้อมูลไม่สำเร็จ", err));
  }, [listKey, toast]);

  const selectedId = list?.some((d) => d.id === openId) ? openId : (list?.[0]?.id ?? null);

  return (
    <div className="h-full grid grid-cols-1 md:grid-cols-[300px_minmax(0,1fr)] overflow-y-auto md:overflow-hidden">
      <aside className="border-b md:border-b-0 md:border-r border-line bg-surface md:overflow-y-auto p-2 flex flex-col gap-1">
        {list === null && (
          <div className="p-6 grid place-items-center">
            <Spinner />
          </div>
        )}
        {list?.map((d) => (
          <button
            key={d.id}
            type="button"
            onClick={() => onOpenId(d.id)}
            className={cx("flex gap-3 items-center text-left rounded-lg p-2 transition-colors cursor-pointer", d.id === selectedId ? "bg-accent-soft" : "hover:bg-surface-2")}
          >
            <div className="h-12 aspect-video rounded-md overflow-hidden bg-viewport shrink-0">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              {d.cover && <img src={d.cover} alt="" className="size-full object-cover" loading="lazy" />}
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium truncate">{d.name}</div>
              <div className="text-[11px] text-muted">
                {d.image_count} ภาพ · {d.box_count} กรอบ
              </div>
              <div className="text-[11px] text-subtle">{formatDateTime(d.created_at)}</div>
            </div>
            {d.status !== "complete" && <Badge tone={d.status === "capturing" ? "accent" : d.status === "aborted" ? "review" : "fail"}>{d.status}</Badge>}
          </button>
        ))}
        {list && !list.length && (
          <EmptyState icon={Database} title="ยังไม่มีชุดข้อมูล">
            ไปที่ “ถ่ายชุดข้อมูล” มาร์ค 4 มุมบอร์ด แล้วเริ่มถ่าย
          </EmptyState>
        )}
      </aside>
      <section className="md:overflow-y-auto p-4 md:p-6">
        {selectedId ? (
          <DatasetDetail
            key={selectedId}
            id={selectedId}
            refreshKey={listKey}
            onDeleted={() => {
              onOpenId(null);
              setReload((r) => r + 1);
            }}
            onChanged={() => setReload((r) => r + 1)}
          />
        ) : (
          list && <EmptyState icon={ImageIcon} title="เลือกชุดข้อมูลทางซ้าย" className="h-full" />
        )}
      </section>
    </div>
  );
}

function DatasetDetail({ id, refreshKey, onDeleted, onChanged }: { id: string; refreshKey: string; onDeleted: () => void; onChanged: () => void }) {
  const toast = useToast();
  const [data, setData] = useState<Dataset | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [valRatio, setValRatio] = useState(0.2);
  const [filter, setFilter] = useState<"all" | "empty" | "model" | "manual">("all");

  useEffect(() => {
    let current = true;
    datasetApi
      .get(id)
      .then((d) => current && setData(d))
      .catch((err) => current && toast.error("โหลดชุดข้อมูลไม่สำเร็จ", err));
    return () => {
      current = false;
    };
  }, [id, refreshKey, toast]);

  const shown = useMemo(() => {
    if (!data) return [];
    return data.images.filter((img) =>
      filter === "all" ? true : filter === "empty" ? img.boxes === 0 : img.labeled_by === filter
    );
  }, [data, filter]);

  if (!data) {
    return (
      <div className="h-full grid place-items-center">
        <Spinner className="size-6" />
      </div>
    );
  }

  const boxes = data.images.reduce((n, i) => n + i.boxes, 0);
  const manual = data.images.filter((i) => i.labeled_by === "manual").length;

  const remove = async () => {
    if (!window.confirm(`ลบชุดข้อมูล “${data.name}” ทั้งหมด ${data.images.length} ภาพ? ไม่สามารถกู้คืนได้`)) return;
    try {
      await datasetApi.remove(data.id);
      toast.success("ลบชุดข้อมูลแล้ว");
      onDeleted();
    } catch (err) {
      toast.error("ลบไม่สำเร็จ", err);
    }
  };

  return (
    <div className="max-w-6xl mx-auto flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold">{data.name}</h2>
          <p className="text-xs text-muted mt-0.5">
            {formatDateTime(data.created_at)} · {data.resolution[0]}×{data.resolution[1]}px · {data.model ? `label เริ่มต้นจาก ${data.model.split(/[\\/]/).pop()}` : "ไม่ใส่ label อัตโนมัติ"}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Select className="w-auto! h-9! text-xs" value={valRatio} onChange={(e) => setValRatio(Number(e.target.value))} aria-label="สัดส่วน validation">
            {[0, 0.1, 0.2, 0.3].map((v) => (
              <option key={v} value={v}>
                val {Math.round(v * 100)}%
              </option>
            ))}
          </Select>
          <a href={datasetApi.downloadUrl(data.id, valRatio)} className={buttonClasses("primary", "md")} download>
            <Download className="size-4" />
            ดาวน์โหลด YOLO (.zip)
          </a>
          <Button variant="ghost" icon={Trash2} className="text-fail" onClick={remove} disabled={data.status === "capturing"}>
            ลบ
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Card className="px-3 py-2.5">
          <div className="text-[11px] text-muted">ภาพ</div>
          <div className="text-xl font-semibold tabular">{data.images.length}</div>
        </Card>
        <Card className="px-3 py-2.5">
          <div className="text-[11px] text-muted">กรอบทั้งหมด</div>
          <div className="text-xl font-semibold tabular">{boxes}</div>
        </Card>
        <Card className="px-3 py-2.5">
          <div className="text-[11px] text-muted">แก้ด้วยมือแล้ว</div>
          <div className="text-xl font-semibold tabular text-pass">
            {manual}/{data.images.length}
          </div>
        </Card>
        <Card className="px-3 py-2.5">
          <div className="text-[11px] text-muted">คลาส</div>
          <div className="text-xl font-semibold tabular">{data.classes.length}</div>
        </Card>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <Segmented
          size="sm"
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: `ทั้งหมด (${data.images.length})` },
            { value: "model", label: "label จากโมเดล" },
            { value: "manual", label: "แก้แล้ว" },
            { value: "empty", label: "ไม่มีกรอบ" },
          ]}
        />
        <span className="text-[11px] text-subtle">คลิกภาพเพื่อแก้ label</span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
        {shown.map((img) => (
          <button
            key={img.file}
            type="button"
            onClick={() => setEditing(data.images.indexOf(img))}
            className="text-left rounded-lg border border-line overflow-hidden hover:border-accent transition-colors cursor-pointer bg-surface animate-fade"
          >
            <div className="relative aspect-video bg-viewport">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={datasetApi.imageUrl(data.id, img.file)} alt={img.file} className="size-full object-cover" loading="lazy" />
              <span className="absolute top-1.5 right-1.5">
                <Badge tone={img.labeled_by === "manual" ? "pass" : img.boxes ? "info" : "neutral"}>
                  {img.labeled_by === "manual" ? "แก้แล้ว" : `${img.boxes} กรอบ`}
                </Badge>
              </span>
            </div>
            <div className="px-2.5 py-1.5 text-[11px] flex justify-between text-muted">
              <span className="font-mono">{img.file.replace(".jpg", "")}</span>
              <span className="font-mono tabular">
                {formatMm(img.x_mm)}, {formatMm(img.y_mm)}
              </span>
            </div>
          </button>
        ))}
      </div>
      {!shown.length && <EmptyState icon={ImageIcon} title="ไม่มีภาพในตัวกรองนี้" />}

      {editing !== null && data.images[editing] && (
        <LabelEditor
          datasetId={data.id}
          images={data.images}
          index={editing}
          classes={data.classes}
          readOnly={data.status === "capturing"}
          onIndex={setEditing}
          onClose={() => setEditing(null)}
          onSaved={(entry) => {
            setData((d) => (d ? { ...d, images: d.images.map((i) => (i.file === entry.file ? entry : i)) } : d));
            onChanged();
          }}
          onDeleted={(file) => {
            const images = data.images.filter((i) => i.file !== file);
            setData({ ...data, images });
            setEditing(images.length ? Math.min(editing, images.length - 1) : null);
            onChanged();
          }}
        />
      )}
    </div>
  );
}
