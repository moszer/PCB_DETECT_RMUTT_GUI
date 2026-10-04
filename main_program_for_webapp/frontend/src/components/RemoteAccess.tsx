"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Check, Copy, ExternalLink, Globe, Lock, QrCode, RefreshCw, Shield, Wifi } from "lucide-react";
import type { RemoteAccess } from "@/types";
import { api } from "@/lib/api";
import { Badge, Button, Card, CardHeader, IconButton, Modal, Spinner, cx } from "./ui";
import { useToast } from "./Toast";

type Link = { key: string; label: string; hint: string; url: string; icon: typeof Wifi };

/** Every address this station can be opened at, best first. */
function linksOf(r: RemoteAccess | null): Link[] {
  if (!r) return [];
  const links: Link[] = [];
  if (r.serve) {
    links.push({
      key: "serve",
      label: r.serve.funnel ? "อินเทอร์เน็ต (Tailscale Funnel)" : "Tailscale HTTPS",
      hint: r.serve.funnel ? "ใครก็เปิดได้จากทุกที่" : "เฉพาะอุปกรณ์ใน tailnet ของคุณ",
      url: r.serve.url,
      icon: r.serve.funnel ? Globe : Shield,
    });
  }
  if (r.state === "Running" && r.direct_url) links.push({ key: "ts-ip", label: "Tailscale IP", hint: "อุปกรณ์ใน tailnet (ไม่ต้องเปิด HTTPS)", url: r.direct_url, icon: Shield });
  for (const l of r.lan) links.push({ key: l.url, label: `วงแลน · ${l.interface}`, hint: "Wi-Fi / LAN เดียวกัน", url: l.url, icon: Wifi });
  return links;
}

