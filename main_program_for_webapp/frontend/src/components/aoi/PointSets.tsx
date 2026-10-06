"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Check, CircuitBoard, FolderOpen, Loader2, LogOut, Pencil, Plus, Trash2, X } from "lucide-react";
import type { CustomPointRequest, PointSetMeta } from "@/types";
import { api, errorMessage } from "@/lib/api";
import { sfx } from "@/lib/sound";
import { Button, Select, SectionLabel, TextInput, cx } from "../ui";
import { useToast } from "../Toast";

/** The board the operator is working on: its points autosave to it. */
export type ActiveBoard = { id: string; name: string } | null;

const AUTOSAVE_MS = 800;
/** Set by the boards page before switching to the scan page: open this board there. */
export const OPEN_BOARD_KEY = "pcb_aoi_open_board";

/**
 * Boards (named sets of test points) stored on the station. A board must be created or
 * opened before marking points; from then on every change to the points is saved to it.
 */
export function PointSets({
  points,
  board,
  onBoardChange,
  onLoad,
  disabled,
  operator,
}: {
  points: CustomPointRequest[];
  board: ActiveBoard;
  onBoardChange: (board: ActiveBoard) => void;
  onLoad: (points: CustomPointRequest[]) => void;
  disabled?: boolean;
  /** Operator mode: open/switch boards only (no create, rename or delete). */
  operator?: boolean;
}) {
  const toast = useToast();
  const [sets, setSets] = useState<PointSetMeta[] | null>(null);
  const [pick, setPick] = useState("");
  const [name, setName] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [save, setSave] = useState<"saved" | "saving" | "error">("saved");
  // What the board holds on the server, to skip saving when nothing changed.
  const synced = useRef<string | null>(null);

  const refresh = useCallback(() => {
    api.pointSets
      .list()
      .then(setSets)
      .catch(() => setSets([]));
  }, []);
  useEffect(refresh, [refresh]);

  // A board deleted elsewhere (or on another browser) is no longer open.
  useEffect(() => {
    if (board && sets && !sets.some((s) => s.id === board.id)) onBoardChange(null);
  }, [board, sets, onBoardChange]);

  // Autosave every change of the points to the open board.
  useEffect(() => {
    if (!board) return;
    const json = JSON.stringify(points);
    if (synced.current === null) synced.current = json; // first render after opening: already in sync
    if (json === synced.current) return;
    const timer = setTimeout(() => {
      setSave("saving");
      api.pointSets
        .update(board.id, { points })
        .then((s) => {
          synced.current = json;
          setSave("saved");
          setSets((all) => all?.map((x) => (x.id === s.id ? { ...x, point_count: s.point_count, component_count: s.component_count, updated_at: s.updated_at } : x)) ?? all);
        })
        .catch(() => setSave("error"));
    }, AUTOSAVE_MS);
    return () => clearTimeout(timer);
  }, [points, board]);

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

  const open = (id: string, nameOf: string, loadedPoints: CustomPointRequest[]) => {
    synced.current = JSON.stringify(loadedPoints);
    setSave("saved");
    onLoad(loadedPoints);
    onBoardChange({ id, name: nameOf });
  };

  // "Open in the scan page" from the boards page: it leaves the board id here and switches tab.
  useEffect(() => {
    let id: string | null = null;
    try {
      id = localStorage.getItem(OPEN_BOARD_KEY);
      if (id) localStorage.removeItem(OPEN_BOARD_KEY);
    } catch {
      id = null;
    }
    if (!id) return;
    api.pointSets
      .get(id)
      .then((set) => {
        open(set.id, set.name, set.points);
        toast.success(`เปิดบอร์ด “${set.name}” แล้ว`, `${set.point_count} จุด`);
      })
      .catch((err) => toast.error("เปิดบอร์ดไม่สำเร็จ", errorMessage(err)));
    // Once, when the scan page opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const create = () =>
    run(async () => {
      // Points already on screen (marked before boards existed) go into the new board.
      const set = await api.pointSets.create(name.trim(), points);
      // Add it to the list right away, or the "deleted elsewhere" check would close it again.
      const { points: _saved, ...meta } = set;
      void _saved;
      setSets((all) => [meta, ...(all ?? []).filter((x) => x.id !== set.id)]);
      open(set.id, set.name, points);
      setName("");
      refresh();
      sfx.ding();
      toast.success(`สร้างบอร์ด “${set.name}” แล้ว`, points.length ? `เก็บจุดที่มีอยู่ ${points.length} จุดไว้ในบอร์ดนี้` : "มาร์คจุดตรวจได้เลย — บันทึกอัตโนมัติ");
    }, "สร้างบอร์ดไม่สำเร็จ");

  const load = () =>
    run(async () => {
      const id = pick || sets?.[0]?.id;
      if (!id) return;
      const set = await api.pointSets.get(id);
      open(set.id, set.name, set.points);
      sfx.ding();
      toast.success(`เปิดบอร์ด “${set.name}”`, `${set.point_count} จุด · ต้นแบบ ${set.component_count} ชิ้น`);
    }, "เปิดบอร์ดไม่สำเร็จ");

  const close = () => {
    if (save !== "saved" && !window.confirm("ยังบันทึกการแก้ไขล่าสุดไม่เสร็จ ปิดบอร์ดเลยไหม?")) return;
    onBoardChange(null);
    onLoad([]);
    synced.current = null;
    refresh();
  };

  const rename = () =>
    run(async () => {
      if (!board) return;
      const set = await api.pointSets.update(board.id, { name: name.trim() });
      onBoardChange({ id: set.id, name: set.name });
      setRenaming(false);
      refresh();
      toast.success("เปลี่ยนชื่อบอร์ดแล้ว", set.name);
    }, "เปลี่ยนชื่อไม่สำเร็จ");

  const remove = (target: PointSetMeta | undefined) =>
    run(async () => {
      if (!target || !window.confirm(`ลบบอร์ด “${target.name}” (${target.point_count} จุด) ถาวร?`)) return;
      await api.pointSets.remove(target.id);
      if (board?.id === target.id) {
        onBoardChange(null);
        onLoad([]);
        synced.current = null;
      }
      setPick("");
      refresh();
      toast.success(`ลบบอร์ด “${target.name}” แล้ว`);
    }, "ลบไม่สำเร็จ");

  const current = sets?.find((s) => s.id === board?.id);

  /* ── A board is open ── */
  if (board) {
    return (
      <div className="flex flex-col gap-2 rounded-lg border border-accent/40 bg-accent-soft/40 p-3" data-tour="board">
        <div className="flex items-center gap-2">
          <CircuitBoard className="size-4 text-accent shrink-0" />
          {renaming ? (
            <form
              className="flex-1 flex gap-1.5"
              onSubmit={(e) => {
                e.preventDefault();
                if (name.trim()) rename();
              }}
            >
              <TextInput autoFocus value={name} maxLength={80} onChange={(e) => setName(e.target.value)} aria-label="ชื่อบอร์ด" className="h-8! text-sm" />
              <Button type="submit" size="sm" variant="success" icon={Check} loading={busy} disabled={!name.trim()} title="บันทึกชื่อ" />
              <Button type="button" size="sm" variant="ghost" icon={X} onClick={() => setRenaming(false)} title="ยกเลิก" />
            </form>
          ) : (
            <>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold truncate" title={board.name}>
                  {board.name}
                </div>
                <div className={cx("text-xs flex items-center gap-1", save === "error" ? "text-fail" : "text-muted")}>
                  {save === "saving" ? (
                    <>
                      <Loader2 className="size-3 animate-spin" /> กำลังบันทึก…
                    </>
                  ) : save === "error" ? (
                    "บันทึกไม่สำเร็จ — จะลองใหม่เมื่อแก้ไขครั้งต่อไป"
                  ) : (
                    <>
                      <Check className="size-3 text-pass" /> บันทึกอัตโนมัติแล้ว · {points.length} จุด
                      {current ? ` · ต้นแบบ ${current.component_count} ชิ้น` : ""}
                    </>
                  )}
                </div>
              </div>
              {!operator && (
                <>
                  <button
                    type="button"
                    title="เปลี่ยนชื่อบอร์ด"
                    disabled={disabled}
                    onClick={() => {
                      setName(board.name);
                      setRenaming(true);
                    }}
                    className="size-7 grid place-items-center rounded-md text-subtle hover:text-text hover:bg-surface-2 cursor-pointer disabled:opacity-40"
                  >
                    <Pencil className="size-3.5" />
                  </button>
                  <button
                    type="button"
                    title="ลบบอร์ดนี้"
                    disabled={disabled || busy}
                    onClick={() => remove(current)}
                    className="size-7 grid place-items-center rounded-md text-subtle hover:text-fail hover:bg-fail-soft cursor-pointer disabled:opacity-40"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </>
              )}
            </>
          )}
        </div>
        {!renaming && (
          <Button size="sm" variant="ghost" icon={LogOut} disabled={disabled} onClick={close} className="self-start">
            {operator ? "เปลี่ยนบอร์ด" : "ปิดบอร์ด / เปลี่ยนบอร์ด"}
          </Button>
        )}
      </div>
    );
  }

  /* ── No board open: create one or open a saved one ── */
  const selectedId = pick && sets?.some((s) => s.id === pick) ? pick : (sets?.[0]?.id ?? "");
  const selected = sets?.find((s) => s.id === selectedId);
  return (
    <div className="flex flex-col gap-3 rounded-lg border-2 border-dashed border-accent/50 p-3" data-tour="board">
      <div className="flex items-center gap-2">
        <CircuitBoard className="size-4 text-accent" />
        <span className="text-sm font-semibold">{operator ? "เลือกบอร์ดที่จะตรวจ" : "บอร์ด"}</span>
      </div>

      {!operator && (
        <form
          className="flex flex-col gap-1.5"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) create();
          }}
        >
          <SectionLabel>สร้างบอร์ดใหม่</SectionLabel>
          <div className="flex gap-2">
            <TextInput value={name} maxLength={80} disabled={disabled} onChange={(e) => setName(e.target.value)} placeholder="ชื่อบอร์ด เช่น Astron CPLD รุ่น A" aria-label="ชื่อบอร์ดใหม่" className="flex-1" />
            <Button type="submit" variant="primary" icon={Plus} loading={busy} disabled={disabled || !name.trim()}>
              สร้าง
            </Button>
          </div>
          {points.length > 0 && <p className="text-xs text-review">จุดที่มาร์คไว้ตอนนี้ {points.length} จุด จะถูกเก็บเข้าบอร์ดใหม่ด้วย</p>}
        </form>
      )}

      {sets && sets.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {!operator && <SectionLabel>หรือเปิดบอร์ดที่บันทึกไว้</SectionLabel>}
          <div className="flex gap-2">
            <Select value={selectedId} onChange={(e) => setPick(e.target.value)} disabled={disabled || busy} aria-label="บอร์ดที่บันทึกไว้" className="flex-1 h-9 text-sm">
              {sets.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} · {s.point_count} จุด
                </option>
              ))}
            </Select>
            <Button icon={FolderOpen} loading={busy} disabled={disabled} onClick={load}>
              เปิด
            </Button>
          </div>
          {selected && (
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-subtle">
                ต้นแบบ {selected.component_count} ชิ้น · แก้ล่าสุด {new Date(selected.updated_at * 1000).toLocaleString("th-TH", { dateStyle: "medium", timeStyle: "short" })}
              </span>
              {!operator && (
                <button type="button" onClick={() => remove(selected)} disabled={disabled || busy} className="text-xs text-fail hover:underline cursor-pointer disabled:opacity-40">
                  ลบ
                </button>
              )}
            </div>
          )}
        </div>
      )}
      {sets === null && <p className="text-xs text-muted">กำลังโหลดรายการบอร์ด…</p>}
      {operator && sets?.length === 0 && <p className="text-xs text-muted">ยังไม่มีบอร์ดที่บันทึกไว้ — ให้วิศวกรสร้างบอร์ดในโหมดวิศวกรก่อน</p>}
    </div>
  );
}
