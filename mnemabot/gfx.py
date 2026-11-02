"""Shared drawing helpers for Mnema promo videos (1080x1920, 30fps)."""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"
W, H, FPS = 1080, 1920, 30

BG = (243, 239, 232)
INK = (28, 28, 26)
MUTED = (128, 124, 116)
GREEN = (78, 106, 87)

_font_cache: dict = {}


def play(size: int, weight: str = "SemiBold") -> ImageFont.FreeTypeFont:
    key = ("play", size, weight)
    if key not in _font_cache:
        f = ImageFont.truetype(str(FONTS / "PlayfairDisplay.ttf"), size)
        f.set_variation_by_name(weight)
        _font_cache[key] = f
    return _font_cache[key]


def inter(size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    key = ("inter", size, weight)
    if key not in _font_cache:
        f = ImageFont.truetype(str(FONTS / "Inter.ttf"), size)
        try:
            f.set_variation_by_name(weight)
        except Exception:
            pass
        _font_cache[key] = f
    return _font_cache[key]


def mono(size: int) -> ImageFont.FreeTypeFont:
    key = ("mono", size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(str(FONTS / "DMMono-Regular.ttf"), size)
    return _font_cache[key]


# ---------- easing ----------
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_io(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def prog(t, start, dur):
    return clamp((t - start) / dur) if dur > 0 else float(t >= start)


# ---------- text ----------
_measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))


def wrap(text: str, font, max_w: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if _measure.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_text(text, font_fn, max_w, max_h, start=110, minimum=44, spacing=1.2):
    """Largest font size whose wrapped text fits the box."""
    size = start
    while size >= minimum:
        f = font_fn(size)
        lines = wrap(text, f, max_w)
        asc, desc = f.getmetrics()
        h = int((asc + desc) * spacing) * len(lines)
        if h <= max_h:
            return f, lines
        size -= 4
    f = font_fn(minimum)
    return f, wrap(text, f, max_w)


def text_block(lines, font, fill, width=W, spacing=1.2, align="center", colors=None):
    asc, desc = font.getmetrics()
    lh = int((asc + desc) * spacing)
    img = Image.new("RGBA", (width, lh * len(lines) + desc + 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, ln in enumerate(lines):
        tw = d.textlength(ln, font=font)
        x = (width - tw) / 2 if align == "center" else 0
        d.text((x, i * lh), ln, font=font, fill=(colors[i] if colors else fill))
    return img


def paste_fade(base, layer, xy, alpha, dy=0):
    if alpha <= 0.002:
        return
    lay = layer
    if alpha < 0.998:
        lay = layer.copy()
        lay.putalpha(lay.getchannel("A").point(lambda v: int(v * alpha)))
    base.alpha_composite(lay, (int(xy[0]), int(xy[1] + dy)))


def round_mask(size, r):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), r, fill=255)
    return m


def shadow(size, r, blur=40, opacity=60, color=(60, 50, 30)):
    pad = blur * 2
    s = Image.new("RGBA", (size[0] + pad * 2, size[1] + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(s).rounded_rectangle((pad, pad + 14, pad + size[0], pad + size[1] + 14), r,
                                        fill=color + (opacity,))
    return s.filter(ImageFilter.GaussianBlur(blur)), pad


def icon(size: int) -> Image.Image:
    im = Image.open(ASSETS / "icon.png").convert("RGBA").resize((size, size), Image.LANCZOS)
    im.putalpha(round_mask((size, size), int(size * 0.225)))
    return im


def screen(name: str) -> Image.Image:
    return Image.open(ASSETS / "screens" / name).convert("RGBA")


def end_card(img, t, t0, dark=False):
    """Shared end card: icon, Mnema, tagline, App Store pill."""
    ink = (245, 242, 236) if dark else INK
    sub = (170, 166, 158) if dark else MUTED
    fade_out = 1 - prog(t, t0 + 3.0, 0.4)
    p0 = ease(prog(t, t0, 0.45))
    paste_fade(img, icon(200), ((W - 200) / 2, 600), p0 * fade_out, dy=(1 - p0) * 30)
    paste_fade(img, text_block(["Mnema"], play(88), ink), (0, 840), ease(prog(t, t0 + 0.2, 0.4)) * fade_out)
    lay = Image.new("RGBA", (W, 100), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    f = play(60, "Regular")
    a, b = "Talk. Journal. ", "Done."
    wa, wb = d.textlength(a, font=f), d.textlength(b, font=f)
    x = (W - wa - wb) / 2
    d.text((x, 0), a, font=f, fill=ink)
    d.text((x + wa, 0), b, font=f, fill=(140, 176, 150) if dark else GREEN)
    paste_fade(img, lay, (0, 975), ease(prog(t, t0 + 0.45, 0.4)) * fade_out)
    paste_fade(img, text_block(["Voice journal with an AI that remembers"], inter(32), sub), (0, 1085),
               ease(prog(t, t0 + 0.65, 0.4)) * fade_out)
    pill = Image.new("RGBA", (740, 88), (0, 0, 0, 0))
    ImageDraw.Draw(pill).rounded_rectangle((0, 0, 739, 87), 44, outline=ink, width=3)
    lbl = text_block(["SEARCH “MNEMA” ON THE APP STORE"], mono(27), ink, width=740)
    pill.alpha_composite(lbl, (0, 26))
    paste_fade(img, pill, ((W - 740) / 2, 1190), ease(prog(t, t0 + 0.9, 0.4)) * fade_out)


END_DUR = 3.2


def encode(frame_fn, duration: float, out: Path, audio: Path, crf=20, audio_raw=False):
    """Pipe frames into ffmpeg, mux a looped/trimmed audio bed with fades."""
    n = int(round(duration * FPS))
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           *(["-i", str(audio)] if audio_raw else ["-stream_loop", "-1", "-i", str(audio)]),
           *([] if audio_raw else ["-af", f"afade=t=in:st=0:d=0.4,afade=t=out:st={max(0, duration - 1.2):.2f}:d=1.2"]),
           "-t", f"{duration:.2f}", "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p", "-tune", "animation",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n):
        p.stdin.write(frame_fn(i / FPS).convert("RGB").tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    return out
