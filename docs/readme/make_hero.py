"""Build docs/readme/aoi-hero.svg: the animated banner at the top of the README.

The camera head of the XY gantry visits six test points on a board in a serpentine path,
YOLO boxes appear on the parts it sees, the scan dock tiles turn PASS/FAIL, and point 5
(a resistor left off the board) ends the run as FAIL. CSS keyframes only (no script), so
GitHub renders it in an <img>. With prefers-reduced-motion the picture shows the end state.

    python3 docs/readme/make_hero.py
"""
from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).with_name("aoi-hero.svg")

W, H = 1200, 420
T = 14.0  # loop length (s)
TRAVEL, DWELL = 0.6, 1.2
FOV_W, FOV_H = 150, 120
HOME = (700, 112)
POINTS = [(740, 135), (890, 135), (1040, 135), (1040, 255), (890, 255), (740, 255)]
FAIL_AT = 4  # point 5: the missing resistor
END_FADE = 13.3

BLUE, AMBER, GREEN, SLATE, RED = "#3b82f6", "#f59e0b", "#10b981", "#94a3b8", "#ef4444"

arrive = [TRAVEL + (TRAVEL + DWELL) * i for i in range(len(POINTS))]
leave = [a + DWELL for a in arrive]
HOME_AGAIN = leave[-1] + 0.8
VERDICT = leave[-1] + 0.2


def pct(t: float) -> str:
    return f"{max(0.0, min(100.0, t / T * 100)):.3f}%"


css: list[str] = []
_n = 0


def appear(at: float, until: float = END_FADE, fade: float = 0.25, peak: float = 1.0) -> str:
    """Class of an element hidden until `at`, shown until `until`, then hidden again."""
    global _n
    _n += 1
    name = f"a{_n}"
    css.append(
        f"@keyframes {name}{{0%,{pct(at)}{{opacity:0}}{pct(at + fade)},{pct(until)}{{opacity:{peak}}}"
        f"{pct(until + 0.4)},100%{{opacity:0}}}}"
        f".{name}{{animation:{name} {T}s linear infinite both}}"
    )
    return name


def flash(at: float) -> str:
    global _n
    _n += 1
    name = f"f{_n}"
    css.append(
        f"@keyframes {name}{{0%,{pct(at)}{{opacity:0}}{pct(at + 0.08)}{{opacity:.45}}{pct(at + 0.4)},100%{{opacity:0}}}}"
        f".{name}{{opacity:0;animation:{name} {T}s linear infinite both}}"
    )
    return name


def tile_fill(at: float, color: str) -> str:
    global _n
    _n += 1
    name = f"t{_n}"
    css.append(
        f"@keyframes {name}{{0%,{pct(at)}{{fill:#1e293b}}{pct(at + 0.2)},{pct(END_FADE)}{{fill:{color}}}"
        f"{pct(END_FADE + 0.4)},100%{{fill:#1e293b}}}}"
        f".{name}{{animation:{name} {T}s linear infinite both}}"
    )
    return name


