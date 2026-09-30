"use client";

import React, { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Download, History, Image as ImageIcon, RotateCw, ScanLine } from "lucide-react";
import type { AOIPointResult, RunRecord, SingleInspectionRecord, Statistics, Verdict } from "@/types";
import { API_BASE, api } from "@/lib/api";
import { fileName, formatDateTime } from "@/lib/format";
import { PointResultModal } from "./PointResultModal";
import { Badge, Button, Card, EmptyState, IconButton, Modal, Segmented, Select, Spinner, Stat, VerdictBadge, buttonClasses, cx } from "./ui";
import { useToast } from "./Toast";

const PAGE = 50;

export function HistoryView() {
  const [tab, setTab] = useState<"aoi" | "single">("aoi");
  const [stats, setStats] = useState<Statistics | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    api.getStatistics().then(setStats).catch(() => undefined);
  }, [refreshKey]);

  const exportUrl = `${API_BASE}/api/history/export/${tab === "aoi" ? "csv" : "single-csv"}`;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-7xl mx-auto p-4 md:p-6 flex flex-col gap-5">
        {stats && (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Stat label="บอร์ดที่ผลิต (ไม่รวมจำลอง/ต้นแบบ)" value={stats.total_runs} hint={`ผ่าน ${stats.pass_runs} · ไม่ผ่าน ${stats.fail_runs}`} />
            <Stat label="Yield ระดับบอร์ด" value={`${stats.board_yield_rate}%`} tone="pass" hint="ผ่าน ÷ (ผ่าน + ไม่ผ่าน)" />
            <Stat label="Yield ระดับจุด" value={`${stats.point_yield_rate}%`} tone="accent" hint={`${stats.total_pass_points} ผ่าน · ${stats.total_fail_points} ไม่ผ่าน`} />
            <Stat label="รอตรวจซ้ำ" value={stats.review_runs} tone="review" hint={`จำลอง ${stats.simulation_runs} · ต้นแบบ ${stats.golden_runs} รอบ`} />
          </div>
        )}

        <div className="flex items-center gap-2 flex-wrap">
          <Segmented
            value={tab}
            onChange={setTab}
            options={[
              { value: "aoi", label: "การสแกน AOI", icon: ScanLine },
              { value: "single", label: `ตรวจภาพเดี่ยว${stats ? ` (${stats.single_inspections_count})` : ""}`, icon: ImageIcon },
            ]}
          />
          <div className="ml-auto flex items-center gap-2">
            <Button icon={RotateCw} variant="ghost" onClick={() => setRefreshKey((k) => k + 1)}>
              รีเฟรช
            </Button>
            <a href={exportUrl} className={buttonClasses("secondary", "md")}>
              <Download className="size-4" />
              ส่งออก CSV
            </a>
          </div>
        </div>

        {tab === "aoi" ? <RunsTable refreshKey={refreshKey} /> : <SinglesTable refreshKey={refreshKey} />}
      </div>
    </div>
  );
}

function Pager({ offset, total, count, onOffset }: { offset: number; total: number; count: number; onOffset: (o: number) => void }) {
  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      <span className="tabular">
        {count ? offset + 1 : 0}–{offset + count} จาก {total}
      </span>
      <IconButton size="sm" icon={ChevronLeft} label="หน้าก่อน" disabled={offset === 0} onClick={() => onOffset(Math.max(0, offset - PAGE))} />
      <IconButton size="sm" icon={ChevronRight} label="หน้าถัดไป" disabled={offset + PAGE >= total} onClick={() => onOffset(offset + PAGE)} />
    </div>
  );
}

