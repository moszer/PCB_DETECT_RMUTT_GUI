"use client";

import React from "react";
import { Check } from "lucide-react";
import { cx } from "../ui";

export type StepKey = "board" | "stage" | "points" | "scan";
export type StepState = "done" | "current" | "todo";
export interface WorkflowStep {
  key: StepKey;
  label: string;
  state: StepState;
  /** What to do now; shown under the stepper for the current step. */
  hint: string;
}

/** ① board → ② stage ready → ③ points & references → ④ scan, with the next action spelled out. */
export function WorkflowSteps({ steps, onPick }: { steps: WorkflowStep[]; onPick: (key: StepKey) => void }) {
  const current = steps.find((s) => s.state === "current") ?? steps[steps.length - 1];
  return (
    <div className="flex flex-col gap-2" data-tour="steps">
      <ol className="flex items-start">
        {steps.map((s, i) => (
          <li key={s.key} className="flex-1 flex flex-col items-center relative min-w-0">
            {i > 0 && (
              <span
                aria-hidden
                className={cx("absolute top-3.5 pointer-coarse:top-[18px] right-1/2 w-full h-0.5", steps[i - 1].state === "done" ? "bg-pass" : "bg-line")}
              />
            )}
            <button
              type="button"
              onClick={() => onPick(s.key)}
              aria-current={s.state === "current" ? "step" : undefined}
              className="relative z-10 flex flex-col items-center gap-1 cursor-pointer group min-w-0 px-0.5"
            >
              <span
                className={cx(
                  "size-7 pointer-coarse:size-9 rounded-full grid place-items-center text-xs font-bold border-2 transition-colors",
                  s.state === "done" && "bg-pass border-pass text-white",
                  s.state === "current" && "bg-accent border-accent text-on-accent ring-4 ring-accent/25",
                  s.state === "todo" && "bg-surface border-line-strong text-muted group-hover:border-accent"
                )}
              >
                {s.state === "done" ? <Check className="size-4" /> : i + 1}
              </span>
              <span
                className={cx(
                  "text-xs leading-tight text-center truncate max-w-full",
                  s.state === "current" ? "font-semibold text-text" : s.state === "done" ? "text-pass" : "text-muted"
                )}
              >
                {s.label}
              </span>
            </button>
          </li>
        ))}
      </ol>
      <p key={current.key} className="text-sm leading-snug rounded-lg bg-accent-soft/60 text-text px-3 py-2 animate-fade">
        <span className="font-semibold text-accent">ขั้นที่ {steps.indexOf(current) + 1}:</span> {current.hint}
      </p>
    </div>
  );
}