def head_keyframes() -> None:
    """Head (FOV) and gantry beam follow the same timeline: HOME, P1..P6, HOME."""
    stops = [(0.0, HOME)]
    for a, l, p in zip(arrive, leave, POINTS):
        stops += [(a, p), (l, p)]
    stops += [(HOME_AGAIN, HOME), (T, HOME)]
    head = "".join(f"{pct(t)}{{transform:translate({x}px,{y}px)}}" for t, (x, y) in stops)
    beam = "".join(f"{pct(t)}{{transform:translate(0px,{y - 76}px)}}" for t, (_x, y) in stops)
    css.append(f"@keyframes head{{{head}}}.head{{transform:translate({HOME[0]}px,{HOME[1]}px);animation:head {T}s ease-in-out infinite}}")
    css.append(f"@keyframes beam{{{beam}}}.beam{{transform:translate(0px,{HOME[1] - 76}px);animation:beam {T}s ease-in-out infinite}}")
    # Progress bar of the scan dock.
    prog = "".join(f"{pct(l)}{{transform:scaleX({(i + 1) / len(POINTS):.3f})}}" for i, l in enumerate(leave))
    css.append(
        f"@keyframes prog{{0%,{pct(arrive[0])}{{transform:scaleX(0)}}{prog}{pct(END_FADE)}{{transform:scaleX(1)}}"
        f"{pct(END_FADE + 0.4)},100%{{transform:scaleX(0)}}}}"
        f".prog{{transform-box:fill-box;transform-origin:left center;animation:prog {T}s linear infinite both}}"
    )
    css.append(
        f"@keyframes pop{{0%,{pct(VERDICT)}{{opacity:0;transform:scale(.6)}}{pct(VERDICT + 0.35)}{{opacity:1;transform:scale(1.06)}}"
        f"{pct(VERDICT + 0.55)},{pct(END_FADE)}{{opacity:1;transform:scale(1)}}{pct(END_FADE + 0.4)},100%{{opacity:0;transform:scale(1)}}}}"
        f".pop{{transform-box:fill-box;transform-origin:center;animation:pop {T}s ease-out infinite both}}"
    )


# ---------------------------------------------------------------- board parts (top view)

def chip(x, y, w=64, h=40, name="U1"):
    pins = "".join(
        f'<rect x="{x - w / 2 + 6 + i * (w - 12) / 6:.1f}" y="{y - h / 2 - 5}" width="4" height="5" fill="#cbd5e1"/>'
        f'<rect x="{x - w / 2 + 6 + i * (w - 12) / 6:.1f}" y="{y + h / 2}" width="4" height="5" fill="#cbd5e1"/>'
        for i in range(7)
    )
    return (
        f'{pins}<rect x="{x - w / 2}" y="{y - h / 2}" width="{w}" height="{h}" rx="3" fill="#0b0f19"/>'
        f'<circle cx="{x - w / 2 + 7}" cy="{y - h / 2 + 7}" r="2.2" fill="#334155"/>'
        f'<text x="{x}" y="{y + 4}" class="silk" text-anchor="middle">{name}</text>'
    )


def smd(x, y, w, h, body, cap="#d4d4d8", vertical=False):
    if vertical:
        w, h = h, w
        return (
            f'<rect x="{x - w / 2}" y="{y - h / 2}" width="{w}" height="{h}" rx="1.5" fill="{body}"/>'
            f'<rect x="{x - w / 2}" y="{y - h / 2}" width="{w}" height="4" fill="{cap}"/>'
            f'<rect x="{x - w / 2}" y="{y + h / 2 - 4}" width="{w}" height="4" fill="{cap}"/>'
        )
    return (
        f'<rect x="{x - w / 2}" y="{y - h / 2}" width="{w}" height="{h}" rx="1.5" fill="{body}"/>'
        f'<rect x="{x - w / 2}" y="{y - h / 2}" width="4" height="{h}" fill="{cap}"/>'
        f'<rect x="{x + w / 2 - 4}" y="{y - h / 2}" width="4" height="{h}" fill="{cap}"/>'
    )


def pads(x, y, w=26, h=12):
    return (
        f'<rect x="{x - w / 2}" y="{y - h / 2}" width="6" height="{h}" rx="1" fill="#e5c07b" opacity=".85"/>'
        f'<rect x="{x + w / 2 - 6}" y="{y - h / 2}" width="6" height="{h}" rx="1" fill="#e5c07b" opacity=".85"/>'
    )


def electrolytic(x, y, r=16):
    return (
        f'<circle cx="{x}" cy="{y}" r="{r}" fill="#1f2937" stroke="#94a3b8" stroke-width="1.5"/>'
        f'<path d="M{x - r * .7:.1f} {y - r * .7:.1f} A{r} {r} 0 0 1 {x + r * .7:.1f} {y - r * .7:.1f}" '
        f'stroke="#cbd5e1" stroke-width="4" fill="none" opacity=".7"/>'
        f'<path d="M{x - 5} {y + 1}h10M{x} {y - 4}v10" stroke="#64748b" stroke-width="1.5"/>'
    )


