#!/usr/bin/env python3
"""
render_cards.py — turn real sim.py output into PNG sticker cards.

Every card is sliced out of an actual `python3 sim.py` run captured at render
time, so nothing here can drift from what the simulator really prints. The
report's own ASCII frames are stripped and replaced by the PNG card's rounded
edge; text content is otherwise untouched (the footer is re-wrapped so it fits a
phone screen). Cards are RGBA with transparent corners, for overlay on 9:16
vertical video.

    python3 launch-assets/render_cards.py

Requires Pillow.
"""

import os
import subprocess
import sys
import textwrap
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

BG     = (13, 13, 13, 255)       # #0d0d0d
BORDER = (38, 38, 38, 255)
TEXT   = (226, 226, 226, 255)
MUTED  = (138, 138, 138, 255)
DIM    = (72, 72, 72, 255)
TRACK  = (39, 39, 39, 255)
GREEN  = (74, 222, 128, 255)
AMBER  = (245, 179, 1, 255)
WHITE  = (255, 255, 255, 255)

BOX = set("─│┌┐└┘━┃┏┓┗┛┼")
BLOCKS = set("▁▂▃▄▅▆▇█")
FONTS = ["/System/Library/Fonts/Menlo.ttc",
         "/System/Library/Fonts/SFNSMono.ttf",
         "/Library/Fonts/Menlo.ttc"]


def load_font(size):
    for path in FONTS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    raise SystemExit("no monospace font found; tried:\n  " + "\n  ".join(FONTS))


def run_sim(*args):
    """Capture a real run. Cards are only ever built from this."""
    return subprocess.run([sys.executable, "sim.py", *args], cwd=REPO,
                          capture_output=True, text=True, check=True).stdout.split("\n")


def between(lines, start, end, start_at=0):
    i = next(k for k in range(start_at, len(lines)) if start(lines[k]))
    j = next(k for k in range(i, len(lines)) if end(lines[k]))
    return lines[i:j + 1]


def unbox(lines):
    """Drop a surrounding ASCII frame; the PNG's rounded edge replaces it."""
    body = [l for l in lines if l.strip()]
    if len(body) >= 2 and set(body[0].strip()) <= BOX and set(body[-1].strip()) <= BOX:
        lines = [l for l in lines if l is not body[0] and l is not body[-1]]
    out = []
    for l in lines:
        s = l.strip()
        if s and set(s) <= BOX:          # interior rules that were part of the frame
            out.append("")
            continue
        s = l
        for ch in "┃│":                  # strip vertical edges
            s = s.replace(ch, " ")
        out.append(s.rstrip())
    return out


def dedent(lines):
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    ind = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    cut = min(ind) if ind else 0
    return [l[cut:] if l.strip() else "" for l in lines]


def runs(line, chars):
    """Yield (start, end) spans of consecutive characters drawn as solid bars."""
    i = 0
    while i < len(line):
        if line[i] in chars:
            j = i
            while j + 1 < len(line) and line[j + 1] == line[i]:
                j += 1
            yield i, j, line[i]
            i = j + 1
        else:
            i += 1


def emph_cols(line, subs):
    """Columns covered by any emphasised substring, for token-level colouring."""
    cols = set()
    for sub in subs:
        k = line.find(sub)
        while k >= 0:
            cols |= set(range(k, k + len(sub)))
            k = line.find(sub, k + 1)
    return cols


