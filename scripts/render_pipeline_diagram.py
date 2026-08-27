#!/usr/bin/env python3
"""
The one drawing of what this system does.

Emits `frontend/public/img/pipeline-{light,dark}.svg` — used by the landing
page (which swaps the two on the theme toggle), the README, and
docs/02-architecture.md.

Authored as a generator rather than as two hand-kept SVG files for the reason
the logo taught us: a second copy is a second chance to drift, and a diagram
that disagrees with itself between light and dark is worse than no diagram.
Geometry is computed here once; only the palette differs between outputs.

Run after editing:

    python3 scripts/render_pipeline_diagram.py
"""
from __future__ import annotations

import pathlib

# ── Palettes ──────────────────────────────────────────────────────────────────
# The same tokens frontend/src/index.css declares, resolved to literals because
# a standalone SVG has no stylesheet to inherit from.

LIGHT = dict(
    bg="#fbfaf8", surface="#ffffff", rule="#e2dace", ink="#14110c",
    muted="#83786a", faint="#a89c8d", accent="#f2600c", accent_soft="#fdeadd",
    good="#15803d",
)

DARK = dict(
    bg="#0e0c09", surface="#171309", rule="#302925", ink="#f0ece4",
    muted="#9a8f82", faint="#6f655b", accent="#f2600c", accent_soft="#33190a",
    good="#4ade80",
)

W, H = 1180, 562

CARD_W, CARD_H, CARD_Y = 240, 246, 64
CARD_X = [20, 320, 620, 920]

SANS = "Archivo, 'Helvetica Neue', Helvetica, Arial, sans-serif"

# Named to match the four steps the landing page prints beneath this drawing.
# They disagreed once — "Evidence"/"Execute" here against "Ingest"/"Act" there —
# which reads as two different processes to anyone who looks twice.
STAGES = [
    ("01", "INGEST", "what the market said"),
    ("02", "SCORE", "one number, decomposed"),
    ("03", "CONFIRM", "a verdict must hold"),
    ("04", "ACT", "guards, then size"),
]

INPUTS = [
    "Prices & volume",
    "Filings, accumulated",
    "Earnings history",
    "News sentiment",
    "Macro rates & VIX",
    "Options flow, insiders",
]

FACTORS = [
    ("Technical", 0.82), ("Catalyst", 0.88), ("Fundamental", 0.71),
    ("Sentiment", 0.64), ("Macro", 0.55), ("Volatility", 0.49),
]

CONFIRMS = [
    "3 fresh evaluations agree",
    "45 min minimum dwell",
    "Hysteresis band cleared",
]

GUARDS = ["Position cap", "Daily-loss switch", "Cash reserve", "Never unbracketed"]

AGENTS = ["Fundamentals", "Technical", "News", "Risk"]


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, *, fill, size=11.5, weight=400, anchor="start",
         spacing=None, family=SANS, opacity=None):
    attrs = [
        f'x="{x}"', f'y="{y}"', f'font-family="{family}"',
        f'font-size="{size}"', f'font-weight="{weight}"', f'fill="{fill}"',
    ]
    if anchor != "start":
        attrs.append(f'text-anchor="{anchor}"')
    if spacing:
        attrs.append(f'letter-spacing="{spacing}"')
    if opacity is not None:
        attrs.append(f'opacity="{opacity}"')
    return f'  <text {" ".join(attrs)}>{esc(s)}</text>'


