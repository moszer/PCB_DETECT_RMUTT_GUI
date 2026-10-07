"use client";

import React, { useCallback } from "react";
import { Layers, Loader2, Play, Sparkles, Square } from "lucide-react";
import type { AOIPointResult, AOIRunReport, CustomPointRequest, Verdict } from "@/types";
import { VERDICT_TONE } from "@/lib/format";
import { Badge, Button, VerdictBadge, cx } from "../ui";

const RUN_STATUS: Record<AOIRunReport["status"], { label: string; tone: "accent" | "pass" | "review" | "fail" | "neutral" }> = {
  idle: { label: "ว่าง", tone: "neutral" },
  running: { label: "กำลังสแกน", tone: "accent" },
  complete: { label: "เสร็จสิ้น", tone: "pass" },
  aborted: { label: "ยกเลิก", tone: "review" },
  error: { label: "ผิดพลาด", tone: "fail" },
};

/** Start/teach controls for the open board; null hides them (operator mode has its own). */
export interface DockActions {
  boardName: string | null;
  onStart: () => void;
  onTeachAll: () => void;
  /** Why the scan can't start (null when it can). */
  startReason: string | null;
  teachReason: string | null;
  teachProgress: { current: number; total: number } | null;
  frames: number | null;
  /** Serial number / barcode field shown next to the start button. */
  serial?: React.ReactNode;
}

type Tile = {
  key: string;
  index: number;
  name: string;
  image: string | null;
  verdict?: Verdict;
  state: "result" | "scanning" | "waiting" | "plan";
  parts?: number;
  result?: AOIPointResult;
};

/**
 * The work area under the camera: start the scan, watch its progress, and one thumbnail
 * per point — the plan (reference images) before a scan, the results as they arrive.
 */