def render(lines, out_path, accent=GREEN, size=30, head=0, pad=72, radius=32,
           warn=(), muted=(), emph=(), min_width=1080, center=False):
    lines = [l.strip() for l in lines] if center else dedent(list(lines))
    body_font = load_font(size)
    head_font = load_font(int(size * 1.34))
    adv, hadv = body_font.getlength("M"), head_font.getlength("M")
    lh, hlh = int(size * 1.62), int(size * 1.34 * 1.55)

    rows = []                                  # (text, font, advance, height, is_head)
    for i, l in enumerate(lines):
        h = i < head
        rows.append((l, head_font if h else body_font, hadv if h else adv,
                     hlh if h else lh, h))

    content = max(len(t) * a for t, _, a, _, _ in rows)
    w = max(int(pad * 2 + content + 2), min_width)
    x0 = (w - content) / 2.0          # keep content centred if min_width widened us
    h = int(pad * 2 + sum(r[3] for r in rows))

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=BG,
                        outline=BORDER, width=2)

    y = pad
    for i, (line, font, a, rh, is_head) in enumerate(rows):
        # Centre each row on its own width: head rows use a wider advance, so
        # the source text's own centring no longer lines up.
        rx = x0 + (content - len(line) * a) / 2.0 if center else x0
        # Bars as solid rectangles — the ░ glyph reads as noise at phone size.
        # Only the win-probability bars get the solid-rectangle treatment: they
        # are the lines pairing █ with a ░ track. The margin histogram is built
        # from partial blocks and must stay as glyphs to keep its shape.
        skip = set()
        for bs, be, ch in (runs(line, "█░") if ("█" in line and "░" in line) else ()):
            bx0, bx1 = rx + bs * a, rx + (be + 1) * a
            d.rounded_rectangle([bx0, y + rh * 0.24, bx1 - 2, y + rh * 0.74],
                                radius=4, fill=accent if ch == "█" else TRACK)
            skip |= set(range(bs, be + 1))

        forced = AMBER if i in warn else (accent if is_head else
                                          MUTED if i in muted else None)
        ecols = emph_cols(line, emph)
        for col, ch in enumerate(line):
            if ch == " " or col in skip:
                continue
            fill = forced or (AMBER if col in ecols else
                              DIM if ch in BOX else
                              accent if ch in BLOCKS else TEXT)
            d.text((rx + col * a, y), ch, font=font, fill=fill)
        y += rh

    img.save(out_path)
    return os.path.basename(out_path), w, h


def main():
    default = run_sim()                 # seed 1234
    coin = run_sim("--seed", "7")       # a real run that lands on a coin flip
    made = []

    # 1 — title header
    head = unbox(between(default, lambda l: l.startswith("┌"), lambda l: l.startswith("└")))
    made.append(render(head, f"{HERE}/01-title.png", head=1, muted=(1, 2),
                       min_width=1180, center=True))

    # 2 — win probability, through the summary sentence
    wp = between(default, lambda l: l.strip() == "WIN PROBABILITY",
                 lambda l: "on average." in l)
    made.append(render(wp, f"{HERE}/02-win-probability.png", head=1))

    # 3 — headline verdict at the default seed
    v1 = unbox(between(default, lambda l: l.lstrip().startswith("┏"),
                       lambda l: l.lstrip().startswith("┗")))
    made.append(render(v1, f"{HERE}/03-verdict-stick-with.png", accent=GREEN, head=1))

    # 4 — coin-flip verdict, from the seed-7 run
    v2 = unbox(between(coin, lambda l: l.lstrip().startswith("┏"),
                       lambda l: l.lstrip().startswith("┗")))
    made.append(render(v2, f"{HERE}/04-verdict-coin-flip.png", accent=AMBER, head=1))

    # 5 — footer + unverified-estimate warning, re-wrapped for a phone
    i = max(k for k, l in enumerate(default) if l.strip().startswith("────"))
    foot, warn, hot = [], set(), False
    for src in (x.strip() for x in default[i + 1:] if x.strip()):
        wrapped = textwrap.wrap(src, 62) or [""]
        # sim.py wraps the warning across several lines; only the first carries
        # the "!", and it is always the last thing printed.
        hot = hot or src.startswith("!")
        if hot:
            warn |= set(range(len(foot), len(foot) + len(wrapped)))
        foot += wrapped
    made.append(render(foot, f"{HERE}/05-footer-warning.png", accent=AMBER,
                       warn=warn, muted=(0, 1), emph=("ESTIMATE-UNVERIFIED",)))

    # bonus — the whole report
    full = list(default)
    dl = dedent(list(full))
    bang = next((k for k, l in enumerate(dl) if l.lstrip().startswith("!")), None)
    warn = set(range(bang, len(dl))) if bang is not None else set()
    made.append(render(full, f"{HERE}/06-full-report.png", size=24, pad=60,
                       radius=28, warn=warn,
                       emph=("ESTIMATE-UNVERIFIED", "UNVERIFIED ESTIMATES")))

    for name, w, h in made:
        print("  %-32s %5d x %-5d" % (name, w, h))


if __name__ == "__main__":
    main()
