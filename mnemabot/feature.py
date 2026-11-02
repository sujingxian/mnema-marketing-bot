"""Feature showcase template: headline → real app screen (slow scroll) → two beats → end card.

Headlines are the user's own App Store copy; screens are real App Store screenshots.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from . import gfx
from .gfx import W, H, BG, INK, MUTED, GREEN, ease, ease_io, prog, paste_fade, text_block, fit_text, play, inter, mono

FEATURES = {
    "diary": dict(screen="02-six-part-diary.png", top=236, scroll=900,
                  head=["You stop talking.", "The diary is done."],
                  beats=["Talk about your day for two minutes.", "Mnema writes the entry — in six parts, from your own words."],
                  hook="I haven't written a single journal entry in 30 days. I have 30 entries.",
                  tags="#journaling #journalingapp #voicejournal #selfcare #productivity"),
    "weekly": dict(screen="03-weekly-report.png", top=170, scroll=300,
                   head=["Thirty days.", "Not one missed."],
                   beats=["Every Sunday: your week in feelings.", "What visited most. Your brightest day."],
                   hook="This is what 30 days of talking to my journal looks like.",
                   tags="#journaling #moodtracker #selfawareness #habits #wellbeing"),
    "monthly": dict(screen="05-monthly-report.png", top=170, scroll=560,
                    head=["A month becomes", "a pattern."],
                    beats=["Every dot is a day you kept.", "Then it tells you what kind of feeler you are."],
                    hook="My journal told me I'm a Glimmer Seeker. Wrapped, but for feelings.",
                    tags="#wrapped #journaling #moodtracker #selfawareness #emotions"),
    "insights": dict(screen="06-insights-calendar.png", top=170, scroll=520,
                     head=["The longer you go,", "the clearer you get."],
                     beats=["Streaks, mood trends, recurring patterns.", "A situation shows up three times? It notices."],
                     hook="My journal noticed a pattern before I did.",
                     tags="#journaling #selfawareness #mentalwellbeing #habits #moodtracker"),
    "privacy": dict(screen="07-memory-consent.png", top=170, scroll=0, card_h=700,
                    head=["What you write", "stays yours."],
                    beats=["Your diary lives in your own iCloud — not ours.", "Change your mind and it's all erased."],
                    hook="An AI journal that keeps your diary in YOUR iCloud, not theirs.",
                    tags="#privacy #journaling #aitools #iphone #selfcare"),
    "plan": dict(screen="04-habit-diagnosis.png", top=170, scroll=560,
                 head=["This time,", "it sticks."],
                 beats=["Never know what to write? You won't have to.", "Answer a few questions. It writes the entry."],
                 hook="Every journal I've bought died on page 3. Here's why this one didn't.",
                 tags="#journaling #habits #consistency #selfimprovement #productivity"),
    "journal": dict(screen="08-journal-list.png", top=236, scroll=700,
                    head=["Every day", "leaves a trace."],
                    beats=["Every entry, tagged with what you felt.", "Torn. Flattered. Hurt. Relieved. Searchable."],
                    hook="I talk for two minutes a night. This is my journal now.",
                    tags="#journaling #voicejournal #dailyjournal #selfawareness #emotions"),
}


def build(key: str, out: Path, audio: Path) -> Path:
    spec = FEATURES[key]
    scr = gfx.screen(spec["screen"])
    card_w, card_h = 860, spec.get("card_h", 1000)
    s = card_w / scr.width
    full = scr.resize((card_w, int(scr.height * s)), Image.LANCZOS)
    top = int(spec["top"] * s)
    max_scroll = max(0, full.height - top - card_h)
    scroll_px = min(int(spec["scroll"] * s), max_scroll)
    mask = gfx.round_mask((card_w, card_h), 46)
    sh, pad = gfx.shadow((card_w, card_h), 46)

    head = text_block(spec["head"], play(86), INK, colors=[INK, GREEN], spacing=1.14)
    beats = [text_block(gfx.wrap(b, inter(36, "Medium"), 900), inter(36, "Medium"), MUTED, spacing=1.3)
             for b in spec["beats"]]
    brand = Image.new("RGBA", (W, 80), (0, 0, 0, 0))
    brand.alpha_composite(gfx.icon(44), (70, 18))
    from PIL import ImageDraw
    ImageDraw.Draw(brand).text((128, 24), "Mnema", font=inter(30, "Medium"), fill=INK)
    real = text_block(["REAL APP SCREEN"], mono(22), MUTED)

    B1, B2 = 2.2, 5.6
    end_t0 = 9.4
    duration = end_t0 + gfx.END_DUR
    BEAT_Y = 200 + head.height + 14
    CARD_Y = BEAT_Y + 130

    def frame(t):
        img = Image.new("RGBA", (W, H), BG + (255,))
        if t < end_t0 + 0.05:
            out_a = 1 - prog(t, end_t0 - 0.3, 0.3)
            paste_fade(img, brand, (0, 70), ease(prog(t, 0, 0.4)) * out_a)
            p = ease(prog(t, 0.1, 0.5))
            paste_fade(img, head, (0, 200), p * out_a, dy=(1 - p) * 24)
            for i, (bt, lay) in enumerate(zip((B1, B2), beats)):
                end_b = B2 if i == 0 else end_t0
                a = ease(prog(t, bt, 0.35)) * (1 - prog(t, end_b - 0.3, 0.3))
                paste_fade(img, lay, (0, BEAT_Y), a * out_a)
            p = ease(prog(t, 0.6, 0.6))
            sc = int(ease_io(prog(t, 2.0, 6.5)) * scroll_px)
            card = full.crop((0, top + sc, card_w, top + sc + card_h)).copy()
            card.putalpha(mask)
            x = (W - card_w) / 2
            paste_fade(img, sh, (x - pad, CARD_Y - pad + (1 - p) * 120), p * out_a)
            paste_fade(img, card, (x, CARD_Y + (1 - p) * 120), p * out_a)
            paste_fade(img, real, (0, CARD_Y + card_h + 22), p * out_a * 0.9)
        if t >= end_t0:
            gfx.end_card(img, t, end_t0)
        return img

    gfx.encode(frame, duration, out, audio)
    return out


def captions(key: str) -> dict:
    spec = FEATURES[key]
    head = " ".join(spec["head"])
    hook = spec["hook"]
    return {
        "tiktok": f"{hook} {spec['tags']}",
        "youtube_title": f"{hook[:88]} #shorts"[:100],
        "youtube_desc": f"{head} {' '.join(spec['beats'])}\n\nMnema — talk, and the journal writes itself. Search Mnema on the App Store.",
        "instagram": f"{hook}\n\n{head}\n{spec['beats'][0]} {spec['beats'][1]}\n\nMnema is on the App Store — link in bio.\n\n{spec['tags']}",
        "x": f"{hook} {head}"[:270],
    }
