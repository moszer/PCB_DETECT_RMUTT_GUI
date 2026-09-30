"use client";

import React from "react";
import type { AOIPointResult, SlotStatus } from "@/types";
import { classColor, formatMm, percent } from "@/lib/format";
import { Badge, Modal, SectionLabel, Stat, VerdictBadge } from "./ui";

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

/** Detail of one AOI point result — shared by the live AOI screen and the history screen. */
export function PointResultModal({ point, onClose }: { point: AOIPointResult | null; onClose: () => void }) {
  if (!point) return null;
  const mf = point.multiframe_info;
  const slots = point.component_eval ?? [];
  return (
    <Modal
      open
      onClose={onClose}
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
        <a href={point.annotated_url} target="_blank" rel="noreferrer" className="block rounded-xl overflow-hidden bg-viewport border border-line">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={point.annotated_url} alt="ภาพผลตรวจของจุดนี้" className="w-full max-h-[62vh] object-contain" />
        </a>

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
                    <li key={`${slot.expected.id}-${i}`} className="px-3 py-2 flex items-center gap-2 text-sm">
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
  );
}
