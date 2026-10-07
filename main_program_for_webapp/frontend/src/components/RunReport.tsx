"use client";

import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { RunRecord } from "@/types";
import { VERDICT_LABEL, formatDateTime } from "@/lib/format";
import { isStorageImage, thumbUrl } from "@/lib/media";

const STATUS_TEXT: Record<string, string> = { aborted: "หยุดกลางคัน", error: "ผิดพลาด", running: "กำลังสแกน" };
const VERDICT_COLOR: Record<string, string> = { PASS: "#15803d", FAIL: "#b91c1c", REVIEW: "#b45309", ERROR: "#6d28d9" };

/**
 * A one-run inspection report laid out for paper (A4) and opened in the print dialog, where
 * "Save as PDF" gives the PDF. Rendered into its own root next to the app; print CSS
 * (globals.css, #print-root) shows only this while printing.
 */
export function RunReport({ run, onDone }: { run: RunRecord; onDone: () => void }) {
  const root = useRef<HTMLDivElement>(null);
  const [printedAt] = useState(() => Date.now() / 1000);
  const done = useRef(onDone);
  useEffect(() => {
    done.current = onDone;
  });

  useEffect(() => {
    let cancelled = false;
    const finish = () => done.current();
    window.addEventListener("afterprint", finish, { once: true });
    // Wait for the point pictures, so they are on the paper.
    const imgs = Array.from(root.current?.querySelectorAll("img") ?? []);
    const loaded = Promise.all(imgs.map((img) => (img.complete ? Promise.resolve() : img.decode().catch(() => undefined))));
    const timeout = new Promise((r) => setTimeout(r, 6000));
    void Promise.race([loaded, timeout]).then(() => {
      if (!cancelled) window.print();
    });
    return () => {
      cancelled = true;
      window.removeEventListener("afterprint", finish);
    };
  }, []);

  const results = run.results ?? [];
  const failing = results.filter((r) => r.verdict !== "PASS");
  const verdictText = STATUS_TEXT[run.status] ?? run.overall_verdict;
  const verdictColor = STATUS_TEXT[run.status] ? "#475569" : VERDICT_COLOR[run.overall_verdict] ?? "#111";

  return createPortal(
    <div id="print-root" ref={root} className="print-report">
      <header className="pr-head">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/rmutt-logo.png" alt="" className="pr-logo" />
        <div>
          <div className="pr-title">รายงานผลการตรวจแผงวงจร (AOI)</div>
          <div className="pr-sub">RMUTT AOI · PCB Inspection Station</div>
        </div>
        <div className="pr-verdict" style={{ color: verdictColor, borderColor: verdictColor }}>
          {verdictText}
          {!STATUS_TEXT[run.status] && <span>{VERDICT_LABEL[run.overall_verdict]}</span>}
        </div>
      </header>

      <table className="pr-meta">
        <tbody>
          <tr>
            <th>บอร์ด</th>
            <td>{run.board_name || "–"}</td>
            <th>เลขบอร์ด (serial)</th>
            <td className="pr-mono">{run.serial || "–"}</td>
          </tr>
          <tr>
            <th>วันเวลา</th>
            <td>{formatDateTime(run.created_at)}</td>
            <th>รหัสรอบ</th>
            <td className="pr-mono">{run.id}</td>
          </tr>
          <tr>
            <th>ผลรายจุด</th>
            <td>
              ผ่าน {run.pass_count} · ไม่ผ่าน {run.fail_count} · ตรวจซ้ำ {run.review_count} จาก {run.total_points} จุด
            </td>
            <th>เครื่อง / โมเดล</th>
            <td>
              {[run.host, run.device].filter(Boolean).join(" · ") || "–"}
              {run.model && <div className="pr-mono pr-small">{run.model}</div>}
            </td>
          </tr>
          {run.is_simulation ? (
            <tr>
              <th>หมายเหตุ</th>
              <td colSpan={3}>สแกนด้วยสเตจจำลอง (ไม่ใช่ผลจากเครื่องจริง)</td>
            </tr>
          ) : null}
        </tbody>
      </table>

      {failing.length > 0 && (
        <section>
          <h2 className="pr-h2">จุดที่ไม่ผ่าน / ต้องตรวจซ้ำ</h2>
          <table className="pr-list">
            <thead>
              <tr>
                <th>จุด</th>
                <th>ผล</th>
                <th>ชิ้นส่วนที่มีปัญหา</th>
              </tr>
            </thead>
            <tbody>
              {failing.map((pt) => {
                const bad = (pt.component_eval ?? []).filter((c) => c.status === "missing" || c.status === "wrong");
                return (
                  <tr key={pt.point_index}>
                    <td>
                      {pt.point_index + 1}. {pt.name || `จุด ${pt.point_index + 1}`}
                    </td>
                    <td style={{ color: VERDICT_COLOR[pt.verdict] }}>{pt.verdict}</td>
                    <td>
                      {bad.length
                        ? bad
                            .slice(0, 12)
                            .map((c) => `${c.expected.name} (${c.expected.id}) ${c.status === "missing" ? "ขาด" : `ผิดชนิด${c.wrong_label ? ` → ${c.wrong_label}` : ""}`}`)
                            .join(" · ") + (bad.length > 12 ? ` · …อีก ${bad.length - 12} ชิ้น` : "")
                        : pt.reason || `ขาด ${pt.summary.missing} · ผิด ${pt.summary.wrong} · เกิน ${pt.summary.extra}`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}

      <section>
        <h2 className="pr-h2">ภาพทุกจุด</h2>
        <div className="pr-grid">
          {results.map((pt) => (
            <figure key={pt.point_index} className="pr-fig">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={isStorageImage(pt.annotated_url) ? thumbUrl(pt.annotated_url, 480) : pt.annotated_url} alt="" />
              <figcaption>
                <span>
                  {pt.point_index + 1}. {pt.name || `จุด ${pt.point_index + 1}`}
                </span>
                <b style={{ color: VERDICT_COLOR[pt.verdict] }}>{pt.verdict}</b>
              </figcaption>
            </figure>
          ))}
        </div>
      </section>

      <footer className="pr-foot">พิมพ์เมื่อ {formatDateTime(printedAt)} · ผลจากระบบตรวจอัตโนมัติ ควรยืนยันด้วยการตรวจด้วยตาสำหรับจุดที่ไม่ผ่าน</footer>
    </div>,
    document.body
  );
}
