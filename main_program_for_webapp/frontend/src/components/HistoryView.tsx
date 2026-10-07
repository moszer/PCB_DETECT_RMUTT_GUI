"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Barcode, ChevronLeft, ChevronRight, Download, FlaskConical, History, Image as ImageIcon, Printer, RotateCw, ScanLine, Search } from "lucide-react";
import type { AOIPointResult, RunRecord, SingleInspectionRecord, Statistics, Verdict } from "@/types";
import { API_BASE, api, withToken } from "@/lib/api";
import { fileName, formatDateTime } from "@/lib/format";
import { PointResultModal } from "./PointResultModal";
import { ZoomPan } from "./ZoomPan";
import { PerformanceView } from "./PerformanceView";
import { Badge, Button, Card, EmptyState, IconButton, Modal, Segmented, Select, Spinner, Stat, TextInput, VerdictBadge, buttonClasses, cx } from "./ui";
import { useToast } from "./Toast";
import { ProgressiveImage } from "./ProgressiveImage";
import { RunReport } from "./RunReport";

const PAGE = 50;

export function HistoryView() {
  const [tab, setTab] = useState<"aoi" | "single" | "perf">("aoi");
  const [stats, setStats] = useState<Statistics | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    api.getStatistics().then(setStats).catch(() => undefined);
  }, [refreshKey]);

  const exportUrl = withToken(`${API_BASE}/api/history/export/${tab === "aoi" ? "csv" : "single-csv"}`);

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
              { value: "perf", label: "ผลทดสอบ", icon: FlaskConical },
            ]}
          />
          <div className="ml-auto flex items-center gap-2">
            <Button icon={RotateCw} variant="ghost" onClick={() => setRefreshKey((k) => k + 1)}>
              รีเฟรช
            </Button>
            {tab !== "perf" && (
              <a href={exportUrl} className={buttonClasses("secondary", "md")}>
                <Download className="size-4" />
                ส่งออก CSV
              </a>
            )}
          </div>
        </div>

        {tab === "aoi" ? <RunsTable refreshKey={refreshKey} /> : tab === "single" ? <SinglesTable refreshKey={refreshKey} /> : <PerformanceView refreshKey={refreshKey} />}
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
  const [search, setSearch] = useState("");
  const [detail, setDetail] = useState<RunRecord | null>(null);
  const [point, setPoint] = useState<AOIPointResult | null>(null);
  const [printing, setPrinting] = useState<RunRecord | null>(null);
  const toast = useToast();
  const key = `${verdict}|${search.trim()}|${offset}|${refreshKey}`;
  const loading = page?.key !== key;
  const runs = page?.runs ?? [];
  const total = page?.total ?? 0;

  useEffect(() => {
    api
      .listRuns(verdict || undefined, PAGE, offset, search)
      .then((res) => setPage({ key, runs: res.runs, total: res.total }))
      .catch((err) => {
        setPage((p) => ({ key, runs: p?.runs ?? [], total: p?.total ?? 0 }));
        toast.error("โหลดประวัติไม่สำเร็จ", err);
      });
  }, [key, verdict, search, offset, toast]);

  const markTruth = async (truth: "good" | "defective" | null) => {
    if (!detail) return;
    try {
      await api.setGroundTruth(detail.id, truth);
      setDetail({ ...detail, ground_truth: truth });
      setPage((p) => (p ? { ...p, runs: p.runs.map((r) => (r.id === detail.id ? { ...r, ground_truth: truth } : r)) } : p));
    } catch (err) {
      toast.error("บันทึกผลจริงไม่สำเร็จ", err);
    }
  };

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
        <div className="relative w-full sm:w-64 order-last sm:order-none">
          <Search className="size-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-subtle" />
          <TextInput
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setOffset(0);
            }}
            placeholder="ค้นหาเลขบอร์ด / ชื่อบอร์ด / รหัสรอบ"
            className="pl-8 h-8! text-xs"
          />
        </div>
        <Pager offset={offset} total={total} count={runs.length} onOffset={setOffset} />
      </div>
      <ul className="sm:hidden divide-y divide-line">
        {runs.map((r) => (
          <li key={r.id}>
            <button type="button" onClick={() => open(r.id)} className="w-full text-left px-4 py-3 flex flex-col gap-1.5 hover:bg-surface-2 cursor-pointer">
              <span className="flex items-center gap-2">
                <RunVerdict status={r.status} verdict={r.overall_verdict} />
                <TruthBadge truth={r.ground_truth} />
                <span className="text-xs text-muted">{formatDateTime(r.created_at)}</span>
                <span className="ml-auto text-xs font-mono tabular text-muted">{r.total_points} จุด</span>
              </span>
              {(r.serial || r.board_name) && (
                <span className="text-xs text-muted truncate">
                  {r.board_name}
                  {r.serial && <span className="font-mono text-text"> · {r.serial}</span>}
                </span>
              )}
              <span className="flex items-center gap-1.5 flex-wrap text-xs">
                {r.is_golden_scan ? <Badge tone="info">ต้นแบบ</Badge> : <Badge>ผลิต</Badge>}
                {r.is_simulation ? <Badge tone="review">จำลอง</Badge> : null}
                
                <span className="ml-auto font-mono tabular">
                  <span className="text-pass">ผ่าน {r.pass_count}</span> · <span className="text-fail">ไม่ผ่าน {r.fail_count}</span> ·{" "}
                  <span className="text-review">ซ้ำ {r.review_count}</span>
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      <div className="overflow-x-auto">
        <table className="hidden sm:table w-full min-w-[640px] text-sm">
          <thead className="bg-surface-2 text-[11px] uppercase tracking-wide text-muted">
            <tr>
              <th className="text-left font-medium px-4 py-2">เวลา</th>
              <th className="text-left font-medium px-4 py-2">ผล</th>
              <th className="text-left font-medium px-4 py-2">บอร์ด / เลขบอร์ด</th>
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
                  <div className="flex items-center gap-1">
                    <RunVerdict status={r.status} verdict={r.overall_verdict} />
                    <TruthBadge truth={r.ground_truth} />
                  </div>
                </td>
                <td className="px-4 py-2.5 text-xs max-w-[14rem]">
                  <div className="truncate">{r.board_name || <span className="text-subtle">–</span>}</div>
                  {r.serial && (
                    <div className="font-mono text-[11px] text-muted truncate flex items-center gap-1">
                      <Barcode className="size-3 shrink-0" /> {r.serial}
                    </div>
                  )}
                </td>
                <td className="px-4 py-2.5">
                  <div className="flex gap-1">
                    {r.is_golden_scan ? <Badge tone="info">ต้นแบบ</Badge> : <Badge>ผลิต</Badge>}
                    {r.is_simulation ? <Badge tone="review">จำลอง</Badge> : null}
                    
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
        {!loading && !runs.length && <EmptyState pcb icon={History} title="ยังไม่มีประวัติการสแกน" />}
      </div>

      <Modal
        open={!!detail}
        onClose={() => setDetail(null)}
        size="xl"
        title={
          detail && (
            <>
              รอบสแกน <span className="font-mono text-sm text-muted">{detail.id}</span>
              <RunVerdict status={detail.status} verdict={detail.overall_verdict} />
            </>
          )
        }
        subtitle={
          detail
            ? `${formatDateTime(detail.created_at)} · ${detail.results?.length ?? 0}/${detail.total_points} จุด · ${detail.is_simulation ? "จำลอง" : "เครื่องจริง"}${detail.board_name ? ` · ${detail.board_name}` : ""}${detail.serial ? ` · เลขบอร์ด ${detail.serial}` : ""}`
            : undefined
        }
      >
        {detail && (
          <div className="mb-3 flex justify-end">
            <Button size="sm" icon={Printer} onClick={() => setPrinting(detail)}>
              พิมพ์ / บันทึกเป็น PDF
            </Button>
          </div>
        )}
        {detail?.error_message && <p className="text-sm text-fail mb-3">{detail.error_message}</p>}
        {detail && !detail.is_golden_scan && (
          <div className="mb-4 flex items-center gap-3 flex-wrap rounded-lg border border-line bg-surface-2 px-3 py-2.5">
            <span className="text-sm font-medium">บอร์ดจริงเป็นอย่างไร?</span>
            <Segmented
              size="sm"
              value={detail.ground_truth ?? "none"}
              onChange={(v) => markTruth(v === "none" ? null : v)}
              options={[
                { value: "none", label: "ไม่ระบุ" },
                { value: "good", label: "ดี (ไม่มีจุดเสีย)" },
                { value: "defective", label: "เสีย (มีจุดเสีย)" },
              ]}
            />
            <span className="text-xs text-muted">ใช้คิด Accuracy / F1 ในแท็บ “ผลทดสอบ”{detail.device ? ` · สแกนด้วย ${detail.device}${detail.host ? ` (${detail.host})` : ""}` : ""}</span>
          </div>
        )}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          {detail?.results?.map((pt) => (
            <button
              key={pt.point_index}
              type="button"
              onClick={() => setPoint(pt)}
              className="text-left rounded-lg border border-line overflow-hidden hover:border-accent transition-colors cursor-pointer bg-surface"
            >
              <div className="relative aspect-video bg-viewport">
                <ProgressiveImage src={pt.annotated_url} alt={pt.name ?? ""} fit="object-cover" previewWidth={480} />
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
      {printing && <RunReport run={printing} onDone={() => setPrinting(null)} />}
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
              <ProgressiveImage src={s.annotated_url || s.image_url || ""} alt={`การตรวจ #${s.id}`} fit="object-cover" previewWidth={480} />
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
            <div className="flex flex-col gap-1.5">
              <ZoomPan className="rounded-xl bg-viewport">
                <ProgressiveImage src={detail.annotated_url || detail.image_url || ""} alt="ภาพผลตรวจ" layout="flow" className="max-h-[60vh]" />
              </ZoomPan>
              <a href={detail.annotated_url || detail.image_url} target="_blank" rel="noreferrer" className="self-end text-xs text-accent hover:underline">
                เปิดภาพขนาดเต็มในแท็บใหม่
              </a>
            </div>
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

/** The board's real condition as marked in the run detail (for accuracy / F1). */
function TruthBadge({ truth }: { truth?: "good" | "defective" | null }) {
  if (!truth) return null;
  return <Badge tone={truth === "good" ? "pass" : "fail"}>{truth === "good" ? "จริง: ดี" : "จริง: เสีย"}</Badge>;
}

/** A finished run's verdict; a run that did not finish says so instead (an aborted scan's
 * partial verdict read as "REVIEW", as if it needed checking). */
function RunVerdict({ status, verdict }: { status: string; verdict: Verdict }) {
  if (status === "aborted") return <Badge>หยุดกลางคัน</Badge>;
  if (status === "error") return <Badge tone="fail">ผิดพลาด</Badge>;
  if (status === "running") return <Badge tone="info">กำลังสแกน</Badge>;
  return <VerdictBadge verdict={verdict} />;
}
