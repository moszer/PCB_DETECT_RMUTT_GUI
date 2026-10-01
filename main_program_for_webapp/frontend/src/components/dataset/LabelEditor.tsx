"use client";

import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Save, Trash2 } from "lucide-react";
import type { DatasetImage, LabelBox } from "@/types";
import { datasetApi, errorMessage } from "@/lib/api";
import { classColor } from "@/lib/format";
import { sfx } from "@/lib/sound";
import { Badge, Button, Modal, SectionLabel, Spinner, TextInput, cx } from "../ui";
import { useToast } from "../Toast";

type Box = LabelBox["bbox"];
type Handle = "nw" | "ne" | "sw" | "se";
type Drag =
  | { mode: "draw"; start: [number, number] }
  | { mode: "move"; index: number; start: [number, number]; orig: Box }
  | { mode: "resize"; index: number; handle: Handle; orig: Box };

const MIN_SIZE = 0.004;
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const normalize = ([a, b, c, d]: Box): Box => [Math.min(a, c), Math.min(b, d), Math.max(a, c), Math.max(b, d)];

interface Props {
  datasetId: string;
  images: DatasetImage[];
  index: number;
  classes: string[];
  readOnly?: boolean;
  onIndex: (index: number) => void;
  onClose: () => void;
  onSaved: (entry: DatasetImage) => void;
  onDeleted: (file: string) => void;
}

