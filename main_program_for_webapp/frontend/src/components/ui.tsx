"use client";

import React, { useEffect, useId } from "react";
import { createPortal } from "react-dom";
import { Loader2, Lock, X, type LucideIcon } from "lucide-react";
import type { Verdict } from "@/types";
import { VERDICT_LABEL, VERDICT_TONE } from "@/lib/format";
import { DecorPcb } from "./three/DecorPcb";

const cx = (...parts: Array<string | false | null | undefined>) => parts.filter(Boolean).join(" ");
export { cx };

/* ── Buttons ─────────────────────────────────────────────── */

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "success";
type ButtonSize = "sm" | "md" | "lg";

const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  primary: "bg-accent text-on-accent hover:bg-accent-strong border-transparent",
  secondary: "bg-surface text-text border-line hover:bg-surface-2 hover:border-line-strong",
  ghost: "bg-transparent text-muted border-transparent hover:bg-surface-2 hover:text-text",
  danger: "bg-fail text-white border-transparent hover:brightness-110",
  success: "bg-pass text-white border-transparent hover:brightness-110",
};

// Touch screens (iPad at the machine) get bigger targets.
const BUTTON_SIZE: Record<ButtonSize, string> = {
  sm: "h-8 pointer-coarse:h-10 px-2.5 text-xs gap-1.5 rounded-md",
  md: "h-9 pointer-coarse:h-11 px-3.5 text-sm gap-2 rounded-lg",
  lg: "h-11 pointer-coarse:h-13 px-5 text-sm gap-2 rounded-lg font-semibold",
};

/** Unavailable buttons go neutral grey (a faded green still looks pressable). */
const BUTTON_LOCKED = "bg-surface-2 text-subtle border-line border-dashed cursor-not-allowed";

export function buttonClasses(variant: ButtonVariant = "secondary", size: ButtonSize = "md", block?: boolean, locked?: boolean) {
  return cx(
    "inline-flex items-center justify-center border font-medium whitespace-nowrap transition-colors select-none",
    locked ? BUTTON_LOCKED : cx("disabled:opacity-45 disabled:cursor-not-allowed cursor-pointer", BUTTON_VARIANT[variant]),
    BUTTON_SIZE[size],
    block && "w-full"
  );
}

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: LucideIcon;
  loading?: boolean;
  block?: boolean;
  /** Why the button is disabled: shown as its tooltip, with a lock icon. */
  reason?: string | null;
}

export function Button({
  variant = "secondary",
  size = "md",
  icon: Icon,
  loading,
  block,
  reason,
  className,
  children,
  disabled,
  title,
  type = "button",
  ...rest
}: ButtonProps) {
  // Colored buttons turn grey when unavailable; a loading button keeps its color.
  const locked = Boolean(disabled && !loading && variant !== "secondary" && variant !== "ghost");
  const showLock = Boolean(disabled && !loading && reason);
  return (
    <button
      type={type}
      disabled={disabled || loading}
      title={showLock ? (reason ?? undefined) : title}
      className={cx(buttonClasses(variant, size, block, locked), className)}
      {...rest}
    >
      {loading ? (
        <Loader2 className="size-4 animate-spin" />
      ) : showLock ? (
        <Lock className="size-4 shrink-0" />
      ) : Icon ? (
        <Icon className="size-4 shrink-0" />
      ) : null}
      {children}
    </button>
  );
}

interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  icon: LucideIcon;
  label: string;
  active?: boolean;
  size?: "sm" | "md";
  /** Light-on-dark styling for controls drawn over camera images. */
  overlay?: boolean;
}

