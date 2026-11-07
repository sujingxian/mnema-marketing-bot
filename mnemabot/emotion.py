"""Emotion-series template: HOOK → TURN → NAME → LINE → DO (→ LOOP) → tag proof → end card.

Scripts come from content/EMOTION_SERIES_EN.md (the user's own copy).
"""
from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from . import gfx
from .gfx import W, H, ease, prog, paste_fade, text_block, fit_text, play, inter, mono

ROOT = Path(__file__).resolve().parent.parent
SERIES = ROOT / "content" / "EMOTION_SERIES_EN.md"
GENERATED = ROOT / "content" / "generated"   # weekly AI-written batches, same format

# Never auto-post these: they need a helpline card / special treatment (see series notes).
EXCLUDE = {43, 45}


def parse_series(path: Path = SERIES) -> dict[int, dict]:
    text = path.read_text(encoding="utf-8")
    if path == SERIES and GENERATED.exists():
        for g in sorted(GENERATED.glob("*.md")):
            text += "\n\n" + g.read_text(encoding="utf-8")
    items: dict[int, dict] = {}
    cluster, color = None, None
    cur = None
    key = None
    for raw in text.splitlines():
        m = re.match(r"^# CLUSTER \d+ · (.+?)\s+`(#[0-9A-Fa-f]{6})`", raw)
        if m:
            cluster, color = m.group(1).strip(), m.group(2)
            continue
        m = re.match(r"^### (\d+) (.+?)(?: — (.*))?$", raw)
        if m:
            num = int(m.group(1))
            cur = {"num": num, "emotion": m.group(2).strip(), "meta": (m.group(3) or "").strip(),
                   "cluster": cluster, "color": color}
            items[num] = cur
            key = None
            continue
        if raw.startswith("# ") or raw.startswith("---"):
            cur, key = (None if raw.startswith("# ") else cur), None
            continue
        if cur is None:
            continue
        m = re.match(r"^- \*\*([A-Z]+)\*\* (.*)$", raw)
        if m:
            key = m.group(1).lower()
            cur[key] = m.group(2).strip()
        elif key and raw.startswith("  ") and raw.strip():
            cur[key] += " " + raw.strip()
    return items


def production_order(items: dict[int, dict], path: Path = SERIES) -> list[int]:
    """Weeks listed under '# Production order' first, then the rest in table order."""
    text = path.read_text(encoding="utf-8")
    first = []
    for m in re.finditer(r"^Week \d+ — ([\d, ]+)$", text, re.M):
        first += [int(x) for x in m.group(1).split(",")]
    rest = [n for n in sorted(items) if n not in first]
    return [n for n in first + rest if n not in EXCLUDE and n in items]


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _beat_dur(text: str, extra=0.0) -> float:
    return max(2.0, 0.85 + 0.26 * len(text.split()) + extra)


def _clean(s: str) -> str:
    s = s.replace("*", "").strip()
    # straight double quotes -> curly pairs
    out, open_q = [], True
    for ch in s:
        if ch == '"':
            out.append("“" if open_q else "”")
            open_q = not open_q
        else:
            out.append(ch)
    return "".join(out).replace("'", "’")


