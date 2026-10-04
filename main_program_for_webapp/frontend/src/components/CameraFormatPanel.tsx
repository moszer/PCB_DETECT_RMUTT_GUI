"use client";

import React, { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import {
  CAPTURE_SIZES,
  SQUARE_SIZES,
  applyCameraFormat,
  cropZoom,
  formatFromCamera,
  type CameraFormat,
  type CaptureId,
} from "@/lib/cameraFormat";
import type { CameraDevice } from "@/types";
import { Button, Field, NumberInput, Segmented, Select, Spinner, cx } from "./ui";
import { useToast } from "./Toast";

/**
 * The one camera settings form (device + capture resolution + output size + fit/crop),
 * shown as a popover from the live view and from the point-teaching dialog.
 */
export function CameraFormatPanel({
  onClose,
  onApplied,
  locked,
  className,
  style,
}: {
  onClose: () => void;
  onApplied?: (fmt: CameraFormat) => void;
  locked?: boolean;
  className?: string;
  style?: React.CSSProperties;
}) {
  const toast = useToast();
  const panel = useRef<HTMLDivElement>(null);
  const [devices, setDevices] = useState<CameraDevice[] | null>(null);
  const [device, setDevice] = useState(0);
  const [fmt, setFmt] = useState<CameraFormat | null>(null);
  const [actual, setActual] = useState<[number, number] | null>(null);
  const [custom, setCustom] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .listCameras()
      .then((res) => {
        setDevices(res.devices);
        setDevice(res.current_index);
        const f = formatFromCamera(res);
        setFmt(f);
        setActual(res.capture_resolution ?? null);
        setCustom(!!f.output && (f.output[0] !== f.output[1] || !SQUARE_SIZES.includes(f.output[0] as (typeof SQUARE_SIZES)[number])));
      })
      .catch((err) => toast.error("อ่านสถานะกล้องไม่สำเร็จ", err));
  }, [toast]);

  useEffect(() => {
    const onDown = (e: MouseEvent) => panel.current && !panel.current.contains(e.target as Node) && onClose();
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [onClose]);

  const apply = async () => {
    if (!fmt) return;
    setBusy(true);
    try {
      const res = await applyCameraFormat(device, fmt);
      const cams = await api.listCameras();
      const cap = cams.capture_resolution;
      const want = CAPTURE_SIZES[fmt.capture].size;
      if (res.is_mock) toast.warning("เปิดกล้องจริงไม่ได้ — ใช้ภาพจำลอง");
      else if (cap && (cap[0] < want[0] || cap[1] < want[1]))
        toast.warning("กล้องให้ความละเอียดต่ำกว่าที่ขอ", `ขอ ${want[0]}×${want[1]} ได้ ${cap[0]}×${cap[1]} — ภาพ ${res.resolution[0]}×${res.resolution[1]}`);
      else toast.success("ตั้งค่ากล้องแล้ว", `ภาพ ${res.resolution[0]}×${res.resolution[1]}${cap ? ` (กล้องส่ง ${cap[0]}×${cap[1]})` : ""}`);
      onApplied?.(fmt);
      onClose();
    } catch (err) {
      toast.error("ตั้งค่ากล้องไม่สำเร็จ", err);
    } finally {
      setBusy(false);
    }
  };

  const capSize = fmt ? CAPTURE_SIZES[fmt.capture].size : null;
  const zoom = fmt?.output && capSize ? cropZoom(capSize, fmt.output) : null;
  const sizeValue = !fmt?.output ? "native" : custom ? "custom" : String(fmt.output[0]);

  return (
    <div ref={panel} style={style} className={cx(
        // Scrolls inside its own box: it floats over a camera view that clips anything taller.
        "w-80 max-w-full rounded-xl border border-line bg-surface p-4 shadow-pop flex flex-col gap-3 overflow-y-auto overscroll-contain animate-rise",
        className
      )}>
      <div className="text-sm font-semibold text-text">ตั้งค่ากล้องและขนาดภาพ</div>
      {!fmt || !devices ? (
        <div className="py-6 grid place-items-center">
          <Spinner />
        </div>
      ) : (
        <>
          <Field label="อุปกรณ์กล้อง">
            <Select value={device} onChange={(e) => setDevice(Number(e.target.value))} disabled={locked}>
              {(devices.length ? devices : [{ index: 0, name: "Camera 0", active: false }]).map((d) => (
                <option key={d.index} value={d.index}>
                  {d.name}
                  {d.active ? " • ใช้งานอยู่" : ""}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="ความละเอียดที่ถ่ายจากกล้อง">
            <Segmented
              className="w-full"
              size="sm"
              disabled={locked}
              value={fmt.capture}
              onChange={(capture: CaptureId) => setFmt({ ...fmt, capture })}
              options={(Object.keys(CAPTURE_SIZES) as CaptureId[]).map((id) => ({ value: id, label: id === "4k" ? "4K" : id }))}
            />
          </Field>

          <Field label="ขนาดภาพที่ใช้ตรวจ">
            <Select
              value={sizeValue}
              disabled={locked}
              onChange={(e) => {
                const v = e.target.value;
                if (v === "native") {
                  setCustom(false);
                  setFmt({ ...fmt, output: null });
                } else if (v === "custom") {
                  setCustom(true);
                  setFmt({ ...fmt, output: fmt.output ?? [800, 600] });
                } else {
                  setCustom(false);
                  setFmt({ ...fmt, output: [Number(v), Number(v)] });
                }
              }}
            >
              <option value="native">เต็มภาพจากกล้อง ({capSize?.[0]}×{capSize?.[1]})</option>
              {SQUARE_SIZES.map((s) => (
                <option key={s} value={s}>
                  สี่เหลี่ยมจัตุรัส {s}×{s}
                </option>
              ))}
              <option value="custom">กำหนดเอง (กว้าง × สูง)…</option>
            </Select>
          </Field>
          {custom && fmt.output && (
            <div className="grid grid-cols-2 gap-2 -mt-1">
              <NumberInput value={fmt.output[0]} min={64} max={8192} step={32} suffix="W" disabled={locked} onChange={(w) => setFmt({ ...fmt, output: [Math.round(w), fmt.output![1]] })} />
              <NumberInput value={fmt.output[1]} min={64} max={8192} step={32} suffix="H" disabled={locked} onChange={(h) => setFmt({ ...fmt, output: [fmt.output![0], Math.round(h)] })} />
            </div>
          )}

          {fmt.output && (
            <Field label="วิธีได้ภาพ">
              <Segmented
                className="w-full"
                size="sm"
                disabled={locked}
                value={fmt.mode}
                onChange={(mode) => setFmt({ ...fmt, mode })}
                options={[
                  { value: "fit", label: "ย่อ (เห็นกว้าง)" },
                  { value: "crop", label: "ตัดกลาง 1:1 (ซูม)" },
                ]}
              />
            </Field>
          )}

          {fmt.output && zoom !== null && (
            <p className={cx("text-[11px] leading-snug", fmt.mode === "crop" && zoom < 1 ? "text-review" : "text-subtle")}>
              {fmt.mode === "fit"
                ? `ตัดกลางให้ได้สัดส่วน ${fmt.output[0]}:${fmt.output[1]} แล้วย่อลง — เห็นพื้นที่กว้างที่สุด`
                : zoom < 1
                  ? `ภาพจากกล้องเล็กกว่า ${fmt.output[0]}×${fmt.output[1]} — ตัด 1:1 ไม่ได้ ระบบจะใช้แบบย่อ/ขยายแทน`
                  : `พิกเซลจริงจากกล้อง ไม่ย่อ — เห็นพื้นที่แคบลง ${zoom.toFixed(1)} เท่าเทียบกับแบบย่อ (ชิ้นเล็กชัดขึ้น)`}
            </p>
          )}
          {actual && <p className="text-[11px] text-subtle">ตอนนี้กล้องส่ง {actual[0]}×{actual[1]}</p>}
          <p className="text-[11px] text-review">เปลี่ยนขนาดหรือวิธีได้ภาพแล้ว ต้องสอนต้นแบบใหม่และปรับระยะห่างภาพตอนสแกน</p>
          {locked && <p className="text-[11px] text-review">เปลี่ยนกล้องไม่ได้ระหว่างสแกน</p>}

          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={onClose}>
              ปิด
            </Button>
            <Button size="sm" variant="primary" onClick={apply} loading={busy} disabled={locked}>
              ใช้ค่านี้
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
