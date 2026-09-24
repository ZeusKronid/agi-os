"""Render the Helios images of the Live desktop: the wallpaper and the xfwm4 window frame.

The results are committed under archiso/airootfs; run this again after changing a value here.
Needs rsvg-convert (librsvg). Usage: python scripts/live-desktop/render.py
"""
import math
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]
airootfs = root / 'archiso/airootfs'

CANVAS = '#0b0908'
ACCENT = '#ff6a3d'
ACCENT_DEEP = '#d9532c'
ON_ACCENT = '#160b06'

# Wallpaper geometry. agi-desktop places the installer window from the same numbers:
# keep WIDTH, HEIGHT and HORIZON in sync with archiso/airootfs/usr/local/bin/agi-desktop.
WIDTH, HEIGHT = 2560, 1440
HORIZON = 0.32           # share of the height: the installer window stands on this line
RADIUS = 0.15            # share of the height


def mulberry32(seed):
    """The site's deterministic generator (site/src/shared/ui/sunburst/rays.ts)."""
    state = seed & 0xFFFFFFFF

    def imul(a, b):
        return (a * b) & 0xFFFFFFFF

    def random():
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = state
        t = imul(t ^ (t >> 15), t | 1)
        t ^= (t + imul(t ^ (t >> 7), t | 61)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return random


def noise(index, salt):
    x = math.sin(index * 12.9898 + salt * 78.233) * 43758.5453
    return x - math.floor(x)


def wallpaper():
    """The site's hero sunrise (seed 7, 96 rays) with rays held at their shimmer length."""
    cx, cy, r = WIDTH / 2, HEIGHT * HORIZON, HEIGHT * RADIUS
    unit = r / 155                     # the site draws the hero with radius 155
    random = mulberry32(7)
    rays = []
    for index in range(97):
        major = index % 4 == 0
        length = r * (0.37 if major else 0.13 + (0.27 - 0.13) * random())
        opacity = 0.85 if major else 0.3 + 0.35 * random()
        length *= 1 + 0.7 * (0.4 + 0.9 * noise(index, 1))
        angle = math.pi + math.pi * index / 96
        inner = r + 8 * unit
        c, s = math.cos(angle), math.sin(angle)
        rays.append(f'<line x1="{cx + inner * c:.1f}" y1="{cy + inner * s:.1f}" '
                    f'x2="{cx + (inner + length) * c:.1f}" y2="{cy + (inner + length) * s:.1f}" '
                    f'stroke-opacity="{opacity:.2f}"/>')
    dots = []
    for degrees in (180, 205, 243, 297, 335, 360):
        a = math.radians(degrees)
        size = 2.4 if degrees in (180, 360) else 1.6
        dots.append(f'<circle cx="{cx + r * math.cos(a):.1f}" cy="{cy + r * math.sin(a):.1f}" r="{size * unit:.1f}"/>')
    for side in (-1, 1):
        dots.append(f'<circle cx="{cx + side * 282 * unit:.1f}" cy="{cy - 108 * unit:.1f}" r="{2 * unit:.1f}"/>')
    dots.append(f'<circle cx="{cx}" cy="{cy - r * 0.43:.1f}" r="{2.2 * unit:.1f}"/>')

    random = mulberry32(11)
    stars = []
    for _ in range(170):
        x, y = random() * WIDTH, random() * HEIGHT
        alpha = 0.12 + 0.38 * random()
        coral = random() < 0.07
        size = 1.1 if random() < 0.9 else 1.8
        stars.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{size}" fill="{ACCENT if coral else "#f6f2ec"}" '
                     f'fill-opacity="{alpha + (0.2 if coral else 0):.2f}"/>')

    fade = r * 1.95
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">
<defs>
  <radialGradient id="fade" gradientUnits="userSpaceOnUse" cx="{cx}" cy="{cy}" r="{fade:.1f}">
    <stop offset="{1.03 * r / fade:.2f}" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
  </radialGradient>
  <mask id="rays" maskUnits="userSpaceOnUse" x="0" y="0" width="{WIDTH}" height="{HEIGHT}">
    <rect width="{WIDTH}" height="{HEIGHT}" fill="url(#fade)"/>
  </mask>
  <linearGradient id="horizon" x1="0" x2="1" y1="0" y2="0">
    <stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".2"/>
    <stop offset="1" stop-color="#fff" stop-opacity="0"/>
  </linearGradient>
