"""F2 · ink-serif — the quote-card look: near-black card, Playfair Display, one beat per screen,
hard cuts, music only (no voice). The whole hook is the first frame and the cover.

Screen time per beat: words / 3 + 1 s, clamped to 2–4 s. Ends on the LINE and loops.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .. import gfx
from ..emotion import _clean
from ..gfx import H, W, fit_text, mono, play, text_block

INK = (18, 17, 16)
PAPER = (246, 243, 238)
DIM = (176, 170, 160)
SAFE_TOP, SAFE_BOTTOM = 300, H - 520        # TikTok's own UI covers the top and bottom bands
MAX_W = 834                                 # 96 px left margin, 150 px right (like/comment column)
BEATS = ("hook", "turn", "line")


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _secs(text: str) -> float:
    return max(2.0, min(4.0, len(text.split()) / 3 + 1))


def _screen(text: str, label: str, dot: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGBA", (W, H), INK + (255,))
    d = ImageDraw.Draw(img)
    lf = mono(30)
    lw = d.textlength(label, font=lf) + 34
    x0 = (W - lw) / 2
    d.ellipse([x0, SAFE_TOP + 8, x0 + 18, SAFE_TOP + 26], fill=dot)
    d.text((x0 + 34, SAFE_TOP), label, font=lf, fill=DIM)
    start = 104 if len(text) <= 48 else 84 if len(text) <= 90 else 70
    f, lines = fit_text(text, lambda s: play(s, "SemiBold"), MAX_W, SAFE_BOTTOM - SAFE_TOP - 140,
                        start=start, minimum=56, spacing=1.25)
    block = text_block(lines, f, PAPER, spacing=1.25)
    img.alpha_composite(block, (0, int((SAFE_TOP + SAFE_BOTTOM) / 2 - block.height / 2)))
    return img


def build(item: dict, out: Path, music: Path, workdir: Path | None = None) -> Path:
    accent = _hex(item.get("color") or "#4E6A57")
    dot = tuple(int(c + (255 - c) * 0.35) for c in accent)
    label = f"{item['num']:02d} · {item['emotion'].upper()}"
    screens = []
    for k in BEATS:
        if item.get(k):
            txt = _clean(item[k])
            screens.append((_screen(txt, label, dot), _secs(txt)))
    duration = sum(s for _, s in screens)

    def frame(t: float) -> Image.Image:
        acc = 0.0
        for img, s in screens:
            acc += s
            if t < acc:
                return img
        return screens[-1][0]

    return gfx.encode(frame, duration, out, music, crf=18)
