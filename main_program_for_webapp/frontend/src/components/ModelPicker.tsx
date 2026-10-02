"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Check, FolderPlus, FolderSearch, HardDriveUpload, Layers, RefreshCw, Search, Trophy, X } from "lucide-react";
import type { ModelFile } from "@/types";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { Badge, Button, Card, CardHeader, IconButton, SectionLabel, Spinner, TextInput, Toggle, cx } from "./ui";
import { useToast } from "./Toast";

interface Catalog {
  current_model: string;
  models: ModelFile[];
  custom_dirs: string[];
  search_dirs: string[];
}

/** Pick YOLO weights: training runs (with mAP), project files, uploads and user-added folders. */
export function ModelPicker({ onRefreshStatus }: { onRefreshStatus: () => void }) {
  const toast = useToast();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [reload, setReload] = useState(0);
  const [query, setQuery] = useState("");
  const [showLast, setShowLast] = useState(false);
  const [loadingModel, setLoadingModel] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [newDir, setNewDir] = useState("");
  const [savingDirs, setSavingDirs] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .listModels()
      .then(setCatalog)
      .catch((err) => toast.error("อ่านรายการโมเดลไม่สำเร็จ", err));
  }, [reload, toast]);

  const { runs, others, bestMap } = useMemo(() => {
    const q = query.trim().toLowerCase();
    const match = (m: ModelFile) => !q || `${m.filename} ${m.path}`.toLowerCase().includes(q);
    const all = (catalog?.models ?? []).filter(match);
    const runs = all.filter((m) => m.source === "run" && (showLast || m.kind !== "last" || m.path === catalog?.current_model));
    const others = all.filter((m) => m.source !== "run");
    const bestMap = Math.max(0, ...runs.map((m) => m.run?.map50_95 ?? 0));
    return { runs, others, bestMap };
  }, [catalog, query, showLast]);

  const choose = async (path: string) => {
    setLoadingModel(path);
    try {
      const res = await api.setModel(path);
      setCatalog((c) => (c ? { ...c, current_model: res.model_path } : c));
      toast.success("โหลดโมเดลแล้ว", res.device);
      onRefreshStatus();
    } catch (err) {
      toast.error("โหลดโมเดลไม่สำเร็จ — ยังใช้โมเดลเดิม", err);
    } finally {
      setLoadingModel(null);
    }
  };

  const upload = async (file: File | undefined) => {
    if (!file) return;
    if (!file.name.endsWith(".pt")) return toast.warning("รองรับเฉพาะไฟล์ .pt");
    setUploading(true);
    try {
      const res = await api.uploadModel(file);
      setReload((r) => r + 1);
      toast.success("อัปโหลดและโหลดโมเดลแล้ว", `${res.filename} · ${res.size_mb} MB`);
      onRefreshStatus();
    } catch (err) {
      toast.error("อัปโหลดโมเดลไม่สำเร็จ", err);
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const saveDirs = async (dirs: string[]) => {
    setSavingDirs(true);
    try {
      await api.updateSettings({ model_search_dirs: dirs });
      setNewDir("");
      setReload((r) => r + 1);
    } catch (err) {
      toast.error("เพิ่มโฟลเดอร์ไม่สำเร็จ", err);
    } finally {
      setSavingDirs(false);
    }
  };

  const row = (m: ModelFile) => {
    const active = m.path === catalog?.current_model;
    const run = m.run;
    const top = run?.map50_95 !== undefined && run.map50_95 === bestMap && bestMap > 0;
    return (
      <li key={m.path}>
        <button
          type="button"
          disabled={active || !!loadingModel}
          onClick={() => choose(m.path)}
          title={m.path}
          className={cx("w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors", active ? "bg-accent-soft" : "hover:bg-surface-2 cursor-pointer")}
        >
          <span className={cx("size-4 rounded-full border-2 grid place-items-center shrink-0", active ? "border-accent bg-accent" : "border-line-strong")}>
            {active && <Check className="size-2.5 text-on-accent" strokeWidth={4} />}
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-1.5 text-sm font-medium">
              <span className="truncate">{m.filename}</span>
              {m.kind === "last" && <Badge>last</Badge>}
              {top && (
                <Badge tone="pass">
                  <Trophy className="size-3" /> ดีที่สุด
                </Badge>
              )}
            </span>
            {run ? (
              <span className="flex flex-wrap gap-x-3 text-[11px] text-muted font-mono tabular">
                {run.map50_95 !== undefined && <span>mAP50-95 {run.map50_95.toFixed(3)}</span>}
                {run.map50 !== undefined && <span>mAP50 {run.map50.toFixed(3)}</span>}
                {run.train_imgsz && <span>imgsz {run.train_imgsz}</span>}
                {run.epochs_done !== undefined && (
                  <span>
                    epoch {run.epochs_done}
                    {run.train_epochs ? `/${run.train_epochs}` : ""}
                  </span>
                )}
              </span>
            ) : (
              <span className="block text-[11px] text-subtle font-mono truncate">{m.path}</span>
            )}
          </span>
          <span className="text-xs text-muted font-mono tabular shrink-0">{m.size_mb} MB</span>
          {m.modified_at && <span className="hidden md:block text-[11px] text-subtle shrink-0 w-36 text-right">{formatDateTime(m.modified_at)}</span>}
          {loadingModel === m.path && <Spinner />}
          {active && <Badge tone="accent">ใช้งานอยู่</Badge>}
        </button>
      </li>
    );
  };

  return (
    <Card>
      <CardHeader
        icon={Layers}
        title="โมเดล YOLO"
        subtitle="เลือกจากผลการเทรน (runs) ได้ทันที — คลิกเพื่อโหลด หากโหลดไม่สำเร็จจะใช้โมเดลเดิมต่อ"
        actions={
          <>
            <IconButton size="sm" icon={RefreshCw} label="สแกนใหม่" onClick={() => setReload((r) => r + 1)} />
            <Button size="sm" icon={HardDriveUpload} loading={uploading} onClick={() => fileInput.current?.click()}>
              อัปโหลด .pt
            </Button>
          </>
        }
      />
      <input ref={fileInput} type="file" accept=".pt" className="hidden" onChange={(e) => upload(e.target.files?.[0])} />

      <div className="flex items-center gap-3 px-4 py-3 border-b border-line flex-wrap">
        <div className="relative flex-1 min-w-48">
          <Search className="size-4 text-subtle absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
          <TextInput className="pl-9" placeholder="ค้นหาชื่อ run หรือไฟล์" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <div className="w-44">
          <Toggle label="แสดง last.pt" checked={showLast} onChange={setShowLast} />
        </div>
      </div>

      {!catalog ? (
        <div className="p-6 grid place-items-center">
          <Spinner />
        </div>
      ) : (
        <div className="max-h-[520px] overflow-y-auto">
          <SectionLabel className="px-4 pt-3 pb-1.5">ผลการเทรน · runs ({runs.length})</SectionLabel>
          <ul className="divide-y divide-line">{runs.map(row)}</ul>
          {!runs.length && <p className="px-4 py-3 text-xs text-muted">ไม่พบโฟลเดอร์ runs/&lt;ชื่อ&gt;/weights/*.pt — เพิ่มโฟลเดอร์โปรเจกต์ที่ใช้เทรนด้านล่าง</p>}
          <SectionLabel className="px-4 pt-4 pb-1.5">ไฟล์อื่น ({others.length})</SectionLabel>
          <ul className="divide-y divide-line">{others.map(row)}</ul>
        </div>
      )}

      <div className="border-t border-line p-4 flex flex-col gap-2">
        <SectionLabel>โฟลเดอร์ที่ใช้ค้นหาโมเดล</SectionLabel>
        <ul className="flex flex-col gap-1">
          {catalog?.search_dirs
            .filter((d) => !catalog.custom_dirs.includes(d))
            .map((d) => (
              <li key={d} className="flex items-center gap-2 text-[11px] font-mono text-subtle truncate" title={d}>
                <FolderSearch className="size-3.5 shrink-0" />
                <span className="truncate">{d}</span>
              </li>
            ))}
          {catalog?.custom_dirs.map((d) => (
            <li key={d} className="flex items-center gap-2 text-[11px] font-mono text-text" title={d}>
              <FolderSearch className="size-3.5 shrink-0 text-accent" />
              <span className="truncate flex-1">{d}</span>
              <IconButton size="sm" icon={X} label="เอาโฟลเดอร์นี้ออก" disabled={savingDirs} onClick={() => saveDirs(catalog.custom_dirs.filter((x) => x !== d))} />
            </li>
          ))}
        </ul>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (newDir.trim() && catalog) saveDirs([...catalog.custom_dirs, newDir.trim()]);
          }}
        >
          <TextInput
            className="font-mono text-xs"
            placeholder="วางพาธโฟลเดอร์ เช่น /Users/.../PCB Electronic components/runs"
            value={newDir}
            onChange={(e) => setNewDir(e.target.value)}
          />
          <Button type="submit" icon={FolderPlus} loading={savingDirs} disabled={!newDir.trim()}>
            เพิ่ม
          </Button>
        </form>
        <p className="text-[11px] text-subtle">
          macOS: คลิกขวาที่โฟลเดอร์ใน Finder → กด Option ค้างไว้ → “Copy … as Pathname” แล้ววางที่นี่ · ระบบค้นหาไฟล์ .pt ในโฟลเดอร์ย่อยให้อัตโนมัติ
        </p>
      </div>
    </Card>
  );
}
