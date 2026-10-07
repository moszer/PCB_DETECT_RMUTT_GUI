"use client";

import React, { useEffect, useState } from "react";
import { BellRing, Send } from "lucide-react";
import type { NotifyConfig } from "@/types";
import { api } from "@/lib/api";
import { Button, Card, CardHeader, Field, NumberInput, Spinner, TextInput, Toggle, cx } from "./ui";
import { useToast } from "./Toast";

/** Scan alerts to Telegram and/or a webhook: when a board fails, repeats failing or yield drops. */
export function NotifyCard({ isOperator }: { isOperator: boolean }) {
  const toast = useToast();
  const [cfg, setCfg] = useState<NotifyConfig | null>(null);
  const [token, setToken] = useState("");
  const [hook, setHook] = useState("");
  const [busy, setBusy] = useState<"save" | "test" | null>(null);

  useEffect(() => {
    api.notify
      .get()
      .then(setCfg)
      .catch(() => {});
  }, []);

  if (!cfg) {
    return (
      <Card>
        <CardHeader icon={BellRing} title="แจ้งเตือนผลสแกน" />
        <div className="p-6 grid place-items-center">
          <Spinner />
        </div>
      </Card>
    );
  }
  const set = (patch: Partial<NotifyConfig>) => setCfg({ ...cfg, ...patch });

  const save = async () => {
    setBusy("save");
    try {
      const { enabled, telegram_chat_id, on_fail, on_error, fail_streak, yield_below_pct, yield_window, send_photo, include_simulation } = cfg;
      const rules = { enabled, telegram_chat_id, on_fail, on_error, fail_streak, yield_below_pct, yield_window, send_photo, include_simulation };
      const next = await api.notify.update({ ...rules, ...(token ? { telegram_token: token } : {}), ...(hook ? { webhook_url: hook } : {}) });
      setCfg(next);
      setToken("");
      setHook("");
      toast.success("บันทึกการแจ้งเตือนแล้ว");
    } catch (err) {
      toast.error("บันทึกไม่สำเร็จ", err);
    } finally {
      setBusy(null);
    }
  };
  const clearSecret = async (which: "telegram_token" | "webhook_url") => {
    try {
      setCfg(await api.notify.update({ [which]: "" }));
      toast.success(which === "telegram_token" ? "ลบ Bot token แล้ว" : "ลบ webhook แล้ว");
    } catch (err) {
      toast.error("ลบไม่สำเร็จ", err);
    }
  };
  const test = async () => {
    setBusy("test");
    try {
      const r = await api.notify.test();
      if (r.ok) toast.success("ส่งข้อความทดสอบแล้ว", "ดูใน Telegram / ช่องที่ตั้งไว้");
      else toast.error("ส่งไม่สำเร็จ", r.problems.join(" · "));
    } catch (err) {
      toast.error("ส่งไม่สำเร็จ", err);
    } finally {
      setBusy(null);
    }
  };

  const locked = !isOperator;
  return (
    <Card>
      <CardHeader
        icon={BellRing}
        title="แจ้งเตือนผลสแกน"
        subtitle="ส่งข้อความเข้า Telegram หรือ webhook (Discord, Slack, LINE bot ฯลฯ) เมื่อบอร์ดไม่ผ่าน ไม่ผ่านติดกัน หรือ yield ตก — ส่งเบื้องหลัง ไม่ทำให้สแกนช้า"
      />
      <div className={cx("p-4 flex flex-col gap-4", locked && "opacity-60 pointer-events-none")}>
        <Toggle label="เปิดการแจ้งเตือน" checked={cfg.enabled} onChange={(v) => set({ enabled: v })} />

        <div className="grid sm:grid-cols-2 gap-4">
          <Field
            label="Telegram Bot token"
            hint={cfg.telegram_token_set ? `บันทึกไว้แล้ว: ${cfg.telegram_token_hint} — ใส่ใหม่เพื่อแทนที่` : "สร้างบอทกับ @BotFather ใน Telegram แล้ววาง token ที่ได้"}
          >
            <div className="flex gap-2">
              <TextInput type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} placeholder="123456789:ABC…" />
              {cfg.telegram_token_set && (
                <Button size="sm" variant="ghost" onClick={() => clearSecret("telegram_token")}>
                  ลบ
                </Button>
              )}
            </div>
          </Field>
          <Field label="Telegram Chat ID" hint="ส่งข้อความหาบอทก่อน แล้วดู chat id จาก @userinfobot · กลุ่มขึ้นต้นด้วย -100">
            <TextInput value={cfg.telegram_chat_id} onChange={(e) => set({ telegram_chat_id: e.target.value })} placeholder="เช่น 123456789" />
          </Field>
          <Field
            label="Webhook (ไม่บังคับ)"
            hint={cfg.webhook_set ? `บันทึกไว้แล้ว: ${cfg.webhook_hint}` : "ลิงก์ https ที่รับ JSON {text, content, verdict, serial, …}"}
            className="sm:col-span-2"
          >
            <div className="flex gap-2">
              <TextInput type="password" autoComplete="off" value={hook} onChange={(e) => setHook(e.target.value)} placeholder="https://discord.com/api/webhooks/…" />
              {cfg.webhook_set && (
                <Button size="sm" variant="ghost" onClick={() => clearSecret("webhook_url")}>
                  ลบ
                </Button>
              )}
            </div>
          </Field>
        </div>

        <div className="grid sm:grid-cols-2 gap-x-6 gap-y-3">
          <Toggle label="บอร์ดไม่ผ่าน (FAIL)" description="บอกจุดและชิ้นที่ผิด พร้อมภาพจุดแรกที่ไม่ผ่าน" checked={cfg.on_fail} onChange={(v) => set({ on_fail: v })} />
          <Toggle label="สแกนผิดพลาด" description="เช่น มอเตอร์ค้าง กล้องหลุด" checked={cfg.on_error} onChange={(v) => set({ on_error: v })} />
          <Toggle label="แนบภาพ" description="ส่งภาพจุดที่ไม่ผ่านไปกับข้อความ Telegram" checked={cfg.send_photo} onChange={(v) => set({ send_photo: v })} />
          <Toggle label="รวมการสแกนจำลอง" description="ปกติปิด (ใช้ทดสอบ)" checked={cfg.include_simulation} onChange={(v) => set({ include_simulation: v })} />
        </div>
        <div className="grid sm:grid-cols-3 gap-4">
          <Field label="ไม่ผ่านติดกัน" hint="แจ้งเมื่อไม่ผ่านติดกันครบกี่บอร์ด (0 = ปิด)">
            <NumberInput value={cfg.fail_streak} min={0} max={50} step={1} suffix="บอร์ด" onChange={(v) => set({ fail_streak: v })} />
          </Field>
          <Field label="Yield ต่ำกว่า" hint="แจ้งครั้งเดียวเมื่อตกลงต่ำกว่านี้ (0 = ปิด)">
            <NumberInput value={cfg.yield_below_pct} min={0} max={100} step={1} suffix="%" onChange={(v) => set({ yield_below_pct: v })} />
          </Field>
          <Field label="คิด yield จาก" hint="บอร์ดล่าสุดกี่บอร์ด">
            <NumberInput value={cfg.yield_window} min={3} max={500} step={1} suffix="บอร์ด" onChange={(v) => set({ yield_window: v })} />
          </Field>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" loading={busy === "save"} onClick={save}>
            บันทึก
          </Button>
          <Button icon={Send} loading={busy === "test"} disabled={!cfg.telegram_token_set && !cfg.webhook_set} onClick={test}>
            ส่งข้อความทดสอบ
          </Button>
        </div>
      </div>
      {locked && <p className="px-4 pb-4 -mt-2 text-xs text-muted">ต้องกด “ขอสิทธิ์ควบคุม” และใส่รหัสสถานีก่อนจึงแก้ได้</p>}
    </Card>
  );
}
