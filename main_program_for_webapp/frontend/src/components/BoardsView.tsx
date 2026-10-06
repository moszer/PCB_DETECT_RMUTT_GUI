"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, CircuitBoard, Copy, Download, ExternalLink, ImageOff, Pencil, Trash2, Upload } from "lucide-react";
import type { BoardDetail, BoardSummary, ReferenceSummary } from "@/types";
import { api, errorMessage } from "@/lib/api";
import { classColor, formatDateTime, formatMm } from "@/lib/format";
import { Badge, Button, Card, CardHeader, EmptyState, Spinner, Stat, TextInput, VerdictBadge, cx } from "./ui";
import { ReferencesView } from "./ReferencesView";
import { OPEN_BOARD_KEY } from "./aoi/PointSets";
import { useToast } from "./Toast";

function ClassChips({ classes }: { classes: Record<string, number> }) {
  const entries = Object.entries(classes);
  if (!entries.length) return <span className="text-xs text-subtle">ยังไม่มีชิ้นส่วน</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {entries.map(([name, n]) => (
        <span key={name} className="inline-flex items-center gap-1.5 h-6 px-2 rounded-md bg-surface-2 border border-line text-xs">
          <span className="size-2 rounded-full" style={{ background: classColor(name) }} />
          {name} <span className="text-muted font-mono">×{n}</span>
        </span>
      ))}
    </div>
  );
}

function Readiness({ b }: { b: BoardSummary }) {
  const total = b.point_count;
  const ok = b.ready_points === total && !b.board_issues.length && total > 0;
  return ok ? (
    <span className="inline-flex items-center gap-1 text-[11px] text-pass">
      <CheckCircle2 className="size-3.5" /> พร้อมสแกนทุกจุด
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-[11px] text-review">
      <AlertTriangle className="size-3.5" /> พร้อม {b.ready_points}/{total} จุด
    </span>
  );
}

