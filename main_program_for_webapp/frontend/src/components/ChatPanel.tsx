"use client";

import React, { useEffect, useRef, useState } from "react";
import { Bot, Send, Square, Trash2, User } from "lucide-react";
import { API_BASE } from "@/lib/api";
import { Button, Modal, Spinner, cx } from "./ui";

export interface BoardContext {
  point_name?: string;
  verdict?: string;
  reason?: string | null;
  counts?: Record<string, number>;
  parts?: { name: string; status?: string; text?: string }[];
}

type Msg = { role: "user" | "assistant"; content: string };

const SUGGESTIONS = ["บอร์ดนี้คืออะไร ใช้ทำอะไรได้บ้าง", "ชิปหลักบนบอร์ดนี้ทำหน้าที่อะไร", "ทำไมจุดนี้ถึงได้ผลตรวจแบบนี้", "เอาบอร์ดนี้ไปทำโปรเจกต์อะไรได้บ้าง"];

/** Inline markdown: **bold** and `code`. */
function Inline({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((p, k) =>
        p.startsWith("**") && p.endsWith("**") && p.length > 4 ? (
          <strong key={k}>{p.slice(2, -2)}</strong>
        ) : p.startsWith("`") && p.endsWith("`") && p.length > 2 ? (
          <code key={k} className="font-mono text-[0.9em] bg-surface-3 px-1 rounded">
            {p.slice(1, -1)}
          </code>
        ) : (
          <React.Fragment key={k}>{p}</React.Fragment>
        )
      )}
    </>
  );
}

const cells = (row: string) => row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

