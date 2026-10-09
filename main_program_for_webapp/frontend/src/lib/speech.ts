/**
 * The AI assistant reads its answers aloud with the browser's own text-to-speech (Web Speech
 * API): free, offline, no AI quota. Thai voices come with iOS/macOS (Kanya, Narisa), Android
 * and Chrome (Google ไทย). Chrome stops long utterances after ~15 s, so answers are spoken in
 * short chunks.
 *
 * iOS only lets speech start from a tap; `unlock()` speaks an empty utterance during one (the
 * send button, the speaker toggle) so the reply can be read when it arrives later.
 *
 * State (on/off, which message is being read) is a tiny external store for useSyncExternalStore.
 */
import { useSyncExternalStore } from "react";

const PREF_KEY = "pcb_ai_voice";
const CHUNK = 180;

type State = { auto: boolean; speaking: string | null };
let state: State = { auto: readPref(), speaking: null };
const listeners = new Set<() => void>();
let queue: SpeechSynthesisUtterance[] = [];

function readPref() {
  try {
    return typeof localStorage !== "undefined" && localStorage.getItem(PREF_KEY) === "1";
  } catch {
    return false;
  }
}

function set(next: Partial<State>) {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}

export const speechSupported = () => typeof window !== "undefined" && "speechSynthesis" in window;

/** Markdown answer -> what should be heard: no symbols, tables read row by row, no URLs. */
export function speakable(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .split("\n")
    .filter((l) => !/^\s*\|?\s*:?-{2,}/.test(l)) // table separator rows
    .map((l) =>
      l
        .replace(/^\s*\|/, "")
        .replace(/\|\s*$/, "")
        .replace(/\s*\|\s*/g, ", ")
        .replace(/^\s*#{1,6}\s*/, "")
        .replace(/^\s*[-*•]\s+/, "")
        .replace(/^\s*(\d+)\.\s+/, "$1. ")
    )
    .join("\n")
    .replace(/https?:\/\/\S+/g, "ลิงก์")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[*_`~>#]/g, "")
    .replace(/⚠️|✅|❌|🔴|🟢|[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, "")
    .replace(/\s*\n+\s*/g, ". ")
    .replace(/\s{2,}/g, " ")
    .replace(/(\.\s*){2,}/g, ". ")
    .replace(/([:;,])\s*\.\s*/g, "$1 ")
    .trim();
}

/**
 * Pieces of at most CHUNK characters for Chrome: whole sentences joined while they fit (fewer
 * pauses), a long sentence cut at a comma or space.
 */
function chunks(text: string): string[] {
  const out: string[] = [];
  let buf = "";
  const flush = () => {
    if (buf) out.push(buf);
    buf = "";
  };
  for (const sentence of text.split(/(?<=[.!?。])\s+/)) {
    let rest = sentence.trim();
    while (rest.length > CHUNK) {
      flush();
      const cut = Math.max(rest.lastIndexOf(", ", CHUNK), rest.lastIndexOf(" ", CHUNK));
      const at = cut > CHUNK / 3 ? cut + 1 : CHUNK;
      out.push(rest.slice(0, at).trim());
      rest = rest.slice(at).trim();
    }
    if (!rest) continue;
    if (buf && buf.length + 1 + rest.length > CHUNK) flush();
    buf = buf ? `${buf} ${rest}` : rest;
  }
  flush();
  return out;
}

function thaiVoice(): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith("th"));
  // Prefer the better-sounding ones when several are installed.
  return voices.find((v) => /premium|enhanced|natural|google/i.test(v.name)) ?? voices[0] ?? null;
}

/** Read `text` aloud as message `id`; reading again the message being read stops it. */
export function speak(id: string, text: string) {
  if (!speechSupported()) return;
  const synth = window.speechSynthesis;
  stop();
  const pieces = chunks(speakable(text));
  if (!pieces.length) return;
  const voice = thaiVoice();
  queue = pieces.map((piece, i) => {
    const u = new SpeechSynthesisUtterance(piece);
    u.lang = voice?.lang ?? "th-TH";
    if (voice) u.voice = voice;
    u.rate = 1.05;
    if (i === pieces.length - 1) u.onend = () => state.speaking === id && set({ speaking: null });
    u.onerror = () => state.speaking === id && set({ speaking: null });
    return u;
  });
  set({ speaking: id });
  queue.forEach((u) => synth.speak(u));
}

export function stop() {
  if (!speechSupported()) return;
  queue = [];
  window.speechSynthesis.cancel();
  if (state.speaking) set({ speaking: null });
}

export function toggle(id: string, text: string) {
  if (state.speaking === id) stop();
  else speak(id, text);
}

/** Call inside a tap/click: lets iOS speak a reply that arrives later. */
export function unlock() {
  if (!speechSupported() || !state.auto) return;
  const u = new SpeechSynthesisUtterance(" ");
  u.volume = 0;
  window.speechSynthesis.speak(u);
}

/** Read new answers aloud? (for event handlers; components use useSpeech) */
export const isAuto = () => state.auto;

export function setAuto(auto: boolean) {
  try {
    localStorage.setItem(PREF_KEY, auto ? "1" : "0");
  } catch {
    // The preference just won't persist.
  }
  set({ auto });
  if (!auto) stop();
  else unlock();
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
const SERVER: State = { auto: false, speaking: null };

/** { auto: read new answers aloud, speaking: id of the message being read } */
export function useSpeech(): State {
  return useSyncExternalStore(subscribe, () => state, () => SERVER);
}