def render(p: dict) -> str:
    o: list[str] = []
    add = o.append

    add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}" role="img" '
        f'aria-label="How the SAMSBPM Trading Agent works: evidence, score, '
        f'confirm, execute — with deep research able to veto a buy, and every '
        f'outcome recorded.">')

    add('  <defs>')
    add(f'    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M0,1 L9,5 L0,9" fill="none" stroke="{p["muted"]}" '
        f'stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></marker>')
    add(f'    <marker id="arrow-accent" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M0,1 L9,5 L0,9" fill="none" stroke="{p["accent"]}" '
        f'stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></marker>')
    add('  </defs>')

    add(f'  <rect width="{W}" height="{H}" fill="{p["bg"]}"/>')

    # ── Header ────────────────────────────────────────────────────────────────
    add(text(20, 30, "SAMSBPM TRADING AGENT", fill=p["ink"], size=12,
             weight=700, spacing="0.14em"))
    add(text(W - 20, 30, "ONE CYCLE · EVERY FIVE MINUTES · EVERY WATCHED NAME",
             fill=p["muted"], size=10, weight=600, anchor="end", spacing="0.12em"))

    # ── Stage cards ───────────────────────────────────────────────────────────
    for i, (num, title, sub) in enumerate(STAGES):
        x, y = CARD_X[i], CARD_Y
        add(f'  <rect x="{x}" y="{y}" width="{CARD_W}" height="{CARD_H}" rx="8" '
            f'fill="{p["surface"]}" stroke="{p["rule"]}"/>')
        add(text(x + 18, y + 28, num, fill=p["accent"], size=12, weight=700))
        add(text(x + 42, y + 28, title, fill=p["ink"], size=13, weight=700,
                 spacing="0.1em"))
        add(text(x + 18, y + 46, sub, fill=p["faint"], size=10.5))
        add(f'  <line x1="{x + 18}" y1="{y + 58}" x2="{x + CARD_W - 18}" '
            f'y2="{y + 58}" stroke="{p["rule"]}"/>')

    # Connectors between cards.
    mid = CARD_Y + CARD_H / 2
    for i in range(3):
        x1 = CARD_X[i] + CARD_W + 8
        x2 = CARD_X[i + 1] - 8
        add(f'  <line x1="{x1}" y1="{mid}" x2="{x2}" y2="{mid}" '
            f'stroke="{p["muted"]}" stroke-width="1.4" marker-end="url(#arrow)"/>')

    # ── 01 Evidence ───────────────────────────────────────────────────────────
    x, y = CARD_X[0], CARD_Y + 84
    for i, line in enumerate(INPUTS):
        ly = y + i * 23
        add(f'  <circle cx="{x + 22}" cy="{ly - 4}" r="2.4" fill="{p["accent"]}"/>')
        add(text(x + 34, ly, line, fill=p["muted"], size=11.5))
    add(text(x + 18, CARD_Y + CARD_H - 18,
             "every fact carries a source and a date",
             fill=p["faint"], size=9.5))

    # ── 02 Score ──────────────────────────────────────────────────────────────
    x = CARD_X[1]
    add(text(x + 18, CARD_Y + 104, "78", fill=p["ink"], size=42, weight=700))
    add(text(x + 68, CARD_Y + 104, "/100", fill=p["faint"], size=13))
    bar_x, bar_w = x + 92, 130
    for i, (name, value) in enumerate(FACTORS):
        by = CARD_Y + 122 + i * 17
        add(text(x + 18, by + 3, name, fill=p["muted"], size=9.5))
        add(f'  <rect x="{bar_x}" y="{by - 3}" width="{bar_w}" height="4" rx="2" '
            f'fill="{p["accent_soft"]}"/>')
        add(f'  <rect x="{bar_x}" y="{by - 3}" width="{round(bar_w * value, 1)}" '
            f'height="4" rx="2" fill="{p["accent"]}"/>')
    add(text(x + 18, CARD_Y + CARD_H - 18,
             "six weighted factors, shown with the score",
             fill=p["faint"], size=9.5))

    # ── 03 Confirm ────────────────────────────────────────────────────────────
    x = CARD_X[2]
    for i, line in enumerate(CONFIRMS):
        ly = CARD_Y + 90 + i * 26
        add(f'  <path d="M{x + 19},{ly - 8} l3.6,3.8 l6.6,-7.6" fill="none" '
            f'stroke="{p["good"]}" stroke-width="1.8" stroke-linecap="round" '
            f'stroke-linejoin="round"/>')
        add(text(x + 36, ly, line, fill=p["muted"], size=11.5))
    add(f'  <line x1="{x + 18}" y1="{CARD_Y + 172}" x2="{x + CARD_W - 18}" '
        f'y2="{CARD_Y + 172}" stroke="{p["rule"]}"/>')
    add(text(x + 18, CARD_Y + 192, "SELL IS EXEMPT", fill=p["accent"], size=10,
             weight=700, spacing="0.1em"))
    add(text(x + 18, CARD_Y + 208, "from every delay — a late exit", fill=p["faint"], size=9.5))
    add(text(x + 18, CARD_Y + 221, "costs money, a late entry costs", fill=p["faint"], size=9.5))
    add(text(x + 18, CARD_Y + 234, "an opportunity", fill=p["faint"], size=9.5))

    # ── 04 Execute ────────────────────────────────────────────────────────────
    x = CARD_X[3]
    for i, line in enumerate(GUARDS):
        ly = CARD_Y + 90 + i * 23
        add(f'  <rect x="{x + 19}" y="{ly - 11}" width="11" height="11" rx="2.5" '
            f'fill="none" stroke="{p["muted"]}" stroke-width="1.3"/>')
        add(f'  <path d="M{x + 21.6},{ly - 5.6} l2.6,2.7 l4.6,-5.4" fill="none" '
            f'stroke="{p["good"]}" stroke-width="1.6" stroke-linecap="round" '
            f'stroke-linejoin="round"/>')
        add(text(x + 38, ly, line, fill=p["muted"], size=11.5))
    add(f'  <rect x="{x + 18}" y="{CARD_Y + 176}" width="{CARD_W - 36}" height="40" '
        f'rx="5" fill="{p["accent_soft"]}"/>')
    add(text(x + 30, CARD_Y + 193, "BUY 12 @ 61.40", fill=p["ink"], size=11.5, weight=700))
    add(text(x + 30, CARD_Y + 208, "stop 56.90 · target 70.10", fill=p["muted"], size=10))
    add(text(x + 18, CARD_Y + CARD_H - 14, "proposed to you, or placed unattended",
             fill=p["faint"], size=9.5))

    # ── Deep research ─────────────────────────────────────────────────────────
    rx, ry, rw, rh = 320, 372, 540, 92
    add(f'  <rect x="{rx}" y="{ry}" width="{rw}" height="{rh}" rx="8" '
        f'fill="{p["surface"]}" stroke="{p["rule"]}" stroke-dasharray="4 3"/>')
    add(text(rx + 18, ry + 26, "DEEP RESEARCH", fill=p["ink"], size=11.5,
             weight=700, spacing="0.1em"))
    add(text(rx + 132, ry + 26, "— on demand, and once a day", fill=p["faint"], size=10))
    pill_x = rx + 18
    for name in AGENTS:
        w = 8 + len(name) * 5.9
        add(f'  <rect x="{pill_x}" y="{ry + 40}" width="{round(w, 1)}" height="20" '
            f'rx="4" fill="{p["accent_soft"]}"/>')
        add(text(pill_x + w / 2, ry + 54, name, fill=p["accent"], size=9.5,
                 weight=600, anchor="middle"))
        pill_x += w + 8
    add(text(rx + 18, ry + 79, "four scoped agents · every claim cited, or deleted",
             fill=p["muted"], size=10))

    # Veto path: research → execute. Dashed, one-directional, and labelled with
    # the constraint rather than the capability.
    add(f'  <path d="M{rx + rw},{ry + 30} C {rx + rw + 40},{ry + 30} '
        f'{CARD_X[3] + 60},{ry + 10} {CARD_X[3] + 100},{CARD_Y + CARD_H + 6}" '
        f'fill="none" stroke="{p["accent"]}" stroke-width="1.4" '
        f'stroke-dasharray="4 3" marker-end="url(#arrow-accent)"/>')
    add(text(CARD_X[3] + 4, ry + 62, "MAY VETO A BUY", fill=p["accent"], size=10,
             weight=700, spacing="0.09em"))
    add(text(CARD_X[3] + 4, ry + 78, "never creates one, never", fill=p["faint"], size=9.5))
    add(text(CARD_X[3] + 4, ry + 91, "reaches an exit", fill=p["faint"], size=9.5))

    # ── Feedback loop ─────────────────────────────────────────────────────────
    loop_y = 534
    add(f'  <path d="M{CARD_X[3] + CARD_W - 40},{CARD_Y + CARD_H + 6} '
        f'V{loop_y - 14} Q{CARD_X[3] + CARD_W - 40},{loop_y} '
        f'{CARD_X[3] + CARD_W - 54},{loop_y} '
        f'H{CARD_X[0] + 134} Q{CARD_X[0] + 120},{loop_y} '
        f'{CARD_X[0] + 120},{loop_y - 14} '
        f'V{CARD_Y + CARD_H + 6}" fill="none" stroke="{p["muted"]}" '
        f'stroke-width="1.4" stroke-dasharray="4 3" marker-end="url(#arrow)"/>')
    add(text(W / 2 - 40, loop_y - 10,
             "EVERY OUTCOME RECORDED — WIN RATE, CALIBRATION, NET OF COMMISSION",
             fill=p["muted"], size=9.5, weight=600, anchor="middle", spacing="0.1em"))

    add('</svg>')
    return "\n".join(o) + "\n"


def main() -> None:
    root = pathlib.Path(__file__).resolve().parent.parent
    out = root / "frontend" / "public" / "img"
    out.mkdir(parents=True, exist_ok=True)
    for name, palette in (("light", LIGHT), ("dark", DARK)):
        path = out / f"pipeline-{name}.svg"
        path.write_text(render(palette), encoding="utf-8")
        print(f"wrote {path.relative_to(root)}")


if __name__ == "__main__":
    main()