export function IconButton({ icon: Icon, label, active, size = "md", overlay, className, type = "button", ...rest }: IconButtonProps) {
  const tone = overlay
    ? active
      ? "bg-white/20 text-white"
      : "text-white/75 hover:bg-white/10 hover:text-white"
    : active
      ? "bg-accent-soft text-accent"
      : "text-muted hover:bg-surface-2 hover:text-text";
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      className={cx(
        "inline-flex items-center justify-center rounded-md transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed",
        size === "sm" ? "size-7 pointer-coarse:size-9" : "size-9 pointer-coarse:size-11",
        tone,
        className
      )}
      {...rest}
    >
      <Icon className={size === "sm" ? "size-3.5" : "size-4"} />
    </button>
  );
}

/* ── Surfaces ────────────────────────────────────────────── */

export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx("rounded-xl border border-line bg-surface shadow-card", className)} {...rest}>
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  icon: Icon,
  actions,
  className,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  icon?: LucideIcon;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("flex items-start justify-between gap-3 px-4 pt-3.5 pb-3 border-b border-line", className)}>
      <div className="flex items-start gap-2.5 min-w-0">
        {Icon && <Icon className="size-4 mt-0.5 text-muted shrink-0" />}
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-text leading-5">{title}</h3>
          {subtitle && <p className="text-xs text-muted mt-0.5">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-1.5 shrink-0">{actions}</div>}
    </div>
  );
}

export function SectionLabel({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cx("text-xs font-semibold uppercase tracking-wide text-muted", className)}>{children}</div>;
}

/* ── Status ──────────────────────────────────────────────── */

type Tone = "neutral" | "accent" | "pass" | "fail" | "review" | "info";

const BADGE_TONE: Record<Tone, string> = {
  neutral: "bg-surface-2 text-muted border-line",
  accent: "bg-accent-soft text-accent border-transparent",
  pass: "bg-pass-soft text-pass border-transparent",
  fail: "bg-fail-soft text-fail border-transparent",
  review: "bg-review-soft text-review border-transparent",
  info: "bg-info-soft text-info border-transparent",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: React.ReactNode; className?: string }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 h-5 px-1.5 rounded border text-[11px] font-semibold whitespace-nowrap",
        BADGE_TONE[tone],
        className
      )}
    >
      {children}
    </span>
  );
}

export function VerdictBadge({ verdict, size = "sm", className }: { verdict: Verdict; size?: "sm" | "lg"; className?: string }) {
  const tone = VERDICT_TONE[verdict];
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-md font-bold tracking-wide whitespace-nowrap",
        size === "lg" ? "h-8 px-3 text-sm animate-pop" : "h-5 px-1.5 text-[11px]",
        tone.soft,
        tone.text,
        className
      )}
    >
      <span className={cx("rounded-full", size === "lg" ? "size-2" : "size-1.5", tone.solid)} />
      {verdict}
      {size === "lg" && <span className="font-medium opacity-80">· {VERDICT_LABEL[verdict]}</span>}
    </span>
  );
}

export function StatusDot({ tone, pulse }: { tone: Tone; pulse?: boolean }) {
  const color = {
    neutral: "bg-subtle",
    accent: "bg-accent",
    pass: "bg-pass",
    fail: "bg-fail",
    review: "bg-review",
    info: "bg-info",
  }[tone];
  return (
    <span className="relative inline-flex size-2 shrink-0">
      {pulse && <span className={cx("absolute inset-0 rounded-full opacity-60 animate-ping", color)} />}
      <span className={cx("relative inline-flex size-2 rounded-full", color)} />
    </span>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone,
  className,
}: {
  label: React.ReactNode;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: "pass" | "fail" | "review" | "accent";
  className?: string;
}) {
  const color = tone ? { pass: "text-pass", fail: "text-fail", review: "text-review", accent: "text-accent" }[tone] : "text-text";
  return (
    <div className={cx("rounded-lg border border-line bg-surface-2 px-3 py-2.5", className)}>
      <div className="text-[11px] text-muted">{label}</div>
      <div className={cx("text-xl font-semibold tabular mt-0.5", color)}>{value}</div>
      {hint && <div className="text-[11px] text-subtle mt-0.5">{hint}</div>}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  children,
  className,
  pcb,
}: {
  icon: LucideIcon;
  title: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
  /** A slowly turning 3D board instead of the icon (falls back to the icon when 3D is off). */
  pcb?: boolean;
}) {
  const icon = (
    <div className="size-10 rounded-full bg-surface-2 flex items-center justify-center">
      <Icon className="size-5 text-subtle" />
    </div>
  );
  return (
    <div className={cx("flex flex-col items-center justify-center text-center gap-2 px-6 py-10", className)}>
      {pcb ? <DecorPcb className="w-44 h-28 -my-2" fallback={icon} /> : icon}
      <div className="text-sm font-medium text-text">{title}</div>
      {children && <div className="text-xs text-muted max-w-xs leading-relaxed">{children}</div>}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("size-4 animate-spin text-muted", className)} />;
}

