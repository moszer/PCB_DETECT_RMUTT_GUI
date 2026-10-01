"use client";

import React, { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { errorMessage } from "@/lib/api";
import { sfx } from "@/lib/sound";
import { cx } from "./ui";

type ToastKind = "success" | "error" | "warning" | "info";

interface ToastItem {
  id: number;
  kind: ToastKind;
  title: string;
  detail?: string;
}

interface ToastApi {
  success: (title: string, detail?: string) => void;
  error: (title: string, detail?: unknown) => void;
  warning: (title: string, detail?: string) => void;
  info: (title: string, detail?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const KIND_STYLE: Record<ToastKind, { icon: typeof Info; color: string }> = {
  success: { icon: CheckCircle2, color: "text-pass" },
  error: { icon: XCircle, color: "text-fail" },
  warning: { icon: AlertTriangle, color: "text-review" },
  info: { icon: Info, color: "text-accent" },
};

/** Non-blocking notifications — replaces window.alert(), which froze the operator's screen. */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setItems((all) => all.filter((t) => t.id !== id)), []);

  const push = useCallback(
    (kind: ToastKind, title: string, detail?: string) => {
      const id = nextId.current++;
      if (kind === "error") sfx.error();
      setItems((all) => [...all.slice(-3), { id, kind, title, detail }]);
      setTimeout(() => dismiss(id), kind === "error" ? 8000 : 4000);
    },
    [dismiss]
  );

  const api = useMemo<ToastApi>(
    () => ({
      success: (t, d) => push("success", t, d),
      error: (t, d) => push("error", t, d === undefined ? undefined : errorMessage(d)),
      warning: (t, d) => push("warning", t, d),
      info: (t, d) => push("info", t, d),
    }),
    [push]
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        className="fixed z-[60] bottom-20 md:bottom-5 right-4 left-4 sm:left-auto sm:w-96 flex flex-col gap-2 pointer-events-none"
      >
        {items.map((t) => {
          const { icon: Icon, color } = KIND_STYLE[t.kind];
          return (
            <div
              key={t.id}
              role={t.kind === "error" ? "alert" : "status"}
              className="pointer-events-auto animate-toast-in flex items-start gap-3 rounded-xl border border-line bg-surface p-3 shadow-pop"
            >
              <Icon className={cx("size-5 shrink-0 mt-0.5", color)} />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-text">{t.title}</div>
                {t.detail && <div className="text-xs text-muted mt-0.5 break-words">{t.detail}</div>}
              </div>
              <button
                type="button"
                aria-label="ปิดการแจ้งเตือน"
                onClick={() => dismiss(t.id)}
                className="text-subtle hover:text-text cursor-pointer"
              >
                <X className="size-4" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
