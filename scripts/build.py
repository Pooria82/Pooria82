#!/usr/bin/env python3
"""Build every SVG the profile README shows.

One script draws all of it (header, section titles, social buttons, project
cards, toolbox, stats panel and footer) so the pieces share fonts, colours and
spacing. Each piece comes out twice, dark and light, for GitHub's <picture>
theme switch. Numbers on the cards and the stats panel come from the GitHub
GraphQL API, which is why .github/workflows/profile.yml reruns this daily and
publishes dist/ to the `output` branch.

    pip install fonttools brotli numpy pillow
    python scripts/build.py

The token comes from GITHUB_TOKEN, or from a logged-in `gh` CLI locally. A
token that can read private repositories makes the stats include them.

Animations stay cheap on purpose: an animated SVG inside <img> is repainted
whole on every frame, so there are no filters or masks, only transforms,
opacity and SMIL path morphs, and large gradients are baked into bitmaps.
"""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import math
import os
import subprocess
import sys
import urllib.request
from collections import Counter, defaultdict
from html import escape
from pathlib import Path

import numpy as np
from fontTools import subset
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw

USER = "Pooria82"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist"
FONTS = ROOT / "scripts" / "fonts"
LOGOS = ROOT / "scripts" / "logos"
ICONS = json.loads((ROOT / "scripts" / "icons.json").read_text("utf-8"))

# Five accents: cyan, violet, pink, amber, emerald. `series` (languages) and
# `ramp` (contribution levels) passed the dataviz palette validator for each
# surface: lightness band, chroma, colour-blind separation and contrast.
THEMES = {
    "dark": {
        "bg_a": "#04060A", "bg_b": "#0A1020", "card": "#0B0F17", "card2": "#111826", "line": "#1E293B",
        "ink": "#F1F5F9", "ink2": "#94A3B8", "ink3": "#475569", "dot": "#283548", "off": "#0E141E",
        "cyan": "#22D3EE", "violet": "#A78BFA", "pink": "#F472B6", "amber": "#FBBF24", "emerald": "#34D399",
        "ink_cyan": "#22D3EE", "ink_violet": "#A78BFA", "ink_pink": "#F472B6", "ink_amber": "#FBBF24",
        "ink_emerald": "#34D399", "ok": "#4ADE80", "glow": 0.24, "on_grad": "#05070B", "shine": 0.16,
        "badge": "#F1F5F9",
        "series": ["#00A7C1", "#C08700", "#987CE9", "#DD5DA2", "#00B055", "#4F94E8"], "other": "#475569",
        "ramp": ["#151C28", "#155E75", "#0E7490", "#0891B2", "#22D3EE"],
    },
    "light": {
        "bg_a": "#FFFFFF", "bg_b": "#EEF2F7", "card": "#FFFFFF", "card2": "#F8FAFC", "line": "#E2E8F0",
        "ink": "#0F172A", "ink2": "#475569", "ink3": "#94A3B8", "dot": "#CBD5E1", "off": "#F6F8FA",
        "cyan": "#0891B2", "violet": "#7C3AED", "pink": "#DB2777", "amber": "#D97706", "emerald": "#059669",
        "ink_cyan": "#0E7490", "ink_violet": "#6D28D9", "ink_pink": "#BE185D", "ink_amber": "#B45309",
        "ink_emerald": "#047857", "ok": "#16A34A", "glow": 0.13, "on_grad": "#FFFFFF", "shine": 0.55,
        "badge": "#0F172A",
        "series": ["#0091B4", "#B45309", "#7C3AED", "#DB2777", "#15803D", "#2563EB"], "other": "#94A3B8",
        "ramp": ["#EEF2F6", "#06B6D4", "#0891B2", "#0E7490", "#164E63"],
    },
}
SPECTRUM = ("cyan", "violet", "pink")

# --------------------------------------------------------------------- fonts
# Space Grotesk and JetBrains Mono are SIL OFL fonts (scripts/fonts/OFL.txt).
# Each SVG embeds a subset holding only the glyphs it draws, so it looks the
# same on every OS and never loads anything from the network.
FONT_FILES = {
    ("SG", 400): "SpaceGrotesk-400.woff2", ("SG", 500): "SpaceGrotesk-500.woff2",
    ("SG", 700): "SpaceGrotesk-700.woff2", ("JB", 400): "JetBrainsMono-400.woff2",
    ("JB", 500): "JetBrainsMono-500.woff2", ("JB", 700): "JetBrainsMono-700.woff2",
}
FALLBACK = {"SG": "'Space Grotesk', system-ui, sans-serif", "JB": "'JetBrains Mono', ui-monospace, monospace"}
_fonts: dict = {}
_faces: dict = {}


def _font(family: str, weight: int) -> TTFont:
    key = (family, weight)
    if key not in _fonts:
        _fonts[key] = TTFont(FONTS / FONT_FILES[key])
    return _fonts[key]


def measure(text: str, size: float, weight: int = 400, family: str = "SG", spacing: float = 0) -> float:
    """Advance width of `text`. Kerning is off in every SVG, so this is exact."""
    f = _font(family, weight)
    cmap, hmtx = f.getBestCmap(), f["hmtx"]
    units = sum(hmtx[cmap.get(ord(c), ".notdef")][0] for c in text)
    return units * size / f["head"].unitsPerEm + spacing * max(len(text) - 1, 0)


def font_face(family: str, weight: int, chars: set[str]) -> str:
    key = (family, weight, "".join(sorted(chars)))
    if key not in _faces:
        f = TTFont(FONTS / FONT_FILES[(family, weight)], recalcTimestamp=False)
        missing = sorted(c for c in chars if ord(c) not in f.getBestCmap())
        if missing:
            print(f"warning: {family} {weight} has no glyph for {missing}", file=sys.stderr)
        opts = subset.Options()
        opts.flavor = "woff2"
        opts.layout_features = ["*"]
        opts.name_IDs = [0, 1, 2, 13, 14]  # keep the copyright and OFL notice
        opts.hinting = False
        opts.notdef_outline = True
        sub = subset.Subsetter(opts)
        sub.populate(text="".join(chars))
        sub.subset(f)
        buf = io.BytesIO()
        f.flavor = "woff2"
        f.save(buf)
        data = base64.b64encode(buf.getvalue()).decode()
        _faces[key] = (f"@font-face{{font-family:{family};font-weight:{weight};"
                       f"src:url(data:font/woff2;base64,{data}) format('woff2')}}")
    return _faces[key]


# ----------------------------------------------------------------- SVG shell
BASE_CSS = ("text{font-kerning:none;font-variant-ligatures:none}.still{display:none}"
            "@media (prefers-reduced-motion:reduce){*{animation:none!important}"
            ".motion{display:none}.still{display:inline}}")


class Svg:
    def __init__(self, w: float, h: float, theme: str, title: str):
        self.w, self.h, self.theme, self.t = w, h, theme, THEMES[theme]
        self.title = title
        self.defs: list[str] = []
        self.body: list[str] = []
        self.css: list[str] = []
        self.glyphs: dict = defaultdict(set)

    def text(self, x, y, s, size, weight=400, fill=None, family="SG", anchor="start", spacing=0,
             cls=None, extra=""):
        self.glyphs[(family, weight)].update(s)
        attrs = [f'x="{x:.1f}"', f'y="{y:.1f}"', f'font-family="{family}, {FALLBACK[family]}"',
                 f'font-size="{size}"', f'font-weight="{weight}"', f'fill="{fill or self.t["ink"]}"']
        if anchor != "start":
            attrs.append(f'text-anchor="{anchor}"')
        if spacing:
            attrs.append(f'letter-spacing="{spacing}"')
        if cls:
            attrs.append(f'class="{cls}"')
        if extra:
            attrs.append(extra)
        return f"<text {' '.join(attrs)}>{escape(s, quote=False)}</text>"

    def gradient(self, gid: str, colours, x2=1, y2=0, opacity=None):
        """Linear gradient through accent names (or hex) spread evenly; `opacity` per stop."""
        cols = [self.t.get(c, c) for c in colours]
        ops = opacity or [1] * len(cols)
        body = "".join(f'<stop offset="{i / max(len(cols) - 1, 1):.2f}" stop-color="{c}" stop-opacity="{a}"/>'
                       for i, (c, a) in enumerate(zip(cols, ops)))
        self.defs.append(f'<linearGradient id="{gid}" x1="0" y1="0" x2="{x2}" y2="{y2}">{body}</linearGradient>')

    def add(self, *parts: str):
        self.body.extend(parts)

    def render(self) -> str:
        faces = "".join(font_face(f, w, c) for (f, w), c in sorted(self.glyphs.items()))
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
                f'viewBox="0 0 {self.w} {self.h}" role="img" aria-labelledby="title">'
                f'<title id="title">{escape(self.title)}</title>'
                f'<style>{faces}{BASE_CSS}{"".join(self.css)}</style>'
                f'<defs>{"".join(self.defs)}</defs>{"".join(self.body)}</svg>')


def write(name: str, svg: Svg):
    OUT.mkdir(exist_ok=True)
    (OUT / f"{name}-{svg.theme}.svg").write_text(svg.render(), "utf-8")


# ------------------------------------------------------------------- colour
def _rgb(hex_colour: str) -> np.ndarray:
    return np.array([int(hex_colour[i:i + 2], 16) for i in (1, 3, 5)], dtype=float)


def _luminance(hex_colour: str) -> float:
    c = _rgb(hex_colour) / 255
    c = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return float(0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2])


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mix(a: str, b: str, f: float) -> str:
    c = _rgb(a) * (1 - f) + _rgb(b) * f
    return "#" + "".join(f"{int(round(v)):02X}" for v in c)


