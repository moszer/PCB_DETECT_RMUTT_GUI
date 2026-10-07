/** Green → amber → red for 0..1, as a CSS colour (same scale as the 3D views' goodBadColor). */
export function goodBadHex(t: number): string {
  const x = Math.min(1, Math.max(0, t));
  const [r, g, b] = x < 0.5 ? [0.13 + x * 1.7, 0.72, 0.36 - x * 0.4] : [0.98, 0.72 - (x - 0.5) * 1.1, 0.16];
  const h = (v: number) => Math.round(Math.min(1, Math.max(0, v)) * 255).toString(16).padStart(2, "0");
  return `#${h(r)}${h(g)}${h(b)}`;
}
