"use client";

import React, { useEffect, useState } from "react";
import { Bot, Box, ScanText } from "lucide-react";
import type { AOIPointResult, OcrResult, ResistorResult, SlotStatus } from "@/types";
import { api } from "@/lib/api";
import { classColor, formatMm, percent } from "@/lib/format";
import type { NBox } from "@/lib/labelLayout";
import { BoxOverlay, type OverlayBox } from "./BoxOverlay";
import { DepthModal, type DepthTarget } from "./DepthModal";
import { ChatPanel, type BoardContext } from "./ChatPanel";
import { Badge, Button, Modal, SectionLabel, Spinner, Stat, VerdictBadge, cx } from "./ui";
import { useToast } from "./Toast";

const SLOT_COLOR: Record<SlotStatus, string> = { confirmed: "#22c55e", uncertain: "#f59e0b", missing: "#ef4444", wrong: "#ef4444" };

const SLOT: Record<SlotStatus, { label: string; tone: "pass" | "review" | "fail" }> = {
  confirmed: { label: "ครบ", tone: "pass" },
  uncertain: { label: "ไม่แน่ใจ", tone: "review" },
  missing: { label: "ขาด", tone: "fail" },
  wrong: { label: "ผิดชนิด", tone: "fail" },
};

function countByLabel(detections: AOIPointResult["detections"]) {
  const counts = new Map<string, number>();
  detections.forEach((d) => counts.set(d.label, (counts.get(d.label) ?? 0) + 1));
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

interface Part {
  bbox: NBox;
  name: string;
  /** Class name (resistors are read from their colour bands instead of OCR). */
  kind: string;
  overlay: OverlayBox;
}

const isResistor = (p: Part | null | undefined) => !!p && p.kind.toLowerCase().includes("resistor");

/** A resistor's estimated value and the bands it was read from. */
function ResistorReading({ r }: { r: ResistorResult | "loading" | undefined }) {
  if (r === "loading" || r === undefined) {
    return (
      <span className="text-xs text-muted flex items-center gap-2">
        <Spinner className="size-3.5" /> กำลังอ่านแถบสีตัวต้านทาน…
      </span>
    );
  }
  const unsure = r.confidence < 0.5;
  return (
    <div className="flex flex-col gap-1.5 min-w-0">
      {r.text ? (
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className={cx("font-mono text-base font-semibold", unsure ? "text-review" : "text-text")}>≈ {r.text}</span>
          <span className="text-[10px] text-subtle">
            ประมาณจากแถบสี · มั่นใจ {Math.round(r.confidence * 100)}%{unsure ? " (ไม่แน่ใจ)" : ""}
            {r.alternatives.length > 0 && <> · หรืออาจเป็น {r.alternatives.join(", ")}</>}
          </span>
        </div>
      ) : (
        <span className="text-xs text-muted">อ่านค่าไม่ได้ — {r.reason || "แถบสีไม่ชัด"}</span>
      )}
      {r.bands.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap">
          {r.bands.map((b, i) => (
            <span key={i} className="inline-flex items-center gap-1 rounded border border-line bg-surface px-1.5 py-0.5 text-[11px]">
              <span className="size-3 rounded-sm border border-black/20" style={{ background: b.seen_hex }} />
              {b.name_th || "?"}
            </span>
          ))}
        </div>
      )}
      <span className="text-[10px] text-subtle">ใช้ดูประกอบเท่านั้น ไม่มีผลต่อผลตรวจ PASS/FAIL</span>
    </div>
  );
}

/** Detail of one AOI point result — shared by the live AOI screen and the history screen. */
export function PointResultModal({ point, onClose }: { point: AOIPointResult | null; onClose: () => void }) {
  if (!point) return null;
  return <PointResultDetail key={`${point.point_index}:${point.annotated_url}`} point={point} onClose={onClose} />;
}

