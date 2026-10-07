"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, Copy, Cpu, ExternalLink, FileCode2, Package, RefreshCw, Search, Terminal } from "lucide-react";
import type { LibraryCatalog, LibraryCheckJob, NodeLibrary, PythonLibrary, UpdateKind } from "@/types";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { Badge, Button, Card, CardHeader, Checkbox, EmptyState, Segmented, Spinner, Stat, TextInput, cx } from "./ui";
import { useToast } from "./Toast";

type Tab = "python" | "node" | "system";
type Row = (PythonLibrary | NodeLibrary) & { kind: "python" | "node" };

const KIND_TONE: Record<UpdateKind, "fail" | "review" | "pass"> = { major: "fail", minor: "review", patch: "pass" };
const KIND_LABEL: Record<UpdateKind, string> = { major: "major", minor: "minor", patch: "patch" };
const KIND_HINT: Record<UpdateKind, string> = {
  major: "รุ่นใหญ่ อาจเปลี่ยนการทำงาน/ต้องแก้โค้ด — ทดสอบก่อนอัปเดต",
  minor: "เพิ่มความสามารถ ปกติใช้แทนกันได้",
  patch: "แก้บั๊ก/ช่องโหว่ ปลอดภัยที่จะอัปเดต",
};

function updateCommand(r: Row): string {
  if (!r.latest) return "";
  return r.kind === "python" ? `venv/bin/pip install "${r.name}==${r.latest}"` : `npm install ${r.name}@${r.latest}`;
}

const updates = (u: Record<UpdateKind, number>) => u.major + u.minor + u.patch;