def usb(x, y):
    return (
        f'<rect x="{x - 28}" y="{y - 20}" width="56" height="40" rx="3" fill="#9ca3af" stroke="#e5e7eb"/>'
        f'<rect x="{x - 18}" y="{y - 6}" width="36" height="12" rx="2" fill="#1f2937"/>'
        f'<rect x="{x - 12}" y="{y - 2}" width="24" height="4" fill="#cbd5e1"/>'
    )


def led(x, y, color="#f87171"):
    return smd(x, y, 18, 10, color, "#e5e7eb") + f'<circle cx="{x}" cy="{y}" r="2" fill="#fff" opacity=".7"/>'


def xtal(x, y):
    return (
        f'<rect x="{x - 26}" y="{y - 11}" width="52" height="22" rx="11" fill="#d1d5db" stroke="#f3f4f6"/>'
        f'<text x="{x}" y="{y + 4}" font-size="9" fill="#475569" text-anchor="middle" font-family="ui-monospace,Menlo,monospace">16.000</text>'
    )


def transistor(x, y):
    """SOT-23: a small black body, one lead on top and two below."""
    return (
        f'<rect x="{x - 3}" y="{y - 13}" width="6" height="6" fill="#d4d4d8"/>'
        f'<rect x="{x - 11}" y="{y + 7}" width="6" height="6" fill="#d4d4d8"/>'
        f'<rect x="{x + 5}" y="{y + 7}" width="6" height="6" fill="#d4d4d8"/>'
        f'<rect x="{x - 14}" y="{y - 8}" width="28" height="16" rx="2" fill="#0b0f19"/>'
    )


def button(x, y):
    return (
        f'<rect x="{x - 19}" y="{y - 19}" width="38" height="38" rx="4" fill="#374151" stroke="#9ca3af"/>'
        f'<circle cx="{x}" cy="{y}" r="11" fill="#111827" stroke="#4b5563"/>'
    )


# (part svg, detection box (cx, cy, w, h), label, color) per point
PARTS = [
    [(chip(740, 135), (740, 135, 76, 54), "ic 0.97", BLUE)],
    [
        (electrolytic(858, 135), (858, 135, 38, 38), "capacitor 0.95", AMBER),
        (smd(930, 110, 20, 10, "#c8a46e"), (930, 110, 26, 16), "capacitor 0.93", AMBER),
        (smd(930, 160, 20, 10, "#c8a46e"), (930, 160, 26, 16, True), "capacitor 0.94", AMBER),
    ],
    [
        (usb(1030, 132), (1030, 132, 64, 48), "connector 0.96", BLUE),
        (led(1088, 170), (1088, 170, 26, 18), "led 0.91", SLATE),
    ],
    [
        (xtal(1026, 240), (1026, 240, 60, 30), "clock 0.92", SLATE),
        (transistor(1080, 282), (1080, 282, 34, 32), "transistor 0.90", SLATE),
    ],
    [
        (smd(850, 255, 26, 12, "#0b0f19"), (850, 255, 34, 20, True), "resistor 0.95", GREEN),
        (pads(890, 255), None, None, None),  # the missing one
        (smd(930, 255, 26, 12, "#0b0f19"), (930, 255, 34, 20, True), "resistor 0.94", GREEN),
    ],
    [
        (button(730, 252), (730, 252, 46, 46), "switch 0.95", SLATE),
        (led(785, 288, "#4ade80"), (785, 288, 26, 18), "led 0.92", SLATE),
    ],
]


def det_box(cx, cy, w, h, label, color, below=False):
    x, y = cx - w / 2, cy - h / 2
    tw = len(label) * 5.1 + 8
    ty = y + h + 1 if below or y - 13 < 62 else y - 13
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="2" fill="{color}" fill-opacity=".10" stroke="{color}" stroke-width="1.6"/>'
        f'<rect x="{x}" y="{ty}" width="{tw:.1f}" height="12" rx="2" fill="{color}"/>'
        f'<text x="{x + 4}" y="{ty + 9}" class="tag">{label}</text>'
    )


