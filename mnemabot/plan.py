"""Content calendar: 4 emotion-series posts, then 1 product post, repeating."""
from __future__ import annotations

from .emotion import parse_series, production_order
from . import feature

# Product videos are paused until they get the v2 (voice + paper) treatment.
PRODUCT_ORDER: list[str] = []

# Format test (marketing/ZERO_COST_AGENT_PLAN.md §二): the day's script is rendered in three formats
# and posted in three TikTok slots. Day d uses formats d, d+2, d+4 (mod n), so over a cycle every
# format appears in every slot once and none always gets the evening slot. Add codes here as new
# renderers land in mnemabot/formats.
ENABLED_FORMATS = ["F1", "F2", "F3"]
SLOT_OFFSETS = (0, 2, 4)


def formats_for_day(day_no: int) -> list[str]:
    n = len(ENABLED_FORMATS)
    return [ENABLED_FORMATS[(day_no + o) % n] for o in SLOT_OFFSETS]
PRODUCT_ORDER_V1 = ["same-thing", "diary", "monthly", "privacy", "weekly", "plan", "insights", "journal"]

SAME_THING_CAPTIONS = {
    "tiktok": "What's the most useless thing an AI has ever said to you? #journaling #aitools #voicejournal #overthinking #buildinpublic",
    "youtube_title": "Every AI journal says the same thing. So I built one that can't. #shorts",
    "youtube_desc": "Most AI journals answer everything with “that sounds really hard.” Mnema isn't allowed to. It remembers last week, notices what you didn't say, and writes the diary for you. Search Mnema on the App Store.",
    "instagram": "Every AI journal says the same thing.\n\nSo I built one that isn't allowed to say it. It remembered last week. It noticed what I didn't say. Then it caught the pattern.\n\nReal conversation, not scripted. Mnema is on the App Store — link in bio.\n\n#journaling #aitools #voicejournal #overthinking #buildinpublic",
    "x": "Every AI journal says “that sounds really hard.” I built one that isn't allowed to. Real conversation, not scripted.",
}


def calendar() -> list[dict]:
    items = parse_series()
    emo = [("emotion", n) for n in production_order(items)]
    prod = [("product", k) for k in PRODUCT_ORDER]
    out, ei, pi = [], 0, 0
    while ei < len(emo) or pi < len(prod):
        for _ in range(4):
            if ei < len(emo):
                out.append(emo[ei]); ei += 1
        if pi < len(prod):
            out.append(prod[pi]); pi += 1
    return [{"kind": k, "key": v} for k, v in out]


def slug(entry: dict) -> str:
    if entry["kind"] == "emotion":
        items = parse_series()
        name = items[entry["key"]]["emotion"].lower().replace(" ", "-")
        return f"emotion-{entry['key']:02d}-{name}"
    return f"product-{entry['key']}"


def captions(entry: dict) -> dict:
    if entry["kind"] == "emotion":
        from .emotion import captions as ec
        return ec(parse_series()[entry["key"]])
    if entry["key"] == "same-thing":
        return SAME_THING_CAPTIONS
    return feature.captions(entry["key"])