function RunsTable({ refreshKey }: { refreshKey: number }) {
  const [page, setPage] = useState<{ key: string; runs: RunRecord[]; total: number } | null>(null);
  const [offset, setOffset] = useState(0);
  const [verdict, setVerdict] = useState("");
  const [detail, setDetail] = useState<RunRecord | null>(null);
  const [point, setPoint] = useState<AOIPointResult | null>(null);
  const toast = useToast();
  const key = `${verdict}|${offset}|${refreshKey}`;
  const loading = page?.key !== key;
  const runs = page?.runs ?? [];
  const total = page?.total ?? 0;

  useEffect(() => {
    api
      .listRuns(verdict || undefined, PAGE, offset)
      .then((res) => setPage({ key, runs: res.runs, total: res.total }))
      .catch((err) => {
        setPage((p) => ({ key, runs: p?.runs ?? [], total: p?.total ?? 0 }));
        toast.error("โหลดประวัติไม่สำเร็จ", err);
      });
  }, [key, verdict, offset, toast]);

  const open = useCallback(
    async (id: string) => {
      try {
        setDetail(await api.getRun(id));
      } catch (err) {
        toast.error("โหลดรายละเอียดไม่สำเร็จ", err);
      }
    },
    [toast]
  );

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-line flex-wrap">
        <Select
          className="w-44! h-8! text-xs"
          aria-label="กรองผล"
          value={verdict}
          onChange={(e) => {
            setVerdict(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">ทุกผลการตรวจ</option>
          {(["PASS", "FAIL", "REVIEW", "ERROR"] as Verdict[]).map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </Select>
        <Pager offset={offset} total={total} count={runs.length} onOffset={setOffset} />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-surface-2 text-[11px] uppercase tracking-wide text-muted">
            <tr>
              <th className="text-left font-medium px-4 py-2">เวลา</th>
              <th className="text-left font-medium px-4 py-2">ผล</th>
              <th className="text-left font-medium px-4 py-2">ประเภท</th>
              <th className="text-right font-medium px-4 py-2">จุด</th>
              <th className="text-right font-medium px-4 py-2">ผ่าน / ไม่ผ่าน / ซ้ำ</th>
              <th className="text-left font-medium px-4 py-2">รหัสรอบ</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {runs.map((r) => (
              <tr key={r.id} onClick={() => open(r.id)} className="hover:bg-surface-2 cursor-pointer">
                <td className="px-4 py-2.5 whitespace-nowrap text-xs">{formatDateTime(r.created_at)}</td>
                <td className="px-4 py-2.5">
                  <VerdictBadge verdict={r.overall_verdict} />
                </td>
                <td className="px-4 py-2.5">
                  <div className="flex gap-1">
                    {r.is_golden_scan ? <Badge tone="info">ต้นแบบ</Badge> : <Badge>ผลิต</Badge>}
                    {r.is_simulation ? <Badge tone="review">จำลอง</Badge> : null}
                    {r.status !== "complete" && <Badge tone={r.status === "error" ? "fail" : "neutral"}>{r.status}</Badge>}
                  </div>
                </td>
                <td className="px-4 py-2.5 text-right font-mono tabular text-xs">{r.total_points}</td>
                <td className="px-4 py-2.5 text-right font-mono tabular text-xs">
                  <span className="text-pass">{r.pass_count}</span> / <span className="text-fail">{r.fail_count}</span> /{" "}
                  <span className="text-review">{r.review_count}</span>
                </td>
                <td className="px-4 py-2.5 font-mono text-[11px] text-muted">{r.id}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {loading && !runs.length && (
          <div className="py-10 grid place-items-center">
            <Spinner />
          </div>
        )}
        {!loading && !runs.length && <EmptyState icon={History} title="ยังไม่มีประวัติการสแกน" />}
      </div>

      <Modal
        open={!!detail}
        onClose={() => setDetail(null)}
        size="xl"
        title={
          detail && (
            <>
              รอบสแกน <span className="font-mono text-sm text-muted">{detail.id}</span>
              <VerdictBadge verdict={detail.overall_verdict} />
            </>
          )
        }
        subtitle={detail ? `${formatDateTime(detail.created_at)} · ${detail.results?.length ?? 0}/${detail.total_points} จุด · ${detail.is_simulation ? "จำลอง" : "เครื่องจริง"}` : undefined}
      >
        {detail?.error_message && <p className="text-sm text-fail mb-3">{detail.error_message}</p>}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {detail?.results?.map((pt) => (
            <button
              key={pt.point_index}
              type="button"
              onClick={() => setPoint(pt)}
              className="text-left rounded-lg border border-line overflow-hidden hover:border-accent transition-colors cursor-pointer bg-surface"
            >
              <div className="relative aspect-video bg-viewport">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={pt.annotated_url} alt={pt.name ?? ""} className="size-full object-cover" loading="lazy" />
                <VerdictBadge verdict={pt.verdict} className="absolute top-1.5 right-1.5" />
              </div>
              <div className="px-2.5 py-2 text-xs">
                <div className="font-medium truncate">
                  {pt.point_index + 1}. {pt.name || `จุด ${pt.point_index + 1}`}
                </div>
                <div className="text-muted font-mono tabular">
                  {pt.x_mm}, {pt.y_mm} mm
                </div>
              </div>
            </button>
          ))}
        </div>
        {detail && !detail.results?.length && <EmptyState icon={ImageIcon} title="รอบนี้ไม่มีผลของจุดใด" />}
      </Modal>
      <PointResultModal point={point} onClose={() => setPoint(null)} />
    </Card>
  );
}

function SinglesTable({ refreshKey }: { refreshKey: number }) {
  const [page, setPage] = useState<{ key: string; items: SingleInspectionRecord[]; total: number } | null>(null);
  const [offset, setOffset] = useState(0);
  const [detail, setDetail] = useState<SingleInspectionRecord | null>(null);
  const toast = useToast();
  const key = `${offset}|${refreshKey}`;
  const loading = page?.key !== key;
  const items = page?.items ?? [];
  const total = page?.total ?? 0;

  useEffect(() => {
    api
      .listSingleInspections(PAGE, offset)
      .then((res) => setPage({ key, items: res.inspections, total: res.total }))
      .catch((err) => {
        setPage((p) => ({ key, items: p?.items ?? [], total: p?.total ?? 0 }));
        toast.error("โหลดประวัติไม่สำเร็จ", err);
      });
  }, [key, offset, toast]);

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-end px-4 py-3 border-b border-line">
        <Pager offset={offset} total={total} count={items.length} onOffset={setOffset} />
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 p-4">
        {items.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => setDetail(s)}
            className="text-left rounded-lg border border-line overflow-hidden hover:border-accent transition-colors cursor-pointer"
          >
            <div className="relative aspect-video bg-viewport">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={s.annotated_url || s.image_url} alt={`การตรวจ #${s.id}`} className="size-full object-cover" loading="lazy" />
              <VerdictBadge verdict={s.verdict} className="absolute top-1.5 right-1.5" />
            </div>
            <div className="px-2.5 py-2 text-xs">
              <div className="font-medium">#{s.id}</div>
              <div className="text-muted">{formatDateTime(s.created_at)}</div>
            </div>
          </button>
        ))}
      </div>
      {loading && !items.length && (
        <div className="py-10 grid place-items-center">
          <Spinner />
        </div>
      )}
      {!loading && !items.length && <EmptyState icon={History} title="ยังไม่มีประวัติการตรวจภาพเดี่ยว" />}

      <Modal
        open={!!detail}
        onClose={() => setDetail(null)}
        size="lg"
        title={
          detail && (
            <>
              การตรวจ #{detail.id} <VerdictBadge verdict={detail.verdict} />
            </>
          )
        }
        subtitle={detail ? `${formatDateTime(detail.created_at)} · ${detail.device_used ?? ""} · ${fileName(detail.model_used ?? "")}` : undefined}
      >
        {detail && (
          <div className="flex flex-col gap-4">
            <a href={detail.annotated_url || detail.image_url} target="_blank" rel="noreferrer" className="block rounded-xl overflow-hidden bg-viewport">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={detail.annotated_url || detail.image_url} alt="ภาพผลตรวจ" className="w-full max-h-[60vh] object-contain" />
            </a>
            {detail.reason && <p className="text-sm">{detail.reason}</p>}
            {/* summary is an object; rendering it directly used to crash the page */}
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
              <Stat label="ต้นแบบ" value={detail.summary.total_refs} />
              <Stat label="ตรวจพบ" value={detail.summary.total_detections} tone="accent" />
              <Stat label="ตรงต้นแบบ" value={detail.summary.ok} tone="pass" />
              <Stat label="ขาด / ผิด" value={`${detail.summary.missing} / ${detail.summary.wrong}`} tone={detail.summary.missing + detail.summary.wrong ? "fail" : undefined} />
              <Stat label="เกิน" value={detail.summary.extra} className={cx(!detail.summary.total_refs && "opacity-60")} />
            </div>
          </div>
        )}
      </Modal>
    </Card>
  );
}