function PointResultDetail({ point, onClose }: { point: AOIPointResult; onClose: () => void }) {
  const mf = point.multiframe_info;
  const slots = point.component_eval ?? [];
  const src = point.image_url || point.annotated_url;
  const [selected, setSelected] = useState<number | null>(null);
  const [depth, setDepth] = useState<DepthTarget | null>(null);
  const toast = useToast();
  // Text read on each part (by part index); "loading" while a request is in flight.
  const [ocr, setOcr] = useState<Record<number, OcrResult | "loading">>({});
  // Resistor values from their colour bands (by part index).
  const [res, setRes] = useState<Record<number, ResistorResult | "loading">>({});
  const [showText, setShowText] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  // Detection boxes are in pixels: normalizing them needs the image size.
  const [dims, setDims] = useState<{ src: string; w: number; h: number } | null>(null);
  useEffect(() => {
    if (slots.length) return;
    const img = new Image();
    img.onload = () => setDims({ src, w: img.naturalWidth, h: img.naturalHeight });
    img.src = src;
  }, [src, slots.length]);

  const size = dims?.src === src ? dims : null;
  const parts: Part[] = slots.length
    ? slots.map((slot) => {
        const b = (slot.box_in_frame ?? slot.expected.box ?? slot.expected.bbox ?? [0, 0, 0, 0]) as NBox;
        return {
          bbox: b,
          name: `${slot.expected.id} ${slot.expected.name}`,
          kind: slot.expected.name,
          overlay: { bbox: b, label: slot.expected.id, color: SLOT_COLOR[slot.status] ?? SLOT_COLOR.missing, dashed: slot.status === "missing" },
        };
      })
    : size
      ? point.detections.map((d) => {
          const b: NBox = [d.box[0] / size.w, d.box[1] / size.h, d.box[2] / size.w, d.box[3] / size.h];
          return { bbox: b, name: d.label, kind: d.label, overlay: { bbox: b, label: `${d.label} ${Math.round(d.conf * 100)}%`, color: classColor(d.label) } };
        })
      : [];
  const part = selected !== null ? parts[selected] : null;
  const canOcr = src.startsWith("/api/storage/");

  const boxesOf = (ids: number[]) => ids.map((i) => parts[i].bbox.map((v) => Math.min(1, Math.max(0, v))));
  const readText = async (indices: number[]) => {
    if (!canOcr) return;
    const valid = indices.filter((i) => parts[i]);
    const resistors = valid.filter((i) => isResistor(parts[i]) && res[i] === undefined);
    const todo = valid.filter((i) => !isResistor(parts[i]) && ocr[i] === undefined);
    const jobs: Promise<void>[] = [];
    if (resistors.length) {
      setRes((o) => ({ ...o, ...Object.fromEntries(resistors.map((i) => [i, "loading" as const])) }));
      jobs.push(
        api
          .readResistors(src, boxesOf(resistors))
          .then((out) => setRes((o) => ({ ...o, ...Object.fromEntries(resistors.map((i, k) => [i, out.results[k]])) })))
          .catch((err) => {
            setRes((o) => Object.fromEntries(Object.entries(o).filter(([i]) => !resistors.includes(Number(i)))));
            toast.error("อ่านค่าตัวต้านทานไม่สำเร็จ", err);
          })
      );
    }
    if (todo.length) {
      setOcr((o) => ({ ...o, ...Object.fromEntries(todo.map((i) => [i, "loading" as const])) }));
      jobs.push(
        api
          .readText(src, boxesOf(todo))
          .then((out) => setOcr((o) => ({ ...o, ...Object.fromEntries(todo.map((i, k) => [i, out.results[k]])) })))
          .catch((err) => {
            setOcr((o) => Object.fromEntries(Object.entries(o).filter(([i]) => !todo.includes(Number(i)))));
            toast.error("อ่านตัวอักษรไม่สำเร็จ", err);
          })
      );
    }
    await Promise.all(jobs);
  };
  const choose = (i: number | null) => {
    setSelected(i);
    if (i !== null) readText([i]);
  };
  const readAll = async () => {
    setShowText(true);
    await readText(parts.map((_, i) => i));
  };
  const textOf = (i: number) => {
    if (isResistor(parts[i])) {
      const v = res[i];
      return v && v !== "loading" && v.text ? `≈ ${v.text}` : "";
    }
    const r = ocr[i];
    return r && r !== "loading" ? r.text : "";
  };
  const reading = Object.values(ocr).some((r) => r === "loading") || Object.values(res).some((r) => r === "loading");
  const withText = parts.map((p, i) => ({ p, i, text: textOf(i) })).filter((x) => x.text);
  const overlays = parts.map((p, i) => {
    const first = textOf(i).split("\n")[0];
    return showText && first ? { ...p.overlay, label: `${p.overlay.label} · ${first}` } : p.overlay;
  });
  const selectedText = selected !== null ? ocr[selected] : undefined;
  const chatContext: BoardContext = {
    point_name: point.name || `จุด ${point.point_index + 1}`,
    verdict: point.verdict,
    reason: point.reason,
    counts: Object.fromEntries(countByLabel(point.detections)),
    parts: parts.map((p, i) => ({ name: p.name, status: slots[i] ? SLOT[slots[i].status]?.label : undefined, text: textOf(i) || undefined })),
  };
  const openDepth = () =>
    part &&
    setDepth({
      x_mm: point.x_mm,
      y_mm: point.y_mm,
      zoom: point.zoom && point.zoom > 1 ? point.zoom : 1,
      bbox: part.bbox.map((v) => Math.min(1, Math.max(0, v))) as DepthTarget["bbox"],
      name: part.name,
    });

  return (
    <>
      <Modal
        open
        onClose={depth || chatOpen ? () => undefined : onClose /* Esc closes the inner window first */}
        size="xl"
        title={
          <>
            {point.name || `จุด #${point.point_index + 1}`}
            <VerdictBadge verdict={point.verdict} />
          </>
        }
        subtitle={`ตำแหน่งสเตจ X ${formatMm(point.x_mm)} · Y ${formatMm(point.y_mm)} mm${point.zoom && point.zoom > 1 ? ` · ซูม ${point.zoom}×` : ""}`}
      >
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
          <div className="flex flex-col gap-2 min-w-0">
            <BoxOverlay src={src} alt="ภาพผลตรวจของจุดนี้" boxes={overlays} selected={selected} onSelect={choose} />
            <div className="flex items-center gap-2 flex-wrap min-h-9">
              {part ? (
                <>
                  <span className="text-sm font-medium truncate">{part.name}</span>
                  <Button size="sm" variant="primary" icon={Box} onClick={openDepth}>
                    ดูความสูง 3D
                  </Button>
                  <span className="text-[11px] text-subtle">เลื่อนสเตจไปถ่ายรอบจุดนี้หลายทิศแล้วกลับ — บอร์ดต้องอยู่ที่เดิม</span>
                </>
              ) : (
                <span className="text-xs text-muted">คลิกกรอบบนภาพ (หรือในรายการ) เพื่อเลือกชิ้น — อ่านตัวอักษร ค่าตัวต้านทาน และดูความสูงแบบ 3D</span>
              )}
              {canOcr && parts.length > 0 && (
                <Button size="sm" variant="ghost" icon={ScanText} loading={reading && showText} className="ml-auto" onClick={readAll}>
                  อ่านตัวอักษร/ค่าตัวต้านทาน
                </Button>
              )}
              <Button size="sm" variant="secondary" icon={Bot} className={canOcr && parts.length > 0 ? undefined : "ml-auto"} onClick={() => setChatOpen(true)}>
                ถาม AI
              </Button>
            </div>
            {part && canOcr && isResistor(part) && (
              <div className="rounded-lg bg-surface-2 px-3 py-2 flex items-start gap-2 min-h-10">
                <ScanText className="size-4 text-muted shrink-0 mt-0.5" />
                <ResistorReading r={res[selected as number]} />
              </div>
            )}
            {part && canOcr && !isResistor(part) && (
              <div className="rounded-lg bg-surface-2 px-3 py-2 flex items-start gap-2 min-h-10">
                <ScanText className="size-4 text-muted shrink-0 mt-0.5" />
                {selectedText === "loading" || selectedText === undefined ? (
                  <span className="text-xs text-muted flex items-center gap-2">
                    <Spinner className="size-3.5" /> กำลังอ่านตัวอักษรบนชิ้น…
                  </span>
                ) : selectedText.text ? (
                  <div className="flex flex-col min-w-0">
                    <pre className="font-mono text-sm text-text whitespace-pre-wrap break-all leading-snug">{selectedText.text}</pre>
                    <span className="text-[10px] text-subtle">
                      ความมั่นใจ {Math.round(selectedText.confidence * 100)}%{selectedText.rotation ? ` · ตัวอักษรหมุน ${selectedText.rotation}°` : ""}
                    </span>
                  </div>
                ) : (
                  <span className="text-xs text-muted">ไม่พบตัวอักษรบนชิ้นนี้</span>
                )}
              </div>
            )}
          </div>

          <div className="flex flex-col gap-4 min-w-0">
            {point.reason && <p className="text-sm text-text leading-relaxed">{point.reason}</p>}

            {mf ? (
              <div className="grid grid-cols-3 gap-2">
                <Stat label="ครบ" value={mf.confirmed_count} tone="pass" />
                <Stat label="ขาด" value={mf.missing_count} tone={mf.missing_count ? "fail" : undefined} />
                <Stat label="ผิดชนิด" value={mf.wrong_count} tone={mf.wrong_count ? "fail" : undefined} />
                <p className="col-span-3 text-[11px] text-muted">
                  ตรวจ {mf.total_frames}/{mf.target_frames} เฟรม · ผ่านเมื่อพบ ≥ {mf.pass_threshold} เฟรม ({percent(mf.pass_ratio)})
                  {mf.max_offset_px !== undefined && (
                    <span className={mf.max_offset_px > 20 ? "text-review" : undefined}>
                      {" "}· ภาพเลื่อนจากต้นแบบสูงสุด {mf.max_offset_px} px (ชดเชยแล้ว)
                    </span>
                  )}
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-2">
                <Stat label="ตรงต้นแบบ" value={point.summary.ok} tone="pass" />
                <Stat label="ขาด / ผิด" value={`${point.summary.missing} / ${point.summary.wrong}`} tone={point.summary.missing + point.summary.wrong ? "fail" : undefined} />
              </div>
            )}

            {slots.length > 0 && (
              <div className="flex flex-col gap-2">
                <SectionLabel>ตำแหน่งชิ้นส่วน ({slots.length})</SectionLabel>
                <ul className="rounded-lg border border-line divide-y divide-line max-h-80 overflow-y-auto">
                  {slots.map((slot, i) => {
                    const meta = SLOT[slot.status] ?? SLOT.missing;
                    return (
                      <li
                        key={`${slot.expected.id}-${i}`}
                        className={cx("px-3 py-2 flex items-center gap-2 text-sm cursor-pointer", selected === i ? "bg-accent-soft" : "hover:bg-surface-2")}
                        onClick={() => choose(i)}
                      >
                        <span className="font-mono text-xs text-subtle w-8 shrink-0">{slot.expected.id}</span>
                        <span className="flex-1 truncate">
                          {slot.expected.name}
                          {slot.status === "wrong" && slot.wrong_label && <span className="text-muted"> → {slot.wrong_label}</span>}
                        </span>
                        <span className="font-mono tabular text-xs text-muted">
                          {slot.hits}/{slot.target_frames}
                        </span>
                        <Badge tone={meta.tone}>{meta.label}</Badge>
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}

            {withText.length > 0 && (
              <div className="flex flex-col gap-2">
                <SectionLabel>ตัวอักษร/ค่าที่อ่านได้ ({withText.length})</SectionLabel>
                <ul className="rounded-lg border border-line divide-y divide-line max-h-60 overflow-y-auto">
                  {withText.map(({ p, i, text }) => (
                    <li
                      key={i}
                      className={cx("px-3 py-1.5 flex items-start gap-2 text-sm cursor-pointer", selected === i ? "bg-accent-soft" : "hover:bg-surface-2")}
                      onClick={() => choose(i)}
                    >
                      <span className="text-xs text-muted w-24 shrink-0 truncate pt-0.5">{p.name}</span>
                      <span className="font-mono text-xs whitespace-pre-wrap break-all">{text}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex flex-col gap-2">
              <SectionLabel>ตรวจพบในเฟรมสุดท้าย ({point.detections.length})</SectionLabel>
              <div className="flex flex-wrap gap-1.5">
                {countByLabel(point.detections).map(([label, n]) => (
                  <span key={label} className="inline-flex items-center gap-1.5 h-6 px-2 rounded-md bg-surface-2 text-xs">
                    <span className="size-2 rounded-sm" style={{ background: classColor(label) }} />
                    {label}
                    <span className="font-mono text-subtle">×{n}</span>
                  </span>
                ))}
                {!point.detections.length && <span className="text-xs text-muted">ไม่พบชิ้นส่วน</span>}
              </div>
            </div>
          </div>
        </div>
      </Modal>
      {depth && <DepthModal target={depth} onClose={() => setDepth(null)} />}
      {chatOpen && <ChatPanel context={chatContext} imageUrl={src} onClose={() => setChatOpen(false)} />}
    </>
  );
}