/** Every library the station runs on (Python, JavaScript, system) and newer releases. */
export function LibrariesView() {
  const toast = useToast();
  const [data, setData] = useState<LibraryCatalog | null>(null);
  const [job, setJob] = useState<LibraryCheckJob | null>(null);
  const [tab, setTab] = useState<Tab>("python");
  const [query, setQuery] = useState("");
  const [directOnly, setDirectOnly] = useState(true);
  const [updatesOnly, setUpdatesOnly] = useState(false);

  const load = useCallback(
    () =>
      api.libraries
        .get()
        .then((c) => {
          setData(c);
          setJob(c.job);
        })
        .catch((e) => toast.error("โหลดรายการไลบรารีไม่ได้", e)),
    [toast]
  );
  useEffect(() => {
    load();
  }, [load]);

  const running = job?.state === "running";
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => {
      api.libraries
        .job()
        .then((j) => {
          setJob(j);
          if (j.state === "running") return;
          if (j.state === "done") toast.success("เช็กอัปเดตเสร็จแล้ว");
          else if (j.state === "error") toast.error("เช็กอัปเดตไม่สำเร็จ", j.message);
          load();
        })
        .catch(() => {});
    }, 700);
    return () => window.clearInterval(id);
  }, [running, load, toast]);

  const check = () =>
    api.libraries
      .check()
      .then(setJob)
      .catch((e) => toast.error("เริ่มเช็กอัปเดตไม่ได้", e));

  const rows: Row[] = useMemo(() => {
    if (!data || tab === "system") return [];
    const list: Row[] = tab === "python" ? data.python.map((r) => ({ ...r, kind: "python" as const })) : data.node.map((r) => ({ ...r, kind: "node" as const }));
    const q = query.trim().toLowerCase();
    return list
      .filter((r) => (!directOnly || r.direct) && (!updatesOnly || r.update) && (!q || r.name.toLowerCase().includes(q) || (r.summary ?? "").toLowerCase().includes(q)))
      .sort((a, b) => Number(b.direct) - Number(a.direct) || rank(b.update) - rank(a.update) || a.name.localeCompare(b.name));
  }, [data, tab, query, directOnly, updatesOnly]);

  const copy = (text: string) =>
    navigator.clipboard?.writeText(text).then(
      () => toast.success("คัดลอกคำสั่งแล้ว", text),
      () => toast.error("คัดลอกไม่ได้")
    );

  if (!data) {
    return (
      <div className="h-full grid place-items-center">
        <Spinner className="size-6" />
      </div>
    );
  }
  const s = data.summary;
  const progress = running && job?.total ? Math.round(((job.done ?? 0) / job.total) * 100) : 0;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-6xl mx-auto p-4 flex flex-col gap-4">
        <Card>
          <CardHeader
            icon={Package}
            title="ไลบรารีของโปรเจกต์"
            subtitle="ทุกแพ็กเกจที่สถานีนี้ใช้อยู่จริง: Python ของ backend, JavaScript ของหน้าเว็บ และส่วนของระบบ (CUDA, OpenCV, Node ฯลฯ) — เช็กเวอร์ชันใหม่จาก PyPI และ npm"
          />
          <div className="px-4 pb-4 grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat label="Python ที่ติดตั้ง" value={s.python.installed} hint={`ใช้ตรง ${s.python.direct} · ที่เหลือมาเป็น dependency`} />
            <Stat
              label="Python มีรุ่นใหม่"
              value={data.checked_at ? updates(s.python.updates) : "–"}
              tone={s.python.updates.major ? "review" : undefined}
              hint={data.checked_at ? `major ${s.python.updates.major} · minor ${s.python.updates.minor} · patch ${s.python.updates.patch}` : "ยังไม่ได้เช็ก"}
            />
            <Stat label="JavaScript ที่ติดตั้ง" value={s.node.installed} hint={`ใช้ตรง ${s.node.direct} (package.json)`} />
            <Stat
              label="JavaScript มีรุ่นใหม่"
              value={data.checked_at ? updates(s.node.updates) : "–"}
              tone={s.node.updates.major ? "review" : undefined}
              hint={data.checked_at ? `major ${s.node.updates.major} · minor ${s.node.updates.minor} · patch ${s.node.updates.patch}` : "เช็กเฉพาะที่ใช้ตรง"}
            />
          </div>
          {s.python.mismatched.length > 0 && (
            <div className="mx-4 mb-4 rounded-lg border border-fail/40 bg-fail-soft px-3 py-2 text-xs text-fail flex items-start gap-1.5">
              <AlertTriangle className="size-3.5 shrink-0 mt-0.5" />
              เวอร์ชันที่ติดตั้งไม่ตรงกับ requirements.txt: {s.python.mismatched.join(", ")} — รัน ./install.sh --no-system --yes
            </div>
          )}
          <div className="px-4 pb-4 flex flex-wrap items-center gap-3">
            <Button icon={RefreshCw} variant="primary" loading={running} onClick={check} disabled={running}>
              {running ? `กำลังเช็ก ${job?.done ?? 0}/${job?.total ?? "?"}` : "เช็กอัปเดต"}
            </Button>
            {running && (
              <div className="w-40 h-1.5 rounded-full bg-surface-2 overflow-hidden">
                <div className="h-full bg-accent transition-[width]" style={{ width: `${progress}%` }} />
              </div>
            )}
            <span className={cx("text-xs", data.stale && data.checked_at ? "text-review" : "text-muted")}>
              {data.checked_at ? `เช็กล่าสุด ${formatDateTime(data.checked_at)}${data.stale ? " (เกิน 1 วัน)" : ""}` : "ยังไม่เคยเช็กอัปเดต"}
              {data.failed.length > 0 && ` · เช็กไม่ได้ ${data.failed.length} ตัว (ไม่อยู่บน PyPI หรือติดต่อไม่ได้)`}
            </span>
            {job?.state === "error" && <span className="text-xs text-fail">{job.message}</span>}
          </div>
          <div className="mx-4 mb-4 rounded-lg border border-line bg-surface-2 px-3 py-2 text-[11px] text-muted flex items-start gap-2">
            <Terminal className="size-3.5 shrink-0 mt-0.5" />
            <span>
              หน้านี้ไม่ติดตั้งอะไร — อัปเดตทั้งชุดบนเครื่องด้วย <code className="font-mono text-text">./run_web.sh --update</code> (ไม่แตะ PyTorch และไม่ข้าม major
              ของ JavaScript อัตโนมัติ) แล้วทดสอบสแกนก่อนใช้งานจริง · กดปุ่ม <Copy className="inline size-3" /> ที่แต่ละตัวเพื่อคัดลอกคำสั่งอัปเดตเฉพาะตัวนั้น
            </span>
          </div>
        </Card>

        <div className="flex flex-wrap items-center gap-3">
          <Segmented
            value={tab}
            onChange={setTab}
            options={[
              { value: "python", label: `Python (${s.python.installed})`, icon: FileCode2 },
              { value: "node", label: `JavaScript (${s.node.installed})`, icon: Package },
              { value: "system", label: `ระบบ (${data.system.length})`, icon: Cpu },
            ]}
          />
          {tab !== "system" && (
            <>
              <div className="relative flex-1 min-w-[12rem] max-w-xs">
                <Search className="size-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-subtle" />
                <TextInput value={query} onChange={(e) => setQuery(e.target.value)} placeholder="ค้นหาชื่อหรือคำอธิบาย" className="pl-8" />
              </div>
              <Checkbox checked={directOnly} onChange={setDirectOnly}>
                เฉพาะที่โปรเจกต์ใช้ตรง
              </Checkbox>
              <Checkbox checked={updatesOnly} onChange={setUpdatesOnly}>
                เฉพาะที่มีรุ่นใหม่
              </Checkbox>
            </>
          )}
        </div>

        {tab === "system" ? (
          <Card>
            <ul className="divide-y divide-line">
              {data.system.map((c) => (
                <li key={c.name} className="px-4 py-2.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-sm">
                  <span className="font-medium min-w-[12rem]">{c.name}</span>
                  <span className={cx("font-mono text-xs", c.version ? "text-text" : "text-subtle")}>{c.version ?? "ไม่พบ"}</span>
                  {c.detail && <span className="text-[11px] text-muted truncate max-w-full">{c.detail}</span>}
                </li>
              ))}
            </ul>
          </Card>
        ) : rows.length === 0 ? (
          <EmptyState icon={Package} title="ไม่มีไลบรารีตามตัวกรองนี้" className="rounded-xl border border-dashed border-line" />
        ) : (
          <Card>
            <div className="hidden md:grid grid-cols-[minmax(0,1.6fr)_7rem_8rem_9rem_minmax(0,1fr)] gap-3 px-4 py-2 border-b border-line text-[11px] text-muted">
              <span>ไลบรารี</span>
              <span>ติดตั้งอยู่</span>
              <span>ที่โปรเจกต์ขอ</span>
              <span>รุ่นล่าสุด</span>
              <span>หมายเหตุ</span>
            </div>
            <ul className="divide-y divide-line">
              {rows.map((r) => (
                <LibraryRow key={`${r.kind}:${r.name}`} r={r} onCopy={copy} />
              ))}
            </ul>
          </Card>
        )}
      </div>
    </div>
  );
}

