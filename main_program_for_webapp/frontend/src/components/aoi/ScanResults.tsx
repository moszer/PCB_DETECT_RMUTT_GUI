"use client";

import React, { useEffect, useState } from "react";
import { Expand, ImageOff, Keyboard } from "lucide-react";
import type { AOIPointResult, CapturedFrame, InspectionResult, RunRecord } from "@/types";
import { api } from "@/lib/api";
import { VERDICT_TONE } from "@/lib/format";
import { VerdictBadge, cx } from "../ui";
import { AnimatedResult, CaptureProgress, revealDelay } from "./ResultOverlay";
import { ProgressiveImage } from "../ProgressiveImage";

export type OutputItem = { kind: "point"; point: AOIPointResult } | { kind: "snap"; result: InspectionResult };

/** A frame being analyzed right now (test snap, or the point a scan is capturing). */
export type PendingFrame = { key: string; image: string | null; label: string; frames?: CapturedFrame[]; target?: number; waiting?: string };

/** The latest inspected image with its verdict, click to open the full detail. */
export function OutputView({
  item,
  pending,
  onOpen,
  summaryKey,
  onOpenPoint,
}: {
  item: OutputItem | null;
  pending?: PendingFrame | null;
  onOpen: () => void;
  /** Changes when a scan finishes, to refresh the idle summary. */
  summaryKey?: string;
  onOpenPoint?: (point: AOIPointResult) => void;
}) {
  if (pending) {
    return (
      <div className="relative size-full rounded-xl overflow-hidden bg-viewport border border-line">
        <CaptureProgress key={pending.key} image={pending.image} label={pending.label} frames={pending.frames} target={pending.target} waiting={pending.waiting} />
      </div>
    );
  }
  if (!item) return <IdleSummary refreshKey={summaryKey ?? ""} onOpenPoint={onOpenPoint} />;
  const verdict = item.kind === "point" ? item.point.verdict : item.result.verdict;
  const url = item.kind === "point" ? item.point.annotated_url : item.result.annotated_url || item.result.image_url || "";
  const caption =
    item.kind === "point"
      ? `${item.point.name || `จุด ${item.point.point_index + 1}`} · พบ ${item.point.detections.length} ชิ้น`
      : `ถ่ายทดสอบ · พบ ${item.result.detections.length} ชิ้น · ${item.result.speed_ms?.inference?.toFixed(0) ?? "–"} ms`;
  // The verdict lands when the box sweep finishes.
  const reveal = { animationDelay: `${revealDelay(item)}ms` };
  return (
    <button type="button" onClick={onOpen} className="group relative size-full rounded-xl overflow-hidden bg-viewport border border-line cursor-zoom-in">
      {/* Keyed by image: each new result replays the reveal. */}
      <div key={url} className="absolute inset-0 animate-fade">
        <AnimatedResult item={item} />
        <div className="absolute top-3 left-3 flex items-center gap-1.5 res-fade" style={reveal}>
          <VerdictBadge verdict={verdict} />
        </div>
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

type Summary = { runs: number; pass: number; fail: number; review: number; last: RunRecord | null };

/** Before anything is inspected here: the station's last scan and today's tally instead of a black box. */
function IdleSummary({ refreshKey, onOpenPoint }: { refreshKey: string; onOpenPoint?: (point: AOIPointResult) => void }) {
  const [data, setData] = useState<Summary | null>(null);
  useEffect(() => {
    let live = true;
    api
      .listRuns(undefined, 300, 0)
      .then(async ({ runs }) => {
        const real = runs.filter((r) => !r.is_golden_scan && r.status === "complete");
        const midnight = new Date().setHours(0, 0, 0, 0) / 1000;
        const today = real.filter((r) => r.created_at >= midnight);
        const count = (v: string) => today.filter((r) => r.overall_verdict === v).length;
        const last = real[0] ? await api.getRun(real[0].id).catch(() => real[0]) : null;
        if (live) setData({ runs: today.length, pass: count("PASS"), fail: count("FAIL"), review: count("REVIEW"), last });
      })
      .catch(() => live && setData({ runs: 0, pass: 0, fail: 0, review: 0, last: null }));
    return () => {
      live = false;
    };
  }, [refreshKey]);

  const last = data?.last;
  const thumbs = (last?.results ?? []).slice(0, 4);
  const yieldPct = data && data.runs ? Math.round((data.pass / data.runs) * 100) : null;
  return (
    <div className="size-full rounded-xl bg-viewport border border-line text-white flex flex-col p-4 gap-3 overflow-hidden">
      {last ? (
        <>
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-white/60">ผลสแกนล่าสุด</span>
            <VerdictBadge verdict={last.overall_verdict} />
            <span className="text-xs text-white/60">
              {new Date(last.created_at * 1000).toLocaleString("th-TH", { dateStyle: "medium", timeStyle: "short" })} · {last.total_points} จุด
            </span>
          </div>
          {thumbs.length > 0 && (
            <div className={cx("flex-1 min-h-0 grid gap-2", thumbs.length > 1 ? "grid-cols-2" : "grid-cols-1")}>
              {thumbs.map((pt) => (
                <button
                  key={pt.point_index}
                  type="button"
                  onClick={() => onOpenPoint?.(pt)}
                  className="relative min-h-0 rounded-lg overflow-hidden bg-black/40 cursor-zoom-in"
                >
                  <ProgressiveImage src={pt.annotated_url} alt={pt.name ?? ""} fit="object-contain" imgClassName="opacity-85" previewWidth={480} />
                  <span className={cx("absolute top-1.5 right-1.5 h-4 px-1 rounded text-[9px] font-bold", VERDICT_TONE[pt.verdict].solid)}>{pt.verdict}</span>
                  <span className="absolute bottom-0 inset-x-0 bg-black/60 text-[10px] px-1.5 py-0.5 text-left truncate">
                    {pt.point_index + 1}. {pt.name || `จุด ${pt.point_index + 1}`}
                  </span>
                </button>
              ))}
            </div>
          )}
        </>
      ) : (
        <div className="flex-1 grid place-items-center text-center text-white/60 text-sm">
          <div className="flex flex-col items-center gap-2">
            <ImageOff className="size-8" />
            {data ? "ยังไม่มีผลตรวจ" : "กำลังโหลด…"}
            <span className="text-xs text-white/50">กด “ถ่ายทดสอบ” หรือเริ่มสแกน ผลของแต่ละจุดจะแสดงที่นี่</span>
          </div>
        </div>
      )}
      <div className="mt-auto flex items-center gap-x-3 gap-y-1 flex-wrap text-xs border-t border-white/10 pt-2.5">
        <span className="text-white/60">วันนี้</span>
        <span className="font-semibold tabular">{data?.runs ?? "–"} รอบ</span>
        <span className="text-emerald-400 tabular">ผ่าน {data?.pass ?? "–"}</span>
        <span className="text-red-400 tabular">ไม่ผ่าน {data?.fail ?? "–"}</span>
        {data && data.review > 0 && <span className="text-amber-300 tabular">ตรวจซ้ำ {data.review}</span>}
        {yieldPct !== null && <span className="tabular">Yield {yieldPct}%</span>}
        <span className="ml-auto flex items-center gap-1 text-white/50 pointer-coarse:hidden">
          <Keyboard className="size-3.5" /> Space = ถ่ายทดสอบ
        </span>
      </div>
    </div>
  );
}
