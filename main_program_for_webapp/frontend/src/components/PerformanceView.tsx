"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Download, FileJson, FlaskConical, Gauge, ListChecks, Play, RefreshCw, Table2 } from "lucide-react";
import type { BenchmarkState, PerformanceReport } from "@/types";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { Badge, Button, Card, CardHeader, Field, NumberInput, Segmented, Spinner, Stat, TextInput, Toggle, buttonClasses } from "./ui";
import { useToast } from "./Toast";

const DATA_KEY = "pcb_bench_data";

/**
 * Numbers for comparing machines (computer vs Jetson, thesis table 4.13): this machine's column,
 * a benchmark on a fixed image set (+ mAP50), and accuracy / F1 from scans whose boards were
 * marked good / defective in the scan history.
 */
export function PerformanceView({ refreshKey }: { refreshKey: number }) {
  const toast = useToast();
  const [days, setDays] = useState<number | undefined>(undefined);
  const [sim, setSim] = useState(false);
  const [rep, setRep] = useState<PerformanceReport | null>(null);
  const [job, setJob] = useState<BenchmarkState>({ status: "idle" });
  const [dataYaml, setDataYaml] = useState(() => {
    try {
      return localStorage.getItem(DATA_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [split, setSplit] = useState<"test" | "val">("test");
  const [rounds, setRounds] = useState(3);
  const [warmup, setWarmup] = useState(5);
  const [maxImages, setMaxImages] = useState(50);
  const [label, setLabel] = useState("");

  const load = useCallback(() => {
    api
      .performance({ days, sim })
      .then(setRep)
      .catch((err) => toast.error("โหลดผลทดสอบไม่สำเร็จ", err));
  }, [days, sim, toast]);
  useEffect(load, [load, refreshKey]);

  // Follow a running benchmark; reload the report when it finishes.
  const running = job.status === "running";
  useEffect(() => {
    api.benchmarkStatus().then(setJob).catch(() => undefined);
  }, []);
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => {
      api
        .benchmarkStatus()
        .then((s) => {
          setJob(s);
          if (s.status === "done") {
            toast.success("ทดสอบเสร็จแล้ว", "บันทึกผลลงตารางแล้ว");
            load();
          } else if (s.status === "error") toast.error("ทดสอบไม่สำเร็จ", s.error);
        })
        .catch(() => undefined);
    }, 1000);
    return () => clearInterval(t);
  }, [running, load, toast]);

  const start = async () => {
    try {
      localStorage.setItem(DATA_KEY, dataYaml);
    } catch {
      // only a convenience
    }
    try {
      setJob(await api.startBenchmark({ data_yaml: dataYaml.trim() || undefined, split, rounds, warmup, max_images: maxImages, label }));
    } catch (err) {
      toast.error("เริ่มทดสอบไม่สำเร็จ", err);
    }
  };

  if (!rep) {
    return (
      <div className="py-16 grid place-items-center">
        <Spinner className="size-6" />
      </div>
    );
  }
  const bench = rep.benchmark;
  const b = rep.board;
  const host = rep.system.hostname ?? "เครื่องนี้";
  return (
    <div className="flex flex-col gap-5">
      <Card>
        <CardHeader
          icon={Table2}
          title={`ตารางเปรียบเทียบ — คอลัมน์ของ ${host}`}
          subtitle="รันหน้านี้บนแต่ละเครื่อง (คอมพิวเตอร์ / Jetson) แล้วนำค่ามาใส่ตารางที่ 4.13 · ตัวเลขเป็น ค่าเฉลี่ย ± ส่วนเบี่ยงเบนมาตรฐาน"
          actions={
            <>
              <a href={api.performanceExport("csv", { days, sim })} className={buttonClasses("secondary", "sm")}>
                <Download className="size-4" /> CSV
              </a>
              <a href={api.performanceExport("json", { days, sim })} className={buttonClasses("secondary", "sm")}>
                <FileJson className="size-4" /> JSON
              </a>
            </>
          }
        />
        <div className="px-4 pt-3 flex flex-wrap items-center gap-3">
          <Segmented
            size="sm"
            value={days ?? 0}
            onChange={(d) => setDays(d || undefined)}
            options={[
              { value: 0, label: "ทั้งหมด" },
              { value: 1, label: "24 ชม." },
              { value: 7, label: "7 วัน" },
              { value: 30, label: "30 วัน" },
            ]}
          />
          <div className="w-56">
            <Toggle label="รวมการสแกนจำลอง" checked={sim} onChange={setSim} />
          </div>
          <a href={api.performanceLogUrl()} className="ml-auto text-xs text-accent hover:underline">
            ดาวน์โหลด log ทุกภาพ (JSONL)
          </a>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm mt-3">
            <thead className="bg-surface-2 text-xs text-muted">
              <tr>
                <th className="text-left font-medium px-4 py-2 w-[34%]">รายการเปรียบเทียบ</th>
                <th className="text-left font-medium px-4 py-2">{host}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rep.table.map(([item, value]) => (
                <tr key={item}>
                  <td className="px-4 py-2 align-top">{item}</td>
                  <td className={value.startsWith("–") ? "px-4 py-2 text-subtle" : "px-4 py-2 font-mono text-xs leading-relaxed"}>{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="เวลารวมต่อภาพ (benchmark)" value={bench?.timing_ms?.total ? `${bench.timing_ms.total.mean} ms` : "–"} hint={bench?.throughput_fps ? `${bench.throughput_fps} ภาพ/วินาที` : "ยังไม่ได้ทดสอบ"} tone="accent" />
        <Stat label="mAP50" value={bench?.map?.map50 != null ? `${bench.map.map50}%` : "–"} hint={bench?.map ? `ชุด ${bench.map.split}` : "ใส่ data.yaml เพื่อคำนวณ"} />
        <Stat label="เวลาสแกนต่อบอร์ด" value={rep.scans.scan_time_s ? `${rep.scans.scan_time_s.mean} s` : "–"} hint={`${rep.scans.finished} บอร์ดที่สแกนเสร็จ`} />
        <Stat label="Accuracy / F1 ระดับบอร์ด" value={b.decided ? `${b.accuracy}% / ${b.f1}%` : "–"} hint={`ระบุผลจริงแล้ว ${b.labeled} บอร์ด`} tone="pass" />
      </div>

      <Card>
        <CardHeader
          icon={FlaskConical}
          title="ทดสอบความเร็ว (benchmark)"
          subtitle="ใช้ภาพชุดเดียวกันบนทุกเครื่อง: อุ่นเครื่องก่อน แล้ววัดทุกภาพหลายรอบ · ใส่ data.yaml ของชุดทดสอบเพื่อคำนวณ mAP50 ด้วย"
        />
        <div className="p-4 grid sm:grid-cols-2 lg:grid-cols-6 gap-3 items-end">
          <Field label="data.yaml ของชุดทดสอบ (เว้นว่าง = ภาพตัวอย่าง ไม่คำนวณ mAP)" className="sm:col-span-2 lg:col-span-3">
            <TextInput className="font-mono text-xs" placeholder="/home/…/dataset/data.yaml" value={dataYaml} onChange={(e) => setDataYaml(e.target.value)} />
          </Field>
          <Field label="ชุดภาพ">
            <Segmented className="w-full" value={split} onChange={setSplit} options={[{ value: "test", label: "test" }, { value: "val", label: "val" }]} />
          </Field>
          <Field label="ชื่อการทดสอบ">
            <TextInput placeholder="เช่น Jetson MAXN" value={label} onChange={(e) => setLabel(e.target.value)} />
          </Field>
          <Field label="ภาพสูงสุด">
            <NumberInput value={maxImages} min={1} max={200} step={10} onChange={(v) => setMaxImages(Math.round(v))} />
          </Field>
          <Field label="จำนวนรอบ">
            <NumberInput value={rounds} min={1} max={20} step={1} onChange={(v) => setRounds(Math.round(v))} />
          </Field>
          <Field label="อุ่นเครื่อง (ภาพ)">
            <NumberInput value={warmup} min={0} max={50} step={1} onChange={(v) => setWarmup(Math.round(v))} />
          </Field>
          <div className="sm:col-span-2 lg:col-span-4 flex items-center gap-3 flex-wrap">
            <Button variant="primary" icon={Play} loading={running} disabled={running} onClick={start}>
              เริ่มทดสอบ
            </Button>
            {job.status === "running" && (
              <span className="text-sm text-muted flex items-center gap-2">
                <Gauge className="size-4 animate-pulse" />
                {{ warmup: "อุ่นเครื่อง", timing: "จับเวลา", map: "คำนวณ mAP", start: "เริ่ม" }[job.stage] ?? job.stage} {job.total ? `${job.done}/${job.total}` : ""}
              </span>
            )}
            {job.status === "error" && <span className="text-sm text-fail">{job.error}</span>}
          </div>
        </div>
        {bench && (
          <p className="px-4 pb-4 text-xs text-muted">
            ผลล่าสุด: {formatDateTime(bench.time)} {bench.label ? `· ${bench.label}` : ""} · ไฟล์ {bench.file} (เก็บใน backend/data/benchmarks)
          </p>
        )}
      </Card>

      <Card>
        <CardHeader icon={ListChecks} title="Accuracy และ F1 ระดับบอร์ด" subtitle="บอร์ดเสีย = positive · คิดจากรอบสแกนที่ระบุผลจริงแล้ว (เปิดรอบสแกนในแท็บ “การสแกน AOI” แล้วเลือก ดี / เสีย)" />
        <div className="p-4 grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2 text-center">
          {(
            [
              ["TP", b.tp, "เสีย · ตรวจว่าไม่ผ่าน"],
              ["TN", b.tn, "ดี · ตรวจว่าผ่าน"],
              ["FP", b.fp, "ดี · ตรวจว่าไม่ผ่าน"],
              ["FN", b.fn, "เสีย · ตรวจว่าผ่าน"],
              ["Accuracy", b.accuracy != null ? `${b.accuracy}%` : "–", ""],
              ["Precision", b.precision != null ? `${b.precision}%` : "–", ""],
              ["Recall", b.recall != null ? `${b.recall}%` : "–", ""],
              ["F1", b.f1 != null ? `${b.f1}%` : "–", ""],
            ] as const
          ).map(([k, v, hint]) => (
            <div key={k} className="rounded-lg bg-surface-2 px-2 py-2.5">
              <div className="text-xs text-muted">{k}</div>
              <div className="text-lg font-semibold tabular">{v}</div>
              {hint && <div className="text-[10px] text-subtle leading-tight">{hint}</div>}
            </div>
          ))}
        </div>
        {b.review > 0 && (
          <p className="px-4 pb-4 text-xs text-review">
            <Badge tone="review">REVIEW</Badge> {b.review} บอร์ดไม่นับใน Accuracy/F1 (ระบบไม่ได้ตัดสินผ่าน/ไม่ผ่าน) — รายงานแยกไว้ในวิทยานิพนธ์
          </p>
        )}
      </Card>

      <p className="text-xs text-muted flex items-start gap-2">
        <RefreshCw className="size-3.5 mt-0.5 shrink-0" />
        เวลาอนุมาน = เวลา inference ของ YOLO · เวลารวม = preprocess + inference + postprocess + แปลงผลของระบบต่อหนึ่งภาพ · อัตรา = 1000 ÷ เวลารวม · เวลาสแกนต่อบอร์ด = เริ่มสแกนถึงเสร็จ (รวมการเคลื่อนสเตจ รอภาพนิ่ง และทุกเฟรม) · ใช้งานจริง = ทุกภาพที่ตรวจในช่วงเวลาที่เลือก
      </p>
    </div>
  );
}
