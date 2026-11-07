"""F3 · kinetic-bold — caption-style: near-black background, Inter Black, words pop in as they are
spoken, the key word in the cluster colour. The whole hook is readable on frame 0; TURN and LINE
are revealed word by word with the voice. Ends on the LINE and loops.

Reuses the word layout / timing helpers from emotion_v2 so the voice sync is identical to F1.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from .. import gfx, tts
from ..emotion import _clean
from ..emotion_v2 import assign_times, layout_words, pick_key, scaled
from ..gfx import H, W, ease, inter, mono, paste_fade, prog

INK = (18, 17, 16)
PAPER = (246, 243, 238)
DIM = (176, 170, 160)
SAFE_TOP = 300
BOX_W, BOX_H = 834, 760
BEATS = ("hook", "turn", "line")
HOLD = {"hook": 0.5, "turn": 0.25, "line": 1.1}
GAP = 0.28
POP = 0.10


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _fit(text, weight, max_w, max_h, start, minimum=56):
    s = start
    while s >= minimum:
        f = inter(s, weight)
        words, th = layout_words(text, f, max_w, color=PAPER)
        if th <= max_h:
            return f, words, th
        s -= 4
    f = inter(minimum, weight)
    words, th = layout_words(text, f, max_w, color=PAPER)
    return f, words, th


def _recolor(word, font, color):
    im = Image.new("RGBA", (word.w + 16, word.h + 16), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((8, 8), word.txt, font=font, fill=color)
    word.img = im


def build(item: dict, out: Path, music: Path, workdir: Path | None = None) -> Path:
    workdir = workdir or Path(tempfile.mkdtemp())
    accent = _hex(item.get("color") or "#4E6A57")
    accent = tuple(int(c + (255 - c) * 0.45) for c in accent)
    beats = [(k, _clean(item[k])) for k in BEATS if item.get(k)]
    vo = tts.synth([b[1] for b in beats], workdir)

    t, tl = 0.0, []
    for (kind, txt), (wav, d) in zip(beats, vo):
        tl.append(dict(kind=kind, txt=txt, t0=t, speak=d, end=t + d + HOLD[kind], wav=wav))
        t += d + HOLD[kind] + GAP
    duration = t - GAP + 0.3

    for b in tl:
        weight, start = {"hook": ("Black", 110), "turn": ("ExtraBold", 96), "line": ("ExtraBold", 92)}[b["kind"]]
        f, words, th = _fit(b["txt"], weight, BOX_W, BOX_H, start)
        assign_times(words, b["t0"], b["speak"])
        if b["kind"] == "hook":
            for w in words:              # whole hook visible from frame 0 — it is the cover
                w.t0 = -1.0
        if b["kind"] != "turn":
            pick_key(words)
            for w in words:
                if w.key:
                    _recolor(w, f, accent)
        b.update(words=words, th=th)

    label = f"{item['num']:02d} · {item['emotion'].upper()}"
    lf = mono(30)
    lab = Image.new("RGBA", (W, 60), (0, 0, 0, 0))
    d = ImageDraw.Draw(lab)
    lw = d.textlength(label, font=lf) + 34
    x0 = (W - lw) / 2
    d.ellipse([x0, 8, x0 + 18, 26], fill=accent)
    d.text((x0 + 34, 0), label, font=lf, fill=DIM)

    def frame(tt: float) -> Image.Image:
        img = Image.new("RGBA", (W, H), INK + (255,))
        img.alpha_composite(lab, (0, SAFE_TOP))
        for b in tl:
            if not (b["t0"] - 0.05 <= tt < b["end"] + 0.3):
                continue
            out_a = 1 - prog(tt, b["end"], 0.25)
            y0 = 960 - b["th"] / 2
            for w in b["words"]:
                if tt < w.t0:
                    continue
                p = prog(tt, w.t0, 0.16)
                sc = 1 + POP * (1 - ease(p))
                im, dx, dy = scaled(w.img, sc)
                paste_fade(img, im, (w.x + dx, y0 + w.y + dy), min(1, p * 2.5) * out_a)
        return img

    mix = gfx.mix_audio([(b["wav"], b["t0"]) for b in tl if b["wav"]], music, duration, workdir / "mix.m4a")
    gfx.encode(frame, duration, out, mix, crf=17, audio_raw=True)
    return out
