"use client";

import React from "react";
import { Expand, ImageOff, Square } from "lucide-react";
import type { AOIPointResult, AOIRunReport, InspectionResult } from "@/types";
import { VERDICT_TONE } from "@/lib/format";
import { Badge, Button, VerdictBadge, cx } from "../ui";

const RUN_STATUS: Record<AOIRunReport["status"], { label: string; tone: "accent" | "pass" | "review" | "fail" | "neutral" }> = {
  idle: { label: "ว่าง", tone: "neutral" },
  running: { label: "กำลังสแกน", tone: "accent" },
  complete: { label: "เสร็จสิ้น", tone: "pass" },
  aborted: { label: "ยกเลิก", tone: "review" },
  error: { label: "ผิดพลาด", tone: "fail" },
};

/** Progress + tally of the current (or most recent) scan run. */
export function ScanStatusStrip({ report, onStop }: { report: AOIRunReport; onStop: () => void }) {
  const total = report.total_points || report.points.length || 1;
  const done = report.results.length;
  const running = report.status === "running";
  const status = RUN_STATUS[report.status];
  return (
    <div className="rounded-xl border border-line bg-surface px-3.5 py-2.5 flex flex-col gap-2">
      <div className="flex items-center gap-2 flex-wrap text-sm">
        <Badge tone={status.tone}>{status.label}</Badge>
        {report.is_golden_scan && <Badge tone="info">สแกนต้นแบบ</Badge>}
        {report.is_simulation && <Badge tone="review">จำลอง</Badge>}
        <span className="font-mono tabular text-xs text-muted">
          {done}/{total} จุด
        </span>
        <span className="flex items-center gap-2 text-xs">
          <span className="text-pass">ผ่าน {report.pass_count}</span>
          <span className="text-fail">ไม่ผ่าน {report.fail_count}</span>
          <span className="text-review">ตรวจซ้ำ {report.review_count}</span>
          {report.error_count > 0 && <span className="text-muted">ผิดพลาด {report.error_count}</span>}
        </span>
        <span className="ml-auto flex items-center gap-2">
          {!running && report.status === "complete" && !report.is_golden_scan && <VerdictBadge verdict={report.overall_verdict} />}
          {running && (
            <Button size="sm" variant="danger" icon={Square} onClick={onStop}>
              หยุดสแกน
            </Button>
          )}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-surface-3 overflow-hidden">
        <div className={cx("h-full transition-all duration-300", running ? "bg-accent" : VERDICT_TONE[report.overall_verdict].solid)} style={{ width: `${(done / total) * 100}%` }} />
      </div>
      {report.error_message && <p className="text-xs text-fail">{report.error_message}</p>}
      {report.status === "complete" && report.is_golden_scan && (
        <p className="text-xs text-pass">สร้างโปรไฟล์ต้นแบบแล้ว — เลือกใช้ได้ในแท็บ “ตาราง”</p>
      )}
    </div>
  );
}

export type OutputItem = { kind: "point"; point: AOIPointResult } | { kind: "snap"; result: InspectionResult };

/** The latest inspected image with its verdict, click to open the full detail. */
export function OutputView({ item, onOpen }: { item: OutputItem | null; onOpen: () => void }) {
  if (!item) {
    return (
      <div className="size-full rounded-xl bg-viewport border border-line grid place-items-center text-center text-white/50 text-sm p-6">
        <div className="flex flex-col items-center gap-2">
          <ImageOff className="size-8" />
          ยังไม่มีผลตรวจ
          <span className="text-xs text-white/40">กด “ถ่ายทดสอบ” หรือเริ่มสแกน ผลของแต่ละจุดจะแสดงที่นี่</span>
        </div>
      </div>
    );
  }
  const verdict = item.kind === "point" ? item.point.verdict : item.result.verdict;
  const url = item.kind === "point" ? item.point.annotated_url : item.result.annotated_url || item.result.image_url || "";
  const caption =
    item.kind === "point"
      ? `${item.point.name || `จุด ${item.point.point_index + 1}`} · พบ ${item.point.detections.length} ชิ้น`
      : `ถ่ายทดสอบ · พบ ${item.result.detections.length} ชิ้น · ${item.result.speed_ms?.inference?.toFixed(0) ?? "–"} ms`;
  return (
    <button type="button" onClick={onOpen} className="group relative size-full rounded-xl overflow-hidden bg-viewport border border-line cursor-zoom-in">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={url} alt="ภาพผลตรวจ" className="absolute inset-0 size-full object-contain" />
      <div className="absolute top-3 left-3 flex items-center gap-1.5">
        <VerdictBadge verdict={verdict} />
      </div>
      <div className="absolute bottom-3 left-3 right-3 flex items-center justify-between gap-2">
        <span className="h-6 px-2 rounded-md bg-black/55 backdrop-blur text-[11px] text-white flex items-center truncate">{caption}</span>
        <span className="h-6 px-2 rounded-md bg-black/55 backdrop-blur text-[11px] text-white/80 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <Expand className="size-3" /> รายละเอียด
        </span>
      </div>
    </button>
  );
}

export function Filmstrip({
  results,
  activeIndex,
  onPick,
}: {
  results: AOIPointResult[];
  activeIndex: number | null;
  onPick: (point: AOIPointResult) => void;
}) {
  if (!results.length) return null;
  return (
    <div className="flex gap-2 overflow-x-auto pb-1 shrink-0">
      {results.map((pt) => (
        <button
          key={pt.point_index}
          type="button"
          onClick={() => onPick(pt)}
          className={cx(
            "relative h-20 aspect-video shrink-0 rounded-lg overflow-hidden border-2 bg-viewport cursor-pointer transition",
            activeIndex === pt.point_index ? "border-accent" : "border-transparent hover:border-line-strong"
          )}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={pt.annotated_url} alt={pt.name || `จุด ${pt.point_index + 1}`} className="size-full object-cover" loading="lazy" />
          <span className={cx("absolute top-1 right-1 h-4 px-1 rounded text-[9px] font-bold text-white", VERDICT_TONE[pt.verdict].solid)}>{pt.verdict}</span>
          <span className="absolute bottom-0 inset-x-0 bg-black/60 text-[10px] text-white px-1.5 py-0.5 text-left truncate">
            {pt.point_index + 1}. {pt.name || `จุด ${pt.point_index + 1}`}
          </span>
        </button>
      ))}
    </div>
  );
}