/** Boards (named sets of taught points): pictures, readiness before a scan, history and management. */
export function BoardsView({
  references,
  onRefreshReferences,
  onOpenBoard,
  isOperator,
}: {
  references: ReferenceSummary[];
  onRefreshReferences: () => void;
  onOpenBoard: () => void;
  isOperator: boolean;
}) {
  const toast = useToast();
  const [boards, setBoards] = useState<BoardSummary[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<BoardDetail | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [legacyOpen, setLegacyOpen] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(
    (keep?: string | null) =>
      api.boards
        .list()
        .then((list) => {
          setBoards(list);
          setSelected((cur) => (keep !== undefined ? keep : cur) ?? list[0]?.id ?? null);
        })
        .catch((err) => {
          setBoards([]);
          toast.error("โหลดรายการบอร์ดไม่สำเร็จ", errorMessage(err));
        }),
    [toast]
  );
  const loadOnce = useCallback(() => {
    refresh();
  }, [refresh]);
  useEffect(loadOnce, [loadOnce]);

  useEffect(() => {
    if (!selected) return;
    let live = true;
    api.boards
      .get(selected)
      .then((d) => live && setDetail(d))
      .catch((err) => live && toast.error("โหลดบอร์ดไม่สำเร็จ", errorMessage(err)));
    return () => {
      live = false;
    };
  }, [selected, toast, boards]);

  const act = async (task: () => Promise<unknown>, ok: string, fail: string, keep?: string | null) => {
    setBusy(true);
    try {
      await task();
      toast.success(ok);
      await refresh(keep);
    } catch (err) {
      toast.error(fail, errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const openInScan = (id: string) => {
    try {
      localStorage.setItem(OPEN_BOARD_KEY, id);
    } catch {
      // Without storage the scan page simply keeps its current board.
    }
    onOpenBoard();
  };

  const importFile = async (file: File) => {
    try {
      const body = JSON.parse(await file.text());
      await act(async () => {
        const created = await api.boards.importBoard(body);
        setSelected(created.id);
      }, "นำเข้าบอร์ดแล้ว", "นำเข้าไม่สำเร็จ");
    } catch (err) {
      toast.error("อ่านไฟล์ไม่ได้", errorMessage(err));
    }
  };

  const current = detail && detail.id === selected ? detail : null;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-7xl mx-auto p-4 md:p-6 flex flex-col gap-5">
        <div className="grid gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
          {/* ── list ── */}
          <div className="flex flex-col gap-3 min-w-0">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold flex-1">บอร์ดที่บันทึกไว้ {boards ? `(${boards.length})` : ""}</h2>
              <input
                ref={fileInput}
                type="file"
                accept="application/json,.json"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) importFile(f);
                  e.target.value = "";
                }}
              />
              <Button size="sm" variant="ghost" icon={Upload} disabled={!isOperator || busy} onClick={() => fileInput.current?.click()}>
                นำเข้า
              </Button>
            </div>
            {!boards ? (
              <div className="py-10 grid place-items-center">
                <Spinner className="size-5" />
              </div>
            ) : boards.length === 0 ? (
              <EmptyState icon={CircuitBoard} title="ยังไม่มีบอร์ด" className="rounded-xl border border-dashed border-line">
                สร้างบอร์ดและมาร์คจุดตรวจในหน้าสแกน AOI
              </EmptyState>
            ) : (
              boards.map((b) => (
                <button
                  key={b.id}
                  type="button"
                  onClick={() => setSelected(b.id)}
                  className={cx(
                    "text-left rounded-xl border overflow-hidden transition-colors cursor-pointer bg-surface",
                    selected === b.id ? "border-accent ring-1 ring-accent/40" : "border-line hover:border-line-strong"
                  )}
                >
                  <div className="relative aspect-video bg-viewport">
                    {b.cover_point !== null && b.cover_point !== undefined ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={api.boards.thumb(b.id, b.cover_point, 480, b.updated_at)} alt="" loading="lazy" className="absolute inset-0 size-full object-cover" />
                    ) : (
                      <div className="absolute inset-0 grid place-items-center text-subtle">
                        <ImageOff className="size-6" />
                      </div>
                    )}
                    {b.history.last && <VerdictBadge verdict={b.history.last.overall_verdict} className="absolute top-2 right-2" />}
                  </div>
                  <div className="px-3 py-2.5 flex flex-col gap-1">
                    <div className="font-medium truncate">{b.name}</div>
                    <div className="flex items-center justify-between gap-2 text-[11px] text-muted">
                      <span>
                        {b.point_count} จุด · {b.component_count} ชิ้น
                      </span>
                      <span>{b.history.yield_pct !== null ? `yield ${b.history.yield_pct}% · ${b.history.completed} รอบ` : "ยังไม่เคยสแกน"}</span>
                    </div>
                    <Readiness b={b} />
                  </div>
                </button>
              ))
            )}
          </div>

          {/* ── detail ── */}
          <div className="min-w-0 flex flex-col gap-4">
            {!current ? (
              selected ? (
                <div className="py-20 grid place-items-center">
                  <Spinner className="size-6" />
                </div>
              ) : null
            ) : (
              <>
                <Card>
                  <div className="p-4 flex flex-wrap items-start gap-3">
                    <div className="flex-1 min-w-[16rem]">
                      {renaming !== null ? (
                        <form
                          className="flex gap-2"
                          onSubmit={(e) => {
                            e.preventDefault();
                            const name = renaming.trim();
                            setRenaming(null);
                            if (name && name !== current.name) {
                              act(() => api.pointSets.update(current.id, { name }), "เปลี่ยนชื่อแล้ว", "เปลี่ยนชื่อไม่สำเร็จ", current.id);
                            }
                          }}
                        >
                          <TextInput autoFocus value={renaming} onChange={(e) => setRenaming(e.target.value)} className="max-w-xs" />
                          <Button size="sm" type="submit" variant="primary">
                            บันทึก
                          </Button>
                        </form>
                      ) : (
                        <h2 className="text-lg font-semibold truncate">{current.name}</h2>
                      )}
                      <p className="text-[11px] text-muted mt-0.5">
                        สร้าง {formatDateTime(current.created_at)} · แก้ล่าสุด {formatDateTime(current.updated_at)}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      <Button size="sm" variant="primary" icon={ExternalLink} onClick={() => openInScan(current.id)}>
                        เปิดในหน้าสแกน
                      </Button>
                      <Button size="sm" variant="ghost" icon={Pencil} disabled={!isOperator || busy} onClick={() => setRenaming(current.name)}>
                        เปลี่ยนชื่อ
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={Copy}
                        disabled={!isOperator || busy}
                        onClick={() =>
                          act(async () => {
                            const c = await api.boards.duplicate(current.id);
                            setSelected(c.id);
                          }, "ทำสำเนาแล้ว", "ทำสำเนาไม่สำเร็จ")
                        }
                      >
                        ทำสำเนา
                      </Button>
                      <a className="inline-flex" href={api.boards.exportUrl(current.id)} download>
                        <Button size="sm" variant="ghost" icon={Download}>
                          ส่งออก
                        </Button>
                      </a>
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={Trash2}
                        disabled={!isOperator || busy}
                        onClick={() => {
                          if (!window.confirm(`ลบบอร์ด “${current.name}”? (ประวัติการสแกนยังอยู่)`)) return;
                          act(() => api.pointSets.remove(current.id), "ลบบอร์ดแล้ว", "ลบไม่สำเร็จ", null);
                        }}
                      >
                        ลบ
                      </Button>
                    </div>
                  </div>
                  <div className="px-4 pb-4 grid grid-cols-2 sm:grid-cols-5 gap-2">
                    <Stat label="จุดตรวจ" value={current.point_count} />
                    <Stat label="ชิ้นส่วนที่สอน" value={current.component_count} />
                    <Stat
                      label="พร้อมสแกน"
                      value={`${current.ready_points}/${current.point_count}`}
                      tone={current.ready_points === current.point_count && current.point_count ? "pass" : "review"}
                    />
                    <Stat label="Yield" value={current.history.yield_pct !== null ? `${current.history.yield_pct}%` : "–"} hint={`${current.history.pass} ผ่าน · ${current.history.fail} ไม่ผ่าน`} />
                    <Stat label="รอบสแกน" value={current.history.completed} hint={current.history.last ? `ล่าสุด ${formatDateTime(current.history.last.created_at)}` : undefined} />
                  </div>
                  <div className="px-4 pb-4">
                    <ClassChips classes={current.classes} />
                  </div>
                  {current.board_issues.length > 0 && (
                    <div className="mx-4 mb-4 rounded-lg border border-review/40 bg-review-soft px-3 py-2 text-xs text-review flex flex-col gap-1">
                      {current.board_issues.map((t) => (
                        <span key={t} className="flex items-start gap-1.5">
                          <AlertTriangle className="size-3.5 shrink-0 mt-0.5" /> {t}
                        </span>
                      ))}
                    </div>
                  )}
                </Card>

                <div className="grid gap-4 xl:grid-cols-2">
                  <Card>
                    <CardHeader title="รอบสแกนล่าสุด" subtitle="รอบที่ใช้จุดตรวจของบอร์ดนี้" />
                    {current.history.recent.length === 0 ? (
                      <p className="p-4 text-xs text-muted">ยังไม่เคยสแกนบอร์ดนี้</p>
                    ) : (
                      <ul className="divide-y divide-line max-h-72 overflow-y-auto">
                        {current.history.recent.map((r) => (
                          <li key={r.id} className="px-4 py-2 flex items-center gap-3 text-sm">
                            <VerdictBadge verdict={r.overall_verdict} />
                            <span className="flex-1 text-xs text-muted truncate">{formatDateTime(r.created_at)}</span>
                            <span className="font-mono text-xs tabular">
                              <span className="text-pass">{r.pass_count}</span> / <span className="text-fail">{r.fail_count}</span> / {r.review_count}
                              <span className="text-subtle"> จาก {r.total_points}</span>
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </Card>
                  <Card>
                    <CardHeader title="จุดและชิ้นที่ผิดบ่อย" subtitle="นับจากรอบสแกนที่เสร็จแล้ว" />
                    {current.history.top_failing_points.length === 0 && current.history.top_failing_parts.length === 0 ? (
                      <p className="p-4 text-xs text-muted">ยังไม่มีจุดที่ไม่ผ่าน</p>
                    ) : (
                      <div className="p-4 flex flex-col gap-3 text-sm">
                        {current.history.top_failing_points.map((p) => (
                          <div key={p.point_id} className="flex items-center justify-between gap-2">
                            <span className="truncate">{p.name}</span>
                            <Badge tone="fail">ไม่ผ่าน {p.fails} รอบ</Badge>
                          </div>
                        ))}
                        {current.history.top_failing_parts.length > 0 && (
                          <ul className="text-xs text-muted flex flex-col gap-1 border-t border-line pt-2">
                            {current.history.top_failing_parts.map((p, i) => (
                              <li key={i}>
                                {p.point} · {p.part} <span className="text-text">{p.class}</span> {p.status === "missing" ? "ขาด" : "ผิดชนิด"} {p.count} ครั้ง
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}
                  </Card>
                </div>

                <Card>
                  <CardHeader title={`จุดตรวจ (${current.points.length})`} subtitle="ภาพต้นแบบพร้อมกรอบชิ้นส่วนที่สอนไว้" />
                  <div className="p-4 grid gap-3 grid-cols-1 sm:grid-cols-2 xl:grid-cols-3">
                    {current.points.map((p) => (
                      <div key={p.id} className={cx("rounded-lg border overflow-hidden bg-surface", p.issues.length ? "border-review/50" : "border-line")}>
                        <div
                          className="relative bg-viewport"
                          style={{ aspectRatio: p.reference_size ? `${p.reference_size[0]} / ${p.reference_size[1]}` : "16 / 9" }}
                        >
                          {p.has_reference ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img src={api.boards.thumb(current.id, p.index, 480, current.updated_at)} alt={p.name} loading="lazy" className="absolute inset-0 size-full object-contain" />
                          ) : (
                            <div className="absolute inset-0 grid place-items-center text-subtle text-xs gap-1">
                              <ImageOff className="size-5" /> ไม่มีภาพต้นแบบ
                            </div>
                          )}
                        </div>
                        <div className="px-3 py-2 flex flex-col gap-1">
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-sm font-medium truncate">
                              {p.index + 1}. {p.name}
                            </span>
                            <span className="font-mono text-[11px] text-muted">
                              {formatMm(p.x_mm)}, {formatMm(p.y_mm)}
                              {p.zoom > 1 ? ` · ${p.zoom}×` : ""}
                            </span>
                          </div>
                          <span className="text-[11px] text-muted">
                            {p.components} ชิ้น
                            {Object.keys(p.classes).length > 0 && ` · ${Object.entries(p.classes).map(([k, n]) => `${k} ${n}`).join(", ")}`}
                          </span>
                          {p.issues.map((t) => (
                            <span key={t} className="text-[11px] text-review flex items-start gap-1">
                              <AlertTriangle className="size-3 shrink-0 mt-0.5" /> {t}
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </Card>
              </>
            )}
          </div>
        </div>

        {/* ── legacy reference profiles (single-image inspection still uses them) ── */}
        <Card>
          <button type="button" className="w-full px-4 py-3 flex items-center gap-2 text-left cursor-pointer" onClick={() => setLegacyOpen((v) => !v)}>
            <ChevronDown className={cx("size-4 text-muted transition-transform", legacyOpen && "rotate-180")} />
            <span className="text-sm font-medium flex-1">โปรไฟล์อ้างอิงแบบเก่า ({references.length})</span>
            <span className="text-[11px] text-muted">ใช้กับหน้าตรวจภาพเดี่ยว และ golden scan แบบ grid</span>
          </button>
          {legacyOpen && (
            <div className="border-t border-line h-[70vh]">
              <ReferencesView references={references} onRefresh={onRefreshReferences} />
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