</defs>
<rect width="{WIDTH}" height="{HEIGHT}" fill="{CANVAS}"/>
<g>{''.join(stars)}</g>
<rect y="{cy - 0.5 * unit:.1f}" width="{WIDTH}" height="{1.2 * unit:.1f}" fill="url(#horizon)"/>
<g stroke="{ACCENT}" stroke-width="{0.9 * unit:.2f}" mask="url(#rays)">{''.join(rays)}</g>
<path d="M{cx - r:.1f} {cy:.1f} A{r:.1f} {r:.1f} 0 0 1 {cx + r:.1f} {cy:.1f}" fill="none" stroke="{ACCENT}" stroke-width="{1.5 * unit:.2f}"/>
<line x1="{cx}" y1="{cy - r:.1f}" x2="{cx}" y2="{cy - r * 0.46:.1f}" stroke="{ACCENT}" stroke-width="{unit:.2f}"/>
<g fill="{ACCENT}">{''.join(dots)}</g>
</svg>'''


# Window frame: warm black title bar, 1px border, round coral-on-hover buttons.
TITLE = 34
TITLE_BG = '#0e0b0a'
DIVIDER = '#24211f'                                  # Line (.09) over the title bar
BORDER = {'active': '#2d2b2a', 'inactive': '#211f1e'}  # Line Strong (.14) / Line (.09) over Canvas
RING = {'active': '#4a4745', 'inactive': '#2d2b2a'}
BUTTON = 22


def svg(width, height, body):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">{body}</svg>'


def title_piece(state):
    return svg(4, TITLE, f'<rect width="4" height="{TITLE}" fill="{TITLE_BG}"/>'
                         f'<rect width="4" height="1" fill="{BORDER[state]}"/>'
                         f'<rect y="{TITLE - 1}" width="4" height="1" fill="{DIVIDER}"/>')


def corner(state, mirrored):
    body = (f'<path d="M0 {TITLE} V10 A10 10 0 0 1 10 0 H10 V{TITLE} Z" fill="{TITLE_BG}"/>'
            f'<path d="M0.5 {TITLE} V10 A9.5 9.5 0 0 1 10 0.5" fill="none" stroke="{BORDER[state]}"/>'
            f'<rect x="1" y="{TITLE - 1}" width="9" height="1" fill="{DIVIDER}"/>')
    if mirrored:
        body = f'<g transform="translate(10 0) scale(-1 1)">{body}</g>'
    return svg(10, TITLE, body)


GLYPHS = {
    'close': 'M-2.1 -2.1 L2.1 2.1 M2.1 -2.1 L-2.1 2.1',
    'hide': 'M-2.4 0 H2.4',
    'maximize': 'M-2.4 0 H2.4 M0 -2.4 V2.4',
    'maximize-toggled': 'M-2 -2 H2 V2 H-2 Z',
}


def button(name, state):
    c, y = BUTTON / 2, TITLE / 2
    body = (f'<rect width="{BUTTON}" height="{TITLE}" fill="{TITLE_BG}"/>'
            f'<rect width="{BUTTON}" height="1" fill="{BORDER["inactive" if state == "inactive" else "active"]}"/>'
            f'<rect y="{TITLE - 1}" width="{BUTTON}" height="1" fill="{DIVIDER}"/>')
    if state in ('active', 'inactive'):
        body += f'<circle cx="{c}" cy="{y}" r="5.5" fill="none" stroke="{RING[state]}"/>'
    else:
        body += f'<circle cx="{c}" cy="{y}" r="6" fill="{ACCENT if state == "prelight" else ACCENT_DEEP}"/>'
        glyph = GLYPHS.get(name)
        if glyph:
            body += (f'<path transform="translate({c} {y})" d="{glyph}" fill="none" stroke="{ON_ACCENT}" '
                     f'stroke-width="1.3" stroke-linecap="round"/>')
    return svg(BUTTON, TITLE, body)


def frame():
    images = {}
    for state in ('active', 'inactive'):
        for n in range(1, 6):
            images[f'title-{n}-{state}'] = title_piece(state)
        images[f'top-left-{state}'] = corner(state, False)
        images[f'top-right-{state}'] = corner(state, True)
        for side in ('left', 'right', 'bottom', 'bottom-left', 'bottom-right'):
            images[f'{side}-{state}'] = svg(1, 1, f'<rect width="1" height="1" fill="{BORDER[state]}"/>')
    for name in ('close', 'hide', 'maximize', 'menu', 'shade', 'stick'):
        for state in ('active', 'inactive', 'prelight', 'pressed'):
            images[f'{name}-{state}'] = button(name, state)
            if name in ('maximize', 'shade', 'stick'):
                images[f'{name}-toggled-{state}'] = button(f'{name}-toggled', state)
    return images


def render(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['rsvg-convert', '--format', 'png', '--output', str(target)],
                   input=source.encode(), check=True)


if __name__ == '__main__':
    render(wallpaper(), airootfs / 'usr/share/backgrounds/agios/horizon.png')
    theme = airootfs / 'usr/share/themes/Helios/xfwm4'
    for name, source in frame().items():
        render(source, theme / f'{name}.png')
    print('Rendered the wallpaper and', len(frame()), 'frame images')
