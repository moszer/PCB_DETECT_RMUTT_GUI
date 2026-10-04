"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Camera, Download, ImageUp, Play, RotateCcw, ScanSearch, Tags, Timer } from "lucide-react";
import type { Detection, InspectionResult, ReferenceSummary, SystemStatus } from "@/types";
import { api } from "@/lib/api";
import { IMGSZ_OPTIONS, classColor, percent, refsOfType } from "@/lib/format";
import type { InspectionParams, SetParams } from "@/lib/params";
import { LiveCameraFeed } from "./LiveCameraFeed";
import { Viewport } from "./Viewport";
import { Badge, Button, EmptyState, Field, SectionLabel, Segmented, Select, Slider, Stat, Toggle, VerdictBadge, buttonClasses, cx } from "./ui";
import { useToast } from "./Toast";
import { sfx } from "@/lib/sound";

interface InspectionViewProps {
  references: ReferenceSummary[];
  params: InspectionParams;
  setParams: SetParams;
  status: SystemStatus | null;
}

const STATUS_TONE = { OK: "pass", WRONG: "fail", EXTRA: "review", UNMATCHED: "neutral" } as const;
const STATUS_LABEL = { OK: "ตรงต้นแบบ", WRONG: "ผิดชนิด", EXTRA: "เกินมา", UNMATCHED: "ไม่ได้เทียบ" } as const;