/* ── Form controls ───────────────────────────────────────── */

export function Field({
  label,
  hint,
  children,
  className,
  htmlFor,
  aside,
}: {
  label: React.ReactNode;
  hint?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  htmlFor?: string;
  aside?: React.ReactNode;
}) {
  return (
    <div className={cx("flex flex-col gap-1.5", className)}>
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={htmlFor} className="text-xs font-medium text-muted">
          {label}
        </label>
        {aside}
      </div>
      {children}
      {hint && <p className="text-[11px] text-subtle leading-snug">{hint}</p>}
    </div>
  );
}

const inputBase =
  "w-full h-9 rounded-lg border border-line bg-surface-2 px-3 text-sm text-text placeholder:text-subtle " +
  "focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent/20 disabled:opacity-50 transition-colors";

export function TextInput({ className, ...rest }: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cx(inputBase, className)} {...rest} />;
}

export function NumberInput({
  value,
  onChange,
  min,
  max,
  step,
  suffix,
  className,
  ...rest
}: Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> & {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  suffix?: string;
}) {
  return (
    <div className={cx("relative", className)}>
      <input
        type="number"
        inputMode="decimal"
        value={Number.isFinite(value) ? value : ""}
        min={min}
        max={max}
        step={step}
        onChange={(e) => {
          const v = parseFloat(e.target.value);
          if (Number.isFinite(v)) onChange(v);
        }}
        onBlur={(e) => {
          // Clamp on blur so typing intermediate values isn't fought mid-keystroke.
          const v = parseFloat(e.target.value);
          if (!Number.isFinite(v)) return onChange(min ?? 0);
          const clamped = Math.min(max ?? Infinity, Math.max(min ?? -Infinity, v));
          if (clamped !== v) onChange(clamped);
        }}
        className={cx(inputBase, "font-mono tabular", suffix && "pr-10")}
        {...rest}
      />
      {suffix && (
        <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-subtle">{suffix}</span>
      )}
    </div>
  );
}

export function Select({ className, children, ...rest }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cx(inputBase, "pr-8 cursor-pointer truncate", className)} {...rest}>
      {children}
    </select>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  description,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: React.ReactNode;
  description?: React.ReactNode;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className={cx("flex items-start justify-between gap-3", disabled ? "opacity-50" : "cursor-pointer")}>
      <span className="min-w-0">
        <span className="block text-sm text-text">{label}</span>
        {description && <span className="block text-[11px] text-subtle mt-0.5 leading-snug">{description}</span>}
      </span>
      <span className="relative inline-flex shrink-0 mt-0.5">
        <input
          id={id}
          type="checkbox"
          role="switch"
          className="peer sr-only"
          checked={checked}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span className="h-5 w-9 rounded-full bg-surface-3 transition-colors peer-checked:bg-accent peer-focus-visible:ring-2 peer-focus-visible:ring-accent/40" />
        <span className="absolute left-0.5 top-0.5 size-4 rounded-full bg-white shadow transition-transform peer-checked:translate-x-4" />
      </span>
    </label>
  );
}

