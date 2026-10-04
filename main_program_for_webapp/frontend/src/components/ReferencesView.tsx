"use client";

import React, { useEffect, useMemo, useState } from "react";
import { BookMarked, FileDown, Grid3x3, Image as ImageIcon, Trash2 } from "lucide-react";
import type { ReferencePoint, ReferenceProfile, ReferenceSummary } from "@/types";
import { api } from "@/lib/api";
import { classColor, formatDateTime } from "@/lib/format";
import { Badge, Button, Card, CardHeader, EmptyState, Spinner, Stat, cx } from "./ui";
import { useToast } from "./Toast";

interface ReferencesViewProps {
  references: ReferenceSummary[];
  onRefresh: () => void;
}

const TYPE_LABEL = { single: "ภาพเดี่ยว", aoi_grid: "ตาราง AOI" } as const;

export function ReferencesView({ references, onRefresh }: ReferencesViewProps) {
  const [pickedId, select] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<{ id: string; profile: ReferenceProfile | null } | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [importing, setImporting] = useState(false);
  const toast = useToast();

  const selectedId = references.some((r) => r.id === pickedId) ? pickedId : (references[0]?.id ?? null);
  const profile = loaded?.id === selectedId ? loaded.profile : null;
  const loading = selectedId !== null && loaded?.id !== selectedId;

  useEffect(() => {
    if (!selectedId) return;
    let current = true;
    api
      .getReference(selectedId)
      .then((full) => current && setLoaded({ id: selectedId, profile: full }))
      .catch((err) => {
        if (!current) return;
        setLoaded({ id: selectedId, profile: null });
        toast.error("โหลดโปรไฟล์ไม่สำเร็จ", err);
      });
    return () => {
      current = false;
    };
  }, [selectedId, reloadKey, toast]);

  const importDesktop = async () => {
    setImporting(true);
    try {
      const imported = await api.importDesktopReference();
      onRefresh();
      select(imported.id);
      setReloadKey((k) => k + 1);
      toast.success("นำเข้า Refs.json แล้ว", `${imported.points.length} จุดอ้างอิง`);
    } catch (err) {
      toast.error("นำเข้าไม่สำเร็จ", err);
    } finally {
      setImporting(false);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm("ลบโปรไฟล์อ้างอิงนี้? ไม่สามารถกู้คืนได้")) return;
    try {
      await api.deleteReference(id);
      select(null);
      onRefresh();
      toast.success("ลบโปรไฟล์แล้ว");
    } catch (err) {
      toast.error("ลบไม่สำเร็จ", err);
    }
  };

  return (
    <div className="h-full grid grid-cols-1 md:grid-cols-[320px_minmax(0,1fr)] overflow-y-auto md:overflow-hidden">
      <aside className="border-b md:border-b-0 md:border-r border-line bg-surface flex flex-col md:min-h-0">
        <div className="p-3 border-b border-line">
          <Button block icon={FileDown} loading={importing} onClick={importDesktop}>
            นำเข้า Refs.json จากโปรแกรมเดสก์ท็อป
          </Button>
        </div>
        <ul className="flex-1 md:overflow-y-auto p-2 flex flex-col gap-1">
          {references.map((r) => (
            <li key={r.id}>
              <button
                type="button"
                onClick={() => select(r.id)}
                className={cx(
                  "w-full text-left rounded-lg px-3 py-2.5 transition-colors cursor-pointer",
                  r.id === selectedId ? "bg-accent-soft" : "hover:bg-surface-2"
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium truncate">{r.name}</span>
                  <Badge tone={r.profile_type === "single" ? "neutral" : "info"}>{TYPE_LABEL[r.profile_type]}</Badge>
                </div>
                <div className="flex items-center justify-between mt-1 text-[11px] text-muted">
                  <span>{r.points_count} จุด</span>
                  <span>{formatDateTime(r.updated_at)}</span>
                </div>
              </button>
            </li>
          ))}
          {!references.length && (
            <EmptyState icon={BookMarked} title="ยังไม่มีโปรไฟล์">
              นำเข้า Refs.json หรือสร้างจาก “สแกนบอร์ดต้นแบบ” ในหน้าสแกน AOI
            </EmptyState>
          )}
        </ul>
      </aside>

      <section className={cx("p-4 md:p-6 md:overflow-y-auto", !profile && !loading && "hidden md:block")}>
        {loading ? (
          <div className="h-full grid place-items-center">
            <Spinner className="size-6" />
          </div>
        ) : profile ? (
          <ProfileDetail profile={profile} onDelete={() => remove(profile.id)} />
        ) : (
          <EmptyState icon={BookMarked} title="เลือกโปรไฟล์ทางซ้าย" className="h-full hidden md:flex" />
        )}
      </section>
    </div>
  );
}

function ProfileDetail({ profile, onDelete }: { profile: ReferenceProfile; onDelete: () => void }) {
  const rows = useMemo(() => {
    if (profile.profile_type === "single") return profile.points.map((p, i) => ({ group: "", index: i, point: p }));
    return Object.entries(profile.grid_points).flatMap(([key, pts]) => pts.map((p, i) => ({ group: key, index: i, point: p })));
  }, [profile]);

  const byLabel = useMemo(() => {
    const counts = new Map<string, number>();
    rows.forEach(({ point }) => counts.set(point.label, (counts.get(point.label) ?? 0) + 1));
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [rows]);

  const sig = profile.scan_signature as Record<string, unknown> | null | undefined;

  return (
    <div className="max-w-5xl mx-auto flex flex-col gap-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-lg font-semibold">{profile.name}</h2>
            <Badge tone={profile.profile_type === "single" ? "neutral" : "info"}>
              {profile.profile_type === "single" ? <ImageIcon className="size-3" /> : <Grid3x3 className="size-3" />}
              {TYPE_LABEL[profile.profile_type]}
            </Badge>
          </div>
          {profile.description && <p className="text-sm text-muted mt-1">{profile.description}</p>}
          <p className="text-[11px] text-subtle font-mono mt-1">{profile.id}</p>
        </div>
        <Button variant="ghost" icon={Trash2} className="text-fail" onClick={onDelete}>
          ลบโปรไฟล์
        </Button>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Stat label="จุดอ้างอิง" value={rows.length} />
        <Stat label="ชนิดชิ้นส่วน" value={byLabel.length} />
        {profile.profile_type === "aoi_grid" && <Stat label="ตำแหน่งสแกน" value={Object.keys(profile.grid_points).length} />}
        {profile.image_width ? <Stat label="ความละเอียดภาพ" value={`${profile.image_width}×${profile.image_height}`} /> : null}
      </div>

      {sig && (
        <Card>
          <CardHeader title="ลายเซ็นการสแกน" subtitle="การสแกนที่ใช้โปรไฟล์นี้ต้องใช้ค่าเหล่านี้ตรงกัน" />
          <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-2 p-4 text-xs">
            {Object.entries(sig)
              .filter(([k, v]) => v !== null && k !== "custom_points" && k !== "model")
              .map(([k, v]) => (
                <div key={k}>
                  <dt className="text-muted">{k}</dt>
                  <dd className="font-mono tabular">{Array.isArray(v) ? v.join(" × ") : String(v)}</dd>
                </div>
              ))}
          </dl>
        </Card>
      )}

      <Card>
        <CardHeader title="ชนิดชิ้นส่วน" />
        <div className="flex flex-wrap gap-1.5 p-4">
          {byLabel.map(([label, n]) => (
            <span key={label} className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md bg-surface-2 text-xs">
              <span className="size-2 rounded-sm" style={{ background: classColor(label) }} />
              {label}
              <span className="font-mono text-muted">×{n}</span>
            </span>
          ))}
        </div>
      </Card>

      <Card className="overflow-hidden">
        <CardHeader title="รายการจุดอ้างอิง" />
        <div className="overflow-x-auto max-h-[480px]">
          <table className="w-full min-w-[480px] text-sm">
            <thead className="sticky top-0 bg-surface-2 text-[11px] uppercase tracking-wide text-muted">
              <tr>
                <th className="text-left font-medium px-4 py-2">#</th>
                <th className="text-left font-medium px-4 py-2">คลาส</th>
                <th className="text-right font-medium px-4 py-2">X, Y (px)</th>
                <th className="text-right font-medium px-4 py-2">ระยะยอม</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map(({ group, index, point }) => (
                <ReferenceRow key={`${group}-${index}`} group={group} index={index} point={point} />
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function ReferenceRow({ group, index, point }: { group: string; index: number; point: ReferencePoint }) {
  return (
    <tr className="hover:bg-surface-2">
      <td className="px-4 py-2 font-mono text-xs text-muted">
        {group && <span className="text-subtle">{group} · </span>}
        {index + 1}
      </td>
      <td className="px-4 py-2">
        <span className="inline-flex items-center gap-2">
          <span className="size-2 rounded-sm" style={{ background: classColor(point.label) }} />
          {point.label}
        </span>
      </td>
      <td className="px-4 py-2 text-right font-mono tabular text-xs">
        {Math.round(point.x)}, {Math.round(point.y)}
      </td>
      <td className="px-4 py-2 text-right font-mono tabular text-xs text-muted">
        {point.tolerance_px ? `${point.tolerance_px} px` : "ตามค่าที่ตั้ง"}
      </td>
    </tr>
  );
}