export function InspectionView({ references, params, setParams, status }: InspectionViewProps) {
  const [source, setSource] = useState<"camera" | "upload">("camera");
  const [upload, setUpload] = useState<{ file: File; url: string; id: number } | null>(null);
  const [pickedReference, setReferenceId] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<{ key: string; result: InspectionResult } | null>(null);
  const [selected, setSelected] = useState<Detection | null>(null);
  const [showLabels, setShowLabels] = useState(true);
  const [dragOver, setDragOver] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const toast = useToast();

  // Only single-image profiles apply here; an AOI grid profile would be rejected by the API.
  const singleRefs = useMemo(() => refsOfType(references, "single"), [references]);
  const referenceId = singleRefs.some((r) => r.id === pickedReference) ? pickedReference : "";

  // A result belongs to the exact inputs that produced it; changing any input hides it
  // and discards responses still in flight for the old inputs.
  const file = upload?.file ?? null;
  const preview = upload?.url ?? null;
  const inputKey = [source, upload?.id ?? "", referenceId, params.conf, params.matchDist, params.failOnExtra, params.imgsz].join("|");
  const inputKeyRef = useRef(inputKey);
  useEffect(() => {
    inputKeyRef.current = inputKey;
  });
  const result = outcome?.key === inputKey ? outcome.result : null;
  const loading = pending === inputKey;
  const setResult = (r: null) => setOutcome(r);

  useEffect(() => () => void (upload && URL.revokeObjectURL(upload.url)), [upload]);

  const pickFile = (f: File | undefined) => {
    if (!f) return;
    if (!f.type.startsWith("image/")) return toast.warning("กรุณาเลือกไฟล์ภาพ", f.name);
    setUpload({ file: f, url: URL.createObjectURL(f), id: Date.now() });
    setSource("upload");
  };

  const inspect = async () => {
    const key = inputKey;
    setPending(key);
    if (source === "camera") sfx.shutter();
    try {
      const options = { ...params, referenceId: referenceId || undefined };
      const res = source === "camera" ? await api.inspectLive(options) : await api.inspectUpload(file!, options);
      if (key !== inputKeyRef.current) return;
      sfx.verdict(res.verdict);
      setOutcome({ key, result: res });
      setSelected(null);
    } catch (err) {
      if (key === inputKeyRef.current) toast.error("ตรวจไม่สำเร็จ", err);
    } finally {
      setPending((p) => (p === key ? null : p));
    }
  };

  const canInspect = source === "camera" || !!file;
  const modelMissing = status && !status.model_loaded;
  const cam = status?.camera_resolution;
  const frameRatio = cam && cam[0] > 0 && cam[1] > 0 ? cam[0] / cam[1] : 4 / 3;

  return (
    <div className="h-full grid grid-cols-1 lg:grid-cols-[300px_minmax(0,1fr)] xl:grid-cols-[300px_minmax(0,1fr)_340px] overflow-y-auto xl:overflow-hidden">
      {/* ── Controls ── */}
      <aside className="border-b lg:border-b-0 lg:border-r border-line bg-surface p-4 flex flex-col gap-5 xl:overflow-y-auto">
        <div className="flex flex-col gap-2">
          <SectionLabel>แหล่งภาพ</SectionLabel>
          <Segmented
            className="w-full"
            value={source}
            onChange={setSource}
            options={[
              { value: "camera", label: "กล้องสด", icon: Camera },
              { value: "upload", label: "อัปโหลด", icon: ImageUp },
            ]}
          />
        </div>

        {source === "upload" && (
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              pickFile(e.dataTransfer.files[0]);
            }}
            className={cx(
              "rounded-xl border-2 border-dashed p-5 text-center transition-colors cursor-pointer",
              dragOver ? "border-accent bg-accent-soft" : "border-line hover:border-line-strong bg-surface-2"
            )}
          >
            <ImageUp className="size-6 mx-auto text-muted" />
            <div className="mt-2 text-sm font-medium text-text truncate">{file ? file.name : "เลือกหรือลากภาพมาวาง"}</div>
            <div className="text-[11px] text-subtle mt-0.5">PNG, JPG, WEBP · ไม่เกิน 50 MB</div>
            <input ref={fileInput} type="file" accept="image/*" className="hidden" onChange={(e) => pickFile(e.target.files?.[0])} />
          </button>
        )}

        <div className="flex flex-col gap-4">
          <SectionLabel>การเทียบต้นแบบ</SectionLabel>
          <Field
            label="โปรไฟล์อ้างอิง"
            hint={singleRefs.length ? "ไม่เลือก = ตรวจจับอย่างเดียว ผลเป็น REVIEW" : "ยังไม่มีโปรไฟล์ภาพเดี่ยว — นำเข้าได้ที่หน้าโปรไฟล์อ้างอิง"}
          >
            <Select value={referenceId} onChange={(e) => setReferenceId(e.target.value)}>
              <option value="">ไม่เทียบ (ตรวจจับอย่างเดียว)</option>
              {singleRefs.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name} · {r.points_count} จุด
                </option>
              ))}
            </Select>
          </Field>
          <Slider label="ความมั่นใจขั้นต่ำ" value={params.conf} min={0.01} max={1} step={0.01} format={percent} onChange={(conf) => setParams({ conf })} />
          <Slider
            label="ระยะจับคู่สูงสุด"
            value={params.matchDist}
            min={1}
            max={500}
            step={1}
            format={(v) => `${v} px`}
            onChange={(matchDist) => setParams({ matchDist })}
            disabled={!referenceId}
          />
          <Field label="ขนาดภาพเข้าโมเดล (imgsz)">
            <Select value={params.imgsz} onChange={(e) => setParams({ imgsz: Number(e.target.value) })}>
              {IMGSZ_OPTIONS.map((v) => (
                <option key={v} value={v}>
                  {v} px{v === 1280 ? " (แนะนำ)" : ""}
                </option>
              ))}
            </Select>
          </Field>
          <Toggle
            label="ตัดสินไม่ผ่านเมื่อพบชิ้นเกิน"
            description="ชิ้นส่วนที่ไม่อยู่ในต้นแบบจะทำให้ผลเป็น FAIL"
            checked={params.failOnExtra}
            onChange={(failOnExtra) => setParams({ failOnExtra })}
            disabled={!referenceId}
          />
        </div>

        <div className="mt-auto flex flex-col gap-2">
          {modelMissing && <p className="text-xs text-fail">ยังไม่ได้โหลดโมเดล — ตั้งค่าได้ที่หน้าตั้งค่าสถานี</p>}
          <Button variant="primary" size="lg" block icon={source === "camera" ? Camera : Play} loading={loading} disabled={!canInspect} onClick={inspect}>
            {loading ? "กำลังวิเคราะห์…" : source === "camera" ? "ถ่ายภาพและตรวจ" : "ตรวจภาพนี้"}
          </Button>
        </div>
      </aside>

      {/* ── Viewport ── */}
      <section className="p-3 flex flex-col gap-3 xl:min-h-0">
        {result && (
          <div className="flex items-center gap-2 flex-wrap">
            <VerdictBadge verdict={result.verdict} />
            <span className="text-xs text-muted">{result.summary.total_detections} ชิ้นที่ตรวจพบ</span>
            <div className="ml-auto flex items-center gap-1.5">
              <Button size="sm" variant="ghost" icon={Tags} onClick={() => setShowLabels((v) => !v)}>
                {showLabels ? "ซ่อนป้าย" : "แสดงป้าย"}
              </Button>
              {result.annotated_url && (
                <a href={result.annotated_url} download target="_blank" rel="noreferrer" className={buttonClasses("secondary", "sm")}>
                  <Download className="size-4" />
                  ภาพผลตรวจ
                </a>
              )}
              {source === "camera" && (
                <Button size="sm" icon={RotateCcw} onClick={() => setResult(null)}>
                  กลับไปภาพสด
                </Button>
              )}
            </div>
          </div>
        )}
        {/* Below xl the image area takes the camera's shape (no tall letterboxed column); at xl it fills the column. */}
        <div
          className="w-full mx-auto aspect-(--frame) max-w-[calc(72dvh*var(--frame))] xl:aspect-auto xl:max-w-none xl:flex-1 xl:min-h-0"
          style={{ "--frame": frameRatio } as React.CSSProperties}
        >
          {source === "camera" && !result ? (
            <LiveCameraFeed className="size-full" />
          ) : (
            <Viewport
              imageUrl={result?.image_url || preview}
              detections={result?.detections}
              referenceEval={result?.reference_eval}
              selectedDetectionId={selected?.id}
              onSelectDetection={setSelected}
              showLabels={showLabels}
            />
          )}
        </div>
      </section>

      {/* ── Results ── */}
      <aside className="border-t xl:border-t-0 xl:border-l border-line bg-surface lg:col-span-2 xl:col-span-1 xl:overflow-y-auto">
        {!result ? (
          <EmptyState icon={ScanSearch} title="ยังไม่มีผลตรวจ" className="h-full">
            {source === "camera" ? "จัดบอร์ดให้อยู่ในกรอบแล้วกด “ถ่ายภาพและตรวจ”" : "เลือกภาพแล้วกด “ตรวจภาพนี้”"}
          </EmptyState>
        ) : (
          <ResultPanel result={result} selected={selected} onSelect={setSelected} />
        )}
      </aside>
    </div>
  );
}