export function Checkbox({
  checked,
  onChange,
  children,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  children: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <label className={cx("flex items-start gap-2.5 text-sm text-text", disabled ? "opacity-50" : "cursor-pointer")}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 size-4 accent-[var(--accent)] cursor-pointer"
      />
      <span className="leading-snug">{children}</span>
    </label>
  );
}

export function Segmented<T extends string | number>({
  value,
  onChange,
  options,
  size = "md",
  className,
  disabled,
}: {
  value: T;
  onChange: (v: T) => void;
  options: Array<{ value: T; label: React.ReactNode; icon?: LucideIcon }>;
  size?: "sm" | "md";
  className?: string;
  disabled?: boolean;
}) {
  return (
    <div role="radiogroup" className={cx("inline-flex rounded-lg border border-line bg-surface-2 p-0.5", className)}>
      {options.map((o) => {
        const active = o.value === value;
        const Icon = o.icon;
        return (
          <button
            key={String(o.value)}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={disabled}
            onClick={() => onChange(o.value)}
            className={cx(
              "flex-1 inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors cursor-pointer whitespace-nowrap disabled:cursor-not-allowed disabled:opacity-50",
              size === "sm" ? "h-7 pointer-coarse:h-9 px-2 text-xs" : "h-8 pointer-coarse:h-10 px-3 text-sm",
              active ? "bg-surface text-text shadow-card" : "text-muted hover:text-text"
            )}
          >
            {Icon && <Icon className="size-3.5" />}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function Slider({
  label,
  value,
  onChange,
  min,
  max,
  step,
  format = (v) => String(v),
  hint,
  disabled,
}: {
  label: React.ReactNode;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step: number;
  format?: (v: number) => string;
  hint?: React.ReactNode;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <label htmlFor={id} className="text-xs font-medium text-muted">
          {label}
        </label>
        <span className="text-xs font-mono tabular text-text">{format(value)}</span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(parseFloat(e.target.value))}
      />
      {hint && <p className="text-[11px] text-subtle leading-snug">{hint}</p>}
    </div>
  );
}

/* ── Overlays ────────────────────────────────────────────── */

export function Modal({
  open,
  onClose,
  title,
  subtitle,
  actions,
  size = "lg",
  glow,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  /** AI dialogs: the rainbow "thinking" light (globals.css .ai-glow); true while waiting. */
  glow?: boolean;
  children: React.ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  const width = { sm: "max-w-md", md: "max-w-2xl", lg: "max-w-4xl", xl: "max-w-6xl" }[size];
  // Rendered into <body>: inside a page the animated tab wrapper (animate-fade) is its own
  // stacking context, which put the phone bottom bar and the AI button (z-40) over the dialog.
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-[2px] p-0 sm:p-4 animate-fade"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className={cx(
          "relative w-full flex flex-col max-h-[94dvh] rounded-t-2xl sm:rounded-2xl animate-modal",
          width,
          glow !== undefined && "ai-assistant-frame",
          glow && "is-thinking"
        )}
      >
        {glow !== undefined && (
          <span className="ai-glow" aria-hidden="true">
            <span className="far" />
            <span className="near" />
            <span className="ring" />
          </span>
        )}
        <div
          role="dialog"
          aria-modal="true"
          className="relative isolate w-full min-h-0 flex-1 flex flex-col bg-surface border border-line shadow-pop rounded-[inherit]"
        >
          {glow !== undefined && (
            <span className="ai-glow-edge" aria-hidden="true">
              <span />
            </span>
          )}
          <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-line">
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-text flex items-center gap-2 flex-wrap">{title}</h2>
              {subtitle && <p className="text-xs text-muted mt-0.5">{subtitle}</p>}
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              {actions}
              <IconButton icon={X} label="ปิด" onClick={onClose} />
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-5 pb-[max(1.25rem,env(safe-area-inset-bottom))]">{children}</div>
        </div>
      </div>
    </div>,
    document.body
  );
}
