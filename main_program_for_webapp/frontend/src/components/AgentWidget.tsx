"use client";

import React, { useEffect, useRef, useState } from "react";
import { Bot, Check, Loader2, Send, Sparkles, Square, Trash2, User, X } from "lucide-react";
import { API_BASE } from "@/lib/api";
import type { TabId } from "./AppShell";
import { Rich } from "./ChatPanel";
import { Button, Spinner, cx } from "./ui";

type Step = { label: string; done: boolean };
type Msg = { role: "user" | "assistant"; content: string; steps?: Step[]; error?: boolean };

const SUGGESTIONS = ["สรุป yield ตอนนี้", "รอบสแกนล่าสุดผลเป็นยังไง", "โมเดลไหนแม่นที่สุด", "สถานะเครื่องตอนนี้พร้อมสแกนไหม"];

/**
 * Station-wide AI assistant: a floating button on every page. It answers from live station
 * data (history, yield, scans, references, datasets, models, settings) and can open pages.
 */
export function AgentWidget({ page, onNavigate }: { page: TabId; onNavigate: (page: TabId) => void }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!open || loaded) return;
    fetch(`${API_BASE}/api/chat/agent/history`)
      .then((r) => r.json())
      .then((h) => setMessages((m) => (m.length ? m : (h.messages ?? []).map((x: Msg) => ({ role: x.role, content: x.content })))))
      .catch(() => undefined)
      .finally(() => setLoaded(true));
  }, [open, loaded]);

  useEffect(() => {
    if (open) bottom.current?.scrollIntoView({ block: "end" });
  }, [messages, open]);

  useEffect(() => () => abort.current?.abort(), []);

  const updateLast = (fn: (m: Msg) => Msg) => setMessages((all) => all.map((m, i) => (i === all.length - 1 ? fn(m) : m)));

  const send = async (text: string) => {
    const q = text.trim();
    if (!q || busy) return;
    const history = [...messages.filter((m) => !m.error && m.content), { role: "user" as const, content: q }];
    setMessages((m) => [...m, { role: "user", content: q }, { role: "assistant", content: "", steps: [] }]);
    setInput("");
    setBusy(true);
    const controller = new AbortController();
    abort.current = controller;
    try {
      const res = await fetch(`${API_BASE}/api/chat/agent`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history.map(({ role, content }) => ({ role, content })), page }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const ev = JSON.parse(line);
          if (ev.type === "tool") {
            updateLast((m) => ({ ...m, steps: [...(m.steps ?? []).map((s) => ({ ...s, done: true })), { label: ev.label, done: false }] }));
          } else if (ev.type === "navigate") {
            onNavigate(ev.page as TabId);
          } else if (ev.type === "text") {
            updateLast((m) => ({ ...m, content: ev.text, steps: (m.steps ?? []).map((s) => ({ ...s, done: true })) }));
          } else if (ev.type === "error") {
            updateLast((m) => ({ ...m, content: `⚠️ ${ev.message}`, error: true, steps: (m.steps ?? []).map((s) => ({ ...s, done: true })) }));
          }
        }
      }
    } catch (err) {
      if (!controller.signal.aborted) updateLast((m) => ({ ...m, content: `⚠️ ${(err as Error).message}`, error: true }));
      else updateLast((m) => ({ ...m, content: m.content || "(หยุดแล้ว)", error: !m.content }));
    } finally {
      setBusy(false);
      abort.current = null;
    }
  };

  const clear = async () => {
    if (!window.confirm("ลบประวัติแชทกับผู้ช่วย AI ทั้งหมด?")) return;
    setMessages([]);
    await fetch(`${API_BASE}/api/chat/agent/history`, { method: "DELETE" }).catch(() => undefined);
  };

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setOpen((o) => !o);
          setTimeout(() => inputRef.current?.focus(), 50);
        }}
        aria-label="ผู้ช่วย AI"
        title="ผู้ช่วย AI — ถามข้อมูลอะไรในระบบก็ได้"
        className={cx(
          "fixed bottom-5 right-5 z-40 h-12 rounded-full shadow-lg flex items-center gap-2 px-4 cursor-pointer transition-transform hover:scale-105",
          open ? "bg-surface-2 text-text border border-line" : "bg-accent text-on-accent"
        )}
      >
        {open ? <X className="size-5" /> : <Sparkles className="size-5" />}
        <span className="text-sm font-semibold">{open ? "ปิด" : "ถาม AI"}</span>
      </button>

      {open && (
        <div className="fixed bottom-20 right-5 z-40 w-[440px] max-w-[calc(100vw-2.5rem)] h-[620px] max-h-[calc(100vh-7rem)] rounded-2xl border border-line bg-surface shadow-2xl flex flex-col animate-rise">
          <div className="flex items-center gap-2 px-4 py-3 border-b border-line">
            <span className="size-8 rounded-full bg-accent-soft text-accent grid place-items-center">
              <Bot className="size-4" />
            </span>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold">ผู้ช่วย AI ประจำสถานี</div>
              <div className="text-[11px] text-muted truncate">ถามได้ทุกข้อมูลในระบบ · พาไปหน้าต่างๆ ได้ · อ่านอย่างเดียว</div>
            </div>
            {messages.length > 0 && (
              <button type="button" onClick={clear} disabled={busy} title="ลบประวัติแชท" className="size-8 grid place-items-center rounded-md text-subtle hover:text-fail hover:bg-fail-soft cursor-pointer">
                <Trash2 className="size-4" />
              </button>
            )}
          </div>

          <div className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-3">
            {!loaded && (
              <div className="m-auto flex items-center gap-2 text-sm text-muted">
                <Spinner className="size-4" /> กำลังโหลดประวัติ…
              </div>
            )}
            {loaded && !messages.length && (
              <div className="m-auto flex flex-col items-center gap-3 text-center">
                <Sparkles className="size-7 text-accent" />
                <p className="text-sm text-muted">ถามได้เลย เช่น yield, ผลสแกน, จุดที่ FAIL, โมเดล, ชุดข้อมูล, การตั้งค่า หรือ “พาไปหน้าประวัติ”</p>
                <div className="flex flex-wrap justify-center gap-1.5">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} type="button" onClick={() => send(s)} className="h-7 px-2.5 rounded-full border border-line text-xs hover:bg-surface-2 cursor-pointer">
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, i) => {
              const last = i === messages.length - 1;
              return (
                <div key={i} className={cx("flex gap-2", m.role === "user" && "flex-row-reverse")}>
                  <span className={cx("size-6 shrink-0 rounded-full grid place-items-center", m.role === "user" ? "bg-accent text-on-accent" : "bg-surface-2 text-accent")}>
                    {m.role === "user" ? <User className="size-3" /> : <Bot className="size-3" />}
                  </span>
                  <div className={cx("rounded-xl px-3 py-2 text-sm leading-relaxed max-w-[88%] break-words min-w-0", m.role === "user" ? "bg-accent-soft whitespace-pre-wrap" : "bg-surface-2")}>
                    {m.role === "assistant" && !!m.steps?.length && (
                      <div className="flex flex-col gap-1 mb-1.5">
                        {m.steps.map((s, k) => (
                          <span key={k} className="flex items-center gap-1.5 text-[11px] text-muted animate-fade">
                            {s.done ? <Check className="size-3 text-pass" /> : <Loader2 className="size-3 animate-spin text-accent" />}
                            {s.label}
                          </span>
                        ))}
                      </div>
                    )}
                    {m.role === "user" ? (
                      m.content
                    ) : m.content ? (
                      <div className={m.error ? "text-fail" : undefined}>
                        <Rich text={m.content} />
                      </div>
                    ) : (
                      busy && last && (
                        <span className="flex items-center gap-2 text-xs text-muted">
                          <span className="flex items-end gap-1 h-3" aria-hidden>
                            {[0, 1, 2].map((d) => (
                              <span key={d} className="size-1.5 rounded-full bg-accent chat-dot" style={{ animationDelay: `${d * 160}ms` }} />
                            ))}
                          </span>
                          {m.steps?.length ? "กำลังสรุปคำตอบ…" : "กำลังคิด…"}
                        </span>
                      )
                    )}
                  </div>
                </div>
              );
            })}
            <div ref={bottom} />
          </div>

          <form
            className="p-3 border-t border-line flex items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
          >
            <textarea
              ref={inputRef}
              value={input}
              rows={1}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  send(input);
                }
              }}
              placeholder="ถามอะไรก็ได้เกี่ยวกับสถานี…"
              className="flex-1 resize-none max-h-28 min-h-9 rounded-lg border border-line bg-surface px-3 py-2 text-sm focus:outline-none focus:border-accent"
            />
            {busy ? (
              <Button type="button" variant="secondary" icon={Square} onClick={() => abort.current?.abort()} title="หยุด" />
            ) : (
              <Button type="submit" variant="primary" icon={Send} disabled={!input.trim()} title="ส่ง" />
            )}
          </form>
        </div>
      )}
    </>
  );
}
