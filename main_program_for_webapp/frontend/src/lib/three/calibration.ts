"use client";

import { api } from "@/lib/api";
import { stageCal, type StageCal } from "./boardMap";

let cache: { at: number; cal: StageCal | null } | null = null;

/** The stage→image matrix of the last calibration (cached for a minute; null if none). */
export async function getStageCal(): Promise<StageCal | null> {
  if (cache && Date.now() - cache.at < 60_000) return cache.cal;
  try {
    const cal = stageCal((await api.getStageCalibration()).last);
    cache = { at: Date.now(), cal };
    return cal;
  } catch {
    return cache?.cal ?? null;
  }
}
