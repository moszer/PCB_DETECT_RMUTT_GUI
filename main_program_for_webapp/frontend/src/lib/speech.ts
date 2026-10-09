/**
 * The AI assistant reads its answers aloud. First choice: Gemini TTS through the backend
 * (/api/chat/tts, natural voice, cached per piece). The answer is cut into pieces; one plays
 * while the next is fetched, so the first words come quickly. If Gemini can't speak (no key,
 * quota used up), the browser's own voice (Web Speech API, Thai on iOS/macOS/Android/Chrome)
 * reads the rest, and Gemini is skipped for a few minutes.
 *
 * iOS only lets sound start from a tap; `unlock()` plays silence on the shared audio element
 * and an empty utterance during one (the send button, the speaker toggle), so the reply can
 * be read when it arrives later.
 *
 * State (on/off, which message is loading / being read) is a tiny external store.
 */
import { useSyncExternalStore } from "react";
import { API_BASE, authHeaders } from "./api";

const PREF_KEY = "pcb_ai_voice";
const BROWSER_CHUNK = 180; // Chrome stops an utterance after ~15 s
const CLOUD_FIRST = 140; // short first piece: sound starts sooner
const CLOUD_CHUNK = 360;
const CLOUD_PAUSE_MS = 5 * 60 * 1000;
const SILENT_WAV = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";

type State = { auto: boolean; speaking: string | null; loading: string | null };
let state: State = { auto: readPref(), speaking: null, loading: null };
const listeners = new Set<() => void>();
let session = 0;
let fetches: AbortController | null = null;
let player: HTMLAudioElement | null = null;
let endPiece: (() => void) | null = null;
let cloudPausedUntil = 0;

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

export const speechSupported = () => typeof window !== "undefined" && ("speechSynthesis" in window || "Audio" in window);

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
 * Pieces of at most `size` characters (the first at most `first`): whole sentences joined
 * while they fit (fewer pauses), a long sentence cut at a comma or space.
 */
function chunks(text: string, size: number, first = size): string[] {
  const out: string[] = [];
  let buf = "";
  const limit = () => (out.length ? size : first);
  const flush = () => {
    if (buf) out.push(buf);
    buf = "";
  };
  for (const sentence of text.split(/(?<=[.!?。])\s+/)) {
    let rest = sentence.trim();
    while (rest.length > limit()) {
      flush();
      const max = limit();
      const cut = Math.max(rest.lastIndexOf(", ", max), rest.lastIndexOf(" ", max));
      const at = cut > max / 3 ? cut + 1 : max;
      out.push(rest.slice(0, at).trim());
      rest = rest.slice(at).trim();
    }
    if (!rest) continue;
    if (buf && buf.length + 1 + rest.length > limit()) flush();
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

/** The browser's own voice reads `text` (the fallback). */
function speakBrowser(id: string, text: string, my: number) {
  if (!("speechSynthesis" in window) || my !== session) return done(id, my);
  const pieces = chunks(text, BROWSER_CHUNK);
  if (!pieces.length) return done(id, my);
  const voice = thaiVoice();
  set({ loading: null });
  pieces.forEach((piece, i) => {
    const u = new SpeechSynthesisUtterance(piece);
    u.lang = voice?.lang ?? "th-TH";
    if (voice) u.voice = voice;
    u.rate = 1.05;
    if (i === pieces.length - 1) u.onend = () => done(id, my);
    u.onerror = () => done(id, my);
    window.speechSynthesis.speak(u);
  });
}

function done(id: string, my: number) {
  if (my === session && state.speaking === id) set({ speaking: null, loading: null });
}

async function fetchPiece(text: string, signal: AbortSignal): Promise<string> {
  const res = await fetch(`${API_BASE}/api/chat/tts`, { method: "POST", headers: authHeaders(), body: JSON.stringify({ text }), signal });
  if (!res.ok) throw new Error(`TTS ${res.status}`);
  return URL.createObjectURL(await res.blob());
}

function playPiece(url: string): Promise<void> {
  return new Promise((resolve, reject) => {
    player ??= new Audio();
    const audio = player;
    const finish = (ok: boolean) => {
      audio.onended = audio.onerror = null;
      endPiece = null;
      URL.revokeObjectURL(url);
      if (ok) resolve();
      else reject(new Error("audio"));
    };
    endPiece = () => finish(true);
    audio.onended = () => finish(true);
    audio.onerror = () => finish(false);
    audio.src = url;
    audio.play().catch(() => finish(false));
  });
}

/** Gemini voice, piece by piece (next one fetched while this one plays); browser voice on failure. */
async function speakCloud(id: string, text: string, my: number) {
  const pieces = chunks(text, CLOUD_CHUNK, CLOUD_FIRST);
  const ctl = new AbortController();
  fetches = ctl;
  let next = fetchPiece(pieces[0], ctl.signal);
  for (let i = 0; i < pieces.length; i++) {
    let url: string;
    try {
      url = await next;
    } catch {
      if (my !== session) return;
      cloudPausedUntil = Date.now() + CLOUD_PAUSE_MS; // quota / no key: don't keep trying
      return speakBrowser(id, pieces.slice(i).join(" "), my);
    }
    if (my !== session) return URL.revokeObjectURL(url);
    if (i + 1 < pieces.length) next = fetchPiece(pieces[i + 1], ctl.signal);
    next?.catch(() => undefined); // handled when awaited
    set({ loading: null });
    try {
      await playPiece(url);
    } catch {
      if (my !== session) return;
      return speakBrowser(id, pieces.slice(i).join(" "), my);
    }
    if (my !== session) return;
  }
  done(id, my);
}

/** Read `text` aloud as message `id` (stops whatever was being read). */
export function speak(id: string, text: string) {
  if (!speechSupported()) return;
  stop();
  const plain = speakable(text);
  if (!plain) return;
  const my = session;
  set({ speaking: id, loading: id });
  if (Date.now() < cloudPausedUntil) speakBrowser(id, plain, my);
  else void speakCloud(id, plain, my);
}

export function stop() {
  session++;
  fetches?.abort();
  fetches = null;
  if (player) {
    player.pause();
    endPiece?.();
  }
  if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
  if (state.speaking || state.loading) set({ speaking: null, loading: null });
}

export function toggle(id: string, text: string) {
  if (state.speaking === id) stop();
  else {
    unlock(true);
    speak(id, text);
  }
}

/** Call inside a tap/click: lets iOS play a reply that arrives later. */
export function unlock(force = false) {
  if (!speechSupported() || (!state.auto && !force)) return;
  try {
    player ??= new Audio();
    if (!player.src || player.src === SILENT_WAV || player.paused) {
      player.src = SILENT_WAV;
      player.play().catch(() => undefined);
    }
  } catch {
    // No audio element: the browser voice still works.
  }
  if ("speechSynthesis" in window) {
    const u = new SpeechSynthesisUtterance(" ");
    u.volume = 0;
    window.speechSynthesis.speak(u);
  }
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
const SERVER: State = { auto: false, speaking: null, loading: null };

/** { auto: read new answers aloud, speaking: message being read, loading: message whose voice is being made } */
export function useSpeech(): State {
  return useSyncExternalStore(subscribe, () => state, () => SERVER);
}