function useRemoteAccess() {
  const [data, setData] = useState<RemoteAccess | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(() => {
    api.remote
      .get()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);
  useEffect(refresh, [refresh]);
  return { data, setData, error, refresh };
}

function Qr({ url, size = 176 }: { url: string; size?: number }) {
  return (
    <div className="rounded-xl bg-white p-2 shadow-card" style={{ width: size, height: size }}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={api.qrUrl(url)} alt={`QR code ของ ${url}`} className="size-full [image-rendering:pixelated]" />
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <IconButton
      size="sm"
      icon={done ? Check : Copy}
      label="คัดลอกลิงก์"
      onClick={() => {
        navigator.clipboard?.writeText(text).then(() => {
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        });
      }}
    />
  );
}

/** List of links, each with a QR code; the selected one is shown large. */
function LinkList({ links }: { links: Link[] }) {
  const [picked, setPicked] = useState<string | null>(null);
  const current = links.find((l) => l.key === picked) ?? links[0];
  if (!current) return <p className="text-sm text-muted">ไม่พบที่อยู่เครือข่ายของเครื่องนี้</p>;
  return (
    <div className="flex flex-col sm:flex-row gap-4 items-center sm:items-start">
      <div className="flex flex-col items-center gap-1.5 shrink-0">
        <Qr url={current.url} />
        <span className="text-xs text-muted">สแกนด้วยกล้องมือถือ</span>
      </div>
      <ul className="flex-1 min-w-0 w-full flex flex-col gap-1.5">
        {links.map((l) => (
          <li key={l.key}>
            <div
              role="button"
              tabIndex={0}
              onClick={() => setPicked(l.key)}
              onKeyDown={(e) => e.key === "Enter" && setPicked(l.key)}
              className={cx(
                "flex items-center gap-2.5 rounded-lg border px-3 py-2 cursor-pointer transition-colors",
                l.key === current.key ? "border-accent bg-accent-soft/50" : "border-line hover:bg-surface-2"
              )}
            >
              <l.icon className="size-4 text-muted shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="text-xs text-muted">
                  {l.label} · {l.hint}
                </div>
                <div className="font-mono text-sm truncate">{l.url}</div>
              </div>
              <QrCode className={cx("size-4 shrink-0", l.key === current.key ? "text-accent" : "text-subtle")} />
              <span onClick={(e) => e.stopPropagation()} className="flex">
                <CopyButton text={l.url} />
              </span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Header button: QR codes to open this station on a phone. */
export function OpenOnPhoneButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="เปิดบนมือถือ (QR code)"
        title="เปิดบนมือถือ (QR code)"
        className="size-9 grid place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-text cursor-pointer"
      >
        <QrCode className="size-4" />
      </button>
      {open && <PhoneModal onClose={() => setOpen(false)} />}
    </>
  );
}

function PhoneModal({ onClose }: { onClose: () => void }) {
  const { data, error } = useRemoteAccess();
  return (
    <Modal open onClose={onClose} size="md" title="เปิดสถานีบนอุปกรณ์อื่น" subtitle="สแกน QR code หรือคัดลอกลิงก์ · ตั้งค่า Tailscale ได้ที่หน้าตั้งค่าสถานี">
      {data ? <LinkList links={linksOf(data)} /> : error ? <p className="text-sm text-fail">{error}</p> : <Spinner />}
    </Modal>
  );
}

/** Settings card: links + QR, and the Tailscale tunnel (serve inside the tailnet, or funnel to the internet). */
export function RemoteAccessPanel({ isOperator }: { isOperator: boolean }) {
  const toast = useToast();
  const { data, setData, error, refresh } = useRemoteAccess();
  const [busy, setBusy] = useState<string | null>(null);

  // While waiting for the Tailscale login, check every few seconds.
  const waiting = data?.state === "NeedsLogin" || data?.state === "Starting";
  useEffect(() => {
    if (!waiting) return;
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [waiting, refresh]);

  const run = async (key: string, task: () => Promise<RemoteAccess>, done: string) => {
    setBusy(key);
    try {
      setData(await task());
      toast.success(done);
    } catch (err) {
      toast.error("ตั้งค่า Tailscale ไม่สำเร็จ", err);
    } finally {
      setBusy(null);
    }
  };

  const lock = isOperator ? null : "ขอสิทธิ์ควบคุมก่อน";
  const ts = data;
  return (
    <Card>
      <CardHeader
        icon={Globe}
        title="เข้าใช้งานจากที่อื่น"
        subtitle="ลิงก์และ QR code สำหรับเปิดบนมือถือ/แท็บเล็ต และอุโมงค์ Tailscale สำหรับเข้าจากนอกวงแลน"
        actions={<IconButton size="sm" icon={RefreshCw} label="รีเฟรช" onClick={refresh} />}
      />
      <div className="p-4 flex flex-col gap-5">
        {!ts ? (
          error ? <p className="text-sm text-fail">{error}</p> : <Spinner />
        ) : (
          <>
            <LinkList links={linksOf(ts)} />

            <section className="flex flex-col gap-3 border-t border-line pt-4">
              <div className="flex items-center gap-2 flex-wrap">
                <h4 className="text-sm font-semibold">Tailscale</h4>
                {!ts.installed ? (
                  <Badge>ยังไม่ได้ติดตั้ง</Badge>
                ) : ts.state === "Running" ? (
                  <Badge tone="pass">เชื่อมต่อแล้ว</Badge>
                ) : (
                  <Badge tone="review">{ts.state === "NeedsLogin" ? "รอล็อกอิน" : (ts.state ?? "ไม่ทำงาน")}</Badge>
                )}
                {ts.dns_name && <span className="text-xs font-mono text-muted truncate">{ts.dns_name}</span>}
              </div>

              {!ts.installed && (
                <div className="rounded-lg bg-surface-2 p-3 text-sm flex flex-col gap-1.5">
                  <span>ติดตั้ง Tailscale บนเครื่องสถานีก่อน (ครั้งเดียว) แล้วกดรีเฟรช:</span>
                  <code className="font-mono text-xs bg-surface rounded px-2 py-1 select-all break-all">curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale set --operator=$USER</code>
                  <span className="text-xs text-muted">macOS: ติดตั้งแอป Tailscale จาก App Store หรือ brew install --cask tailscale</span>
                </div>
              )}

              {ts.installed && ts.state !== "Running" && (
                <div className="flex flex-col gap-3">
                  <p className="text-sm text-muted">เชื่อมเครื่องนี้เข้ากับบัญชี Tailscale ของคุณ แล้วเปิดสถานีได้จากทุกอุปกรณ์ในบัญชีเดียวกัน</p>
                  {ts.auth_url ? (
                    <div className="flex flex-col sm:flex-row items-center gap-4">
                      <Qr url={ts.auth_url} size={150} />
                      <div className="flex flex-col gap-2 text-sm">
                        <span>สแกนด้วยมือถือ หรือเปิดลิงก์นี้เพื่อล็อกอิน (หน้านี้อัปเดตเองเมื่อเชื่อมต่อสำเร็จ)</span>
                        <a href={ts.auth_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline break-all">
                          {ts.auth_url} <ExternalLink className="size-3.5 shrink-0" />
                        </a>
                      </div>
                    </div>
                  ) : (
                    <Button variant="primary" className="self-start" loading={busy === "login"} disabled={!!busy || lock !== null} reason={lock} onClick={() => run("login", api.remote.login, "เริ่มเชื่อมต่อ Tailscale แล้ว")}>
                      เชื่อมต่อ Tailscale
                    </Button>
                  )}
                </div>
              )}

              {ts.state === "Running" && (
                <div className="flex flex-col gap-3">
                  <div className="flex flex-wrap gap-2">
                    {!ts.serve || ts.serve.funnel ? (
                      <Button
                        variant={ts.serve ? "secondary" : "primary"}
                        icon={Shield}
                        loading={busy === "serve"}
                        disabled={!!busy || lock !== null}
                        reason={lock}
                        onClick={() => run("serve", () => api.remote.serve(false), "เปิด HTTPS เฉพาะใน tailnet แล้ว")}
                      >
                        {ts.serve ? "ปิดอินเทอร์เน็ต เหลือเฉพาะ tailnet" : "เปิด HTTPS ใน tailnet"}
                      </Button>
                    ) : null}
                    {!ts.serve?.funnel && (
                      <Button
                        icon={Globe}
                        loading={busy === "funnel"}
                        disabled={!!busy || lock !== null || !!ts.default_passcode}
                        reason={lock ?? (ts.default_passcode ? "เปลี่ยนรหัสผ่านสถานีก่อน" : null)}
                        onClick={() => {
                          if (window.confirm("เปิดสถานีสู่อินเทอร์เน็ตสาธารณะ?\n\nใครที่มีลิงก์จะเห็นภาพกล้องสด ผลตรวจ และข้อมูลทั้งหมดได้ (การสั่งเครื่องยังต้องใช้รหัสผ่าน)"))
                            run("funnel", () => api.remote.serve(true), "เปิดสู่อินเทอร์เน็ตแล้ว (Funnel)");
                        }}
                      >
                        เปิดสู่อินเทอร์เน็ต (Funnel)
                      </Button>
                    )}
                    {ts.serve && (
                      <Button variant="ghost" loading={busy === "off"} disabled={!!busy || lock !== null} onClick={() => run("off", api.remote.unserve, "ปิดอุโมงค์ Tailscale ของสถานีแล้ว")}>
                        ปิดอุโมงค์
                      </Button>
                    )}
                  </div>
                  {ts.serve?.funnel && (
                    <p className="text-xs text-fail flex items-center gap-1.5">
                      <Globe className="size-3.5 shrink-0" /> เปิดสู่อินเทอร์เน็ตอยู่ — ใครมีลิงก์ก็ดูภาพกล้องและข้อมูลได้ ปิดเมื่อไม่ใช้
                    </p>
                  )}
                  {ts.default_passcode && !ts.serve?.funnel && (
                    <p className="text-xs text-review flex items-center gap-1.5">
                      <Lock className="size-3.5 shrink-0" /> ยังใช้รหัสผ่านเริ่มต้น — ตั้ง PCB_OPERATOR_PASSCODE ใน backend/.env ก่อนจึงจะเปิดสู่อินเทอร์เน็ตได้
                    </p>
                  )}
                  {!ts.https && <p className="text-xs text-review">HTTPS ของ tailnet ยังไม่เปิด: เปิดที่ login.tailscale.com/admin/dns → Enable HTTPS (ใช้ลิงก์ Tailscale IP ไปก่อนได้)</p>}
                  {!!ts.others?.length && (
                    <p className="text-xs text-muted">
                      บริการอื่นบน Tailscale ของเครื่องนี้ (ระบบไม่แตะ):{" "}
                      {ts.others.map((o) => `:${o.port} → ${o.target}${o.funnel ? " (Funnel)" : ""}`).join(", ")}
                    </p>
                  )}
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </Card>
  );
}