function rank(u?: UpdateKind | null) {
  return u === "major" ? 3 : u === "minor" ? 2 : u === "patch" ? 1 : 0;
}

function LibraryRow({ r, onCopy }: { r: Row; onCopy: (cmd: string) => void }) {
  const py = r.kind === "python" ? (r as PythonLibrary) : null;
  const js = r.kind === "node" ? (r as NodeLibrary) : null;
  const cmd = updateCommand(r);
  return (
    <li className="px-4 py-2.5 grid gap-x-3 gap-y-1 md:grid-cols-[minmax(0,1.6fr)_7rem_8rem_9rem_minmax(0,1fr)] md:items-center text-sm">
      <div className="min-w-0">
        <div className="flex items-center gap-1.5 min-w-0">
          {r.homepage ? (
            <a href={r.homepage} target="_blank" rel="noreferrer" className="font-medium truncate hover:text-accent inline-flex items-center gap-1">
              {r.name} <ExternalLink className="size-3 shrink-0 text-subtle" />
            </a>
          ) : (
            <span className="font-medium truncate">{r.name}</span>
          )}
          {r.direct ? <Badge tone="accent">ใช้ตรง</Badge> : <Badge>dependency</Badge>}
          {js?.dev && <Badge tone="info">dev</Badge>}
        </div>
        {r.summary && <p className="text-[11px] text-muted truncate">{r.summary}</p>}
        {py && !py.direct && py.needed_by.length > 0 && <p className="text-[11px] text-subtle truncate">ใช้โดย {py.needed_by.join(", ")}</p>}
      </div>
      <span className="font-mono text-xs">
        <span className="md:hidden text-muted">ติดตั้ง </span>
        {r.missing ? <span className="text-fail">ไม่ได้ติดตั้ง</span> : r.version}
      </span>
      <span className="font-mono text-xs text-muted">
        {r.spec ? (
          <>
            <span className="md:hidden">ขอ </span>
            {r.spec}
            {py?.satisfies === false && <span className="text-fail"> · ไม่ตรง</span>}
          </>
        ) : (
          <span className="hidden md:inline">–</span>
        )}
      </span>
      <span className="flex items-center gap-1.5 flex-wrap">
        {r.update && r.latest ? (
          <>
            <span className="font-mono text-xs">{r.latest}</span>
            <span title={KIND_HINT[r.update]}>
              <Badge tone={KIND_TONE[r.update]}>{KIND_LABEL[r.update]}</Badge>
            </span>
            {cmd && !py?.pinned && (
              <button type="button" onClick={() => onCopy(cmd)} className="text-subtle hover:text-accent cursor-pointer" title={`คัดลอก: ${cmd}`}>
                <Copy className="size-3.5" />
              </button>
            )}
          </>
        ) : r.latest ? (
          <span className="text-[11px] text-pass">ล่าสุดแล้ว</span>
        ) : (
          <span className="text-[11px] text-subtle">{r.direct || r.kind === "python" ? "ยังไม่ได้เช็ก" : "ไม่เช็ก (dependency)"}</span>
        )}
      </span>
      <span className="text-[11px] text-muted min-w-0">
        {py?.pinned ? (
          <span className="text-review">{py.pinned}</span>
        ) : py?.released && r.update ? (
          `ออกเมื่อ ${new Date(py.released * 1000).toLocaleDateString("th-TH", { day: "numeric", month: "short", year: "numeric" })}${py.latest_in_spec === false ? " · นอกช่วงที่ requirements ขอ" : ""}`
        ) : (
          [r.license, py?.note].filter(Boolean).join(" · ")
        )}
      </span>
    </li>
  );
}