/** YOLO label editor: draw / move / resize / relabel / delete boxes, step through images. */
export function LabelEditor({ datasetId, images, index, classes, readOnly, onIndex, onClose, onSaved, onDeleted }: Props) {
  const image = images[index];
  const toast = useToast();
  const listId = useId();
  const [loaded, setLoaded] = useState<{ file: string; boxes: LabelBox[] } | null>(null);
  const [boxes, setBoxes] = useState<LabelBox[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [activeClass, setActiveClass] = useState(classes[0] ?? "component");
  const [draft, setDraft] = useState<Box | null>(null);
  const [saving, setSaving] = useState(false);
  const surface = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);

  // Load this image's labels (the editable copy is reset from the server response).
  const file = image?.file;
  useEffect(() => {
    if (!file) return;
    let current = true;
    datasetApi
      .labels(datasetId, file)
      .then((res) => {
        if (!current) return;
        setLoaded({ file, boxes: res.boxes });
        setBoxes(res.boxes);
        setSelected(null);
      })
      .catch((err) => current && toast.error("โหลด label ไม่สำเร็จ", err));
    return () => {
      current = false;
    };
  }, [datasetId, file, toast]);

  const ready = loaded?.file === image?.file;
  const dirty = ready && JSON.stringify(boxes) !== JSON.stringify(loaded.boxes);
  const knownClasses = [...new Set([...classes, ...boxes.map((b) => b.label)])];

  const save = useCallback(async () => {
    if (!image || !dirty) return true;
    setSaving(true);
    try {
      const entry = await datasetApi.saveLabels(datasetId, image.file, boxes);
      setLoaded({ file: image.file, boxes });
      onSaved(entry);
      sfx.ding();
      return true;
    } catch (err) {
      toast.error("บันทึก label ไม่สำเร็จ", err);
      return false;
    } finally {
      setSaving(false);
    }
  }, [boxes, datasetId, dirty, image, onSaved, toast]);

  const go = useCallback(
    async (next: number) => {
      if (next < 0 || next >= images.length) return;
      if (await save()) onIndex(next);
    },
    [images.length, onIndex, save]
  );

  const removeSelected = useCallback(() => {
    if (selected === null || readOnly) return;
    setBoxes((all) => all.filter((_, i) => i !== selected));
    setSelected(null);
  }, [readOnly, selected]);

  // Keyboard: ←/→ navigate (auto-saves), Delete removes the selected box, Ctrl/⌘+S saves.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.tagName === "INPUT";
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        save();
      } else if (typing) {
        return;
      } else if (e.key === "ArrowRight") go(index + 1);
      else if (e.key === "ArrowLeft") go(index - 1);
      else if (e.key === "Delete" || e.key === "Backspace") removeSelected();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, index, removeSelected, save]);

  const point = (e: React.PointerEvent): [number, number] => {
    const r = surface.current!.getBoundingClientRect();
    return [clamp01((e.clientX - r.left) / r.width), clamp01((e.clientY - r.top) / r.height)];
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (readOnly || !ready) return;
    const target = e.target as HTMLElement;
    const p = point(e);
    const boxIndex = target.closest<HTMLElement>("[data-box]")?.dataset.box;
    const handle = target.dataset.handle as Handle | undefined;
    surface.current!.setPointerCapture(e.pointerId);
    if (boxIndex !== undefined) {
      const i = Number(boxIndex);
      setSelected(i);
      setActiveClass(boxes[i].label);
      drag.current = handle ? { mode: "resize", index: i, handle, orig: boxes[i].bbox } : { mode: "move", index: i, start: p, orig: boxes[i].bbox };
    } else {
      setSelected(null);
      drag.current = { mode: "draw", start: p };
      setDraft([p[0], p[1], p[0], p[1]]);
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const [x, y] = point(e);
    if (d.mode === "draw") return setDraft([d.start[0], d.start[1], x, y]);
    if (d.mode === "move") {
      const [x1, y1, x2, y2] = d.orig;
      const dx = Math.min(1 - x2, Math.max(-x1, x - d.start[0]));
      const dy = Math.min(1 - y2, Math.max(-y1, y - d.start[1]));
      return setBoxes((all) => all.map((b, i) => (i === d.index ? { ...b, bbox: [x1 + dx, y1 + dy, x2 + dx, y2 + dy] } : b)));
    }
    const [x1, y1, x2, y2] = d.orig;
    const next: Box = {
      nw: [x, y, x2, y2],
      ne: [x1, y, x, y2],
      sw: [x, y1, x2, y],
      se: [x1, y1, x, y],
    }[d.handle] as Box;
    setBoxes((all) => all.map((b, i) => (i === d.index ? { ...b, bbox: normalize(next) } : b)));
  };

  const onPointerUp = () => {
    const d = drag.current;
    drag.current = null;
    if (d?.mode === "draw" && draft) {
      const box = normalize(draft);
      setDraft(null);
      if (box[2] - box[0] > MIN_SIZE && box[3] - box[1] > MIN_SIZE) {
        setBoxes((all) => [...all, { label: activeClass.trim() || "component", bbox: box }]);
        setSelected(boxes.length);
      }
    }
  };

  const relabel = (label: string) => {
    setActiveClass(label);
    if (selected !== null) setBoxes((all) => all.map((b, i) => (i === selected ? { ...b, label } : b)));
  };

  const deleteImage = async () => {
    if (!image || !window.confirm(`ลบภาพ ${image.file} และ label ของภาพนี้?`)) return;
    try {
      await datasetApi.removeImage(datasetId, image.file);
      onDeleted(image.file);
    } catch (err) {
      toast.error("ลบภาพไม่สำเร็จ", errorMessage(err));
    }
  };

  if (!image) return null;
  const sel = selected !== null ? boxes[selected] : null;

  return (
    <Modal
      open
      onClose={async () => {
        if (dirty && !window.confirm("มีการแก้ไขที่ยังไม่บันทึก ปิดโดยไม่บันทึก?")) return;
        onClose();
      }}
      size="xl"
      title={
        <>
          {image.file}
          <span className="text-sm font-normal text-muted">
            {index + 1}/{images.length}
          </span>
          {dirty && <Badge tone="review">ยังไม่ได้บันทึก</Badge>}
        </>
      }
      subtitle={`X ${image.x_mm} · Y ${image.y_mm} mm · ${image.width}×${image.height}px`}
      actions={
        <>
          <Button size="sm" variant="ghost" icon={ChevronLeft} disabled={index === 0 || saving} onClick={() => go(index - 1)} title="ภาพก่อนหน้า (←)" />
          <Button size="sm" variant="ghost" icon={ChevronRight} disabled={index === images.length - 1 || saving} onClick={() => go(index + 1)} title="ภาพถัดไป (→)" />
        </>
      }
    >
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="flex items-start justify-center min-w-0">
          <div
            ref={surface}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            className={cx("relative inline-block select-none touch-none rounded-lg overflow-hidden bg-viewport", readOnly ? "cursor-default" : "cursor-crosshair")}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={datasetApi.imageUrl(datasetId, image.file)} alt={image.file} draggable={false} className="block max-w-full max-h-[68vh]" />
            {!ready && (
              <div className="absolute inset-0 grid place-items-center bg-black/30">
                <Spinner className="text-white" />
              </div>
            )}
            {ready &&
              boxes.map((b, i) => {
                const [x1, y1, x2, y2] = b.bbox;
                const color = classColor(b.label);
                const isSel = i === selected;
                return (
                  <div
                    key={i}
                    data-box={i}
                    className={cx("absolute border-2", readOnly ? "" : "cursor-move")}
                    style={{
                      left: `${x1 * 100}%`,
                      top: `${y1 * 100}%`,
                      width: `${(x2 - x1) * 100}%`,
                      height: `${(y2 - y1) * 100}%`,
                      borderColor: isSel ? "#fff" : color,
                      background: isSel ? `${color}40` : `${color}14`,
                      zIndex: isSel ? 2 : 1,
                    }}
                  >
                    <span
                      className="absolute -top-4 left-[-2px] h-4 px-1 text-[10px] leading-4 font-semibold text-white whitespace-nowrap pointer-events-none"
                      style={{ background: isSel ? "#111827" : color }}
                    >
                      {b.label}
                    </span>
                    {isSel &&
                      !readOnly &&
                      (["nw", "ne", "sw", "se"] as Handle[]).map((h) => (
                        <span
                          key={h}
                          data-handle={h}
                          className="absolute size-3 bg-white border border-gray-900 rounded-sm"
                          style={{
                            left: h.endsWith("w") ? -6 : undefined,
                            right: h.endsWith("e") ? -6 : undefined,
                            top: h.startsWith("n") ? -6 : undefined,
                            bottom: h.startsWith("s") ? -6 : undefined,
                            cursor: h === "nw" || h === "se" ? "nwse-resize" : "nesw-resize",
                          }}
                        />
                      ))}
                  </div>
                );
              })}
            {draft && (
              <div
                className="absolute border-2 border-dashed border-white pointer-events-none"
                style={{
                  left: `${Math.min(draft[0], draft[2]) * 100}%`,
                  top: `${Math.min(draft[1], draft[3]) * 100}%`,
                  width: `${Math.abs(draft[2] - draft[0]) * 100}%`,
                  height: `${Math.abs(draft[3] - draft[1]) * 100}%`,
                }}
              />
            )}
          </div>
        </div>

        <div className="flex flex-col gap-4 min-w-0">
          <div className="flex flex-col gap-2">
            <SectionLabel>{sel ? "คลาสของกรอบที่เลือก" : "คลาสสำหรับกรอบใหม่"}</SectionLabel>
            <TextInput
              list={listId}
              value={sel ? sel.label : activeClass}
              disabled={readOnly}
              onChange={(e) => relabel(e.target.value)}
              placeholder="พิมพ์ชื่อคลาส หรือเลือกด้านล่าง"
            />
            <datalist id={listId}>
              {knownClasses.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
            <div className="flex flex-wrap gap-1 max-h-32 overflow-y-auto">
              {knownClasses.map((c) => (
                <button
                  key={c}
                  type="button"
                  disabled={readOnly}
                  onClick={() => relabel(c)}
                  className={cx(
                    "inline-flex items-center gap-1 h-6 px-2 rounded-md text-[11px] border cursor-pointer",
                    (sel ? sel.label : activeClass) === c ? "bg-accent-soft border-accent text-accent" : "border-line hover:bg-surface-2"
                  )}
                >
                  <span className="size-2 rounded-sm" style={{ background: classColor(c) }} />
                  {c}
                </button>
              ))}
            </div>
            {!readOnly && <p className="text-[11px] text-subtle">ลากบนพื้นที่ว่างเพื่อวาดกรอบ · ลากกรอบเพื่อย้าย · ลากมุมเพื่อปรับขนาด · Delete ลบ · ←/→ เปลี่ยนภาพ (บันทึกอัตโนมัติ)</p>}
          </div>

          <div className="flex flex-col gap-2 min-h-0">
            <SectionLabel>กรอบในภาพนี้ ({boxes.length})</SectionLabel>
            <ul className="rounded-lg border border-line divide-y divide-line max-h-64 overflow-y-auto">
              {boxes.map((b, i) => (
                <li key={i} className={cx("flex items-center gap-2 px-2.5 py-1.5 text-sm cursor-pointer", i === selected ? "bg-accent-soft" : "hover:bg-surface-2")} onClick={() => setSelected(i)}>
                  <span className="size-2.5 rounded-sm shrink-0" style={{ background: classColor(b.label) }} />
                  <span className="flex-1 truncate">{b.label}</span>
                  {!readOnly && (
                    <button
                      type="button"
                      aria-label={`ลบกรอบ ${i + 1}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        setBoxes((all) => all.filter((_, j) => j !== i));
                        setSelected(null);
                      }}
                      className="size-7 grid place-items-center rounded-md text-subtle hover:text-fail hover:bg-fail-soft cursor-pointer"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  )}
                </li>
              ))}
              {!boxes.length && ready && <li className="p-3 text-center text-xs text-muted">ไม่มีกรอบ (นับเป็นภาพพื้นหลัง)</li>}
            </ul>
          </div>

          {!readOnly && (
            <div className="flex flex-col gap-2 mt-auto">
              <Button variant="success" icon={Save} loading={saving} disabled={!dirty} onClick={save}>
                {dirty ? "บันทึก label (⌘/Ctrl+S)" : "บันทึกแล้ว"}
              </Button>
              <Button variant="ghost" icon={Trash2} className="text-fail" onClick={deleteImage}>
                ลบภาพนี้ออกจากชุดข้อมูล
              </Button>
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
