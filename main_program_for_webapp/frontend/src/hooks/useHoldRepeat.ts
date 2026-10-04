"use client";

import { useEffect, useRef } from "react";

const FIRST_REPEAT_MS = 350;
const REPEAT_GAP_MS = 60;

/**
 * Press-and-hold repeat for jog buttons (touch screens have no key repeat). The action
 * runs once on press, then again each time the previous call finishes while the
 * button is still held; it stops on release or when the action returns false.
 * Keyboard activation (Enter/Space on a focused button) still runs it once.
 */
export function useHoldRepeat() {
  const holding = useRef<symbol | null>(null);
  useEffect(() => () => void (holding.current = null), []);

  const stop = () => {
    holding.current = null;
  };

  return (action: () => Promise<boolean>) => ({
    onPointerDown: (e: React.PointerEvent<HTMLButtonElement>) => {
      if (e.button !== 0 || e.currentTarget.disabled) return;
      try {
        e.currentTarget.setPointerCapture(e.pointerId); // keep the hold even if the finger slides off
      } catch {
        // Pointer already gone (e.g. a synthetic event); the hold still runs until pointerup.
      }
      const token = Symbol("hold");
      holding.current = token;
      const loop = async (first: boolean) => {
        const ok = await action();
        if (!ok || holding.current !== token) return;
        await new Promise((r) => setTimeout(r, first ? FIRST_REPEAT_MS : REPEAT_GAP_MS));
        if (holding.current === token) loop(false);
      };
      loop(true);
    },
    onPointerUp: stop,
    onPointerCancel: stop,
    onLostPointerCapture: stop,
    onClick: (e: React.MouseEvent<HTMLButtonElement>) => {
      if (e.detail === 0) action(); // keyboard activation; pointer presses ran on pointerdown
    },
  });
}