export function ScanDock({
  points,
  report,
  scanningIndex,
  activeIndex,
  selected,
  ratio,
  actions,
  onStop,
  onPickResult,
  onPickPoint,
}: {
  points: CustomPointRequest[];
  report: AOIRunReport | null;
  scanningIndex: number | null;
  activeIndex: number | null;
  selected: number;
  ratio: number;
  actions: DockActions | null;
  onStop: () => void;
  onPickResult: (point: AOIPointResult) => void;
  onPickPoint: (index: number) => void;
}) {
  const running = report?.status === "running";
  const results = report?.results ?? [];
  const showRun = Boolean(report && report.status !== "idle" && (running || results.length));
  const tiles: Tile[] = showRun ? runTiles(report!, points, scanningIndex) : planTiles(points);
  const total = report ? report.total_points || report.points.length || 1 : 1;
  const done = results.length;

  // Stable callback ref: keeps the newest result / the point being scanned in view. Only the
  // strip scrolls sideways; scrollIntoView would also scroll the page (it jumped on phones).
  const reveal = useCallback((el: HTMLButtonElement | null) => {
    const strip = el?.parentElement;
    if (!el || !strip) return;
    const left = el.offsetLeft - strip.offsetLeft;
    if (left < strip.scrollLeft || left + el.offsetWidth > strip.scrollLeft + strip.clientWidth) {
      strip.scrollTo({ left: left - (strip.clientWidth - el.offsetWidth) / 2, behavior: "smooth" });
    }
  }, []);
  const focusIndex = running ? scanningIndex : showRun ? (results[results.length - 1]?.point_index ?? null) : null;

  return (
    <div className="rounded-xl border border-line bg-surface p-3 flex flex-col gap-3" data-tour="dock">
      <div className="flex items-center gap-3 flex-wrap">
        {running ? (
          <Button variant="danger" size="lg" icon={Square} onClick={onStop}>
            หยุดสแกน
          </Button>
        ) : (
          actions && (
            <>
              {actions.serial && <div className="w-full sm:w-64">{actions.serial}</div>}
              <Button variant="primary" size="lg" icon={Play} disabled={actions.startReason !== null} reason={actions.startReason} onClick={actions.onStart}>
                {actions.startReason ?? `เริ่มตรวจ ${points.length} จุด`}
                {actions.frames && actions.startReason === null ? (
                  <span className="inline-flex items-center gap-1 opacity-80 font-normal">
                    · <Layers className="size-3.5" /> {actions.frames}F
                  </span>
                ) : null}
              </Button>
              {points.length > 0 && (
                <Button
                  icon={actions.teachProgress ? undefined : Sparkles}
                  disabled={actions.teachReason !== null || !!actions.teachProgress}
                  reason={actions.teachProgress ? null : actions.teachReason}
                  onClick={actions.onTeachAll}
                  title="เคลื่อนไปทุกจุดแล้วถ่ายภาพต้นแบบใหม่ทั้งหมด"
                >
                  {actions.teachProgress ? (
                    <>
                      <Loader2 className="size-4 animate-spin" />
                      สอนต้นแบบ {actions.teachProgress.current}/{actions.teachProgress.total}
                    </>
                  ) : (
                    "สอนต้นแบบทุกจุด"
                  )}
                </Button>
              )}
            </>
          )
        )}

        <div className="flex-1 min-w-[220px] flex flex-col gap-1.5">
          {showRun && report ? (
            <>
              <div className="flex items-center gap-2 flex-wrap text-sm">
                <Badge tone={RUN_STATUS[report.status].tone}>{RUN_STATUS[report.status].label}</Badge>
                {report.is_golden_scan && <Badge tone="info">สแกนต้นแบบ</Badge>}
                {report.is_simulation && <Badge tone="review">จำลอง</Badge>}
                <span className="font-mono tabular text-xs text-muted">
                  {done}/{total} จุด
                </span>
                <span className="flex items-center gap-2 text-xs">
                  <span className="text-pass">
                    ผ่าน <Count value={report.pass_count} />
                  </span>
                  <span className="text-fail">
                    ไม่ผ่าน <Count value={report.fail_count} />
                  </span>
                  <span className="text-review">
                    ตรวจซ้ำ <Count value={report.review_count} />
                  </span>
                  {report.error_count > 0 && <span className="text-muted">ผิดพลาด {report.error_count}</span>}
                </span>
                {!running && report.status === "complete" && !report.is_golden_scan && (
                  <VerdictBadge verdict={report.overall_verdict} size="lg" className="ml-auto" />
                )}
              </div>
              <div className="h-1.5 rounded-full bg-surface-3 overflow-hidden">
                <div
                  className={cx(
                    "h-full transition-all duration-500 ease-out",
                    running ? "bg-accent bg-stripes animate-stripes" : VERDICT_TONE[report.overall_verdict].solid
                  )}
                  style={{ width: `${(done / total) * 100}%` }}
                />
              </div>
              {report.error_message && <p className="text-xs text-fail">{report.error_message}</p>}
              {report.status === "complete" && report.is_golden_scan && <p className="text-xs text-pass">สร้างโปรไฟล์ต้นแบบแล้ว — เลือกใช้ได้ในแท็บ “ตาราง”</p>}
            </>
          ) : (
            <PlanSummary points={points} boardName={actions?.boardName ?? null} />
          )}
        </div>
      </div>

      {tiles.length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-1 -mx-0.5 px-0.5">
          {tiles.map((t) => {
            const active = t.state === "plan" ? t.index === selected : t.index === activeIndex;
            return (
              <button
                key={t.key}
                ref={t.index === focusIndex ? reveal : undefined}
                type="button"
                disabled={t.state === "waiting" || t.state === "scanning"}
                onClick={() => (t.result ? onPickResult(t.result) : onPickPoint(t.index))}
                title={t.name}
                style={{ aspectRatio: ratio }}
                className={cx(
                  "relative h-20 pointer-coarse:h-24 shrink-0 rounded-lg overflow-hidden border-2 bg-viewport transition cursor-pointer disabled:cursor-default",
                  t.state === "scanning" ? "border-accent" : active ? "border-accent" : "border-transparent hover:border-line-strong"
                )}
              >
                {t.image ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={t.image} alt="" loading="lazy" className={cx("size-full object-cover", t.state !== "result" && "opacity-45 grayscale-[40%]")} />
                ) : (
                  <span className="absolute inset-0 grid place-items-center text-white/30 text-xl font-bold font-mono">{t.index + 1}</span>
                )}
                {t.state === "scanning" && (
                  <span className="absolute inset-0 grid place-items-center bg-accent/20">
                    <Loader2 className="size-5 text-white animate-spin" />
                  </span>
                )}
                {t.verdict && (
                  <span className={cx("absolute top-1 right-1 h-4 px-1 rounded text-[9px] font-bold text-white animate-pop", VERDICT_TONE[t.verdict].solid)}>
                    {t.verdict}
                  </span>
                )}
                {t.state === "plan" && (
                  <span
                    className={cx(
                      "absolute top-1 right-1 h-4 px-1 rounded text-[9px] font-semibold",
                      t.parts ? "bg-black/60 text-white" : "bg-review text-black"
                    )}
                  >
                    {t.parts ? `${t.parts} ชิ้น` : "ไม่มีต้นแบบ"}
                  </span>
                )}
                <span className="absolute bottom-0 inset-x-0 bg-black/60 text-[10px] text-white px-1.5 py-0.5 text-left truncate">
                  {t.index + 1}. {t.name}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function PlanSummary({ points, boardName }: { points: CustomPointRequest[]; boardName: string | null }) {
  if (!boardName) return <p className="text-sm text-muted">ยังไม่ได้เปิดบอร์ด — สร้างหรือเปิดบอร์ดที่แผงด้านซ้าย</p>;
  const untaught = points.filter((p) => !p.expected_components?.length).length;
  return (
    <div className="flex flex-col gap-0.5">
      <div className="text-sm">
        <span className="font-semibold">{boardName}</span>
        <span className="text-muted"> · {points.length} จุดตรวจ</span>
      </div>
      {points.length === 0 ? (
        <p className="text-xs text-muted">มาร์คจุดตรวจอย่างน้อย 1 จุดก่อนเริ่มสแกน — ภาพย่อของแต่ละจุดจะแสดงที่นี่</p>
      ) : untaught ? (
        <p className="text-xs text-review">{untaught} จุดยังไม่มีต้นแบบ ผลของจุดนั้นจะเป็น REVIEW (ตรวจจับอย่างเดียว)</p>
      ) : (
        <p className="text-xs text-pass">ทุกจุดมีต้นแบบแล้ว พร้อมสแกน</p>
      )}
    </div>
  );
}

function runTiles(report: AOIRunReport, points: CustomPointRequest[], scanningIndex: number | null): Tile[] {
  const count = report.total_points || report.points.length;
  // Reference thumbnails come from the open board when the run is its custom plan.
  const same = report.plan.plan_mode === "custom" && points.length === count;
  const byIndex = new Map(report.results.map((r) => [r.point_index, r]));
  return Array.from({ length: count }, (_, i) => {
    const result = byIndex.get(i);
    const name = result?.name || report.points[i]?.name || (same ? points[i].name : undefined) || `จุด ${i + 1}`;
    return {
      key: `${report.id}:${i}`,
      index: i,
      name,
      image: result?.annotated_url || (same ? (points[i].reference_image ?? null) : null),
      verdict: result?.verdict,
      state: result ? "result" : i === scanningIndex ? "scanning" : "waiting",
      result,
    };
  });
}

function planTiles(points: CustomPointRequest[]): Tile[] {
  return points.map((p, i) => ({
    key: p.id ?? String(i),
    index: i,
    name: p.name || `จุด ${i + 1}`,
    image: p.reference_image ?? null,
    state: "plan",
    parts: p.expected_components?.length ?? 0,
  }));
}

/** A number that pops each time it changes. */
function Count({ value }: { value: number }) {
  return (
    <span key={value} className="inline-block font-semibold tabular animate-pop">
      {value}
    </span>
  );
}