def build(item: dict, out: Path, audio: Path) -> Path:
    accent = _hex(item.get("color") or "#4E6A57")
    bg = tuple(int(14 + c * 0.06) for c in accent)
    ink = (245, 242, 236)
    sub = (168, 164, 156)
    soft_accent = tuple(min(255, int(c * 0.55 + 255 * 0.45)) for c in accent)

    beats = []  # (kind, text)
    for k in ("hook", "turn", "name", "line", "do", "loop"):
        if item.get(k):
            beats.append((k, _clean(item[k])))

    # timeline
    t = 0.25
    timeline = []
    for kind, txt in beats:
        d = _beat_dur(txt, extra=0.45 if kind in ("line", "do") else 0.0)
        timeline.append((kind, txt, t, d))
        t += d
    proof_t0 = t
    proof_d = 2.7
    end_t0 = proof_t0 + proof_d
    duration = end_t0 + gfx.END_DUR

    # pre-render beat layers
    BOX_W, BOX_H = 860, 640
    layers = []
    for kind, txt, t0, d in timeline:
        if kind == "line":
            q = txt.strip()
            f, lines = fit_text(q, lambda s: play(s, "SemiBold"), BOX_W, BOX_H, start=96, minimum=48)
            lay = text_block(lines, f, soft_accent, spacing=1.22)
        elif kind == "hook":
            f, lines = fit_text(txt, lambda s: play(s, "Bold"), BOX_W, BOX_H, start=104, minimum=52)
            lay = text_block(lines, f, ink, spacing=1.18)
        elif kind == "do":
            f, lines = fit_text(txt, lambda s: inter(s, "Medium"), BOX_W, BOX_H - 120, start=72, minimum=40)
            lay = text_block(lines, f, ink, spacing=1.35)
        elif kind == "loop":
            f, lines = fit_text(txt, lambda s: play(s, "Regular"), BOX_W, BOX_H, start=80, minimum=44)
            lay = text_block(lines, f, sub, spacing=1.22)
        else:
            f, lines = fit_text(txt, lambda s: play(s, "Regular"), BOX_W, BOX_H, start=84, minimum=46)
            lay = text_block(lines, f, ink, spacing=1.22)
        layers.append(lay)

    label_do = text_block(["TRY THIS — 60 SECONDS"], mono(28), soft_accent)
    emo_label = text_block([item["emotion"].upper()], mono(30), sub)
    brand = Image.new("RGBA", (W, 80), (0, 0, 0, 0))
    brand.alpha_composite(gfx.icon(44), (70, 18))
    ImageDraw.Draw(brand).text((128, 24), "Mnema", font=inter(30, "Medium"), fill=ink)

    # glow background
    base = Image.new("RGBA", (W, H), bg + (255,))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((-200, 300, W + 200, 1500), fill=accent + (70,))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(220)))

    # tag-proof card: real journal list screenshot (emotion tags on real entries)
    jl = gfx.screen("08-journal-list.png")
    card_w = 900
    s = card_w / jl.width
    jl = jl.resize((card_w, int(jl.height * s)), Image.LANCZOS)
    card = jl.crop((0, int(330 * s), card_w, int(330 * s) + 980))
    card.putalpha(gfx.round_mask(card.size, 44))
    sh, pad = gfx.shadow(card.size, 44, opacity=120, color=(0, 0, 0))
    proof_cap = text_block(["Every entry, named for you."], play(64), ink)
    proof_sub = text_block(["Talk for two minutes. Mnema writes it up and tags what you felt."],
                           inter(30), sub, width=W)

    def frame(tt: float) -> Image.Image:
        img = base.copy()
        if tt < end_t0:
            fade_bar = 1 - prog(tt, end_t0 - 0.3, 0.3)
            paste_fade(img, brand, (0, 70), ease(prog(tt, 0, 0.4)) * fade_bar)
        if tt < proof_t0 + 0.3:
            paste_fade(img, emo_label, (0, 210), ease(prog(tt, 0.1, 0.4)) * (1 - prog(tt, proof_t0 - 0.2, 0.3)))
        for (kind, txt, t0, d), lay in zip(timeline, layers):
            if t0 - 0.05 <= tt < t0 + d + 0.05:
                a_in = ease(prog(tt, t0, 0.35))
                a_out = 1 - prog(tt, t0 + d - 0.28, 0.28)
                y = 960 - lay.height / 2
                if kind == "do":
                    paste_fade(img, label_do, (0, y - 90), a_in * a_out)
                paste_fade(img, lay, (0, y), a_in * a_out, dy=(1 - a_in) * 26)
        if proof_t0 <= tt < end_t0 + 0.05:
            a_in = ease(prog(tt, proof_t0, 0.4))
            a_out = 1 - prog(tt, end_t0 - 0.3, 0.3)
            paste_fade(img, proof_cap, (0, 300), a_in * a_out)
            paste_fade(img, proof_sub, (0, 400), a_in * a_out)
            x = (W - card_w) / 2
            paste_fade(img, sh, (x - pad, 520 - pad + (1 - a_in) * 80), a_in * a_out)
            paste_fade(img, card, (x, 520 + (1 - a_in) * 80), a_in * a_out)
        if tt >= end_t0:
            gfx.end_card(img, tt, end_t0, dark=True)
        return img

    gfx.encode(frame, duration, out, audio)
    return out


def captions(item: dict) -> dict:
    emo = item["emotion"]
    hook = _clean(item.get("hook", ""))
    line = _clean(item.get("line", "")).strip("“”\"")
    do = _clean(item.get("do", ""))
    tag = re.sub(r"[^a-z]", "", emo.lower())
    tiktok = (f"{hook.rstrip('—-').strip()} "
              f"#{tag} #feelings #emotionalintelligence #overthinking #selfawareness")
    yt_title = f"{emo}: what it's actually asking for #shorts"[:100]
    yt_desc = (f"{hook} {_clean(item.get('turn',''))} {_clean(item.get('name',''))}\n\n"
               f"Try this: {do}\n\nMnema — a voice journal that names what you feel. Search Mnema on the App Store.")
    insta = (f"{hook}\n\n“{line}”\n\nTry this: {do}\n\n"
             f"Mnema turns two minutes of talking into a journal entry and tags what you felt. Link in bio.\n\n"
             f"#{tag} #emotions #selfawareness #journaling #emotionalintelligence #feelings")
    x = f"{hook} “{line}” Try this: {do}"
    if len(x) > 270:
        x = f"{hook} “{line}”"[:270]
    return {"tiktok": tiktok, "youtube_title": yt_title, "youtube_desc": yt_desc,
            "instagram": insta, "x": x}
