/**
 * UI sound effects, synthesized with the Web Audio API (no audio files to ship or load).
 *
 * Browsers only allow audio after a user gesture, so the context is created lazily and
 * resumed by `unlock()` on the first pointer/key press. Preference (on/off + volume) is
 * kept in localStorage; components subscribe through useSyncExternalStore.
 */
import type { Verdict } from "@/types";

const STORAGE_KEY = "pcb_sound";

type Wave = OscillatorType;

interface ToneOptions {
  type?: Wave;
  gain?: number;
  delay?: number;
  /** Glide to this frequency over the tone's duration. */
  slideTo?: number;
}

class SoundEngine {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private listeners = new Set<() => void>();
  private lastTick = 0;
  private lastAlarm = 0;
  private lastStep = 0;
  enabled = true;
  volume = 0.6;
  private snapshot = { enabled: true, volume: 0.6 };

  constructor() {
    if (typeof window === "undefined") return;
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
      if (saved && typeof saved === "object") {
        this.enabled = saved.enabled !== false;
        if (typeof saved.volume === "number") this.volume = Math.min(1, Math.max(0, saved.volume));
      }
    } catch {
      // Keep defaults.
    }
    this.snapshot = { enabled: this.enabled, volume: this.volume };
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  /** Snapshot for useSyncExternalStore (must be referentially stable between changes). */
  getSnapshot = () => this.snapshot;

