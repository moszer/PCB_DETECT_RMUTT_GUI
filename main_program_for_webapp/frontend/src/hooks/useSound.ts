"use client";

import { useSyncExternalStore } from "react";
import { sfx } from "@/lib/sound";

const SERVER = { enabled: true, volume: 0.6 };

/** Current sound preference ({ enabled, volume }); change it with sfx.setEnabled / sfx.setVolume. */
export function useSoundPrefs() {
  return useSyncExternalStore(sfx.subscribe, sfx.getSnapshot, () => SERVER);
}
