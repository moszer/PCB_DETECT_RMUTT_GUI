"use client";

import React, { useEffect, useRef, useState } from "react";
import { Camera, PenSquare, Play, Save, Square, Trash2 } from "lucide-react";
import {
  boardComplete,
  inspectFrame,
  newRound,
  slotStatus,
  validateReference,
  type ExpectedComponent,
  type InspectionFrame,
  type InspectionRound,
} from "@/lib/board-inspection";
import { captureInspection } from "@/lib/capture-inspection";
import { api, errorMessage } from "@/lib/api";
import { CAMERA_PRESETS, presetForCamera } from "@/lib/format";
import { sfx } from "@/lib/sound";
import type { CustomPointRequest } from "@/types";
import type { InspectionParams } from "@/lib/params";
import { Badge, Button, Checkbox, EmptyState, SectionLabel, Select, TextInput, cx } from "./ui";

interface Props {
  point: CustomPointRequest;
  params: InspectionParams;
  onSave: (image: string, items: ExpectedComponent[]) => void;
  onMoveToPoint?: () => Promise<void>;
}

type View = "reference" | number;

/**
 * Teach and verify the golden components of one marked point: capture a reference
 * frame, review/edit the detected boxes, then dry-run an N-frame completeness check.
 */
export default function BoardInspection({ point, params, onSave, onMoveToPoint }: Props) {
  // Stored previews are downscaled, so their capture resolution is unknown (0) and the
  // resolution guard only applies to references captured in this session.
  // The parent remounts this component (key) when a different point is edited.
  const [reference, setReference] = useState<InspectionFrame | null>(() =>
    point.reference_image ? { id: 0, capturedAt: 0, context: "live_camera", width: 0, height: 0, image: point.reference_image, boxes: [] } : null
  );
  const [items, setItems] = useState<ExpectedComponent[]>(point.expected_components ?? []);
  const [confirmed, setConfirmed] = useState(false);
  const [aligned, setAligned] = useState(false);
  const [round, setRound] = useState<InspectionRound | null>(null);
  const [view, setView] = useState<View>("reference");
  const [selected, setSelected] = useState(0);
  const [drawing, setDrawing] = useState(false);
  const [busy, setBusy] = useState<"capture" | "run" | "camera" | null>(null);
  const [presetId, setPresetId] = useState<string>("");
  const [message, setMessage] = useState<{ tone: "info" | "pass" | "fail"; text: string } | null>(null);
  const abort = useRef<AbortController | null>(null);
  const dragStart = useRef<[number, number] | null>(null);

  const targetFrames = params.targetFrames;
  const passThreshold = Math.max(1, Math.ceil(targetFrames * params.passRatio));
  const running = busy === "run";

  useEffect(() => () => abort.current?.abort(), []);

  // Show the camera's current capture size in the selector.
  useEffect(() => {
    api
      .listCameras()
      .then((res) => setPresetId(presetForCamera(res)?.id ?? ""))
      .catch(() => undefined);
  }, []);

  const changeCapture = async (id: string) => {
    const preset = CAMERA_PRESETS.find((p) => p.id === id);
    if (!preset || busy) return;
    setBusy("camera");
    try {
      const cams = await api.listCameras();
      await api.startCamera(cams.current_index, preset.width, preset.height, preset.output, preset.mode);
      setPresetId(id);
      // A different frame size/crop changes the framing, so the taught boxes no longer line up.
      setConfirmed(false);
      setAligned(false);
      setRound(null);
      setMessage({ tone: "info", text: "เปลี่ยนขนาดภาพแล้ว — กด “ถ่ายต้นแบบใหม่” เพื่อสอนต้นแบบที่ขนาดนี้" });
    } catch (err) {
      setMessage({ tone: "fail", text: errorMessage(err) });
    } finally {
      setBusy(null);
    }
  };

  const edit = (next: ExpectedComponent[]) => {
    setItems(next);
    setConfirmed(false);
    setRound(null);
  };

  const withAbort = async (kind: "capture" | "run", task: (signal: AbortSignal) => Promise<void>) => {
    if (abort.current) return;
    const controller = new AbortController();
    abort.current = controller;
    setBusy(kind);
    try {
      await task(controller.signal);
    } catch (err) {
      if (!controller.signal.aborted) setMessage({ tone: "fail", text: errorMessage(err) });
    } finally {
      if (abort.current === controller) {
        abort.current = null;
        setBusy(null);
      }
    }
  };

  const capture = () =>
    withAbort("capture", async (signal) => {
      setMessage({ tone: "info", text: "กำลังถ่ายภาพและตรวจหาชิ้นส่วน…" });
      if (onMoveToPoint) {
        await onMoveToPoint();
        await new Promise((r) => setTimeout(r, 600));
      }
      signal.throwIfAborted();
      sfx.shutter();
      const captured = await captureInspection(point.zoom || 1, params.conf, params.imgsz, signal);
      sfx.ding();
      setReference(captured.frame);
      setItems(captured.items);
      setConfirmed(false);
      setAligned(true);
      setRound(null);
      setView("reference");
      setSelected(0);
      setMessage({ tone: "info", text: `พบชิ้นส่วน ${captured.items.length} ตำแหน่ง — ตรวจทานกับบอร์ดจริง/BOM แล้วยืนยัน` });
    });

  const run = () =>
    withAbort("run", async (signal) => {
      if (!reference) return;
      let current = newRound(items.length, Date.now(), targetFrames, passThreshold);
      setRound(current);
      setView("reference");
      setMessage(null);
      if (onMoveToPoint) {
        setMessage({ tone: "info", text: "กำลังเคลื่อนสเตจไปยังจุดนี้…" });
        await onMoveToPoint();
        await new Promise((r) => setTimeout(r, 600));
        signal.throwIfAborted();
      }
      let lastTimestamp = -1;
      sfx.start();
      for (let i = 0; i < targetFrames; i++) {
        const captured = await captureInspection(point.zoom || 1, params.conf, params.imgsz, signal);
        if (captured.timestamp <= lastTimestamp) throw new Error("กล้องส่งเฟรมเดิมซ้ำ รอบตรวจไม่สมบูรณ์");
        if (captured.simulation) throw new Error("กล้องอยู่ในโหมดจำลอง จึงยืนยันความครบของบอร์ดจริงไม่ได้");
        if (reference.width && (captured.frame.width !== reference.width || captured.frame.height !== reference.height)) {
          throw new Error("ความละเอียดกล้องเปลี่ยน กรุณาถ่ายต้นแบบใหม่");
        }
        lastTimestamp = captured.timestamp;
        current = inspectFrame(current, items, captured.frame, "live_camera", params.conf);
        sfx.tick();
        setRound(current);
        await new Promise((r) => setTimeout(r, 80));
      }
      sfx.verdict(boardComplete(current) ? "PASS" : "FAIL");
      setMessage(
        boardComplete(current)
          ? { tone: "pass", text: `ครบทุกตำแหน่ง (${items.length}/${items.length}) ใน ${targetFrames} เฟรม` }
          : { tone: "fail", text: `มีตำแหน่งที่พบน้อยกว่าเกณฑ์ ${passThreshold}/${targetFrames} เฟรม` }
      );
    });

  const stop = () => {
    abort.current?.abort();
    abort.current = null;
    setBusy(null);
    setRound((r) => (r ? { ...r, status: "cancelled" } : r));
    setMessage({ tone: "info", text: "หยุดรอบตรวจแล้ว — ยังสรุปผลไม่ได้" });
  };

  const normPoint = (e: React.PointerEvent<SVGSVGElement>): [number, number] => {
    const r = e.currentTarget.getBoundingClientRect();
    return [Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)), Math.max(0, Math.min(1, (e.clientY - r.top) / r.height))];
  };

  const valid = validateReference(items);
  const dirty =
    JSON.stringify(items) !== JSON.stringify(point.expected_components ?? []) || (reference?.image ?? null) !== (point.reference_image ?? null);
  const frameRec = typeof view === "number" ? round?.capturedFrames?.[view] : undefined;
  const shownImage = frameRec?.image || reference?.image;

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
      {/* ── Image + overlay ── */}
      <div className="flex flex-col gap-3 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <Select
            aria-label="ขนาดภาพที่ถ่าย"
            title="ขนาดภาพที่ถ่าย"
            className="w-auto! h-9! text-xs"
            value={presetId}
            disabled={!!busy}
            onChange={(e) => changeCapture(e.target.value)}
          >
            {!presetId && <option value="">ขนาดภาพที่ถ่าย…</option>}
            {CAMERA_PRESETS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </Select>
          <Button variant={reference ? "secondary" : "primary"} icon={Camera} loading={busy === "capture"} disabled={running} onClick={capture}>
            {reference ? "ถ่ายต้นแบบใหม่" : "ถ่ายต้นแบบจากบอร์ดที่ครบ"}
          </Button>
          {reference && (
            <Button variant={drawing ? "primary" : "ghost"} icon={PenSquare} disabled={running || view !== "reference"} onClick={() => setDrawing((d) => !d)}>
              {drawing ? "ลากบนภาพเพื่อวาดกรอบ" : "เพิ่มกรอบที่ตกหล่น"}
            </Button>
          )}
        </div>

        {shownImage ? (
          <div className="relative rounded-xl overflow-hidden bg-viewport border border-line">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={shownImage} alt="ภาพต้นแบบของจุดตรวจ" className="w-full block select-none" draggable={false} />
            <svg
              viewBox="0 0 1000 1000"
              preserveAspectRatio="none"
              className={cx("absolute inset-0 size-full touch-none", drawing ? "cursor-crosshair" : "cursor-pointer")}
              onPointerDown={(e) => {
                if (!drawing || running) return;
                dragStart.current = normPoint(e);
                e.currentTarget.setPointerCapture(e.pointerId);
              }}
              onPointerUp={(e) => {
                const start = dragStart.current;
                dragStart.current = null;
                if (!start || !drawing) return;
                const end = normPoint(e);
                if (Math.abs(start[0] - end[0]) < 0.004 || Math.abs(start[1] - end[1]) < 0.004) return;
                let n = items.length + 1;
                while (items.some((i) => i.id === `P${n}`)) n++;
                edit([
                  ...items,
                  {
                    id: `P${n}`,
                    name: items[selected]?.name ?? "component",
                    bbox: [Math.min(start[0], end[0]), Math.min(start[1], end[1]), Math.max(start[0], end[0]), Math.max(start[1], end[1])],
                  },
                ]);
                setSelected(items.length);
                setDrawing(false);
              }}
            >
              {items.map((item, i) => {
                const matched = frameRec ? frameRec.matchedIndices.includes(i) : null;
                const isSel = i === selected;
                const color = matched === null ? (isSel ? "#f59e0b" : "#22d3ee") : matched ? "#22c55e" : "#ef4444";
                const [x1, y1, x2, y2] = item.bbox.map((v) => v * 1000);
                return (
                  <g key={i} onClick={() => !drawing && setSelected(i)}>
                    <rect
                      x={x1}
                      y={y1}
                      width={x2 - x1}
                      height={y2 - y1}
                      fill={color}
                      fillOpacity={isSel ? 0.22 : 0.08}
                      stroke={color}
                      strokeWidth={isSel ? 4 : 2.5}
                      strokeDasharray={matched === false ? "8 5" : undefined}
                      vectorEffect="non-scaling-stroke"
                    />
                    <rect x={x1} y={Math.max(0, y1 - 22)} width={item.id.length * 11 + 12} height={20} fill={color} rx={2} />
                    <text x={x1 + 5} y={Math.max(15, y1 - 7)} fontSize={13} fontWeight={700} fill="#000" fontFamily="ui-monospace, monospace">
                      {item.id}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>
        ) : items.length ? (
          <EmptyState icon={Camera} title="ไม่มีภาพต้นแบบในเครื่องนี้" className="rounded-xl border border-dashed border-line">
            ต้นแบบ {items.length} ตำแหน่งยังใช้สแกนได้ แต่ต้องถ่ายภาพใหม่หากต้องการแก้ไขกรอบ
          </EmptyState>
        ) : (
          <EmptyState icon={Camera} title="จุดนี้ยังไม่มีต้นแบบ" className="rounded-xl border border-dashed border-line">
            วางบอร์ดที่ประกอบครบแล้วกด “ถ่ายต้นแบบจากบอร์ดที่ครบ” ระบบจะตรวจหาชิ้นส่วนให้อัตโนมัติ
          </EmptyState>
        )}

        {round && (
          <div className="flex items-center gap-1 overflow-x-auto pb-1">
            <FrameChip active={view === "reference"} onClick={() => setView("reference")}>
              ต้นแบบ
            </FrameChip>
            {Array.from({ length: round.targetFrames ?? targetFrames }).map((_, i) => {
              const rec = round.capturedFrames?.[i];
              const missed = rec ? rec.unmatchedIndices.length : 0;
              return (
                <FrameChip key={`${i}:${rec ? 1 : 0}`} popped={!!rec} active={view === i} disabled={!rec} tone={!rec ? undefined : missed === 0 ? "pass" : missed <= 2 ? "review" : "fail"} onClick={() => setView(i)}>
                  F{i + 1}
                </FrameChip>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Component list + actions ── */}
      <div className="flex flex-col gap-4 min-w-0">
        <div className="flex items-center justify-between">
          <SectionLabel>ชิ้นส่วนต้นแบบ ({items.length})</SectionLabel>
          {!valid && items.length > 0 ? (
            <Badge tone="fail">รหัสซ้ำหรือชื่อว่าง</Badge>
          ) : (
            dirty && <Badge tone="review">ยังไม่ได้บันทึก</Badge>
          )}
        </div>
        <ul className="rounded-lg border border-line divide-y divide-line max-h-72 overflow-y-auto">
          {items.map((item, i) => {
            const hits = round?.hits[i] ?? 0;
            const status = round?.status === "complete" ? slotStatus(hits, targetFrames, passThreshold) : null;
            return (
              <li key={i} className={cx("flex items-center gap-1.5 p-1.5", i === selected && "bg-accent-soft")} onClick={() => setSelected(i)}>
                <TextInput
                  aria-label={`รหัสตำแหน่ง ${i + 1}`}
                  className="w-16! h-8! font-mono text-xs"
                  value={item.id}
                  disabled={running}
                  onChange={(e) => edit(items.map((v, j) => (j === i ? { ...v, id: e.target.value } : v)))}
                />
                <TextInput
                  aria-label={`คลาสตำแหน่ง ${i + 1}`}
                  className="h-8! text-xs flex-1"
                  value={item.name}
                  disabled={running}
                  onChange={(e) => edit(items.map((v, j) => (j === i ? { ...v, name: e.target.value } : v)))}
                />
                {round && (
                  <span
                    key={`${round.frames}:${status}`}
                    className={cx(
                      "font-mono tabular text-[11px] w-10 text-right",
                      status ? "animate-pop" : undefined,
                      status === "confirmed" ? "text-pass" : status ? "text-fail" : "text-muted"
                    )}
                  >
                    {hits}/{round.frames}
                  </span>
                )}
                <button
                  type="button"
                  aria-label={`ลบตำแหน่ง ${i + 1}`}
                  disabled={running}
                  onClick={(e) => {
                    e.stopPropagation();
                    edit(items.filter((_, j) => j !== i));
                  }}
                  className="size-8 grid place-items-center rounded-md text-subtle hover:text-fail hover:bg-fail-soft cursor-pointer"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </li>
            );
          })}
          {!items.length && <li className="p-4 text-center text-xs text-muted">ยังไม่มีชิ้นส่วน</li>}
        </ul>
        <p className="text-[11px] text-subtle -mt-2">ชื่อคลาสต้องตรงกับชื่อในโมเดล (เช่น resistor, capacitor) · ตั้งรหัสเป็น R1, C3 ตามบอร์ดได้</p>

        <div className="flex flex-col gap-2.5 rounded-lg bg-surface-2 p-3">
          <Checkbox checked={confirmed} onChange={setConfirmed} disabled={running || !valid || !reference}>
            ตรวจเทียบบอร์ดจริง/BOM แล้ว ต้นแบบครบทุกตำแหน่งและคลาสถูกต้อง
          </Checkbox>
          <Checkbox checked={aligned} onChange={setAligned} disabled={running}>
            บอร์ดที่จะทดสอบวางตรงกับต้นแบบ ภาพชัด ไม่มีสิ่งบัง
          </Checkbox>
        </div>

        <div className="flex flex-col gap-2">
          <Button variant="success" icon={Save} disabled={!valid || !!busy || !dirty} onClick={() => onSave(reference?.image ?? point.reference_image ?? "", items)}>
            {dirty ? "บันทึกต้นแบบของจุดนี้" : "บันทึกแล้ว"}
          </Button>
          {running ? (
            <Button variant="secondary" icon={Square} onClick={stop}>
              หยุดทดสอบ ({round?.frames ?? 0}/{targetFrames})
            </Button>
          ) : (
            <Button variant="secondary" icon={Play} disabled={!confirmed || !aligned || !valid || !reference || !!busy} onClick={run}>
              ทดสอบตรวจ {targetFrames} เฟรม (ผ่าน ≥ {passThreshold})
            </Button>
          )}
        </div>

        {message && (
          <p
            role="status"
            className={cx(
              "text-sm rounded-lg px-3 py-2",
              message.tone === "pass" ? "bg-pass-soft text-pass" : message.tone === "fail" ? "bg-fail-soft text-fail" : "bg-surface-2 text-muted"
            )}
          >
            {message.text}
          </p>
        )}
      </div>
    </div>
  );
}

function FrameChip({
  active,
  popped,
  disabled,
  tone,
  onClick,
  children,
}: {
  active: boolean;
  /** Animate in (the frame was just captured). */
  popped?: boolean;
  disabled?: boolean;
  tone?: "pass" | "review" | "fail";
  onClick: () => void;
  children: React.ReactNode;
}) {
  const toneClass = tone ? { pass: "text-pass", review: "text-review", fail: "text-fail" }[tone] : "text-subtle";
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cx(
        "h-7 px-2.5 rounded-md text-xs font-mono shrink-0 border cursor-pointer disabled:cursor-not-allowed disabled:opacity-40",
        popped && "animate-pop",
        active ? "bg-accent text-on-accent border-transparent" : cx("bg-surface border-line", toneClass)
      )}
    >
      {children}
    </button>
  );
}
