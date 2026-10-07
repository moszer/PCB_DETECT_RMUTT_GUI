"use client";

import React from "react";
import { Barcode, X } from "lucide-react";
import { cx } from "../ui";

/**
 * The board's serial number for this scan. A USB barcode / QR scanner types like a keyboard
 * and ends with Enter, so scanning the label fills the field and (with `onEnter`) starts the
 * scan right away. Optional: an empty field scans without a serial.
 */
export function SerialInput({
  value,
  onChange,
  onEnter,
  disabled,
  size = "md",
  autoFocus,
}: {
  value: string;
  onChange: (v: string) => void;
  onEnter?: () => void;
  disabled?: boolean;
  size?: "md" | "lg";
  autoFocus?: boolean;
}) {
  return (
    <label className={cx("relative flex items-center", disabled && "opacity-60")}>
      <Barcode className={cx("absolute left-3 text-subtle pointer-events-none", size === "lg" ? "size-5" : "size-4")} />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value.slice(0, 64))}
        onKeyDown={(e) => {
          if (e.key === "Enter" && onEnter) {
            e.preventDefault();
            onEnter();
          }
        }}
        disabled={disabled}
        autoFocus={autoFocus}
        placeholder="เลขบอร์ด / สแกนบาร์โค้ด (ไม่บังคับ)"
        aria-label="เลขบอร์ด (serial) ของบอร์ดที่จะตรวจ"
        inputMode="text"
        autoComplete="off"
        spellCheck={false}
        className={cx(
          "w-full rounded-lg border border-line bg-surface text-text font-mono placeholder:font-sans placeholder:text-subtle",
          "focus:outline-none focus:ring-2 focus:ring-accent/40 focus:border-accent",
          size === "lg" ? "h-12 pl-10 pr-9 text-base" : "h-9 pl-9 pr-8 text-sm"
        )}
      />
      {value && !disabled && (
        <button type="button" onClick={() => onChange("")} className="absolute right-2 text-subtle hover:text-text cursor-pointer" aria-label="ล้างเลขบอร์ด">
          <X className="size-4" />
        </button>
      )}
    </label>
  );
}
