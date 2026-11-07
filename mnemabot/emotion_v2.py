"""Emotion series v2 — paper + kinetic captions + handwriting + AI voiceover.

Beats (user's copy): HOOK → TURN → NAME → LINE (handwritten) → DO (sticky note) → proof + CTA.
Every word pops in when it is spoken; the key word gets a marker highlight.
"""
from __future__ import annotations

import math
import os
import random
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import gfx, tts
from .gfx import W, H, FPS, ease, prog, paste_fade
from .emotion import parse_series, _clean

FONTS = gfx.FONTS
PAPER = (244, 239, 230)
INK = (24, 24, 28)
INK_SOFT = (92, 88, 82)
PEN = (32, 40, 70)
NOTE = (252, 228, 140)

# Short format (default since 2026-11-05): HOOK → TURN → LINE, no proof card, no end card.
# Data from the first posts: 20–24 s videos were watched for ~2 s on average and almost never
# finished, so the long format never left the first test audience. MNEMA_FORMAT=full restores it.
SHORT = os.environ.get("MNEMA_FORMAT", "short") != "full"
POP = 0.10 if SHORT else 0.32   # pop-in overshoot; 0.32 made a growing word cover its neighbour ("muchwhat")

STOP = set("a an the is it its it's i you your you're to of and or but not in on for with that this be are was "
           "what if can could than then just so do don't isn't it’s you’re isn’t don’t".split())