/** Minimal markdown: headings, bullets, tables, **bold**, `code` (what the model actually emits). */
export function Rich({ text }: { text: string }) {
  const lines = text.split("\n");
  const out: React.ReactNode[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.trim().startsWith("|")) {
      const rows: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(lines[i++]);
      i--;
      const body = rows.filter((r) => !/^\s*\|?\s*:?-{2,}/.test(r));
      const [head, ...rest] = body;
      out.push(
        <div key={i} className="overflow-x-auto my-1">
          <table className="text-xs border-collapse">
            {head && (
              <thead>
                <tr>
                  {cells(head).map((c, k) => (
                    <th key={k} className="border border-line px-2 py-1 text-left bg-surface-3 font-semibold">
                      <Inline text={c} />
                    </th>
                  ))}
                </tr>
              </thead>
            )}
            <tbody>
              {rest.map((r, ri) => (
                <tr key={ri}>
                  {cells(r).map((c, k) => (
                    <td key={k} className="border border-line px-2 py-1 align-top">
                      <Inline text={c} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }
    if (!line.trim()) {
      out.push(<div key={i} className="h-2" />);
      continue;
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      out.push(<hr key={i} className="border-line my-1" />);
      continue;
    }
    const heading = /^\s*#{1,4}\s+/.test(line);
    const bullet = /^\s*[-*•]\s+/.test(line);
    const numbered = line.match(/^\s*(\d+)[.)]\s+/);
    const body = line.replace(/^\s*#{1,4}\s+/, "").replace(/^\s*[-*•]\s+/, "").replace(/^\s*\d+[.)]\s+/, "");
    out.push(
      bullet || numbered ? (
        <div key={i} className="flex gap-1.5 pl-1">
          <span className="text-muted shrink-0">{numbered ? `${numbered[1]}.` : "•"}</span>
          <span>
            <Inline text={body} />
          </span>
        </div>
      ) : (
        <div key={i} className={heading ? "font-semibold mt-1" : undefined}>
          <Inline text={body} />
        </div>
      )
    );
  }
  return <>{out}</>;
}

const THINKING_STEPS = ["กำลังดูภาพบอร์ด", "กำลังอ่านข้อมูลชิ้นส่วนและตัวอักษร", "กำลังวิเคราะห์", "กำลังเรียบเรียงคำตอบ"];

/** "AI is thinking": three softly bouncing dots, a status that advances with time, elapsed seconds. */
function ThinkingIndicator() {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 250);
    return () => clearInterval(timer);
  }, []);
  const step = THINKING_STEPS[Math.min(THINKING_STEPS.length - 1, Math.floor(elapsed / 3))];
  return (
    <div className="flex items-center gap-2.5 text-xs text-muted" role="status" aria-live="polite">
      <span className="flex items-end gap-1 h-3" aria-hidden>
        {[0, 1, 2].map((i) => (
          <span key={i} className="size-1.5 rounded-full bg-accent chat-dot" style={{ animationDelay: `${i * 160}ms` }} />
        ))}
      </span>
      <span key={step} className="animate-fade">
        {step}…
      </span>
      <span className="font-mono tabular text-subtle">{elapsed}s</span>
      {elapsed >= 15 && <span className="text-subtle animate-fade">· เซิร์ฟเวอร์ AI อาจมีคิว กำลังรอ</span>}
    </div>
  );
}

/** Chat with an AI about the inspected board; context + photo go along with every question. */
export function ChatPanel({ context, imageUrl, onClose }: { context: BoardContext; imageUrl?: string; onClose: () => void }) {
  // One saved conversation per inspected image (kept in the station database).
  const conversationKey = imageUrl?.startsWith("/api/storage/") ? imageUrl : null;
  const [messages, setMessages] = useState<Msg[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(!!conversationKey);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [model, setModel] = useState("");
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/chat/status`)
      .then((r) => r.json())
      .then((s) => setModel(s.configured ? s.model : "ยังไม่ได้ตั้งค่า API key"))
      .catch(() => undefined);
    if (conversationKey) {
      fetch(`${API_BASE}/api/chat/history?key=${encodeURIComponent(conversationKey)}`)
        .then((r) => r.json())
        .then((h) => setMessages((m) => (m.length ? m : (h.messages ?? []).map((x: Msg) => ({ role: x.role, content: x.content })))))
        .catch(() => undefined)
        .finally(() => setLoadingHistory(false));
    }
    return () => abort.current?.abort();
  }, [conversationKey]);

  const clearHistory = async () => {
    if (!window.confirm("ลบประวัติแชทของจุดนี้ทั้งหมด?")) return;
    setMessages([]);
    if (conversationKey) {
      await fetch(`${API_BASE}/api/chat/history?key=${encodeURIComponent(conversationKey)}`, { method: "DELETE" }).catch(() => undefined);
    }
  };

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [messages]);

  const send = async (text: string) => {
    const q = text.trim();
    if (!q || busy) return;
    const history: Msg[] = [...messages, { role: "user", content: q }];
    setMessages([...history, { role: "assistant", content: "" }]);
    setInput("");
    setBusy(true);
    const controller = new AbortController();
    abort.current = controller;
    const append = (chunk: string) =>
      setMessages((m) => m.map((msg, i) => (i === m.length - 1 ? { ...msg, content: msg.content + chunk } : msg)));
    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history, context, image_url: conversationKey, conversation_key: conversationKey }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        const err = await res.json().catch(() => ({}));
        append(`⚠️ ${err.detail ?? `HTTP ${res.status}`}`);
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        append(decoder.decode(value, { stream: true }));
      }
    } catch (err) {
      if (!controller.signal.aborted) append(`\n⚠️ ${(err as Error).message}`);
    } finally {
      setBusy(false);
      abort.current = null;
    }
  };

  const last = messages[messages.length - 1];
  const thinking = busy && last?.role === "assistant" && !last.content;

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={
        <>
          <Bot className="size-4 text-accent" />
          ถาม AI เกี่ยวกับบอร์ดนี้
        </>
      }
      subtitle={`ส่งภาพจุดนี้ + ชิ้นส่วน + ตัวอักษรที่อ่านได้ ให้ AI ทุกคำถาม${conversationKey ? " · บันทึกประวัติแชทของจุดนี้" : ""}${model ? ` · ${model}` : ""}`}
    >
      <div className="flex flex-col h-[62vh] min-h-[420px]">
        <div className="flex-1 overflow-y-auto flex flex-col gap-3 pr-1">
          {loadingHistory && (
            <div className="m-auto flex items-center gap-2 text-sm text-muted">
              <Spinner className="size-4" /> กำลังโหลดประวัติแชท…
            </div>
          )}
          {!messages.length && !loadingHistory && (
            <div className="m-auto flex flex-col items-center gap-3 text-center max-w-md">
              <Bot className="size-8 text-subtle" />
              <p className="text-sm text-muted">
                ถามได้ว่าบอร์ดนี้คืออะไร ชิปแต่ละตัวทำอะไร หรือทำไมได้ผลตรวจแบบนี้
                {!context.parts?.some((p) => p.text) && <span className="block text-xs text-review mt-1">แนะนำ: กด “อ่านตัวอักษรทุกชิ้น” ก่อน AI จะระบุชิปได้แม่นขึ้น</span>}
              </p>
              <div className="flex flex-wrap justify-center gap-1.5">
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" onClick={() => send(s)} className="h-7 px-2.5 rounded-full border border-line text-xs hover:bg-surface-2 cursor-pointer">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={cx("flex gap-2", m.role === "user" && "flex-row-reverse")}>
              <span className={cx("size-7 shrink-0 rounded-full grid place-items-center", m.role === "user" ? "bg-accent text-on-accent" : "bg-surface-2 text-accent")}>
                {m.role === "user" ? <User className="size-3.5" /> : <Bot className="size-3.5" />}
              </span>
              <div
                className={cx(
                  "rounded-xl px-3 py-2 text-sm leading-relaxed max-w-[85%] break-words",
                  m.role === "user" ? "bg-accent-soft whitespace-pre-wrap" : "bg-surface-2"
                )}
              >
                {m.role === "user" ? m.content : m.content ? <Rich text={m.content} /> : null}
                {thinking && i === messages.length - 1 && <ThinkingIndicator />}
              </div>
            </div>
          ))}
          <div ref={bottom} />
        </div>

        <form
          className="mt-3 flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          {messages.length > 0 && (
            <Button type="button" variant="ghost" icon={Trash2} disabled={busy} onClick={clearHistory} title="ลบประวัติแชทของจุดนี้" />
          )}
          <textarea
            value={input}
            rows={1}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                send(input);
              }
            }}
            placeholder="พิมพ์คำถาม… (Enter ส่ง, Shift+Enter ขึ้นบรรทัด)"
            className="flex-1 resize-none max-h-32 min-h-9 rounded-lg border border-line bg-surface px-3 py-2 text-sm focus:outline-none focus:border-accent"
          />
          {busy ? (
            <Button type="button" variant="secondary" icon={Square} onClick={() => abort.current?.abort()}>
              หยุด
            </Button>
          ) : (
            <Button type="submit" variant="primary" icon={Send} disabled={!input.trim()}>
              ส่ง
            </Button>
          )}
        </form>
      </div>
    </Modal>
  );
}