def spectrum_at(t: dict, f: float) -> str:
    """A colour along cyan -> violet -> pink, f in [0, 1]."""
    a, b, c = (t[k] for k in SPECTRUM)
    return mix(a, b, f * 2) if f < 0.5 else mix(b, c, f * 2 - 1)


# ------------------------------------------------------------------ bitmaps
def _png_uri(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def backdrop(w, h, base: tuple[str, str] | str, orbs=(), scale=0.25) -> str:
    """Background gradient plus soft light orbs, baked into a small bitmap.

    Large radial gradients are among the most expensive things to repaint, and
    an animated SVG repaints everything each frame. Painting them once here and
    scaling the bitmap up costs almost nothing, and smooth light loses nothing
    at quarter resolution. `orbs` are (cx, cy, radius, colour, opacity).
    """
    bw, bh = round(w * scale), round(h * scale)
    ys, xs = np.mgrid[0:bh, 0:bw].astype(float) / scale
    if isinstance(base, str):
        img = np.broadcast_to(_rgb(base), (bh, bw, 3)).copy()
    else:
        f = ((xs / w + ys / h) / 2)[..., None]
        img = _rgb(base[0]) * (1 - f) + _rgb(base[1]) * f
    for cx, cy, r, colour, opacity in orbs:
        alpha = (np.clip(1 - np.hypot(xs - cx, ys - cy) / r, 0, 1) * opacity)[..., None]
        img = img * (1 - alpha) + _rgb(colour) * alpha
    img += np.random.default_rng(7).uniform(-0.5, 0.5, img.shape)  # dither away banding
    return _png_uri(Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB"))


def dot_field(w, h, colour: str, gap=22, r=1.1, opacity=0.8) -> str:
    """The dot grid as one 2x bitmap; a <pattern> of circles repaints far slower."""
    img = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    fill = tuple(int(c) for c in _rgb(colour)) + (round(255 * opacity),)
    for x in range(0, w, gap):
        for y in range(0, h, gap):
            cx, cy = (x + gap / 2) * 2, (y + gap / 2) * 2
            draw.ellipse((cx - 2 * r, cy - 2 * r, cx + 2 * r, cy + 2 * r), fill=fill)
    return _png_uri(img)


# ------------------------------------------------------------------- drawing
def frame(svg: Svg, w, h, r, fill=None) -> str:
    return (f'<rect x=".75" y=".75" width="{w - 1.5}" height="{h - 1.5}" rx="{r - .75}" '
            f'fill="{fill or svg.t["card"]}" stroke="{svg.t["line"]}" stroke-width="1.5"/>')


def beam(svg: Svg, w, h, r, colours, seconds=7, length=180, delay=0.0) -> str:
    """A short gradient stroke that travels around the card's border."""
    svg.gradient("beamGrad", colours, 1, 1)
    rw, rh, rr = w - 1.5, h - 1.5, r - .75
    perimeter = 2 * (rw + rh) - 8 * rr + 2 * math.pi * rr
    svg.css.append(f".beam{{stroke-dasharray:{length} {perimeter - length:.0f};"
                   f"animation:beam {seconds}s linear infinite;animation-delay:{delay:.2f}s}}"
                   f"@keyframes beam{{to{{stroke-dashoffset:-{perimeter:.0f}}}}}")
    return (f'<rect class="beam motion" x=".75" y=".75" width="{rw}" height="{rh}" rx="{rr}" fill="none" '
            f'stroke="url(#beamGrad)" stroke-width="2" stroke-linecap="round"/>')


def shine(svg: Svg, x, y, w, h, seconds=6, delay=0.0, width=120) -> str:
    """A soft highlight that sweeps left to right across a region."""
    svg.defs.append('<linearGradient id="shineGrad" x1="0" y1="0" x2="1" y2="0">'
                    '<stop offset="0" stop-color="#fff" stop-opacity="0"/>'
                    f'<stop offset=".5" stop-color="#fff" stop-opacity="{svg.t["shine"]}"/>'
                    '<stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>')
    svg.defs.append(f'<clipPath id="shineClip"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12"/></clipPath>')
    svg.css.append(f".shine{{animation:shine {seconds}s cubic-bezier(.5,0,.5,1) infinite;"
                   f"animation-delay:{delay:.2f}s}}"
                   f"@keyframes shine{{0%{{transform:translateX(0)}}35%,100%{{transform:translateX({w + width}px)}}}}")
    return (f'<g clip-path="url(#shineClip)" class="motion"><rect class="shine" x="{x - width}" y="{y}" '
            f'width="{width}" height="{h}" fill="url(#shineGrad)" transform="skewX(-20)"/></g>')


def five_star(cx, cy, r) -> str:
    pts = []
    for k in range(10):
        rad = r if k % 2 == 0 else r * 0.45
        a = math.radians(-90 + k * 36)
        pts.append(f"{cx + rad * math.cos(a):.2f},{cy + rad * math.sin(a):.2f}")
    return " ".join(pts)


def fork_icon(x, y, color) -> str:
    return (f'<g fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round">'
            f'<circle cx="{x + 3}" cy="{y + 3}" r="2.4"/><circle cx="{x + 15}" cy="{y + 3}" r="2.4"/>'
            f'<circle cx="{x + 9}" cy="{y + 17}" r="2.4"/>'
            f'<path d="M{x + 3} {y + 5.5}v2q0 3 3 3h6q3 0 3-3v-2M{x + 9} {y + 11}v3.5"/></g>')


def arrow(x, y, color) -> str:
    """A right arrow ending at x, centred on y."""
    return (f'<path d="M{x - 13} {y}h12M{x - 5.5} {y - 4.5}l4.5 4.5-4.5 4.5" fill="none" stroke="{color}" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>')


# Line glyphs on a 24-unit grid: project card corners and stat tiles.
GLYPHS = {
    "shield": "M12 2.5l7.5 3v6c0 4.7-3.2 8.4-7.5 10-4.3-1.6-7.5-5.3-7.5-10v-6zM8.6 12.2l2.4 2.4 4.6-4.8",
    "search": "M10.5 4a6.5 6.5 0 1 1 0 13a6.5 6.5 0 1 1 0-13zM15.4 15.4L20.5 20.5M7.8 10.5h5.4",
    "chip": "M7 5h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zM9.5 9.5h5v5h-5z"
            "M9 2v3M12 2v3M15 2v3M9 19v3M12 19v3M15 19v3M2 9h3M2 12h3M2 15h3M19 9h3M19 12h3M19 15h3",
    "network": "M12 3.5a2.5 2.5 0 1 1 0 5a2.5 2.5 0 1 1 0-5zM5 15.5a2.5 2.5 0 1 1 0 5a2.5 2.5 0 1 1 0-5z"
               "M19 15.5a2.5 2.5 0 1 1 0 5a2.5 2.5 0 1 1 0-5zM10.8 8.2l-4.6 7.6M13.2 8.2l4.6 7.6M7.5 18h9",
    "pulse": "M2.5 12h4.5l2.5-7 5 14 2.5-7h4.5",
    "calendar": "M5 5.5h14a1.5 1.5 0 0 1 1.5 1.5v12a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 19V7A1.5 1.5 0 0 1 5 5.5z"
                "M3.5 10h17M8.5 3v4M15.5 3v4M8 14h2M14 14h2M8 17h2",
    "star": "M12 3l2.7 5.6 6.1.8-4.5 4.2 1.1 6.1L12 16.8l-5.4 2.9 1.1-6.1-4.5-4.2 6.1-.8z",
    "pr": "M6 3.5a2 2 0 1 1 0 4a2 2 0 1 1 0-4zM6 7.5v9M6 16.5a2 2 0 1 1 0 4a2 2 0 1 1 0-4z"
          "M18 16.5a2 2 0 1 1 0 4a2 2 0 1 1 0-4zM18 16.5V10a3 3 0 0 0-3-3h-4.5M12.5 4.5L10.5 7l2 2.5",
    "repo": "M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5zM5 19.5A1.5 1.5 0 0 0 6.5 21H19v-3M9 7.5h6",
}


def glyph(kind: str, x, y, size, stroke, width=1.5) -> str:
    return (f'<path transform="translate({x} {y}) scale({size / 24:.4f})" d="{GLYPHS[kind]}" fill="none" '
            f'stroke="{stroke}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>')


def wrap(text: str, size, weight, width, family="SG") -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and measure(trial, size, weight, family) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + [line]


def fit(text: str, size, weight, width, floor=18) -> float:
    while size > floor and measure(text, size, weight) > width:
        size -= 1
    return size


def chips(svg: Svg, x, y, labels, size=13, h=30, pad=12, gap=8, width=None):
    t, parts, cx, cy = svg.t, [], x, y
    for label in labels:
        w = measure(label, size, 500, "JB") + 2 * pad
        if width and cx > x and cx + w > x + width:
            cx, cy = x, cy + h + gap
        parts.append(f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{w:.1f}" height="{h}" rx="8" '
                     f'fill="{t["card2"]}" stroke="{t["line"]}"/>')
        parts.append(svg.text(cx + w / 2, cy + h / 2 + size * 0.36, label, size, 500, t["ink2"], "JB",
                              anchor="middle"))
        cx += w + gap
    return "".join(parts)


def typing(svg: Svg, x, y, roles, size, weight, color, caret, prefix="type", hold=1.9) -> str:
    """Typewriter cycling through `roles`, driven by SMIL so every browser plays it."""
    TYPE, DELETE, GAP = 0.07, 0.03, 0.4
    seqs, t0 = [], 0.0
    for role in roles:
        widths = [measure(role[:k], size, weight, "JB") for k in range(len(role) + 1)]
        n = len(role)
        seq = [(t0, 0.0)] + [(t0 + k * TYPE, widths[k]) for k in range(1, n + 1)]
        typed = t0 + n * TYPE + hold
        seq += [(typed + k * DELETE, widths[n - k]) for k in range(1, n + 1)]
        seqs.append(seq)
        t0 = typed + n * DELETE + GAP
    total = t0

    def animate(attr, frames, offset=0.0):
        keyed: dict[str, float] = {}
        for time, value in sorted(frames):
            keyed[f"{time / total:.5f}"] = value + offset
        keyed.setdefault("0.00000", offset)
        items = sorted(keyed.items(), key=lambda kv: float(kv[0]))
        return (f'<animate attributeName="{attr}" dur="{total:.2f}s" repeatCount="indefinite" '
                f'calcMode="discrete" keyTimes="{";".join(k for k, _ in items)}" '
                f'values="{";".join(f"{v:.1f}" for _, v in items)}"/>')

    cw = measure("M", size, weight, "JB")
    parts = ['<g class="motion">']
    for i, (role, seq) in enumerate(zip(roles, seqs)):
        frames = [(0.0, 0.0)] + seq if seq[0][0] > 0 else seq
        svg.defs.append(f'<clipPath id="{prefix}{i}"><rect x="{x - 2}" y="{y - size * 1.05:.1f}" width="0" '
                        f'height="{size * 1.45:.1f}">{animate("width", frames, 2)}</rect></clipPath>')
        parts.append(svg.text(x, y, role, size, weight, color, "JB", extra=f'clip-path="url(#{prefix}{i})"'))
    caret_frames = [frame for seq in seqs for frame in seq]
    parts.append(f'<rect x="{x}" y="{y - size * 0.82:.1f}" width="{cw:.1f}" height="{size * 1.02:.1f}" '
                 f'fill="{caret}" opacity=".85">{animate("x", caret_frames, x + 3)}'
                 f'<animate attributeName="opacity" values=".85;0" dur="1s" calcMode="discrete" '
                 f'repeatCount="indefinite"/></rect></g>')
    parts.append(svg.text(x, y, roles[0], size, weight, color, "JB", cls="still"))
    return "".join(parts)


# -------------------------------------------------------------------- logos
def logo_symbol(svg: Svg, key: str) -> tuple[str, str | None]:
    """Define a tool's logo once as a <symbol>; return its id and backdrop colour.

    `dv:name` is a full-colour devicon file, `si:slug` a simple-icons glyph in
    its brand colour, `txt:AB:#hex` a monogram for tools with neither. Logos
    that would vanish on this theme's tile (black on dark, pale on light) sit
    on a small contrasting badge instead of being recoloured.
    """
    t, sid = svg.t, "lg-" + key.replace(":", "-").replace("#", "")
    kind, name = key.split(":", 1)
    badge = None
    if kind == "dv":
        data = base64.b64encode((LOGOS / f"{name}.svg").read_bytes()).decode()
        body = f'<image href="data:image/svg+xml;base64,{data}" width="24" height="24"/>'
        if name in LOW_CONTRAST[svg.theme]:
            badge = t["badge"]
    elif kind == "si":
        colour = ICONS[name]["hex"]
        if contrast(colour, t["card2"]) < 2.0:
            badge = t["badge"]
        body = f'<path d="{ICONS[name]["path"]}" fill="{colour}"/>'
    else:
        mark, colour = name.split(":")
        svg.glyphs[("JB", 700)].update(mark)
        body = (f'<rect x="1" y="1" width="22" height="22" rx="6" fill="{colour}"/>'
                f'<text x="12" y="16.2" font-family="JB, {FALLBACK["JB"]}" font-size="10.5" font-weight="700" '
                f'text-anchor="middle" fill="#fff">{mark}</text>')
    svg.defs.append(f'<symbol id="{sid}" viewBox="0 0 24 24">{body}</symbol>')
    return sid, badge


# Devicon logos measured (rendered on each tile colour) to lose most of their
# pixels into the background; these get the contrasting badge.
LOW_CONTRAST = {
    "dark": {"bash", "django", "express", "flask", "latex", "mongoose", "mysql", "ollama", "pandas", "powershell",
             "socketio", "sqlalchemy", "threejs"},
    "light": {"huggingface", "matplotlib", "react", "swagger", "vault"},
}


# ------------------------------------------------------------------- globe
def icosphere(freq: int):
    """Vertices and edges of a geodesic sphere: an icosahedron with each face split `freq` times."""
    p = (1 + 5 ** 0.5) / 2
    base = [(-1, p, 0), (1, p, 0), (-1, -p, 0), (1, -p, 0), (0, -1, p), (0, 1, p),
            (0, -1, -p), (0, 1, -p), (p, 0, -1), (p, 0, 1), (-p, 0, -1), (-p, 0, 1)]
    faces = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2),
             (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5),
             (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    verts, index, edges = [], {}, set()

    def vertex(v):
        n = math.sqrt(sum(c * c for c in v))
        v = tuple(c / n for c in v)
        key = tuple(round(c, 6) for c in v)
        if key not in index:
            index[key] = len(verts)
            verts.append(v)
        return index[key]

    for a, b, c in faces:
        A, B, C = base[a], base[b], base[c]
        grid = {}
        for i in range(freq + 1):
            for j in range(freq + 1 - i):
                k = freq - i - j
                grid[i, j] = vertex(tuple((i * A[n] + j * B[n] + k * C[n]) / freq for n in range(3)))
        for (i, j), v in grid.items():
            for di, dj in ((1, 0), (0, 1)):
                if (i + di, j + dj) in grid:
                    edges.add(tuple(sorted((v, grid[i + di, j + dj]))))
            if (i + 1, j) in grid and (i, j + 1) in grid:
                edges.add(tuple(sorted((grid[i + 1, j], grid[i, j + 1]))))
    return verts, sorted(edges)


def globe(svg: Svg, cx, cy, R, freq=2, steps=20, tilt=24, seconds=12) -> str:
    """A geodesic sphere spinning about an axis through one of its vertices.

    The sphere has five-fold symmetry about that axis, so a 72-degree turn lands
    on an identical picture and the loop restarts without a visible jump. The
    whole sphere is three morphing paths (back edges, front edges, vertices);
    the glow is a second, wider copy of the front path rather than a blur filter.
    """
    t = svg.t
    verts, edges = icosphere(freq)
    ax = verts[0]
    # Rotate the chosen vertex onto +y (Rodrigues), so the spin axis is vertical.
    k = (ax[2], 0.0, -ax[0])
    kn = math.sqrt(k[0] ** 2 + k[2] ** 2)
    k = (k[0] / kn, 0.0, k[2] / kn)
    ang = math.acos(ax[1])

    def align(v):
        c, s = math.cos(ang), math.sin(ang)
        dot = k[0] * v[0] + k[2] * v[2]
        cross = (k[1] * v[2] - k[2] * v[1], k[2] * v[0] - k[0] * v[2], k[0] * v[1] - k[1] * v[0])
        return tuple(v[n] * c + cross[n] * s + k[n] * dot * (1 - c) for n in range(3))

    aligned = [align(v) for v in verts]
    tl = math.radians(tilt)
    frames = []
    for f in range(steps + 1):
        th = math.radians(72 * f / steps)
        pts = []
        for x, y, z in aligned:
            x, z = x * math.cos(th) + z * math.sin(th), -x * math.sin(th) + z * math.cos(th)
            y, z = y * math.cos(tl) - z * math.sin(tl), y * math.sin(tl) + z * math.cos(tl)
            pts.append((cx + R * x, cy - R * y, z))
        frames.append(pts)

    def edge_path(pts, front):
        out = []
        for a, b in edges:
            (x1, y1, z1), (x2, y2, z2) = pts[a], pts[b]
            if ((z1 + z2) / 2 >= 0) == front:
                out.append(f"M{x1:.0f} {y1:.0f}L{x2:.0f} {y2:.0f}")
            else:  # this edge belongs to the other path now; shrink it to a point
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                out.append(f"M{mx:.0f} {my:.0f}L{mx:.0f} {my:.0f}")
        return "".join(out)

    def morph(pid, d_list):
        return (f'<path id="{pid}" d="{d_list[0]}"><animate attributeName="d" dur="{seconds}s" '
                f'repeatCount="indefinite" values="{";".join(d_list)}"/></path>')

    svg.gradient("wire", SPECTRUM, 1, 1)
    svg.defs += [morph("gBack", [edge_path(p, False) for p in frames]),
                 morph("gFront", [edge_path(p, True) for p in frames]),
                 morph("gVerts", ["".join(f"M{x:.0f} {y:.0f}h0" for x, y, _ in p) for p in frames])]
    return (f'<use href="#gBack" fill="none" stroke="url(#wire)" stroke-width="1" opacity=".3"/>'
            f'<use href="#gFront" fill="none" stroke="url(#wire)" stroke-width="6" stroke-linecap="round" '
            f'opacity=".14"/>'
            f'<use href="#gFront" fill="none" stroke="url(#wire)" stroke-width="1.5" stroke-linecap="round"/>'
            f'<use href="#gVerts" fill="none" stroke="{t["ink"]}" stroke-width="4" stroke-linecap="round" '
            f'opacity=".9"/>')


# -------------------------------------------------------------------- header
ROLES = ["Backend Engineer", "Full-Stack Developer", "QA Automation Engineer", "AI & LLM Engineer"]


def header(theme: str):
    W, H = 1200, 400
    svg = Svg(W, H, theme, "Pouria Madani Sani: backend, full-stack, QA automation and AI engineer")
    t = svg.t
    gx, gy = 965, 200  # globe centre
    svg.css.append(
        ".rise{animation:rise .9s cubic-bezier(.2,.7,.2,1) both}"
        ".d1{animation-delay:.1s}.d2{animation-delay:.22s}.d3{animation-delay:.34s}.d4{animation-delay:.46s}"
        "@keyframes rise{from{opacity:0;transform:translateY(10px)}}"
        ".blink{animation:blink 1.6s ease-in-out infinite}@keyframes blink{50%{opacity:.25}}"
        ".tw{animation:tw 4s ease-in-out infinite;opacity:0}@keyframes tw{50%{opacity:1}}")
    svg.defs.append(f'<clipPath id="frame"><rect width="{W}" height="{H}" rx="24"/></clipPath>')
    svg.gradient("edge", ["cyan", "line", "violet", "pink"], 1, 1, [.75, 1, .6, .75])
    svg.gradient("accent", SPECTRUM)
    bg = backdrop(W, H, (t["bg_a"], t["bg_b"]), [(250, -40, 420, t["cyan"], t["glow"]),
                                                 (1080, 440, 420, t["violet"], t["glow"] * 1.2),
                                                 (640, 470, 300, t["pink"], t["glow"] * 0.7),
                                                 (gx, gy, 220, t["cyan"], t["glow"] * 0.85)])
    # Grid dots that light up one after another, like activity on a network.
    palette = [t["cyan"], t["violet"], t["pink"], t["amber"], t["emerald"]]
    twinkles = []
    for i in range(22):
        col, row = (i * 7 + 3) % 52, (i * 5 + 2) % 17
        twinkles.append(f'<circle class="tw" cx="{11 + col * 22}" cy="{33 + row * 22}" r="2" '
                        f'fill="{palette[i % 5]}" style="animation-delay:{(i * 0.83) % 4:.2f}s"/>')
    orbit = f"M{gx - 212} {gy}a212 54 0 1 0 424 0a212 54 0 1 0-424 0"
    svg.add(
        f'<g clip-path="url(#frame)"><image href="{bg}" width="{W}" height="{H}" preserveAspectRatio="none"/>',
        f'<image href="{dot_field(W, H, t["dot"])}" width="{W}" height="{H}"/>',
        f'<g class="motion">{"".join(twinkles)}</g>',
        globe(svg, gx, gy, 150),
        f'<g transform="rotate(-14 {gx} {gy})"><path d="{orbit}" fill="none" stroke="url(#accent)" '
        f'stroke-opacity=".6" stroke-dasharray="3 7"/>'
        f'<g><circle r="12" fill="{t["pink"]}" opacity=".2"/><circle r="4.5" fill="{t["pink"]}"/>'
        f'<animateMotion dur="7s" repeatCount="indefinite" path="{orbit}"/></g>'
        f'<g><circle r="9" fill="{t["amber"]}" opacity=".2"/><circle r="3.2" fill="{t["amber"]}"/>'
        f'<animateMotion dur="7s" begin="-3.5s" repeatCount="indefinite" path="{orbit}"/></g></g>',
        '</g>',
        f'<rect x=".75" y=".75" width="{W - 1.5}" height="{H - 1.5}" rx="23.25" fill="none" '
        f'stroke="url(#edge)" stroke-width="1.5"/>',
    )
    x = 70
    size = fit("Pouria Madani Sani", 74, 700, 680, 50)
    last_x = x - 3 + measure("Pouria Madani ", size, 700, spacing=-1.5) - 1.5
    svg.add(
        f'<g class="rise">', svg.text(x, 98, "$", 18, 700, t["ink_emerald"], "JB"),
        svg.text(x + 20, 98, "whoami", 18, 500, t["ink2"], "JB"), '</g>',
        '<g class="rise d1">',
        svg.text(x - 3, 178, "Pouria Madani", size, 700, t["ink"], spacing=-1.5),
        svg.text(last_x, 178, "Sani", size, 700, "url(#accent)", spacing=-1.5),
        '</g>',
        svg.text(x, 226, "Backend, full-stack, QA automation and applied AI.", 23, 400, t["ink2"], cls="rise d2"),
        '<g class="rise d3">',
        svg.text(x, 290, ">", 26, 700, t["ink_pink"], "JB"),
        typing(svg, x + 30, 290, ROLES, 26, 500, t["ink"], t["cyan"]),
        '</g>',
    )
    cx, parts = x, []
    for label, color, pulse in [("QA Engineer @ MediQo", t["ok"], True),
                                ("CE @ Ferdowsi University", t["cyan"], False),
                                ("Mashhad, Iran", t["pink"], False)]:
        w = measure(label, 14, 500, "JB") + 46
        parts.append(f'<rect x="{cx}" y="324" width="{w:.1f}" height="36" rx="10" fill="{t["card"]}" '
                     f'fill-opacity=".6" stroke="{t["line"]}"/>'
                     f'<circle cx="{cx + 19}" cy="342" r="4" fill="{color}"{" class=\"blink\"" if pulse else ""}/>')
        parts.append(svg.text(cx + 32, 347, label, 14, 500, t["ink2"], "JB"))
        cx += w + 10
    svg.add(f'<g class="rise d4">{"".join(parts)}</g>')
    write("header", svg)


# ------------------------------------------------------------ section titles
SECTIONS = {"about": ("01", "About", ("cyan", "violet")), "work": ("02", "Featured work", ("violet", "pink")),
            "toolbox": ("03", "Toolbox", ("amber", "pink")), "glance": ("04", "At a glance", ("emerald", "cyan"))}


def section_title(theme: str, key: str):
    num, title, (c1, c2) = SECTIONS[key]
    W, H = 1200, 64
    svg = Svg(W, H, theme, title)
    t = svg.t
    svg.gradient("rule", [c1, c2, c2], 1, 0, [1, .8, 0])
    svg.defs.append(f'<radialGradient id="spark"><stop offset="0" stop-color="{t[c1]}"/>'
                    f'<stop offset="1" stop-color="{t[c1]}" stop-opacity="0"/></radialGradient>')
    nw = measure(num, 18, 700, "JB")
    sx = 4 + nw + 10
    tx = sx + measure("/", 18, 400, "JB") + 14
    tw = measure(title, 34, 700, spacing=-.5)
    caret = tx + tw + 6
    end = caret + 34
    run = W - end - 60
    svg.css.append(".cur{animation:cur 1.1s steps(1) infinite}@keyframes cur{50%{opacity:0}}"
                   f".run{{animation:run 4.5s cubic-bezier(.45,0,.55,1) infinite}}"
                   f"@keyframes run{{0%{{transform:translateX(0);opacity:0}}10%{{opacity:1}}"
                   f"80%{{opacity:1}}100%{{transform:translateX({run:.0f}px);opacity:0}}}}")
    svg.add(svg.text(4, 42, num, 18, 700, t[f"ink_{c1}"], "JB"),
            svg.text(sx, 42, "/", 18, 400, t["ink3"], "JB"),
            svg.text(tx, 44, title, 34, 700, t["ink"], spacing=-.5),
            f'<rect class="cur" x="{caret:.1f}" y="42" width="16" height="3.5" fill="{t[c1]}"/>',
            f'<rect x="{end:.1f}" y="33" width="{W - end - 4:.1f}" height="1.5" rx=".75" fill="url(#rule)"/>',
            f'<g class="run motion"><ellipse cx="{end:.1f}" cy="33.75" rx="26" ry="5" fill="url(#spark)" '
            f'opacity=".75"/><circle cx="{end:.1f}" cy="33.75" r="2.2" fill="{t["ink"]}"/></g>')
    write(f"title-{key}", svg)


# ------------------------------------------------------------------- socials
SOCIALS = [("linkedin", "LinkedIn"), ("x", "X"), ("instagram", "Instagram")]


def social(theme: str, index: int, slug: str, label: str):
    size, H = 16, 44
    W = round(18 + 20 + 10 + measure(label, size, 500) + 20)
    svg = Svg(W, H, theme, label)
    t = svg.t
    if slug == "linkedin":  # not in simple-icons, so draw the mark in its brand blue
        mark = ('<rect x="18" y="12" width="20" height="20" rx="3.6" fill="#0A66C2"/>'
                '<text x="28" y="28" font-family="Arial, sans-serif" font-size="14.4" font-weight="700" '
                'text-anchor="middle" fill="#fff">in</text>')
    elif slug == "instagram":
        svg.defs.append('<linearGradient id="ig" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#FEDA75"/>'
                        '<stop offset=".3" stop-color="#FA7E1E"/><stop offset=".55" stop-color="#D62976"/>'
                        '<stop offset=".8" stop-color="#962FBF"/><stop offset="1" stop-color="#4F5BD5"/>'
                        '</linearGradient>')
        mark = f'<path transform="translate(18 12) scale(.8333)" d="{ICONS[slug]["path"]}" fill="url(#ig)"/>'
    else:
        mark = f'<path transform="translate(18 12) scale(.8333)" d="{ICONS[slug]["path"]}" fill="{t["ink"]}"/>'
    svg.add(f'<rect x=".75" y=".75" width="{W - 1.5}" height="{H - 1.5}" rx="12" fill="{t["card"]}" '
            f'stroke="{t["line"]}" stroke-width="1.5"/>',
            shine(svg, 0, 0, W, H, seconds=5, delay=index * 0.35, width=60),
            mark, svg.text(48, 27.5, label, size, 500, t["ink"]))
    write(f"social-{slug}", svg)


# ------------------------------------------------------------------ projects
HERO = {
    "repo": "ParsRAG",
    "label": "FLAGSHIP · LOCAL-FIRST AI",
    "kicker": "offline · private · cited answers",
    "blurb": "Chat with PDF, Word, PowerPoint and scanned documents in Persian or English. "
             "Runs fully offline on local LLMs and cites the source of every answer.",
    "tags": ["FastAPI", "React", "LlamaIndex", "Qdrant", "Ollama", "Tesseract"],
}
FEATURED = [
    {"repo": "DistributedAuthSecurityAnalysis", "title": "Distributed Auth Security Analysis",
     "label": "SECURITY RESEARCH", "glyph": "shield", "accent": ("emerald", "cyan"),
     "blurb": "A reproducible lab that attacks, then hardens, OAuth 2.0 and OIDC flows "
              "with Keycloak, FastAPI and attacker tooling.",
     "tags": ["OAuth 2.0", "OIDC", "Keycloak", "FastAPI"]},
    {"repo": "linkedin-talent-discovery", "title": "LinkedIn Talent Discovery",
     "label": "SEARCH ENGINEERING", "glyph": "search", "accent": ("amber", "pink"),
     "blurb": "A talent search engine on Elasticsearch 8 with an SQLite FTS fallback, "
              "faceted filters and sub-15 ms queries.",
     "tags": ["Elasticsearch", "SQLite FTS", "ETL", "React"]},
    {"repo": "HPC-Parallel-Algorithms", "title": "HPC Parallel Algorithms",
     "label": "HIGH-PERFORMANCE COMPUTING", "glyph": "chip", "accent": ("cyan", "violet"),
     "blurb": "Matrix multiplication, Gaussian blur and Barnes-Hut N-body, "
              "tuned with OpenMP on the CPU and CUDA on the GPU.",
     "tags": ["C", "C++", "OpenMP", "CUDA"]},
    {"repo": "beer-distribution-game", "title": "Beer Distribution Game",
     "label": "REAL-TIME SYSTEMS", "glyph": "network", "accent": ("pink", "violet"),
     "blurb": "The MIT Beer Game as turn-based multiplayer: a hexagonal TypeScript core, "
              "WebSockets, SQLite WAL and bullwhip analytics.",
     "tags": ["TypeScript", "React 19", "WebSockets", "DDD"]},
]


def repo_meta(svg: Svg, x, y, repo: dict) -> str:
    t = svg.t
    lang = (repo.get("primaryLanguage") or {}).get("name", "")
    parts = [f'<circle cx="{x + 6}" cy="{y - 5}" r="5" fill="url(#accent)"/>',
             svg.text(x + 18, y, lang, 15, 500, t["ink2"], "JB")]
    cx = x + 18 + measure(lang, 15, 500, "JB") + 24
    stars, forks = str(repo["stargazerCount"]), str(repo["forkCount"])
    parts += [f'<polygon points="{five_star(cx + 8, y - 5.5, 8.5)}" fill="{t["amber"]}" fill-opacity=".2" '
              f'stroke="{t["amber"]}" stroke-width="1.6" stroke-linejoin="round"/>',
              svg.text(cx + 22, y, stars, 15, 700, t["ink"], "JB")]
    cx += 22 + measure(stars, 15, 700, "JB") + 22
    parts += [fork_icon(cx, y - 15, t["ink2"]), svg.text(cx + 26, y, forks, 15, 700, t["ink"], "JB")]
    return "".join(parts)


def project_card(theme: str, index: int, spec: dict, repo: dict):
    W, H = 590, 300
    svg = Svg(W, H, theme, f'{spec["title"]}: {spec["blurb"]}')
    t = svg.t
    c1, c2 = spec["accent"]
    svg.gradient("accent", [c1, c2])
    svg.gradient("top", [c1, c2, c2], 1, 0, [1, .7, 0])
    svg.defs.append(f'<clipPath id="card"><rect width="{W}" height="{H}" rx="18"/></clipPath>')
    svg.css.append(".float{animation:float 4s ease-in-out infinite}@keyframes float{50%{transform:translateY(-5px)}}")
    bg = backdrop(W, H, t["card"], [(W - 40, 10, 230, t[c1], t["glow"] * .75), (W - 160, -20, 200, t[c2], t["glow"] * .5)])
    title_size = fit(spec["title"], 28, 700, W - 64 - 60, 22)
    lines = wrap(spec["blurb"], 18, 400, W - 64)
    svg.add(
        f'<g clip-path="url(#card)"><image href="{bg}" width="{W}" height="{H}" preserveAspectRatio="none"/>'
        f'<rect x="0" y="0" width="{W}" height="2" fill="url(#top)"/></g>',
        frame(svg, W, H, 18, fill="none"),
        beam(svg, W, H, 18, [c1, c2], seconds=8, delay=-index * 2.0),
        f'<g class="float">{glyph(spec["glyph"], W - 76, 28, 44, "url(#accent)", 1.6)}</g>',
        f'<circle cx="36" cy="45" r="3.5" fill="{t[c1]}"/>',
        svg.text(48, 50, spec["label"], 13, 700, t[f"ink_{c1}"], "JB", spacing=1.2),
        svg.text(32, 94, spec["title"], title_size, 700, t["ink"], spacing=-.4),
        *[svg.text(32, 132 + i * 27, line, 18, 400, t["ink2"]) for i, line in enumerate(lines[:3])],
        chips(svg, 32, 208, spec["tags"]),
        f'<rect x="32" y="{H - 54}" width="{W - 64}" height="1" fill="{t["line"]}"/>',
        repo_meta(svg, 32, H - 21, repo),
        svg.text(W - 54, H - 21, "View repo", 15, 500, t[f"ink_{c1}"], anchor="end"),
        arrow(W - 32, H - 26, t[f"ink_{c1}"]),
    )
    write(f"card-{spec['repo'].lower()}", svg)


def hero_card(theme: str, repo: dict):
    W, H = 1200, 420
    svg = Svg(W, H, theme, f"ParsRAG: {HERO['blurb']}")
    t = svg.t
    svg.gradient("accent", SPECTRUM)
    svg.gradient("top", ["cyan", "violet", "pink", "pink"], 1, 0, [1, .9, .7, 0])
    svg.defs.append(f'<clipPath id="card"><rect width="{W}" height="{H}" rx="22"/></clipPath>')
    bg = backdrop(W, H, t["card"], [(1000, 40, 380, t["violet"], t["glow"]), (760, 430, 320, t["cyan"], t["glow"]),
                                    (1180, 400, 260, t["pink"], t["glow"] * .8), (120, -60, 260, t["cyan"], t["glow"] * .5)])
    # One 12-second story: files index, a question arrives, the answer types out, citations pop in.
    svg.css.append(
        ".idx{transform-origin:0 0;animation:idx 12s linear infinite}"
        "@keyframes idx{0%{transform:scaleX(0)}14%,100%{transform:scaleX(1)}}"
        ".q{animation:q 12s ease infinite}.a1{animation:a 12s ease infinite}.a2{animation:a2 12s ease infinite}"
        ".c1{animation:c1 12s ease infinite}.c2{animation:c2 12s ease infinite}"
        ".typing circle{animation:dot 12s infinite}.typing circle:nth-child(2){animation-delay:.15s}"
        ".typing circle:nth-child(3){animation-delay:.3s}"
        ".blink{animation:blink 1.6s ease-in-out infinite}@keyframes blink{50%{opacity:.25}}"
        "@keyframes q{0%,15%{opacity:0;transform:translateY(10px)}19%,93%{opacity:1;transform:none}98%,100%{opacity:0}}"
        "@keyframes dot{0%,21%{opacity:0}23%{opacity:1}25%{opacity:.3}27%{opacity:1}29%{opacity:.3}"
        "31%{opacity:1}33%,100%{opacity:0}}"
        "@keyframes a{0%,33%{opacity:0;transform:translateY(8px)}37%,93%{opacity:1;transform:none}98%,100%{opacity:0}}"
        "@keyframes a2{0%,37%{opacity:0;transform:translateY(8px)}41%,93%{opacity:1;transform:none}98%,100%{opacity:0}}"
        "@keyframes c1{0%,43%{opacity:0;transform:scale(.8)}46%,93%{opacity:1;transform:none}98%,100%{opacity:0}}"
        "@keyframes c2{0%,47%{opacity:0;transform:scale(.8)}50%,93%{opacity:1;transform:none}98%,100%{opacity:0}}")
    lines = wrap(HERO["blurb"], 20, 400, 560)
    svg.add(
        f'<g clip-path="url(#card)"><image href="{bg}" width="{W}" height="{H}" preserveAspectRatio="none"/>'
        f'<image href="{dot_field(W - 600, H, t["dot"], opacity=.6)}" x="600" width="{W - 600}" height="{H}"/>'
        f'<rect width="{W}" height="2" fill="url(#top)"/></g>',
        frame(svg, W, H, 22, fill="none"),
        beam(svg, W, H, 22, SPECTRUM, seconds=10, length=260),
        f'<circle cx="52" cy="61" r="3.5" fill="{t["pink"]}" class="blink"/>',
        svg.text(64, 66, HERO["label"], 14, 700, t["ink_pink"], "JB", spacing=1.4),
        svg.text(44, 136, "ParsRAG", 70, 700, t["ink"], spacing=-2),
        svg.text(48, 176, HERO["kicker"], 17, 500, "url(#accent)", "JB"),
        *[svg.text(48, 222 + i * 30, line, 20, 400, t["ink2"]) for i, line in enumerate(lines[:3])],
        chips(svg, 48, 300, HERO["tags"], size=14, h=32, pad=13, width=600),
        repo_meta(svg, 48, 380, repo),
    )
    # Chat window: indexing, a question, the answer, and the two passages it cites.
    wx, wy, ww, wh = 672, 40, 484, 340
    svg.add(
        f'<rect x="{wx}" y="{wy}" width="{ww}" height="{wh}" rx="16" fill="{t["card2"]}" fill-opacity=".94" '
        f'stroke="{t["line"]}" stroke-width="1.5"/>',
        *[f'<circle cx="{wx + 22 + i * 16}" cy="{wy + 22}" r="5" fill="{c}"/>'
          for i, c in enumerate(("#FF5F57", "#FEBC2E", "#28C840"))],
        svg.text(wx + 82, wy + 27, "parsrag", 13, 500, t["ink2"], "JB"),
        f'<circle cx="{wx + ww - 82}" cy="{wy + 22}" r="4" fill="{t["ok"]}" class="blink"/>',
        svg.text(wx + ww - 20, wy + 27, "offline", 13, 500, t["ink2"], "JB", anchor="end"),
        f'<rect x="{wx}" y="{wy + 44}" width="{ww}" height="1" fill="{t["line"]}"/>',
    )
    dx = wx + 20
    for name, colour in [("report.pdf", "#EF4444"), ("notes.docx", "#3B82F6"), ("slides.pptx", "#F97316"),
                         ("scan.png", "#10B981")]:
        w = measure(name, 12, 500, "JB") + 34
        svg.add(f'<rect x="{dx}" y="{wy + 58}" width="{w:.1f}" height="26" rx="7" fill="{t["card"]}" stroke="{t["line"]}"/>',
                f'<path d="M{dx + 10} {wy + 64}h7l4 4v10h-11z" fill="{colour}" fill-opacity=".18" stroke="{colour}" '
                f'stroke-width="1.4"/>',
                svg.text(dx + 27, wy + 75.5, name, 12, 500, t["ink2"], "JB"))
        dx += w + 8
    bar_w = ww - 40
    svg.add(f'<rect x="{wx + 20}" y="{wy + 94}" width="{bar_w}" height="3" rx="1.5" fill="{t["line"]}"/>',
            f'<g transform="translate({wx + 20} {wy + 94})"><rect class="idx" width="{bar_w}" height="3" rx="1.5" '
            f'fill="url(#accent)"/></g>')
    q = "What does chapter 3 conclude?"
    qw = measure(q, 16, 500) + 32
    qx = wx + ww - 20 - qw
    svg.add(f'<g class="q"><rect x="{qx:.1f}" y="{wy + 112}" width="{qw:.1f}" height="42" rx="13" fill="url(#accent)"/>',
            svg.text(qx + 16, wy + 138, q, 16, 500, t["on_grad"]), '</g>')
    svg.add('<g class="typing motion">',
            *[f'<circle cx="{wx + 40 + i * 14}" cy="{wy + 190}" r="4" fill="{c}"/>'
              for i, c in enumerate((t["cyan"], t["violet"], t["pink"]))], '</g>')
    ans = wrap("It compares two retrieval methods and finds the hybrid one more accurate on long reports.",
               16, 400, 330)
    aw, ay = 362, wy + 168
    svg.add(f'<g class="a1"><rect x="{wx + 20}" y="{ay}" width="{aw}" height="{24 + 26 * len(ans)}" rx="13" '
            f'fill="{t["card"]}" stroke="{t["line"]}"/>',
            svg.text(wx + 36, ay + 29, ans[0], 16, 400, t["ink"]), '</g>',
            *[f'<g class="a2">{svg.text(wx + 36, ay + 29 + i * 26, line, 16, 400, t["ink"])}</g>'
              for i, line in enumerate(ans) if i])
    cx = wx + 20
    cy = ay + 24 + 26 * len(ans) + 12
    for i, (cite, colour) in enumerate([("[1] report.pdf · p.12", "violet"), ("[2] notes.docx · p.4", "pink")]):
        w = measure(cite, 12, 500, "JB") + 24
        svg.add(f'<g class="c{i + 1}" style="transform-origin:{cx + w / 2:.0f}px {cy + 13}px">'
                f'<rect x="{cx}" y="{cy}" width="{w:.1f}" height="26" rx="8" fill="{t[colour]}" fill-opacity=".1" '
                f'stroke="{t[colour]}" stroke-width="1.2"/>',
                svg.text(cx + 12, cy + 17.5, cite, 12, 500, t[f"ink_{colour}"], "JB"), '</g>')
        cx += w + 8
    svg.add(svg.text(wx + ww - 20, wy + wh - 18, "answers grounded in your files", 12, 400, t["ink2"], "JB",
                     anchor="end"))
    write("card-parsrag", svg)


# ------------------------------------------------------------------- toolbox
# Everything here turned up in the repositories' manifests (requirements,
# package.json, composer.json, go.mod, Dockerfiles, workflows). Keys: "dv:" is
# a colour devicon logo, "si:" a simple-icons glyph in its brand colour,
# "txt:AB:#hex" a monogram for tools with no logo in either set.
TOOLBOX = [
    ("LANGUAGES", "cyan", [
        ("dv:python", "Python"), ("dv:typescript", "TypeScript"), ("dv:javascript", "JavaScript"),
        ("dv:go", "Go"), ("dv:c", "C"), ("dv:cplusplus", "C++"), ("dv:java", "Java"), ("dv:php", "PHP"),
        ("si:nvidia", "CUDA"), ("dv:bash", "Bash"), ("dv:powershell", "PowerShell"), ("dv:html5", "HTML"),
        ("dv:css3", "CSS"), ("dv:latex", "LaTeX")]),
    ("BACKEND & APIs", "violet", [
        ("dv:fastapi", "FastAPI"), ("dv:django", "Django"), ("dv:flask", "Flask"), ("dv:express", "Express"),
        ("dv:nodejs", "Node.js"), ("dv:laravel", "Laravel"), ("si:pydantic", "Pydantic"),
        ("dv:sqlalchemy", "SQLAlchemy"), ("dv:socketio", "Socket.IO"), ("si:jsonwebtokens", "JWT"),
        ("dv:openapi", "OpenAPI"), ("dv:swagger", "Swagger")]),
    ("FRONTEND", "pink", [
        ("dv:react", "React"), ("dv:vitejs", "Vite"), ("dv:tailwindcss", "Tailwind CSS"),
        ("dv:threejs", "Three.js"), ("si:framer", "Framer Motion"), ("si:greensock", "GSAP"),
        ("dv:reactrouter", "React Router"), ("si:reacthookform", "React Hook Form"), ("dv:axios", "Axios")]),
    ("AI & DATA", "amber", [
        ("dv:ollama", "Ollama"), ("txt:LI:#7C3AED", "LlamaIndex"), ("si:qdrant", "Qdrant"),
        ("dv:huggingface", "Hugging Face"), ("txt:GQ:#F55036", "Groq"), ("si:claude", "Claude"),
        ("si:modelcontextprotocol", "MCP"), ("dv:scikitlearn", "scikit-learn"), ("dv:numpy", "NumPy"),
        ("dv:pandas", "pandas"), ("dv:matplotlib", "Matplotlib"), ("dv:jupyter", "Jupyter"),
        ("dv:opencv", "OpenCV"), ("txt:OC:#2563EB", "Tesseract OCR"), ("txt:MP:#0E7490", "OpenMP")]),
    ("DATABASES", "emerald", [
        ("dv:postgresql", "PostgreSQL"), ("dv:mysql", "MySQL"), ("dv:mongodb", "MongoDB"), ("dv:redis", "Redis"),
        ("dv:sqlite", "SQLite"), ("dv:elasticsearch", "Elasticsearch"), ("dv:mongoose", "Mongoose")]),
    ("TESTING & QA", "pink", [
        ("dv:pytest", "pytest"), ("dv:playwright", "Playwright"), ("dv:selenium", "Selenium"), ("dv:jest", "Jest"),
        ("dv:vitest", "Vitest"), ("dv:puppeteer", "Puppeteer"), ("txt:LC:#16A34A", "Locust"),
        ("txt:AL:#EA580C", "Allure"), ("dv:postman", "Postman"), ("dv:eslint", "ESLint"), ("si:ruff", "Ruff"),
        ("si:precommit", "pre-commit")]),
    ("DEVOPS & SECURITY", "cyan", [
        ("dv:docker", "Docker"), ("dv:nginx", "Nginx"), ("si:linux", "Linux"), ("si:alpinelinux", "Alpine"),
        ("dv:githubactions", "GitHub Actions"), ("si:githubpages", "GitHub Pages"), ("dv:git", "Git"),
        ("si:keycloak", "Keycloak"), ("dv:vault", "Vault"), ("si:trivy", "Trivy"), ("si:uv", "uv"),
        ("si:cloudinary", "Cloudinary"), ("si:telegram", "Telegram Bots"), ("si:whatsapp", "WhatsApp"),
        ("dv:figma", "Figma")]),
]


def toolbox(theme: str):
    """Each category is a row of logo pills scrolling sideways, alternating direction."""
    W, row_h, top = 1200, 66, 34
    H = top * 2 + row_h * len(TOOLBOX) - 14
    total = sum(len(items) for _, _, items in TOOLBOX)
    names = "; ".join(f"{label.title()}: " + ", ".join(n for _, n in items) for label, _, items in TOOLBOX)
    svg = Svg(W, H, theme, f"Toolbox, {total} tools. {names}")
    t = svg.t
    vx0, vx1 = 262, W - 26
    svg.defs.append(f'<clipPath id="vp"><rect x="{vx0}" y="0" width="{vx1 - vx0}" height="{H}"/></clipPath>')
    for side, (a, b) in (("fl", (1, 0)), ("fr", (0, 1))):
        svg.defs.append(f'<linearGradient id="{side}" x1="0" y1="0" x2="1" y2="0">'
                        f'<stop offset="0" stop-color="{t["card"]}" stop-opacity="{a}"/>'
                        f'<stop offset="1" stop-color="{t["card"]}" stop-opacity="{b}"/></linearGradient>')
    logos = {}
    for _, _, items in TOOLBOX:
        for key, _ in items:
            if key not in logos:
                logos[key] = logo_symbol(svg, key)
    svg.add(frame(svg, W, H, 22))
    for r, (label, colour, items) in enumerate(TOOLBOX):
        y = top + r * row_h
        if r:
            svg.add(f'<rect x="40" y="{y - 11}" width="{W - 80}" height="1" fill="{t["line"]}" opacity=".6"/>')
        svg.add(f'<rect x="40" y="{y + 7}" width="3" height="36" rx="1.5" fill="{t[colour]}"/>',
                svg.text(54, y + 20, f"0{r + 1}", 13, 700, t["ink3"], "JB"),
                svg.text(80, y + 20, label, 13, 700, t[f"ink_{colour}"], "JB", spacing=.8),
                svg.text(54, y + 39, f"{len(items)} tools", 13, 400, t["ink2"], "JB"))
        pills, x = [], 0.0
        for key, name in items:
            w = 12 + 26 + 9 + measure(name, 15, 500) + 16
            sid, badge = logos[key]
            art = (f'<rect x="{x + 12:.1f}" y="{y - 1}" width="26" height="26" rx="7" fill="{badge}"/>'
                   f'<use href="#{sid}" x="{x + 16:.1f}" y="{y + 3}" width="18" height="18"/>' if badge else
                   f'<use href="#{sid}" x="{x + 13:.1f}" y="{y}" width="24" height="24"/>')
            pills.append(f'<rect x="{x:.1f}" y="{y - 10}" width="{w:.1f}" height="44" rx="12" fill="{t["card2"]}" '
                         f'stroke="{t["line"]}"/>{art}' + svg.text(x + 47, y + 17.5, name, 15, 500, t["ink"]))
            x += w + 10
        period = x
        reps = math.ceil((vx1 - vx0) / period) + 1
        row = "".join(f'<g transform="translate({vx0 + k * period:.1f} 0)">{"".join(pills)}</g>' for k in range(reps))
        seconds = period / 26
        svg.css.append(f".m{r}{{animation:m{r} {seconds:.1f}s linear infinite{' reverse' if r % 2 else ''}}}"
                       f"@keyframes m{r}{{to{{transform:translateX(-{period:.1f}px)}}}}")
        svg.add(f'<g clip-path="url(#vp)"><g class="m{r}">{row}</g></g>')
    svg.add(f'<rect x="{vx0}" y="10" width="70" height="{H - 20}" fill="url(#fl)"/>',
            f'<rect x="{vx1 - 70}" y="10" width="70" height="{H - 20}" fill="url(#fr)"/>')
    write("toolbox", svg)


# ---------------------------------------------------------------- live stats
QUERY = """
query($login: String!, $after: String, $prs: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount contributionLevel } }
      }
    }
    repositories(first: 100, after: $after, ownerAffiliations: OWNER, isFork: false) {
      pageInfo { hasNextPage endCursor }
      nodes { name isPrivate stargazerCount forkCount primaryLanguage { name } }
    }
  }
  search(query: $prs, type: ISSUE) { issueCount }
}
"""


def token() -> str:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        sys.exit("No GitHub token: set GITHUB_TOKEN or log in with `gh auth login`.")


def graphql(tok: str, **variables) -> dict:
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {tok}", "User-Agent": f"{USER}-profile-build"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    if data.get("errors"):
        sys.exit(f"GitHub API error: {json.dumps(data['errors'])}")
    return data["data"]


def fetch() -> dict:
    """Counts cover every repository the token can see, private ones included."""
    tok, repos, after = token(), [], None
    while True:
        data = graphql(tok, login=USER, after=after, prs=f"author:{USER} type:pr")
        page = data["user"]["repositories"]
        repos += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    cal = data["user"]["contributionsCollection"]["contributionCalendar"]
    print(f"{len(repos)} repositories ({sum(r['isPrivate'] for r in repos)} private) visible to the token")
    return {"repos": {r["name"]: r for r in repos}, "weeks": [w["contributionDays"] for w in cal["weeks"]],
            "total": cal["totalContributions"], "prs": data["search"]["issueCount"]}


# Colour follows the language, not its rank: a language keeps its slot when
# the ranking shifts. The six slots match the order of THEMES[...]["series"].
LANG_SLOTS = ["Python", "Java", "C++", "C", "JavaScript", "HTML"]
LEVELS = ["NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE"]


def language_segments(repos: dict, t: dict) -> tuple[list[tuple[str, int, str]], int]:
    counts = Counter(r["primaryLanguage"]["name"] for r in repos.values() if r["primaryLanguage"])
    total = sum(counts.values())
    top = [name for name, _ in counts.most_common(6)]
    free = [s for s, name in enumerate(LANG_SLOTS) if name not in top]
    segments = [(name, counts[name], t["series"][LANG_SLOTS.index(name) if name in LANG_SLOTS else free.pop(0)])
                for name in top]
    other = total - sum(n for _, n, _ in segments)
    if other:
        segments.append(("Other", other, t["other"]))
    return segments, total


def month_labels(weeks: list[list[dict]]) -> list[tuple[int, str]]:
    marks, prev = [], None
    for c, week in enumerate(weeks):
        first = dt.date.fromisoformat(week[0]["date"])
        if first.month != prev:
            marks.append((c, first.strftime("%b")))
        prev = first.month
    if len(marks) > 1 and marks[1][0] - marks[0][0] < 3:
        marks.pop(0)  # a partial first month would collide with the next label
    return marks


CYCLE = 12  # seconds; the stats panel replays its story on this loop
SCAN_START, SCAN_TIME = 0.5, 4.8  # when the scan beam enters the calendar, and how long it takes


def odometer(svg: Svg, key: str, x, y, value: str, size, delay) -> str:
    """Digits that spin one full turn and land on `value`, every CYCLE seconds.

    Each digit column holds 0-9 twice. It starts on its digit and ends on the
    same digit one turn later, so the loop restarts on an identical picture.
    """
    t = svg.t
    lh = size * 1.12
    dw = max(measure(d, size, 700) for d in "0123456789")
    svg.defs.append(f'<clipPath id="od{key}"><rect x="{x - 4}" y="{y - size * 0.92:.1f}" width="400" '
                    f'height="{lh:.1f}"/></clipPath>')
    parts, cx = [], x
    for i, ch in enumerate(value):
        if not ch.isdigit():
            parts.append(svg.text(cx, y, ch, size, 700, t["ink"]))
            cx += measure(ch, size, 700)
            continue
        d = int(ch)
        col = "".join(svg.text(cx + dw / 2, y + n * lh, str(n % 10), size, 700, t["ink"], anchor="middle")
                      for n in range(20))
        start, end = -d * lh, -(d + 10) * lh
        parts.append(f'<g class="odo" style="transform:translateY({start:.1f}px);--a:{start:.1f}px;--b:{end:.1f}px;'
                     f'animation-delay:{delay + i * 0.12:.2f}s">{col}</g>')
        cx += dw
    return f'<g clip-path="url(#od{key})">{"".join(parts)}</g>'


def glance(theme: str, stats: dict):
    W, H = 1200, 556
    svg = Svg(W, H, theme, "GitHub at a glance")
    t = svg.t
    days = [d for week in stats["weeks"] for d in week]
    stars = sum(r["stargazerCount"] for r in stats["repos"].values())
    active = sum(1 for d in days if d["contributionCount"])
    gx, gy, pitch, cell = 82, 246, 20.3, 16
    ncol = len(stats["weeks"])
    span = ncol * pitch
    p0, p1 = SCAN_START / CYCLE * 100, (SCAN_START + SCAN_TIME) / CYCLE * 100
    # Every cell starts dark. The scan beam crosses the year and switches each
    # day on as it passes; active days pop in with a coloured flash ring.
    # `backwards` holds each cell at its dark 0% frame until its own moment.
    svg.css.append(
        f".odo{{animation:odo {CYCLE}s cubic-bezier(.3,.9,.3,1) infinite}}"
        "@keyframes odo{0%{transform:translateY(var(--a))}14%,100%{transform:translateY(var(--b))}}"
        f".lit{{animation:lit {CYCLE}s linear infinite backwards}}"
        "@keyframes lit{0%{opacity:0}2%,90%{opacity:1}95%,100%{opacity:0}}"
        f".pop{{animation:pop {CYCLE}s cubic-bezier(.2,.8,.2,1) infinite backwards}}"
        "@keyframes pop{0%{opacity:0;transform:scale(.2)}2%{opacity:1;transform:scale(1.5)}"
        "4.5%,90%{opacity:1;transform:scale(1)}95%,100%{opacity:0;transform:scale(1)}}"
        f".ring{{animation:ring {CYCLE}s ease-out infinite backwards;opacity:0}}"
        "@keyframes ring{0%{opacity:0;transform:scale(1)}.5%{opacity:1}8%,100%{opacity:0;transform:scale(2.8)}}"
        f".scan{{animation:scan {CYCLE}s linear infinite}}"
        f"@keyframes scan{{0%,{p0:.2f}%{{transform:translateX(0);opacity:0}}{p0 + 1:.2f}%{{opacity:1}}"
        f"{p1:.2f}%{{transform:translateX({span:.0f}px);opacity:1}}{p1 + 2:.2f}%,100%{{transform:translateX({span:.0f}px);"
        "opacity:0}}"
        ".ping{animation:ping 2.4s ease-out infinite}@keyframes ping{from{transform:scale(.4);opacity:.9}"
        "to{transform:scale(2.6);opacity:0}}"
        f".grow{{animation:grow {CYCLE}s cubic-bezier(.2,.8,.2,1) infinite}}"
        "@keyframes grow{0%,46%{transform:scaleX(0)}58%,100%{transform:scaleX(1)}}")
    svg.add(frame(svg, W, H, 22))

    kpis = [(f'{stats["total"]:,}', "contributions, past year", "cyan", "pulse"),
            (str(active), "active days, past year", "emerald", "calendar"),
            (str(stars), "stars earned", "amber", "star"),
            (str(stats["prs"]), "pull requests", "violet", "pr"),
            (str(len(stats["repos"])), "repositories", "pink", "repo")]
    gap = 14
    tw = (W - 80 - 4 * gap) / 5
    for i, (value, label, colour, icon_kind) in enumerate(kpis):
        x = 40 + i * (tw + gap)
        tile = backdrop(round(tw), 108, t["card2"], [(tw - 20, 0, 150, t[colour], t["glow"] * .7)], scale=.5)
        svg.defs.append(f'<clipPath id="kp{i}"><rect x="{x:.1f}" y="36" width="{tw:.1f}" height="108" rx="14"/></clipPath>')
        svg.add(f'<image href="{tile}" x="{x:.1f}" y="36" width="{tw:.1f}" height="108" preserveAspectRatio="none" '
                f'clip-path="url(#kp{i})"/>',
                f'<rect x="{x:.1f}" y="36" width="{tw:.1f}" height="108" rx="14" fill="none" stroke="{t["line"]}"/>',
                f'<rect x="{x + 20:.1f}" y="36" width="36" height="2.5" fill="{t[colour]}"/>',
                glyph(icon_kind, x + tw - 42, 54, 22, t[colour], 1.7),
                odometer(svg, str(i), x + 20, 94, value, 42, i * 0.15),
                svg.text(x + 20, 124, label, 15, 400, t["ink2"]))

    hy = 196
    svg.add(svg.text(40, hy, "Contributions", 16, 700, t["ink"]),
            svg.text(40 + measure("Contributions", 16, 700) + 10, hy, "last 12 months", 14, 400, t["ink2"], "JB"))
    lx = W - 40 - 5 * 20 - measure("More", 13, 500, "JB") - 6
    svg.add(svg.text(lx - 8, hy, "Less", 13, 500, t["ink2"], "JB", anchor="end"),
            *[f'<rect x="{lx + i * 20}" y="{hy - 12}" width="14" height="14" rx="3.5" fill="{t["ramp"][i]}"/>'
              for i in range(5)],
            svg.text(lx + 5 * 20 + 2, hy, "More", 13, 500, t["ink2"], "JB"))
    for c, label in month_labels(stats["weeks"]):
        svg.add(svg.text(gx + c * pitch, gy - 12, label, 13, 500, t["ink2"], "JB"))
    dark, lit, pops, rings, last_active = [], [], [], [], None
    for c, week in enumerate(stats["weeks"]):
        for d in week:
            row = (dt.date.fromisoformat(d["date"]).weekday() + 1) % 7  # Sunday first, like GitHub
            x, y = gx + c * pitch, gy + row * pitch
            when = SCAN_START + SCAN_TIME * (c * pitch + cell / 2) / span + row * 0.015
            level = LEVELS.index(d["contributionLevel"])
            tip = f'<title>{d["date"]}: {d["contributionCount"]} contributions</title>'
            dark.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell}" height="{cell}" rx="3.5"/>')
            if level:
                origin = f"transform-origin:{x + cell / 2:.1f}px {y + cell / 2:.1f}px"
                pops.append(f'<rect class="pop" style="animation-delay:{when:.2f}s;{origin}" x="{x:.1f}" y="{y:.1f}" '
                            f'width="{cell}" height="{cell}" rx="3.5" fill="{t["ramp"][level]}">{tip}</rect>')
                rings.append(f'<rect class="ring" style="animation-delay:{when:.2f}s;{origin}" x="{x:.1f}" '
                             f'y="{y:.1f}" width="{cell}" height="{cell}" rx="4" fill="none" '
                             f'stroke="{spectrum_at(t, c / max(ncol - 1, 1))}" stroke-width="2"/>')
                last_active = (x + cell / 2, y + cell / 2)
            else:
                lit.append(f'<rect class="lit" style="animation-delay:{when:.2f}s" x="{x:.1f}" y="{y:.1f}" '
                           f'width="{cell}" height="{cell}" rx="3.5">{tip}</rect>')
    svg.gradient("beam", ["cyan", "cyan", "violet", "pink"], 1, 0, [0, .18, .55, .95])
    svg.defs.append(f'<clipPath id="grid"><rect x="{gx - 4}" y="{gy - 6}" width="{span + 6:.0f}" '
                    f'height="{7 * pitch + 8:.0f}"/></clipPath>')
    svg.add(f'<g fill="{t["off"]}">{"".join(dark)}</g>',
            f'<g fill="{t["ramp"][0]}">{"".join(lit)}</g>',
            "".join(pops),
            f'<g class="motion">{"".join(rings)}<g clip-path="url(#grid)">'
            f'<rect class="scan" x="{gx - 120}" y="{gy - 4}" width="120" height="{7 * pitch + 4:.0f}" rx="3" '
            f'fill="url(#beam)" opacity="0"/></g></g>')
    if last_active:
        px, py = last_active
        svg.add(f'<g class="motion"><circle class="ping" style="transform-origin:{px:.1f}px {py:.1f}px" '
                f'cx="{px:.1f}" cy="{py:.1f}" r="9" fill="none" stroke="{t["pink"]}" stroke-width="2"/></g>')
    for row, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        svg.add(svg.text(40, gy + row * pitch + 12.5, label, 13, 500, t["ink2"], "JB"))

    # Primary language of each repository: one stacked bar plus a legend.
    segments, total = language_segments(stats["repos"], t)
    by = gy + 7 * pitch + 30
    svg.add(f'<rect x="40" y="{by}" width="{W - 80}" height="1" fill="{t["line"]}"/>',
            svg.text(40, by + 44, "Primary language", 16, 700, t["ink"]),
            svg.text(40 + measure("Primary language", 16, 700) + 10, by + 44,
                     "of each repository", 14, 400, t["ink2"], "JB"))
    x, bar_y = 40.0, by + 62
    bars = []
    for i, (name, n, color) in enumerate(segments):
        w = (W - 80) * n / total - (2 if i < len(segments) - 1 else 0)
        bars.append(f'<rect x="{x:.1f}" y="{bar_y}" width="{max(w, 2):.1f}" height="12" rx="4" fill="{color}">'
                    f'<title>{name}: {n} of {total} repositories</title></rect>')
        x += w + 2
    svg.add(f'<g class="grow" style="transform-origin:40px {bar_y}px">{"".join(bars)}</g>')
    lx = 40
    for name, n, color in segments:
        pct = f"{round(100 * n / total)}%"
        svg.add(f'<circle cx="{lx + 5}" cy="{bar_y + 40}" r="5" fill="{color}"/>',
                svg.text(lx + 16, bar_y + 45, name, 15, 500, t["ink"]),
                svg.text(lx + 22 + measure(name, 15, 500), bar_y + 45, pct, 14, 400, t["ink2"], "JB"))
        lx += 22 + measure(name, 15, 500) + measure(pct, 14, 400, "JB") + 24
    day = dt.datetime.now(dt.timezone.utc)
    svg.add(svg.text(W - 40, bar_y + 45, f"updated {day:%Y-%m-%d}", 13, 400, t["ink2"], "JB", anchor="end"))
    write("glance", svg)


# -------------------------------------------------------------------- footer
def footer(theme: str):
    W, H = 1200, 170
    svg = Svg(W, H, theme, "Thanks for stopping by. Open to collaborating on backend, full-stack, QA and AI.")
    t = svg.t
    svg.gradient("rule", ["cyan", "cyan", "violet", "pink", "amber", "amber"], 1, 0, [0, .9, .9, .9, .9, 0])
    svg.defs.append('<linearGradient id="spark" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#fff" '
                    'stop-opacity="0"/><stop offset=".5" stop-color="#fff"/><stop offset="1" stop-color="#fff" '
                    'stop-opacity="0"/></linearGradient>')
    svg.css.append(".sweep{animation:sweep 5s cubic-bezier(.6,0,.4,1) infinite}"
                   "@keyframes sweep{from{transform:translateX(-160px)}to{transform:translateX(1060px)}}"
                   ".blink{animation:blink 1.6s ease-in-out infinite}@keyframes blink{50%{opacity:.25}}")
    line = "Thanks for stopping by."
    lw = measure(line, 30, 700, "JB") + 30
    cta = "open to collaborating on backend, full-stack, QA and AI"
    cw = measure(cta, 15, 500, "JB") + 22
    lx = W / 2 - lw / 2
    svg.add(f'<rect x="120" y="24" width="{W - 240}" height="2" fill="url(#rule)"/>',
            f'<rect class="sweep motion" x="150" y="23" width="140" height="4" rx="2" fill="url(#spark)" '
            f'opacity=".8"/>',
            svg.text(lx, 92, ">", 30, 700, t["ink_pink"], "JB"),
            typing(svg, lx + 30, 92, [line], 30, 700, t["ink"], t["cyan"], prefix="foot", hold=6),
            f'<circle cx="{W / 2 - cw / 2 + 5}" cy="{127}" r="4.5" fill="{t["ok"]}" class="blink"/>',
            svg.text(W / 2 - cw / 2 + 22, 132, cta, 15, 500, t["ink2"], "JB"))
    write("footer", svg)


# ---------------------------------------------------------------------- main
def main():
    stats = fetch()
    for theme in THEMES:
        header(theme)
        for key in SECTIONS:
            section_title(theme, key)
        for i, (slug, label) in enumerate(SOCIALS):
            social(theme, i, slug, label)
        hero_card(theme, stats["repos"][HERO["repo"]])
        for i, spec in enumerate(FEATURED):
            project_card(theme, i, spec, stats["repos"][spec["repo"]])
        toolbox(theme)
        glance(theme, stats)
        footer(theme)
    sizes = sorted((p.stat().st_size, p.name) for p in OUT.glob("*.svg"))
    print(f"wrote {len(sizes)} files to {OUT.relative_to(ROOT)}; largest {sizes[-1][1]} ({sizes[-1][0] // 1024} KB)")


if __name__ == "__main__":
    main()
