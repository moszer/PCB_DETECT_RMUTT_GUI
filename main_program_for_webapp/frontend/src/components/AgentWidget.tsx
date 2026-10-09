"use client";

import React, { useEffect, useRef, useState } from "react";
import { Bot, Check, RefreshCw, Send, Sparkles, Square, Trash2, User, X } from "lucide-react";
import { API_BASE, authHeaders } from "@/lib/api";
import { sfx } from "@/lib/sound";
import type { TabId } from "./AppShell";
import { Rich } from "./ChatPanel";
import { Button, Spinner, cx } from "./ui";

/** One step of an answer; `retry` = a model could not answer and the next one is tried. */
type Step = { label: string; done: boolean; retry?: boolean };
/** `fresh`: the answer just arrived in this page (it is revealed with an animation; history is not). */
type Msg = { role: "user" | "assistant"; content: string; steps?: Step[]; error?: boolean; fresh?: boolean };

const SUGGESTIONS = ["สรุปสถานะและการตั้งค่าทั้งหมดของเครื่อง", "สรุปโครงงานในเล่มปริญญานิพนธ์", "รางแม่นแค่ไหน ควรตั้งชดเชยไหม", "รอบสแกนล่าสุดผลเป็นยังไง", "มี error อะไรล่าสุดบ้าง", "สรุป yield ตอนนี้"];

function ThinkingIndicator({ reading }: { reading: boolean }) {
  return (
    <div className="flex items-center gap-2.5 min-h-6" role="status" aria-live="polite">
      <span className="ai-thinking-orb" aria-hidden="true" />
      <span className="text-xs font-medium text-text">
        {reading ? "กำลังอ่านข้อมูล…" : "กำลังคิด…"}
      </span>
    </div>
  );
}