def build() -> str:
    head_keyframes()
    board: list[str] = []
    boxes: list[str] = []
    for i, parts in enumerate(PARTS):
        cls = appear(arrive[i] + 0.55)
        group = []
        for svg, box, label, color in parts:
            board.append(svg)
            if box:
                group.append(det_box(*box[:4], label, color, *box[4:]))
        if i == FAIL_AT:
            group.append(
                f'<circle cx="890" cy="255" r="19" fill="{RED}" fill-opacity=".12" stroke="{RED}" stroke-width="2" stroke-dasharray="4 3"/>'
                f'<rect x="866" y="229" width="48" height="12" rx="2" fill="{RED}"/>'
                f'<text x="870" y="238" class="tag" style="fill:#fff">MISSING</text>'
            )
        boxes.append(f'<g class="{cls}">{"".join(group)}</g>')

    flashes = "".join(
        f'<rect class="{flash(a + 0.25)}" x="{x - FOV_W / 2}" y="{y - FOV_H / 2}" width="{FOV_W}" height="{FOV_H}" rx="6" fill="#fff"/>'
        for a, (x, y) in zip(arrive, POINTS)
    )

    # Scan dock: one tile per point under the board, plus a progress bar.
    tile_w, gap, tx0, ty0 = 74, 11.2, 640, 352
    tiles = []
    for i, l in enumerate(leave):
        x = tx0 + i * (tile_w + gap)
        bad = i == FAIL_AT
        color = "#7f1d1d" if bad else "#064e3b"
        word, wcolor = ("FAIL", "#fca5a5") if bad else ("PASS", "#6ee7b7")
        tiles.append(
            f'<rect class="{tile_fill(l - 0.1, color)}" x="{x:.1f}" y="{ty0}" width="{tile_w}" height="34" rx="7" fill="{color}" stroke="#334155"/>'
            f'<rect class="{appear(arrive[i], leave[i], 0.15)}" x="{x:.1f}" y="{ty0}" width="{tile_w}" height="34" rx="7" fill="none" stroke="#60a5fa" stroke-width="2"/>'
            f'<text x="{x + 10:.1f}" y="{ty0 + 22}" class="mono" style="font-size:12px" fill="#cbd5e1">{i + 1}</text>'
            f'<text class="mono {appear(l - 0.1)}" x="{x + tile_w - 10:.1f}" y="{ty0 + 22}" style="font-size:11px" '
            f'font-weight="700" fill="{wcolor}" text-anchor="end">{word}</text>'
        )
    progress = (
        f'<rect x="{tx0}" y="{ty0 + 44}" width="500" height="4" rx="2" fill="#1e293b"/>'
        f'<rect class="prog" x="{tx0}" y="{ty0 + 44}" width="500" height="4" rx="2" fill="url(#progress)"/>'
    )

    log_rows = [
        ("01", "ic", "0.97", "OK"),
        ("02", "capacitor ×3", "0.94", "OK"),
        ("03", "connector · led", "0.94", "OK"),
        ("04", "clock · transistor", "0.91", "OK"),
        ("05", "resistor R2", "—", "MISSING"),
        ("06", "switch · led", "0.94", "OK"),
    ]
    log = []
    for i, (n, part, conf, status) in enumerate(log_rows):
        y = 284 + i * 18
        ok = status == "OK"
        log.append(
            f'<g class="{appear(leave[i] - 0.1)}">'
            f'<text x="56" y="{y}" class="mono" fill="#64748b">{n}</text>'
            f'<text x="86" y="{y}" class="mono" fill="#cbd5e1">{part}</text>'
            f'<text x="262" y="{y}" class="mono" fill="#94a3b8">{conf}</text>'
            f'<text x="312" y="{y}" class="mono" font-weight="700" fill="{"#34d399" if ok else "#f87171"}">{status}</text></g>'
        )
    log.append(
        f'<g class="{appear(VERDICT)}"><text x="56" y="{284 + 6 * 18 + 6}" class="mono" font-weight="700" fill="#f87171">'
        f'FAIL</text><text x="98" y="{284 + 6 * 18 + 6}" class="mono" fill="#94a3b8">5/6 points OK · 1 part missing</text></g>'
    )

    traces = (
        '<g stroke="#22c55e" stroke-opacity=".28" stroke-width="2.2" fill="none" stroke-linecap="round">'
        '<path d="M772 135h40l20 -20h18"/><path d="M772 150h56l14 14v40h-24"/>'
        '<path d="M935 112h40l20 20h7"/><path d="M935 156h36l14 -14h17"/>'
        '<path d="M1040 155v40l-14 14v18"/><path d="M1088 180v30l-10 10v50"/>'
        '<path d="M865 255h12"/><path d="M903 255h14"/><path d="M943 255h50v-15h7"/>'
        '<path d="M749 252h12l12 12v24"/><path d="M708 135h-30v117h33"/>'
        '<path d="M800 288h37v-33h-4"/><path d="M1063 284h-49l-12 -12h-60"/></g>'
        '<g fill="#bbf7d0" fill-opacity=".35">'
        + "".join(f'<circle cx="{x}" cy="{y}" r="3"/>' for x, y in [(850, 115), (842, 204), (1002, 132), (1026, 227), (1078, 220), (993, 240), (761, 252), (678, 135), (837, 288), (940, 272)])
        + "</g>"
    )

    style = (
        ".title{font:800 40px ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;fill:#f8fafc;letter-spacing:-.5px}"
        ".sub{font:500 17px ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;fill:#94a3b8}"
        ".chip{font:600 12px ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;fill:#cbd5e1}"
        ".mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px}"
        ".silk{font:600 9px ui-monospace,Menlo,monospace;fill:#64748b}"
        ".tag{font:700 8.5px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;fill:#0b1220}"
        "@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:0}}.cursor{animation:blink 1s step-end infinite}"
        "@keyframes rec{0%,100%{opacity:1}50%{opacity:.25}}.rec{animation:rec 1.6s ease-in-out infinite}"
        "@keyframes glow{0%,100%{opacity:.25}50%{opacity:.8}}.glow{animation:glow 2.4s ease-in-out infinite}"
        + "".join(css)
        + "@media (prefers-reduced-motion:reduce){*{animation:none!important}.head{transform:translate(890px,255px)}.beam{transform:translate(0,179px)}}"
    )

    chips = []
    x = 56
    for label in ["YOLO", "FastAPI", "Next.js 16", "three.js", "Jetson Orin Nano", "Arduino XY stage"]:
        w = len(label) * 7 + 22
        chips.append(f'<rect x="{x}" y="206" width="{w}" height="26" rx="13" fill="#1e293b" stroke="#334155"/>'
                     f'<text x="{x + w / 2}" y="223" class="chip" text-anchor="middle">{label}</text>')
        x += w + 8
        if x > 520:
            break

    fov_brackets = (
        f'<g stroke="#60a5fa" stroke-width="2.5" fill="none" stroke-linecap="round">'
        f'<path d="M{-FOV_W / 2} {-FOV_H / 2 + 18}v-18h18M{FOV_W / 2 - 18} {-FOV_H / 2}h18v18'
        f'M{FOV_W / 2} {FOV_H / 2 - 18}v18h-18M{-FOV_W / 2 + 18} {FOV_H / 2}h-18v-18"/></g>'
        f'<rect x="{-FOV_W / 2}" y="{-FOV_H / 2}" width="{FOV_W}" height="{FOV_H}" rx="4" fill="#60a5fa" fill-opacity=".06"/>'
        '<path d="M-7 0h14M0 -7v14" stroke="#93c5fd" stroke-width="1.5"/>'
        # arm up to the carriage on the beam
        f'<path d="M0 {-FOV_H / 2}v-16" stroke="#64748b" stroke-width="3"/>'
        f'<rect x="-17" y="{-FOV_H / 2 - 24}" width="34" height="14" rx="3" fill="#64748b" stroke="#94a3b8"/>'
        f'<circle cx="0" cy="{-FOV_H / 2 - 17}" r="3" fill="#60a5fa" class="rec"/>'
    )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">
