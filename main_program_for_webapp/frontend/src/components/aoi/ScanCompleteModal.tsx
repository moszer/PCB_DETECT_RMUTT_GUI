"use client";

import React, { useState } from "react";
import { CheckCircle2, Images, OctagonX, Play, Printer, TriangleAlert } from "lucide-react";
import type { AOIRunReport, RunRecord } from "@/types";
import { VERDICT_LABEL, VERDICT_TONE } from "@/lib/format";
import { Button, Modal, cx } from "../ui";
import { RunReport } from "../RunReport";

function duration(report: AOIRunReport): string | null {
  if (!report.completed_at) return null;
  const s = Math.max(0, Math.round(report.completed_at - report.created_at));
  return s >= 60 ? `${Math.floor(s / 60)} นาที ${s % 60} วินาที` : `${s} วินาที`;
}

/**
 * Shown once when a scan ends while the page is open: the board's verdict in big letters,
 * the point counts, which points failed, and what to do next (next board, look at the
 * results, print the report).
 */
export function ScanCompleteModal({
  report,
  onClose,
  onNextBoard,
  onShowResults,
}: {
  report: AOIRunReport;
  onClose: () => void;
  onNextBoard?: () => void;
  onShowResults: () => void;
}) {
  const [printing, setPrinting] = useState(false);
  const done = report.status === "complete";
  const golden = report.is_golden_scan;
  const verdict = report.overall_verdict;
  const tone = VERDICT_TONE[verdict];
  const total = report.total_points || report.points.length || report.results.length;
  const failed = report.results.filter((r) => r.verdict !== "PASS");
  const took = duration(report);
  const asRecord: RunRecord = {
    ...report,
    total_points: total,
    serial: report.plan.serial ?? null,
    board_name: report.plan.board_name ?? null,
  } as unknown as RunRecord;

  const title = !done ? (report.status === "aborted" ? "หยุดการสแกนแล้ว" : "สแกนผิดพลาด") : golden ? "สแกนต้นแบบเสร็จแล้ว" : "สแกนเสร็จแล้ว";
  return (
    <>
      <Modal
        open
        onClose={onClose}
        size="md"
        title={title}
        subtitle={[report.plan.board_name, report.plan.serial && `เลขบอร์ด ${report.plan.serial}`, took && `ใช้เวลา ${took}`].filter(Boolean).join(" · ") || undefined}
        actions={
          <>
            {done && !golden && (
              <Button variant="ghost" icon={Printer} onClick={() => setPrinting(true)}>
                พิมพ์รายงาน
              </Button>
            )}
            <Button
              variant="secondary"
              icon={Images}
              onClick={() => {
                onShowResults();
                onClose();
              }}
            >
              ดูผลทุกจุด
            </Button>
            {onNextBoard && done && !golden ? (
              <Button
                variant="primary"
                icon={Play}
                onClick={() => {
                  onClose();
                  onNextBoard();
                }}
              >
                บอร์ดถัดไป
              </Button>
            ) : (
              <Button variant="primary" onClick={onClose}>
                ตกลง
              </Button>
            )}
          </>
        }
      >
        {done && !golden ? (
          <div className={cx("rounded-2xl border-2 p-5 flex flex-col items-center gap-1 text-center animate-pop", tone.border, tone.soft)}>
            {verdict === "PASS" ? <CheckCircle2 className={cx("size-10", tone.text)} /> : <OctagonX className={cx("size-10", tone.text)} />}
            <div className={cx("text-6xl font-black tracking-wider", tone.text)}>{verdict}</div>
            <div className={cx("text-lg font-semibold", tone.text)}>{VERDICT_LABEL[verdict]}</div>
          </div>
        ) : (
          <div className="rounded-2xl border border-line bg-surface-2 p-5 flex items-center gap-3">
            {golden && done ? <CheckCircle2 className="size-8 text-accent shrink-0" /> : <TriangleAlert className="size-8 text-review shrink-0" />}
            <p className="text-sm">
              {golden && done
                ? "บันทึกผลสแกนต้นแบบเป็นโปรไฟล์อ้างอิงแล้ว"
                : report.error_message || (report.status === "aborted" ? "การสแกนถูกหยุดก่อนครบทุกจุด" : "การสแกนหยุดเพราะเกิดข้อผิดพลาด")}
            </p>
          </div>
        )}

        <div className="grid grid-cols-3 gap-2 mt-4 text-center">
          <Count label="ผ่าน" value={report.pass_count} className="text-pass" />
          <Count label="ไม่ผ่าน" value={report.fail_count} className="text-fail" />
          <Count label="ตรวจซ้ำ" value={report.review_count} className="text-review" />
        </div>
        <p className="mt-2 text-center text-xs text-muted">
          ตรวจแล้ว {report.results.length}/{total} จุด
        </p>

        {done && !golden && failed.length > 0 && (
          <div className="mt-4">
            <div className="text-xs font-medium text-muted mb-1.5">จุดที่ไม่ผ่าน / ต้องตรวจซ้ำ</div>
            <ul className="flex flex-col gap-1">
              {failed.slice(0, 6).map((r) => {
                const bad = (r.component_eval ?? []).filter((c) => c.status === "missing" || c.status === "wrong");
                return (
                  <li key={r.point_index} className="flex items-start gap-2 text-sm rounded-md bg-surface-2 px-2.5 py-1.5">
                    <span className={cx("font-semibold shrink-0", VERDICT_TONE[r.verdict].text)}>{r.verdict}</span>
                    <span className="font-medium shrink-0">
                      {r.point_index + 1}. {r.name || `จุด ${r.point_index + 1}`}
                    </span>
                    <span className="text-xs text-muted truncate">
                      {bad.length
                        ? bad
                            .slice(0, 4)
                            .map((c) => `${c.expected.name} ${c.status === "missing" ? "ขาด" : "ผิดชนิด"}`)
                            .join(" · ") + (bad.length > 4 ? ` · …อีก ${bad.length - 4}` : "")
                        : r.reason}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </Modal>
      {printing && <RunReport run={asRecord} onDone={() => setPrinting(false)} />}
    </>
  );
}

function Count({ label, value, className }: { label: string; value: number; className: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-2 py-2">
      <div className={cx("text-2xl font-bold tabular", className)}>{value}</div>
      <div className="text-[11px] text-muted">{label}</div>
    </div>
  );
}
