"use client";

import React, { useEffect, useState } from "react";
import { Box } from "lucide-react";
import type { AOIPointResult, SlotStatus } from "@/types";
import { classColor, formatMm, percent } from "@/lib/format";
import type { NBox } from "@/lib/labelLayout";
import { BoxOverlay, type OverlayBox } from "./BoxOverlay";
import { DepthModal, type DepthTarget } from "./DepthModal";
import { Badge, Button, Modal, SectionLabel, Stat, VerdictBadge, cx } from "./ui";

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
  overlay: OverlayBox;
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
        const b = (slot.expected.box ?? slot.expected.bbox ?? [0, 0, 0, 0]) as NBox;
        return {
          bbox: b,
          name: `${slot.expected.id} ${slot.expected.name}`,
          overlay: { bbox: b, label: slot.expected.id, color: SLOT_COLOR[slot.status] ?? SLOT_COLOR.missing, dashed: slot.status === "missing" },
        };
      })
    : size
      ? point.detections.map((d) => {
          const b: NBox = [d.box[0] / size.w, d.box[1] / size.h, d.box[2] / size.w, d.box[3] / size.h];
          return { bbox: b, name: d.label, overlay: { bbox: b, label: `${d.label} ${Math.round(d.conf * 100)}%`, color: classColor(d.label) } };
        })
      : [];
  const part = selected !== null ? parts[selected] : null;
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
        onClose={depth ? () => undefined : onClose /* Esc closes the 3D view first */}
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
            <BoxOverlay src={src} alt="ภาพผลตรวจของจุดนี้" boxes={parts.map((p) => p.overlay)} selected={selected} onSelect={setSelected} />
            <div className="flex items-center gap-2 flex-wrap min-h-9">
              {part ? (
                <>
                  <span className="text-sm font-medium truncate">{part.name}</span>
                  <Button size="sm" variant="primary" icon={Box} onClick={openDepth}>
                    ดูความสูง 3D
                  </Button>
                  <span className="text-[11px] text-subtle">เลื่อนสเตจไปที่จุดนี้ ถ่าย 2 ภาพ แล้วกลับ — บอร์ดต้องอยู่ที่เดิม</span>
                </>
              ) : (
                <span className="text-xs text-muted">คลิกกรอบบนภาพ (หรือในรายการ) เพื่อเลือกชิ้น แล้วดูความสูงแบบ 3D</span>
              )}
            </div>
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
                        onClick={() => setSelected(i)}
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
    </>
  );
}
