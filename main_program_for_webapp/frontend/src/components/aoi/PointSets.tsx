"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Check, FolderOpen, Pencil, Save, Trash2, X } from "lucide-react";
import type { CustomPointRequest, PointSetMeta } from "@/types";
import { api, errorMessage } from "@/lib/api";
import { usePersistentState } from "@/hooks/usePersistentState";
import { sfx } from "@/lib/sound";
import { Button, Select, SectionLabel, TextInput, cx } from "../ui";
import { useToast } from "../Toast";

type Mode = "idle" | "save" | "rename";
/** Which saved set the current points came from, and what they looked like then. */
type Loaded = { id: string; name: string; snapshot: string } | null;

const snapshotOf = (points: CustomPointRequest[]) => JSON.stringify(points);
const defaultName = () => `ชุดจุดตรวจ ${new Date().toLocaleDateString("th-TH", { day: "numeric", month: "short" })}`;

/** Save the current test points under a name and load them again later (stored on the station). */
export function PointSets({
  points,
  onLoad,
  disabled,
}: {
  points: CustomPointRequest[];
  onLoad: (points: CustomPointRequest[]) => void;
  disabled?: boolean;
}) {
  const toast = useToast();
  const [sets, setSets] = useState<PointSetMeta[] | null>(null);
  const [pick, setPick] = useState("");
  const [loaded, setLoaded] = usePersistentState<Loaded>("pcb_aoi_point_set", null);
  const [mode, setMode] = useState<Mode>("idle");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    api
      .pointSets.list()
      .then(setSets)
      .catch(() => setSets([]));
  }, []);
  useEffect(refresh, [refresh]);

  const current = sets?.find((s) => s.id === loaded?.id) ?? null;
  // A set that was deleted elsewhere is no longer "loaded".
  const active = current ? loaded : null;
  const dirty = !!active && snapshotOf(points) !== active.snapshot;

  const run = async (task: () => Promise<void>, failMessage: string) => {
    setBusy(true);
    try {
      await task();
    } catch (err) {
      toast.error(failMessage, errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const load = () =>
    run(async () => {
      const id = pick || sets?.[0]?.id;
      if (!id) return;
      const unsaved = points.length > 0 && (!active || dirty);
      if (unsaved && !window.confirm(`แทนที่จุดตรวจปัจจุบัน ${points.length} จุด ด้วยชุดที่เลือก?${active ? " (การแก้ไขที่ยังไม่ได้บันทึกจะหายไป)" : " (จุดปัจจุบันยังไม่ได้บันทึกเป็นชุด)"}`)) return;
      const set = await api.pointSets.get(id);
      onLoad(set.points);
      setLoaded({ id: set.id, name: set.name, snapshot: snapshotOf(set.points) });
      sfx.ding();
      toast.success(`โหลด “${set.name}” แล้ว`, `${set.point_count} จุด · ต้นแบบ ${set.component_count} ชิ้น`);
    }, "โหลดชุดจุดตรวจไม่สำเร็จ");

  const saveNew = () =>
    run(async () => {
      const set = await api.pointSets.create(name.trim(), points);
      setLoaded({ id: set.id, name: set.name, snapshot: snapshotOf(points) });
      setPick(set.id);
      setMode("idle");
      refresh();
      sfx.ding();
      toast.success(`บันทึก “${set.name}” แล้ว`, `${set.point_count} จุด · ต้นแบบ ${set.component_count} ชิ้น`);
    }, "บันทึกไม่สำเร็จ");

  const overwrite = () =>
    run(async () => {
      if (!active) return;
      if (!window.confirm(`บันทึกทับชุด “${active.name}” ด้วยจุดตรวจปัจจุบัน ${points.length} จุด?`)) return;
      const set = await api.pointSets.update(active.id, { points });
      setLoaded({ id: set.id, name: set.name, snapshot: snapshotOf(points) });
      refresh();
      sfx.ding();
      toast.success(`อัปเดต “${set.name}” แล้ว`);
    }, "บันทึกทับไม่สำเร็จ");

  const rename = () =>
    run(async () => {
      const id = pick || active?.id;
      if (!id) return;
      const set = await api.pointSets.update(id, { name: name.trim() });
      if (active?.id === id) setLoaded({ ...active, name: set.name });
      setMode("idle");
      refresh();
      toast.success("เปลี่ยนชื่อแล้ว", set.name);
    }, "เปลี่ยนชื่อไม่สำเร็จ");

  const remove = () =>
    run(async () => {
      const target = sets?.find((s) => s.id === (pick || sets[0]?.id));
      if (!target || !window.confirm(`ลบชุด “${target.name}” (${target.point_count} จุด) ถาวร?`)) return;
      await api.pointSets.remove(target.id);
      if (loaded?.id === target.id) setLoaded(null);
      setPick("");
      refresh();
      toast.success(`ลบ “${target.name}” แล้ว`);
    }, "ลบไม่สำเร็จ");

  const selectedId = pick && sets?.some((s) => s.id === pick) ? pick : (sets?.[0]?.id ?? "");
  const selected = sets?.find((s) => s.id === selectedId);
  const formOpen = mode !== "idle";

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-line p-3">
      <div className="flex items-center justify-between gap-2">
        <SectionLabel>ชุดจุดตรวจที่บันทึกไว้</SectionLabel>
        {active && (
          <span className={cx("text-[11px] truncate max-w-[60%]", dirty ? "text-review" : "text-pass")} title={active.name}>
            {dirty ? "แก้ไขแล้ว · " : "ใช้ชุด · "}
            {active.name}
          </span>
        )}
      </div>

      {formOpen ? (
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) (mode === "save" ? saveNew : rename)();
          }}
        >
          <TextInput autoFocus value={name} maxLength={80} onChange={(e) => setName(e.target.value)} placeholder="ตั้งชื่อชุด เช่น บอร์ด Astron รุ่น A" aria-label="ชื่อชุดจุดตรวจ" />
          <div className="flex gap-2">
            <Button type="submit" size="sm" variant="success" icon={Check} loading={busy} disabled={!name.trim()} className="flex-1">
              {mode === "save" ? `บันทึก ${points.length} จุด` : "เปลี่ยนชื่อ"}
            </Button>
            <Button type="button" size="sm" variant="ghost" icon={X} disabled={busy} onClick={() => setMode("idle")}>
              ยกเลิก
            </Button>
          </div>
        </form>
      ) : (
        <>
          {sets === null ? (
            <p className="text-xs text-muted">กำลังโหลดรายการ…</p>
          ) : sets.length ? (
            <div className="flex gap-2">
              <Select value={selectedId} onChange={(e) => setPick(e.target.value)} disabled={disabled || busy} aria-label="ชุดจุดตรวจ" className="flex-1 h-9 text-sm">
                {sets.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} · {s.point_count} จุด
                  </option>
                ))}
              </Select>
              <Button size="sm" variant="primary" icon={FolderOpen} loading={busy} disabled={disabled} onClick={load}>
                โหลด
              </Button>
            </div>
          ) : (
            <p className="text-xs text-muted">ยังไม่มีชุดที่บันทึกไว้ มาร์คจุดตรวจแล้วกด “บันทึกเป็นชุดใหม่”</p>
          )}
          {selected && (
            <p className="text-[11px] text-subtle">
              ต้นแบบ {selected.component_count} ชิ้น · บันทึกเมื่อ {new Date(selected.updated_at * 1000).toLocaleString("th-TH", { dateStyle: "medium", timeStyle: "short" })}
            </p>
          )}
          <div className="flex flex-wrap gap-1.5">
            <Button
              size="sm"
              icon={Save}
              disabled={disabled || busy || !points.length}
              title={points.length ? undefined : "ยังไม่มีจุดตรวจให้บันทึก"}
              onClick={() => {
                setName(defaultName());
                setMode("save");
              }}
            >
              บันทึกเป็นชุดใหม่
            </Button>
            {dirty && (
              <Button size="sm" variant="secondary" icon={Check} disabled={disabled || busy} onClick={overwrite}>
                อัปเดต “{active?.name}”
              </Button>
            )}
            {selected && (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  icon={Pencil}
                  disabled={disabled || busy}
                  onClick={() => {
                    setName(selected.name);
                    setMode("rename");
                  }}
                >
                  เปลี่ยนชื่อ
                </Button>
                <Button size="sm" variant="ghost" icon={Trash2} className="text-fail" disabled={disabled || busy} onClick={remove}>
                  ลบ
                </Button>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
