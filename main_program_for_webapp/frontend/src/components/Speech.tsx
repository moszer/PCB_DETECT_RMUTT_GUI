"use client";

import React from "react";
import { Loader2, Square, Volume2, VolumeX } from "lucide-react";
import { setAuto, speechSupported, toggle, useSpeech } from "@/lib/speech";
import { cx } from "./ui";

/** Header switch: read new AI answers aloud (remembered on this device). */
export function VoiceToggle({ className }: { className?: string }) {
  const { auto } = useSpeech();
  if (!speechSupported()) return null;
  const Icon = auto ? Volume2 : VolumeX;
  return (
    <button
      type="button"
      onClick={() => setAuto(!auto)}
      aria-pressed={auto}
      title={auto ? "AI อ่านคำตอบออกเสียง (กดเพื่อปิด)" : "ให้ AI อ่านคำตอบออกเสียง"}
      className={cx(
        "size-8 grid place-items-center rounded-md cursor-pointer transition-colors",
        auto ? "text-accent bg-accent-soft" : "text-subtle hover:text-text hover:bg-surface-2",
        className
      )}
    >
      <Icon className="size-4" />
    </button>
  );
}

/** Under an answer: read it aloud / stop. A spinner while the voice is made, bars while it plays. */
export function SpeakButton({ id, text }: { id: string; text: string }) {
  const { speaking, loading } = useSpeech();
  if (!speechSupported() || !text.trim()) return null;
  const on = speaking === id;
  const preparing = on && loading === id;
  return (
    <button
      type="button"
      onClick={() => toggle(id, text)}
      title={on ? "หยุดอ่าน" : "อ่านออกเสียง"}
      className={cx(
        "mt-1.5 inline-flex items-center gap-1.5 h-6 px-2 rounded-full text-[11px] cursor-pointer transition-colors",
        on ? "bg-accent-soft text-accent" : "text-subtle hover:text-text hover:bg-surface-3"
      )}
    >
      {preparing ? (
        <>
          <Loader2 className="size-3.5 animate-spin" />
          เตรียมเสียง…
        </>
      ) : on ? (
        <>
          <span className="speak-bars" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          <Square className="size-3" />
          หยุด
        </>
      ) : (
        <>
          <Volume2 className="size-3.5" />
          ฟัง
        </>
      )}
    </button>
  );
}
