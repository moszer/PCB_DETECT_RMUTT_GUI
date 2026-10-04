"use client";

import React from "react";
import { Play, Square } from "lucide-react";
import type { AOIRunReport } from "@/types";
import { VERDICT_LABEL, VERDICT_TONE } from "@/lib/format";
import { Button, cx } from "../ui";

/**
 * Operator mode: pick a board, press one big button, read one big verdict.
 * Marking points, references and parameters stay in engineer mode.
 */
export function OperatorPanel({
  report,
  pointCount,
  currentName,
  startReason,
  onStart,
  onStop,
}: {
  report: AOIRunReport | null;
  pointCount: number;
  /** Name of the point being scanned right now. */
  currentName: string | null;
  startReason: string | null;
  onStart: () => void;
  onStop: () => void;
}) {
  const running = report?.status === "running";
  const total = report ? report.total_points || report.points.length || 1 : pointCount;
  const done = report?.results.length ?? 0;
  const finished = report && !running && report.status !== "idle" && !report.is_golden_scan ? report : null;

  return (
    <div className="flex flex-col gap-4" data-tour="operator">
      <div
        className={cx(
          "rounded-2xl border-2 min-h-56 flex flex-col items-center justify-center text-center gap-2 p-5 transition-colors",
          running
            ? "border-accent bg-accent-soft/50"
            : finished
              ? cx(VERDICT_TONE[finished.overall_verdict].border, VERDICT_TONE[finished.overall_verdict].soft)
              : "border-dashed border-line-strong bg-surface-2"
        )}
      >
        {running ? (
          <>
            <div className="text-sm font-medium text-accent">กำลังตรวจ</div>
            <div className="text-5xl font-bold tabular">
              {done}
              <span className="text-2xl text-muted">/{total}</span>
            </div>
            <div className="w-full h-2 rounded-full bg-surface-3 overflow-hidden">
              <div className="h-full bg-accent bg-stripes animate-stripes transition-all duration-500" style={{ width: `${(done / total) * 100}%` }} />
            </div>
            {currentName && <div className="text-sm text-muted truncate max-w-full">{currentName}</div>}
          </>
        ) : finished?.status === "complete" ? (
          <div key={finished.id} className="flex flex-col items-center gap-1 animate-pop">
            <div className={cx("text-6xl font-black tracking-wider", VERDICT_TONE[finished.overall_verdict].text)}>{finished.overall_verdict}</div>
            <div className={cx("text-lg font-semibold", VERDICT_TONE[finished.overall_verdict].text)}>{VERDICT_LABEL[finished.overall_verdict]}</div>
            <div className="text-sm text-muted tabular">
              ผ่าน {finished.pass_count} · ไม่ผ่าน {finished.fail_count} · ตรวจซ้ำ {finished.review_count} จาก {total} จุด
            </div>
          </div>
        ) : finished ? (
          <>
            <div className="text-2xl font-bold text-review">{finished.status === "aborted" ? "ยกเลิกการสแกน" : "สแกนผิดพลาด"}</div>
            {finished.error_message && <div className="text-sm text-fail">{finished.error_message}</div>}
          </>
        ) : (
          <>
            <div className="text-2xl font-semibold">{startReason ? "ยังไม่พร้อม" : "พร้อมตรวจ"}</div>
            <div className="text-sm text-muted">{startReason ?? `${pointCount} จุดตรวจ · กดปุ่มด้านล่างเพื่อเริ่ม`}</div>
          </>
        )}
      </div>

      {running ? (
        <Button variant="danger" size="lg" icon={Square} className="h-16! text-lg rounded-xl" block onClick={onStop}>
          หยุดสแกน
        </Button>
      ) : (
        <Button
          variant="primary"
          size="lg"
          icon={Play}
          className="h-16! text-lg rounded-xl"
          block
          disabled={startReason !== null}
          reason={startReason}
          onClick={onStart}
        >
          {startReason ?? (finished ? "ตรวจบอร์ดถัดไป" : "เริ่มตรวจบอร์ด")}
        </Button>
      )}
      <p className="text-xs text-muted text-center">ผลของแต่ละจุดแสดงเป็นภาพย่อใต้ภาพกล้อง กดเพื่อดูรายละเอียด</p>
    </div>
  );
}