/**
 * Station-wide AI assistant: a floating button on every page. It answers from live station
 * data (history, yield, scans, references, datasets, models, settings), the project
 * thesis PDF and can open pages.
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
    sfx.chatSend();
    const controller = new AbortController();
    abort.current = controller;
    try {
      const res = await fetch(`${API_BASE}/api/chat/agent`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({ messages: history.map(({ role, content }) => ({ role, content })), page }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        const err = await res.json().catch(() => ({}));
        throw new Error(typeof err.detail === "string" ? err.detail : `HTTP ${res.status}`);
      }
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
          if (ev.type === "ping") continue; // keep-alive while the AI waits
          if (ev.type === "tool") {
            sfx.chatStep();
            updateLast((m) => ({ ...m, steps: [...(m.steps ?? []).map((s) => ({ ...s, done: true })), { label: ev.label, done: false, retry: ev.name === "retry" }] }));
          } else if (ev.type === "navigate") {
            sfx.whoosh();
            onNavigate(ev.page as TabId);
          } else if (ev.type === "text") {
            sfx.chatReply();
            updateLast((m) => ({ ...m, content: ev.text, fresh: true, steps: (m.steps ?? []).map((s) => ({ ...s, done: true })) }));
          } else if (ev.type === "error") {
            sfx.error();
            updateLast((m) => ({ ...m, content: `⚠️ ${ev.message}`, error: true, steps: (m.steps ?? []).map((s) => ({ ...s, done: true })) }));
          }
        }
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        sfx.error();
        const msg = (err as Error).message;
        const friendly = /network|fetch|load failed/i.test(msg)
          ? "การเชื่อมต่อกับ backend ถูกตัดระหว่างรอ AI — ตรวจว่า backend ยังทำงานอยู่ แล้วลองถามใหม่"
          : msg;
        updateLast((m) => ({ ...m, content: `⚠️ ${friendly}`, error: true, steps: (m.steps ?? []).map((s) => ({ ...s, done: true })) }));
      }
      else updateLast((m) => ({ ...m, content: m.content || "(หยุดแล้ว)", error: !m.content }));
    } finally {
      setBusy(false);
      abort.current = null;
    }
  };

  const clear = async () => {
    if (!window.confirm("ลบประวัติแชทกับผู้ช่วย AI ทั้งหมด?")) return;
    setMessages([]);
    await fetch(`${API_BASE}/api/chat/agent/history`, { method: "DELETE", headers: authHeaders({}) }).catch(() => undefined);
  };

  const lastMessage = messages[messages.length - 1];
  const thinking = busy && lastMessage?.role === "assistant" && !lastMessage.content;

  return (
    <>
      <button
        type="button"
        onClick={() => {
          if (open) sfx.chatClose();
          else sfx.chatOpen();
          setOpen((o) => !o);
          setTimeout(() => inputRef.current?.focus(), 50);
        }}
        aria-label="ผู้ช่วย AI"
        title="ผู้ช่วย AI — ถามข้อมูลอะไรในระบบก็ได้"
        className={cx(
          "group fixed bottom-20 md:bottom-4 right-4 z-40 size-12 rounded-full shadow-lg grid place-items-center cursor-pointer transition-transform hover:scale-105",
          open ? "bg-surface-2 text-text border border-line" : "bg-accent text-on-accent"
        )}
      >
        {open ? <X className="size-5" /> : <Sparkles className="size-5" />}
        {/* Label on hover only, so the button doesn't cover the viewers. */}
        {!open && (
          <span className="pointer-events-none absolute right-14 whitespace-nowrap rounded-md bg-surface border border-line px-2 py-1 text-xs text-text shadow opacity-0 transition-opacity group-hover:opacity-100">
            ถาม AI
          </span>
        )}
      </button>

      {open && (
        <div className={cx(
          "ai-assistant-frame fixed bottom-36 md:bottom-20 right-2 sm:right-4 z-40 w-[440px] max-w-[calc(100vw-1rem)] sm:max-w-[calc(100vw-2.5rem)] h-[620px] max-h-[calc(100dvh-13rem)] md:max-h-[calc(100dvh-7rem)] rounded-2xl animate-rise",
          thinking && "is-thinking"
        )}>
          {/* rainbow light round the window while the AI thinks (globals.css) */}
          <span className="ai-glow" aria-hidden="true">
            <span className="far" />
            <span className="near" />
            <span className="ring" />
          </span>
          <div className="relative isolate h-full rounded-2xl border border-line bg-surface shadow-2xl flex flex-col">
            <span className="ai-glow-edge" aria-hidden="true">
              <span />
            </span>
            <div className="flex items-center gap-2 px-4 py-3 border-b border-line">
              <span className="ai-assistant-icon relative overflow-hidden size-8 rounded-xl text-white grid place-items-center">
                <span className="ai-glow-orb" aria-hidden="true" />
                <Bot className="relative size-4" />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold">ผู้ช่วย AI ประจำสถานี</div>
                <div className="text-[11px] text-muted truncate">ถามข้อมูลสถานีและเล่มโครงงาน · พาไปหน้าต่างๆ ได้</div>
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
                  <p className="text-sm text-muted">ถามได้เลย เช่น yield, ผลสแกน, โมเดล, ชุดข้อมูล, การตั้งค่า หรือเนื้อหาในเล่มปริญญานิพนธ์</p>
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
                    <div className={cx(
                      "rounded-xl px-3 py-2 text-sm leading-relaxed max-w-[88%] break-words min-w-0",
                      m.role === "user" ? "bg-accent-soft whitespace-pre-wrap" : "bg-surface-2",
                      m.role === "assistant" && m.fresh && !m.error && "ai-reveal-sweep",
                      m.role === "assistant" && busy && last && !m.content && "ai-thinking-bubble"
                    )}>
                      {m.role === "assistant" && busy && last && !m.content && (
                        <ThinkingIndicator reading={!!m.steps?.length} />
                      )}
                      {m.role === "assistant" && !!m.steps?.length && (
                        <div className={cx("flex flex-col gap-1", m.content ? "mb-1.5" : "mt-2.5 pl-8")}>
                          {m.steps.map((s, k) => (
                            <span key={k} className={cx("flex items-center gap-1.5 text-[11px] animate-fade", s.retry ? "text-review" : "text-muted")}>
                              {s.retry ? (
                                <RefreshCw className="size-3 shrink-0" aria-hidden="true" />
                              ) : s.done ? (
                                <Check className="size-3 text-pass" aria-hidden="true" />
                              ) : (
                                <span className="ai-thinking-step-dot" aria-hidden="true" />
                              )}
                              {s.label}
                            </span>
                          ))}
                        </div>
                      )}
                      {m.role === "user" ? (
                        m.content
                      ) : m.content ? (
                        <div className={cx(m.error && "text-fail", m.fresh && "ai-reveal")}>
                          <Rich text={m.content} />
                        </div>
                      ) : null}
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
              <div className="relative flex-1 flex">
                <span className="ai-glow-input" aria-hidden="true">
                  <span />
                  <span />
                </span>
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
                  className="relative flex-1 resize-none max-h-28 min-h-9 rounded-lg border border-line bg-surface px-3 py-2 text-sm focus:outline-none focus:border-accent"
                />
              </div>
              {busy ? (
                <Button type="button" variant="secondary" icon={Square} onClick={() => abort.current?.abort()} title="หยุด" />
              ) : (
                <Button type="submit" variant="primary" icon={Send} disabled={!input.trim()} title="ส่ง" />
              )}
            </form>
          </div>
        </div>
      )}
    </>
  );
}