  private emit() {
    this.snapshot = { enabled: this.enabled, volume: this.volume };
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.snapshot));
    } catch {
      // Preference just won't persist.
    }
    if (this.master) this.master.gain.value = this.volume;
    this.listeners.forEach((l) => l());
  }

  setEnabled(enabled: boolean) {
    this.enabled = enabled;
    this.emit();
    if (enabled) this.ding();
  }

  setVolume(volume: number) {
    this.volume = Math.min(1, Math.max(0, volume));
    this.emit();
  }

  /** Call from a user gesture so later (event-driven) sounds are allowed to play. */
  unlock = () => {
    const ctx = this.context();
    if (ctx && ctx.state === "suspended") ctx.resume().catch(() => undefined);
  };

  private context(): AudioContext | null {
    if (typeof window === "undefined") return null;
    if (!this.ctx) {
      const Ctor = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Ctor) return null;
      this.ctx = new Ctor();
      const compressor = this.ctx.createDynamicsCompressor();
      this.master = this.ctx.createGain();
      this.master.gain.value = this.volume;
      this.master.connect(compressor).connect(this.ctx.destination);
    }
    return this.ctx;
  }

  private ready(): AudioContext | null {
    if (!this.enabled || this.volume <= 0) return null;
    const ctx = this.context();
    if (!ctx || ctx.state !== "running") {
      ctx?.resume().catch(() => undefined);
      return ctx?.state === "running" ? ctx : null;
    }
    return ctx;
  }

  private tone(freq: number, duration: number, { type = "sine", gain = 0.25, delay = 0, slideTo }: ToneOptions = {}) {
    const ctx = this.ready();
    if (!ctx || !this.master) return;
    const t0 = ctx.currentTime + delay;
    const osc = ctx.createOscillator();
    const env = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t0);
    if (slideTo) osc.frequency.exponentialRampToValueAtTime(slideTo, t0 + duration);
    // Short attack + exponential release: clicks-free and snappy.
    env.gain.setValueAtTime(0.0001, t0);
    env.gain.exponentialRampToValueAtTime(gain, t0 + 0.008);
    env.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);
    osc.connect(env).connect(this.master);
    osc.start(t0);
    osc.stop(t0 + duration + 0.02);
  }

  private noise(duration: number, { gain = 0.2, delay = 0, freq = 2500, q = 0.8 } = {}) {
    const ctx = this.ready();
    if (!ctx || !this.master) return;
    const t0 = ctx.currentTime + delay;
    const buffer = ctx.createBuffer(1, Math.ceil(ctx.sampleRate * duration), ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / data.length);
    const src = ctx.createBufferSource();
    const filter = ctx.createBiquadFilter();
    const env = ctx.createGain();
    src.buffer = buffer;
    filter.type = "bandpass";
    filter.frequency.value = freq;
    filter.Q.value = q;
    env.gain.setValueAtTime(gain, t0);
    env.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);
    src.connect(filter).connect(env).connect(this.master);
    src.start(t0);
  }

  /* ── Effects ─────────────────────────────────────────── */

  /** One inspected frame. Rate-limited so fast multi-frame runs don't turn into a buzz. */
  tick() {
    const now = performance.now();
    if (now - this.lastTick < 45) return;
    this.lastTick = now;
    this.tone(2100, 0.035, { type: "triangle", gain: 0.07 });
  }

  /** Camera capture. */
  shutter() {
    this.noise(0.05, { gain: 0.35, freq: 3200, q: 0.6 });
    this.noise(0.07, { gain: 0.25, freq: 1800, q: 0.9, delay: 0.06 });
  }

  pass() {
    this.tone(1046.5, 0.12, { gain: 0.18 });
    this.tone(1318.5, 0.18, { gain: 0.18, delay: 0.09 });
  }

  fail() {
    this.tone(220, 0.16, { type: "square", gain: 0.1, slideTo: 190 });
    this.tone(196, 0.24, { type: "square", gain: 0.1, delay: 0.17, slideTo: 150 });
  }

  review() {
    this.tone(740, 0.1, { type: "triangle", gain: 0.16 });
    this.tone(740, 0.12, { type: "triangle", gain: 0.16, delay: 0.14 });
  }

  verdict(v: Verdict) {
    if (v === "PASS") this.pass();
    else if (v === "FAIL") this.fail();
    else if (v === "REVIEW") this.review();
    else this.error();
  }

  /** Whole scan finished. */
  complete(v: Verdict) {
    if (v === "PASS") {
      [523.25, 659.25, 783.99, 1046.5].forEach((f, i) => this.tone(f, 0.22, { gain: 0.16, delay: i * 0.09 }));
    } else if (v === "FAIL") {
      [392, 311.13, 246.94].forEach((f, i) => this.tone(f, 0.28, { type: "sawtooth", gain: 0.07, delay: i * 0.16 }));
    } else {
      [659.25, 587.33].forEach((f, i) => this.tone(f, 0.2, { type: "triangle", gain: 0.15, delay: i * 0.14 }));
    }
  }

  /** Scan / motion started. */
  start() {
    this.tone(440, 0.18, { type: "triangle", gain: 0.12, slideTo: 880 });
  }

  /** Emergency stop or aborted scan. */
  alarm() {
    // STOP from the header and the resulting "aborted" scan event shouldn't double up.
    const now = performance.now();
    if (now - this.lastAlarm < 1500) return;
    this.lastAlarm = now;
    [880, 660, 880, 660].forEach((f, i) => this.tone(f, 0.12, { type: "square", gain: 0.08, delay: i * 0.13 }));
  }

  /** Generic confirmation (connected, homed, saved). */
  ding() {
    this.tone(1568, 0.25, { gain: 0.12 });
  }

  error() {
    this.tone(330, 0.14, { type: "triangle", gain: 0.16, slideTo: 220 });
  }

  /* ── AI assistant ─────────────────────────────────────── */

  /** Assistant window opened. */
  chatOpen() {
    this.tone(659.25, 0.09, { gain: 0.1 });
    this.tone(987.77, 0.16, { gain: 0.1, delay: 0.07 });
  }

  /** Assistant window closed. */
  chatClose() {
    this.tone(880, 0.08, { gain: 0.08 });
    this.tone(587.33, 0.14, { gain: 0.08, delay: 0.07 });
  }

  /** A question was sent. */
  chatSend() {
    this.tone(520, 0.11, { type: "triangle", gain: 0.1, slideTo: 940 });
  }

  /** The agent started a tool step (reading data). Rate-limited like tick(). */
  chatStep() {
    const now = performance.now();
    if (now - this.lastStep < 120) return;
    this.lastStep = now;
    this.tone(1320, 0.05, { gain: 0.07 });
  }

  /** The agent opened another page. */
  whoosh() {
    this.noise(0.14, { gain: 0.1, freq: 1400, q: 0.5 });
    this.tone(400, 0.14, { type: "sine", gain: 0.05, slideTo: 800 });
  }

  /** The answer is complete. */
  chatReply() {
    [783.99, 987.77, 1174.66].forEach((f, i) => this.tone(f, 0.16, { gain: 0.11, delay: i * 0.07 }));
  }
}

export const sfx = new SoundEngine();