function ResultPanel({
  result,
  selected,
  onSelect,
}: {
  result: InspectionResult;
  selected: Detection | null;
  onSelect: (d: Detection) => void;
}) {
  const s = result.summary;
  const problems = result.reference_eval.filter((r) => r.status !== "OK");
  return (
    <div className="p-4 flex flex-col gap-4">
      <div key={result.timestamp} className={cx("rounded-xl p-4 border", result.verdict === "FAIL" ? "animate-shake" : "animate-rise", {
        PASS: "bg-pass-soft border-pass/30",
        FAIL: "bg-fail-soft border-fail/30",
        REVIEW: "bg-review-soft border-review/30",
        ERROR: "bg-surface-2 border-line",
      }[result.verdict])}>
        <VerdictBadge verdict={result.verdict} size="lg" />
        {result.reason && <p className="text-sm text-text mt-2 leading-relaxed">{result.reason}</p>}
        {result.is_simulation && <p className="text-xs text-review mt-1">กล้องจำลอง — ไม่ใช่ผลตรวจจริง</p>}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Stat label="ต้นแบบคาดหวัง" value={s.total_refs} />
        <Stat label="ตรวจพบ" value={s.total_detections} tone="accent" />
        <Stat label="ตรงต้นแบบ" value={s.ok} tone="pass" />
        <Stat label="ขาด / ผิดชนิด" value={`${s.missing} / ${s.wrong}`} tone={s.missing + s.wrong ? "fail" : undefined} />
      </div>
      {s.extra > 0 && s.total_refs > 0 && <Badge tone="review">ชิ้นเกินจากต้นแบบ {s.extra} ชิ้น</Badge>}

      {problems.length > 0 && (
        <div className="flex flex-col gap-2">
          <SectionLabel>ตำแหน่งที่มีปัญหา</SectionLabel>
          <ul className="rounded-lg border border-line divide-y divide-line text-sm">
            {problems.map((p) => (
              <li key={p.ref_index} className="flex items-center justify-between gap-2 px-3 py-2">
                <span className="truncate">
                  <span className="text-subtle font-mono text-xs mr-1.5">#{p.ref_index + 1}</span>
                  {p.ref.label}
                  {p.status === "WRONG" && p.det && <span className="text-muted"> → {p.det.label}</span>}
                </span>
                <Badge tone="fail">{p.status === "MISSING" ? "ขาด" : "ผิดชนิด"}</Badge>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-col gap-2">
        <SectionLabel>ชิ้นส่วนที่ตรวจพบ ({result.detections.length})</SectionLabel>
        <ul className="rounded-lg border border-line divide-y divide-line max-h-72 overflow-y-auto">
          {result.detections.map((d) => (
            <li key={d.id}>
              <button
                type="button"
                onClick={() => onSelect(d)}
                className={cx(
                  "w-full flex items-center gap-2 px-3 py-2 text-left text-sm cursor-pointer",
                  selected?.id === d.id ? "bg-accent-soft" : "hover:bg-surface-2"
                )}
              >
                <span className="size-2.5 rounded-sm shrink-0" style={{ background: classColor(d.label) }} />
                <span className="flex-1 truncate">{d.label}</span>
                <span className="font-mono tabular text-xs text-muted">{percent(d.conf)}</span>
                {s.total_refs > 0 && <Badge tone={STATUS_TONE[d.status]}>{STATUS_LABEL[d.status]}</Badge>}
              </button>
            </li>
          ))}
        </ul>
        {selected && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-lg bg-surface-2 p-3 text-xs">
            <dt className="text-muted">คลาส</dt>
            <dd className="font-medium">{selected.label}</dd>
            <dt className="text-muted">ความมั่นใจ</dt>
            <dd className="font-mono tabular">{percent(selected.conf)}</dd>
            <dt className="text-muted">จุดกึ่งกลาง</dt>
            <dd className="font-mono tabular">
              {Math.round(selected.cx)}, {Math.round(selected.cy)} px
            </dd>
            <dt className="text-muted">กรอบ</dt>
            <dd className="font-mono tabular">{selected.box.map(Math.round).join(", ")}</dd>
          </dl>
        )}
      </div>

      <div className="flex items-center gap-2 text-xs text-muted">
        <Timer className="size-3.5" />
        อนุมาน {result.speed_ms?.inference?.toFixed(1) ?? "–"} ms · {result.device_used}
      </div>
    </div>
  );
}