<title id="t">RMUTT PCB AOI Station</title>
<desc id="d">Animated: the camera head of an XY gantry visits six test points on a circuit board, YOLO marks the parts it finds, and the scan ends FAIL because a resistor is missing at point 5.</desc>
<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0b1220"/><stop offset="1" stop-color="#111a2e"/></linearGradient>
<linearGradient id="pcb" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#166534"/><stop offset="1" stop-color="#14532d"/></linearGradient>
<linearGradient id="progress" x1="0" x2="1"><stop offset="0" stop-color="#3b82f6"/><stop offset="1" stop-color="#60a5fa"/></linearGradient>
<pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M24 0H0V24" fill="none" stroke="#1e293b" stroke-width="1"/></pattern>
<clipPath id="card"><rect width="{W}" height="{H}" rx="20"/></clipPath>
</defs>
<style>{style}</style>
<g clip-path="url(#card)">
<rect width="{W}" height="{H}" fill="url(#bg)"/>
<rect width="{W}" height="{H}" fill="url(#grid)" opacity=".55"/>

<text x="56" y="92" class="mono" fill="#60a5fa"><tspan class="rec">●</tspan> rmutt · automated optical inspection</text>
<text x="54" y="138" class="title">RMUTT PCB AOI Station</text>
<text x="56" y="166" class="sub">A camera on an XY stage checks every test point of a board</text>
<text x="56" y="189" class="sub">against a taught golden reference, then says PASS or FAIL.</text>
{"".join(chips)}
<text x="56" y="262" class="mono" fill="#64748b">$ scan board RMUTT-01 · 6 points<tspan class="cursor" fill="#94a3b8"> ▌</tspan></text>
{"".join(log)}

