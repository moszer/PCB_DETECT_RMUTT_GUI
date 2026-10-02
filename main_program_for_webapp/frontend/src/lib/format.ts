import type { ReferenceSummary, Verdict } from "@/types";

/** Component category colors — mirrors CATEGORY_COLORS_HEX in backend/app/core/inspection.py. */
const CATEGORY_COLORS = {
  ic: "#3B82F6",
  capacitor: "#F59E0B",
  resistor: "#10B981",
  diode: "#8B5CF6",
  led: "#EC4899",
  default: "#94A3B8",
} as const;

const CATEGORY_KEYWORDS: Array<[keyof typeof CATEGORY_COLORS, string[]]> = [
  ["capacitor", ["capacitor", "cap"]],
  ["resistor", ["resistor", "res"]],
  ["diode", ["diode"]],
  ["led", ["led"]],
  ["ic", ["chip", "sot", "connector", "usb", "sdcard", "xtal", "input", "ic"]],
];

export function classColor(label: string): string {
  const lowered = label.toLowerCase();
  for (const [category, keywords] of CATEGORY_KEYWORDS) {
    if (keywords.some((k) => lowered.includes(k))) return CATEGORY_COLORS[category];
  }
  return CATEGORY_COLORS.default;
}

export const VERDICT_LABEL: Record<Verdict, string> = {
  PASS: "ผ่าน",
  FAIL: "ไม่ผ่าน",
  REVIEW: "ตรวจซ้ำ",
  ERROR: "ผิดพลาด",
};

/** Tailwind classes for a verdict, built only from design tokens. */
export const VERDICT_TONE: Record<Verdict, { text: string; soft: string; solid: string; border: string }> = {
  PASS: { text: "text-pass", soft: "bg-pass-soft", solid: "bg-pass", border: "border-pass" },
  FAIL: { text: "text-fail", soft: "bg-fail-soft", solid: "bg-fail", border: "border-fail" },
  REVIEW: { text: "text-review", soft: "bg-review-soft", solid: "bg-review", border: "border-review" },
  ERROR: { text: "text-muted", soft: "bg-surface-3", solid: "bg-subtle", border: "border-line-strong" },
};

/** YOLO inference sizes (imgsz). This is the model input size, not the camera resolution. */
export const IMGSZ_OPTIONS = [320, 416, 512, 640, 768, 960, 1280, 1600, 1920, 2560, 3200, 3840, 4096] as const;

export const formatDateTime = (epochSeconds: number) =>
  new Date(epochSeconds * 1000).toLocaleString("th-TH", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

export const formatMm = (v: number | undefined | null) => (typeof v === "number" ? v.toFixed(2) : "–");

export const percent = (ratio: number) => `${Math.round(ratio * 100)}%`;

export const fileName = (path: string) => path.split(/[\\/]/).pop() || path;

export const refsOfType = (refs: ReferenceSummary[], type: ReferenceSummary["profile_type"]) =>
  refs.filter((r) => r.profile_type === type);