def _f(name, size, var=None):
    f = ImageFont.truetype(str(FONTS / name), size)
    if var:
        f.set_variation_by_name(var)
    return f


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------- background
def make_paper(seed=7):
    rng = np.random.default_rng(seed)
    w, h = W + 80, H + 140
    base = np.ones((h, w, 3), np.float32) * np.array(PAPER, np.float32)
    # large soft mottling
    low = rng.normal(0, 1, (h // 60 + 2, w // 60 + 2)).astype(np.float32)
    low = np.array(Image.fromarray(((low * 20) + 128).clip(0, 255).astype(np.uint8)).resize((w, h), Image.BICUBIC),
                   np.float32) - 128
    base += low[..., None] * 0.07
    # fibres
    img = Image.fromarray(base.clip(0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img, "RGBA")
    for _ in range(900):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        a = rng.uniform(0, math.pi)
        l = rng.uniform(6, 26)
        d.line((x, y, x + math.cos(a) * l, y + math.sin(a) * l), fill=(120, 105, 85, int(rng.uniform(8, 22))), width=1)
    # vignette
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.sqrt(((xx - w / 2) / (w * 0.75)) ** 2 + ((yy - h / 2) / (h * 0.7)) ** 2)
    vig = (1 - np.clip(r - 0.55, 0, 1) * 0.35)[..., None]
    arr = np.array(img, np.float32) * vig
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8)).convert("RGBA")


def make_grain(n=4, seed=3):
    rng = np.random.default_rng(seed)
    frames = []
    for _ in range(n):
        g = rng.normal(0, 1, (H // 2, W // 2)).astype(np.float32)
        a = (np.abs(g) * 9).clip(0, 22).astype(np.uint8)
        c = np.where(g > 0, 255, 0).astype(np.uint8)
        im = Image.fromarray(np.dstack([c, c, c, a]), "RGBA").resize((W, H), Image.NEAREST)
        frames.append(im)
    return frames


# ---------------------------------------------------------------- hand-drawn bits
def rough_rect(w, h, color, seed=0, alpha=150):
    rng = random.Random(seed)
    im = Image.new("RGBA", (w + 40, h + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for k in range(2):
        pts = []
        j = lambda: rng.uniform(-7, 7)  # noqa: E731
        pts = [(20 + j(), 24 + j()), (20 + w + j(), 18 + j()), (20 + w + j(), 20 + h + j()), (20 + j(), 16 + h + j())]
        d.polygon(pts, fill=color + (alpha // 2 + 30 * k,))
    return im.filter(ImageFilter.GaussianBlur(1.2))


def scribble_underline(width, color, seed=1, thick=9):
    rng = random.Random(seed)
    im = Image.new("RGBA", (width + 40, 60), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pts = []
    for i in range(0, width + 1, 12):
        pts.append((20 + i, 30 + math.sin(i / 37) * 5 + rng.uniform(-2, 2)))
    d.line(pts, fill=color + (235,), width=thick, joint="curve")
    pts2 = [(x + 6, y + 9 + rng.uniform(-2, 2)) for x, y in pts[2:-6]]
    d.line(pts2, fill=color + (170,), width=thick - 3, joint="curve")
    return im


# ---------------------------------------------------------------- kinetic text
class Word:
    __slots__ = ("txt", "img", "x", "y", "w", "h", "t0", "key", "hl")


def layout_words(text, font, max_w, line_gap=1.12, color=INK):
    words = text.split()
    sp = font.getlength(" ")
    asc, desc = font.getmetrics()
    lh = int((asc + desc) * line_gap)
    lines, cur, cur_w = [], [], 0
    for w in words:
        ww = font.getlength(w)
        if cur and cur_w + sp + ww > max_w:
            lines.append(cur); cur, cur_w = [], 0
        cur.append((w, ww)); cur_w += (sp if len(cur) > 1 else 0) + ww
    if cur:
        lines.append(cur)
    out = []
    total_h = lh * len(lines)
    for li, ln in enumerate(lines):
        lw = sum(x[1] for x in ln) + sp * (len(ln) - 1)
        x = (W - lw) / 2
        for w, ww in ln:
            o = Word()
            o.txt, o.w, o.h = w, int(ww) + 8, asc + desc + 8
            im = Image.new("RGBA", (o.w + 16, o.h + 16), (0, 0, 0, 0))
            ImageDraw.Draw(im).text((8, 8), w, font=font, fill=color)
            o.img, o.x, o.y, o.key, o.hl = im, x - 8, li * lh - 8, False, None
            out.append(o)
            x += ww + sp
    return out, total_h


def fit_kinetic(text, var, max_w, max_h, start, minimum=52):
    s = start
    while s >= minimum:
        f = _f("Inter.ttf", s, var)
        words, th = layout_words(text, f, max_w)
        if th <= max_h:
            return f, words, th
        s -= 4
    f = _f("Inter.ttf", minimum, var)
    words, th = layout_words(text, f, max_w)
    return f, words, th


def assign_times(words, t0, dur):
    weights = [len(w.txt) + 2.2 for w in words]
    tot = sum(weights)
    t = t0 + 0.03
    span = dur * 0.94
    for w, wt in zip(words, weights):
        w.t0 = t
        t += span * wt / tot


def pick_key(words):
    cands = [w for w in words if w.txt.strip(".,!?“”\"'’").lower() not in STOP]
    if not cands:
        return
    best = max(cands, key=lambda w: len(w.txt.strip(".,!?“”\"'’")))
    best.key = True


def scaled(im, s):
    if abs(s - 1) < 0.01:
        return im, 0, 0
    nw, nh = max(1, int(im.width * s)), max(1, int(im.height * s))
    return im.resize((nw, nh), Image.BILINEAR), (im.width - nw) / 2, (im.height - nh) / 2


# ---------------------------------------------------------------- handwriting block
def hand_block(text, size, color, max_w):
    f = _f("Caveat.ttf", size, "Bold")
    lines = gfx.wrap(text, f, max_w)
    asc, desc = f.getmetrics()
    lh = int((asc + desc) * 1.0)
    img = Image.new("RGBA", (W, lh * len(lines) + desc + 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    widths = []
    for i, ln in enumerate(lines):
        tw = d.textlength(ln, font=f)
        x = (W - tw) / 2
        d.text((x, i * lh), ln, font=f, fill=color)
        widths.append((x, tw, i * lh, lh))
    return img, widths


def wipe(img, rows, p):
    """Reveal handwriting left→right, line by line, p in 0..1."""
    total = sum(r[1] for r in rows)
    if p >= 1:
        return img
    mask = Image.new("L", img.size, 0)
    d = ImageDraw.Draw(mask)
    budget = total * p
    for x, tw, y, lh in rows:
        if budget <= 0:
            break
        show = min(tw, budget)
        d.rectangle((0, y - 10, x + show, y + lh + 25), fill=255)
        budget -= tw
    out = img.copy()
    out.putalpha(Image.composite(img.getchannel("A"), Image.new("L", img.size, 0), mask))
    return out


# ---------------------------------------------------------------- build
def build(item: dict, out: Path, music: Path, workdir: Path | None = None) -> Path:
    workdir = workdir or Path(tempfile.mkdtemp())
    accent = _hex(item.get("color") or "#4E6A57")
    # pastel highlighter version of the cluster colour
    marker = tuple(int(c * 0.45 + 255 * 0.55) for c in accent)
    marker = tuple(min(255, int(m + (m - sum(marker) / 3) * 0.9)) for m in marker)
    kinds = ("hook", "turn", "line") if SHORT else ("hook", "turn", "name", "line", "do")
    beats = [(k, _clean(item[k])) for k in kinds if item.get(k)]
    vo = tts.synth([b[1] for b in beats], workdir)

    # ---- timeline
    GAP = 0.32
    t = 0.0
    tl = []
    for (kind, txt), (wav, d) in zip(beats, vo):
        hold = {"hook": 0.35, "line": 0.7, "do": 0.6}.get(kind, 0.15)
        tl.append(dict(kind=kind, txt=txt, t0=t, speak=d, end=t + d + hold, wav=wav))
        t += d + hold + GAP
    if SHORT:
        duration = t - GAP + 0.35          # ends on the LINE, then loops straight back to the hook
        proof_t0 = cta_t0 = float("inf")
    else:
        proof_t0 = t - GAP + 0.1
        cta_t0 = proof_t0 + 2.0
        duration = cta_t0 + 2.6

    # ---- assets
    paper = make_paper()
    grain = make_grain()
    brand = Image.new("RGBA", (W, 80), (0, 0, 0, 0))
    brand.alpha_composite(gfx.icon(44), (70, 18))
    ImageDraw.Draw(brand).text((128, 24), "Mnema", font=_f("Inter.ttf", 30, "SemiBold"), fill=INK)
    emo_f = _f("Caveat.ttf", 58, "Bold")
    emo_txt = item["emotion"].lower()
    ew = int(emo_f.getlength(emo_txt))
    emo = Image.new("RGBA", (ew + 80, 100), (0, 0, 0, 0))
    emo.alpha_composite(rough_rect(ew + 20, 60, marker, seed=item["num"], alpha=220), (10, 6))
    ImageDraw.Draw(emo).text((40, 14), emo_txt, font=emo_f, fill=INK)

    BOX_W, BOX_H = 900, 760
    for b in tl:
        if b["kind"] in ("hook", "turn", "name"):
            var, start = {"hook": ("Black", 118), "turn": ("ExtraBold", 96), "name": ("ExtraBold", 92)}[b["kind"]]
            f, words, th = fit_kinetic(b["txt"], var, BOX_W, BOX_H, start)
            assign_times(words, b["t0"], b["speak"])
            if b["kind"] == "hook" and SHORT:
                # the whole hook is readable on frame 0 (and on the cover) — no word-by-word reveal
                for w in words:
                    w.t0 = -1.0
            if b["kind"] != "turn":
                pick_key(words)
            for w in words:
                if w.key:
                    w.hl = rough_rect(w.w - 6, int(w.h * 0.62), marker, seed=len(w.txt) * 31, alpha=230)
            b.update(words=words, th=th)
        elif b["kind"] == "line":
            img, rows = hand_block(b["txt"], 120, PEN, 880)
            if img.height > 900:
                img, rows = hand_block(b["txt"], 96, PEN, 900)
            last = rows[-1]
            b.update(img=img, rows=rows, ul=scribble_underline(int(min(last[1], 700)), accent, seed=item["num"]))
        elif b["kind"] == "do":
            nw = 880
            hb, rows = hand_block(b["txt"], 82, INK, nw - 120)
            nh = hb.height + 190
            note = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
            ImageDraw.Draw(note).rectangle((0, 0, nw, nh), fill=NOTE + (255,))
            tape = Image.new("RGBA", (220, 56), (255, 255, 255, 120))
            note.alpha_composite(tape, ((nw - 220) // 2, -10 + 10))
            lbl = _f("Inter.ttf", 30, "Bold")
            ImageDraw.Draw(note).text((60, 52), "TRY THIS · 60 SECONDS", font=lbl, fill=(120, 92, 20))
            sh = Image.new("RGBA", (nw + 120, nh + 120), (0, 0, 0, 0))
            ImageDraw.Draw(sh).rectangle((60, 74, 60 + nw, 74 + nh), fill=(60, 45, 10, 70))
            sh = sh.filter(ImageFilter.GaussianBlur(22))
            b.update(note=note, hb=hb.crop(((W - nw) // 2, 0, (W + nw) // 2, hb.height)),
                     rows=[(r[0] - (W - nw) / 2, r[1], r[2], r[3]) for r in rows], nh=nh, nw=nw, sh=sh)

    jl = gfx.screen("08-journal-list.png")
    cw = 820
    s = cw / jl.width
    jl = jl.resize((cw, int(jl.height * s)), Image.LANCZOS).crop((0, int(330 * s), cw, int(330 * s) + 900))
    jl.putalpha(gfx.round_mask(jl.size, 40))
    jl_sh, jl_pad = gfx.shadow(jl.size, 40, opacity=70)
    proof_cap = gfx.text_block(["Talk for two minutes.", "It writes it up — and names the feeling."],
                               _f("Inter.ttf", 46, "Bold"), INK, spacing=1.25, colors=[INK, INK_SOFT])

    def frame(tt):
        z = 1.0 + 0.035 * (tt / duration)
        cw2, ch2 = int(paper.width / z), int(paper.height / z)
        ox = min(max(0, (paper.width - cw2) / 2 + math.sin(tt * 0.4) * 10), paper.width - cw2)
        oy = min(max(0, (paper.height - ch2) / 2 + math.cos(tt * 0.3) * 12), paper.height - ch2)
        img = paper.crop((int(ox), int(oy), int(ox) + cw2, int(oy) + ch2)).resize((W, H), Image.BILINEAR)

        top_a = 1 - prog(tt, cta_t0 - 0.25, 0.25)
        paste_fade(img, brand, (0, 70), top_a)
        if tt < proof_t0:
            paste_fade(img, emo, ((W - emo.width) / 2, 190), 1.0 if SHORT else ease(prog(tt, 0, 0.25)))

        for b in tl:
            if not (b["t0"] - 0.05 <= tt < b["end"] + 0.3):
                continue
            out_a = 1 - prog(tt, b["end"], 0.25)
            k = b["kind"]
            if k in ("hook", "turn", "name"):
                y0 = 980 - b["th"] / 2
                for w in b["words"]:
                    if tt < w.t0:
                        continue
                    p = prog(tt, w.t0, 0.16)
                    sc = 1 + POP * (1 - ease(p))
                    if getattr(w, "hl", None) is not None:
                        hp = ease(prog(tt, w.t0 + 0.05, 0.25))
                        hl = w.hl.crop((0, 0, max(1, int(w.hl.width * hp)), w.hl.height))
                        paste_fade(img, hl, (w.x - 12, y0 + w.y + w.h * 0.33), out_a)
                    im, dx, dy = scaled(w.img, sc)
                    paste_fade(img, im, (w.x + dx, y0 + w.y + dy), min(1, p * 2.5) * out_a)
            elif k == "line":
                p = prog(tt, b["t0"], max(0.6, b["speak"] * 0.92))
                hb = wipe(b["img"], b["rows"], p)
                y0 = 960 - b["img"].height / 2
                paste_fade(img, hb, (0, y0), out_a)
                up = ease(prog(tt, b["t0"] + b["speak"] * 0.92, 0.35))
                if up > 0:
                    x, tw, ly, lh = b["rows"][-1]
                    ul = b["ul"].crop((0, 0, max(1, int(b["ul"].width * up)), b["ul"].height))
                    paste_fade(img, ul, (x + (tw - b["ul"].width + 40) / 2 - 20, y0 + ly + lh - 18), out_a)
            elif k == "do":
                a_in = ease(prog(tt, b["t0"] - 0.05, 0.3))
                x0 = (W - b["nw"]) / 2
                y0 = 960 - b["nh"] / 2 + (1 - a_in) * 140
                paste_fade(img, b["sh"], (x0 - 60, y0 - 60), a_in * out_a)
                layer = b["note"].copy()
                hb = wipe(b["hb"], b["rows"], prog(tt, b["t0"] + 0.1, max(0.6, b["speak"] * 0.9)))
                layer.alpha_composite(hb, (0, 140))
                rot = layer.rotate(-2.2, resample=Image.BICUBIC, expand=True)
                paste_fade(img, rot, (x0 - (rot.width - b["nw"]) / 2, y0 - (rot.height - b["nh"]) / 2), a_in * out_a)

        if proof_t0 <= tt < cta_t0 + 0.3:
            a = ease(prog(tt, proof_t0, 0.35)) * (1 - prog(tt, cta_t0 - 0.1, 0.3))
            paste_fade(img, proof_cap, (0, 260), a)
            x = (W - jl.width) / 2
            y = 470 + (1 - ease(prog(tt, proof_t0, 0.45))) * 160
            paste_fade(img, jl_sh, (x - jl_pad, y - jl_pad), a)
            paste_fade(img, jl, (x, y), a)
        if tt >= cta_t0:
            gfx.end_card(img, tt, cta_t0)
        img.alpha_composite(grain[int(tt * 12) % len(grain)])
        return img

    mix = gfx.mix_audio([(b["wav"], b["t0"]) for b in tl if b["wav"]], music, duration, workdir / "mix.m4a")
    gfx.encode(frame, duration, out, mix, crf=17, audio_raw=True)
    return out


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 41
    o = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(f"videos/v2-{n:02d}.mp4")
    build(parse_series()[n], o, gfx.ASSETS / "audio" / "03-a-question-for-tomorrow.m4a")
    print(o)