<rect x="620" y="40" width="540" height="368" rx="16" fill="#0b1220" opacity=".55" stroke="#1e293b"/>
<rect x="626" y="48" width="8" height="300" rx="3" fill="#334155"/>
<rect x="1146" y="48" width="8" height="300" rx="3" fill="#334155"/>
<rect x="640" y="60" width="500" height="270" rx="14" fill="url(#pcb)" stroke="#15803d" stroke-width="2"/>
<g fill="#d4d4d8" opacity=".8"><circle cx="658" cy="78" r="6"/><circle cx="1122" cy="78" r="6"/><circle cx="658" cy="312" r="6"/><circle cx="1122" cy="312" r="6"/></g>
<g fill="none" stroke="#14532d" stroke-width="3"><circle cx="658" cy="78" r="3"/><circle cx="1122" cy="78" r="3"/><circle cx="658" cy="312" r="3"/><circle cx="1122" cy="312" r="3"/></g>
{traces}
<text x="1124" y="324" class="silk" style="fill:#bbf7d0" opacity=".55" text-anchor="end">RMUTT-01 REV B</text>
<text x="676" y="91" class="silk" style="fill:#93c5fd" text-anchor="start"><tspan class="glow">HOME</tspan></text>
{"".join(board)}
{flashes}
{"".join(boxes)}

<g class="beam"><rect x="626" y="0" width="528" height="9" rx="3" fill="#475569" opacity=".85"/></g>
<g class="head">{fov_brackets}</g>

<g class="pop"><rect x="934" y="68" width="200" height="74" rx="14" fill="#450a0a" fill-opacity=".94" stroke="{RED}" stroke-width="2"/>
<text x="1034" y="111" text-anchor="middle" font-family="ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif" font-size="34" font-weight="900" letter-spacing="4" fill="#fecaca">FAIL</text>
<text x="1034" y="131" text-anchor="middle" class="mono" style="font-size:10px" fill="#fca5a5">resistor R2 missing · pt 5</text></g>

{"".join(tiles)}
{progress}
</g>
</svg>
'''


if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.1f} KB)")
