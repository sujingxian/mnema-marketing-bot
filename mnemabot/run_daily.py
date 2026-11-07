"""Daily job (runs in GitHub Actions): render the day's script in three formats, publish the files
to the repo, schedule them on every Buffer channel.

    python -m mnemabot.run_daily                 # full run (needs BUFFER_API_KEY secret + contents:write)
    python -m mnemabot.run_daily --dry-run       # render + print the schedule, no git / Buffer
    python -m mnemabot.run_daily --index 7       # force a calendar slot
    python -m mnemabot.run_daily --formats F2    # override the day's formats (testing)

Format test (marketing/ZERO_COST_AGENT_PLAN.md §二): one script per day, rendered in the formats
plan.formats_for_day() picks, posted to TikTok and YouTube in three slots (08:00 / 13:00 / 19:30
US Eastern) and to Instagram once (the 13:00 slot). Captions are identical, so the format is the
only variable. Which format went out in which slot is recorded in state/state.json — that is how
the weekly analytics join screenshots and YouTube data back to a format.

State lives in state/state.json (committed), so every fresh session picks up where the last left off.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

from . import plan, emotion, feature, buffer
from .formats import FORMATS

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state" / "state.json"
VIDEOS = ROOT / "videos"
AUDIO = sorted((ROOT / "assets" / "audio").glob("*.m4a"))
REPO = "sujingxian/mnema-marketing-bot"
BRANCH = "main"
ET = ZoneInfo("America/New_York")
SLOTS_ET = [(8, 0), (13, 0), (19, 30)]   # morning commute, lunch, evening (the guide's 19:00–22:00 window)
IG_SLOT = 1                              # Instagram gets one post a day
MIN_LEAD = dt.timedelta(minutes=90)      # Buffer needs time to fetch the file before the first slot
KEEP_DAYS = 21                           # delete repo videos older than this (Buffer has fetched them long before)
SERVICES = {"tiktok", "youtube", "instagram", "twitter", "x"}


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"next_index": 0, "history": []}


def save_state(s: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1, ensure_ascii=False) + "\n")


def used_days(history: list | None) -> set[dt.date]:
    """ET days that already have at least one successfully scheduled post."""
    used = set()
    for h in history or []:
        if not any(r.get("ok") for r in h.get("results", [])):
            continue
        if h.get("post_day"):
            used.add(dt.date.fromisoformat(h["post_day"]))
        else:  # entries written before the format test: one post at 19:30 ET
            used.add(dt.datetime.fromisoformat(h["due"]).astimezone(ET).date())
    return used


def next_post_day(now_utc: dt.datetime, history: list | None = None) -> dt.date:
    """The next ET day whose *first* slot is still ≥ 90 min away and that has no posts yet."""
    local = now_utc.astimezone(ET)
    day = local.date()
    first = dt.datetime.combine(day, dt.time(*SLOTS_ET[0]), tzinfo=ET)
    if first - local < MIN_LEAD:
        day += dt.timedelta(days=1)
    used = used_days(history)
    while day in used:
        day += dt.timedelta(days=1)
    return day


def slot_time(day: dt.date, slot: int) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(*SLOTS_ET[slot]), tzinfo=ET).astimezone(dt.timezone.utc)


def slots_for(service: str, n_slots: int) -> list[int]:
    if service in ("tiktok", "youtube"):
        return list(range(n_slots))
    if service == "instagram":
        return [min(IG_SLOT, n_slots - 1)]
    return [n_slots - 1]                 # x / twitter: evening only


def render(entry: dict, fmt: str, out: Path, idx: int) -> Path:
    music = AUDIO[idx % len(AUDIO)]      # same music for every format of the day — not a variable
    if entry["kind"] == "emotion":
        item = emotion.parse_series()[entry["key"]]
        return FORMATS[fmt].build(item, out, music, Path(tempfile.mkdtemp()))
    if entry["key"] == "same-thing":
        shutil.copy(ROOT / "content" / "prerendered" / "same-thing.mp4", out)
        return out
    return feature.build(entry["key"], out, music)


def git(*args):
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def wait_public(url: str, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(10)
    raise RuntimeError(f"video never became public: {url} (is the repo public?)")


def metadata_for(service: str, caps: dict) -> dict | None:
    """Per-network extras. Field names verified against the live schema (see README)."""
    if service == "youtube":
        return {"youtube": {"title": caps["youtube_title"], "categoryId": "22", "privacy": "public",
                            "madeForKids": False, "notifySubscribers": True, "embeddable": True}}
    if service == "instagram":
        return {"instagram": {"type": "reel", "shouldShareToFeed": True}}
    return None


def text_for(service: str, caps: dict) -> str:
    return {"tiktok": caps["tiktok"], "youtube": caps["youtube_desc"], "instagram": caps["instagram"],
            "twitter": caps["x"], "x": caps["x"]}[service]


def cleanup_old():
    cutoff = dt.date.today() - dt.timedelta(days=KEEP_DAYS)
    for f in VIDEOS.glob("*.mp4"):
        try:
            d = dt.date.fromisoformat(f.name[:10])
        except ValueError:
            continue
        if d < cutoff:
            git("rm", "-q", str(f.relative_to(ROOT)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--index", type=int)
    ap.add_argument("--formats", help="comma-separated format codes, e.g. F2 or F1,F2,F3")
    args = ap.parse_args()

    cal = plan.calendar()
    state = load_state()
    idx = args.index if args.index is not None else state["next_index"]
    if idx >= len(cal):
        print(f"WARNING: calendar exhausted ({len(cal)} slots) — looping. Add fresh content.")
    entry = cal[idx % len(cal)]
    slug = plan.slug(entry)
    caps = plan.captions(entry)
    now = dt.datetime.now(dt.timezone.utc)
    day = next_post_day(now, state["history"])

    if entry["kind"] == "emotion":
        formats = args.formats.split(",") if args.formats else plan.formats_for_day(idx)
        for f in formats:
            if f not in FORMATS:
                raise SystemExit(f"unknown format {f}; known: {', '.join(FORMATS)}")
        # a day with fewer formats than slots uses the last slots (evening first)
        slot_of = {i: s for i, s in enumerate(range(len(SLOTS_ET) - len(formats), len(SLOTS_ET)))}
    else:
        formats = ["product"]
        slot_of = {0: len(SLOTS_ET) - 1}

    videos = []
    for i, fmt in enumerate(formats):
        fname = f"{day.isoformat()}-{slug}-{fmt.lower()}.mp4"
        due = slot_time(day, slot_of[i])
        print(f"slot {idx}: {slug} [{fmt}] → {fname}, due {due.astimezone(ET).strftime('%a %H:%M ET')}")
        render(entry, fmt, VIDEOS / fname, idx)
        videos.append({"format": fmt, "slot": slot_of[i], "file": fname, "due": due})
    print(json.dumps(caps, indent=1, ensure_ascii=False))
    if args.dry_run:
        return

    # publish video files (raw URL needs a public repo)
    cleanup_old()
    for v in videos:
        git("add", f"videos/{v['file']}")
    git("commit", "-q", "-m", f"video: {day.isoformat()} {slug} ({', '.join(formats)})")
    git("push", "-q", "origin", BRANCH)
    for v in videos:
        v["url"] = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/videos/{v['file']}"
        wait_public(v["url"])

    results = []
    by_slot = {v["slot"]: v for v in videos}
    for ch in buffer.channels():
        svc = (ch.get("service") or "").lower()
        if svc not in SERVICES or ch.get("isQueuePaused"):
            continue
        for s in slots_for(svc, len(SLOTS_ET)):
            v = by_slot.get(s)
            if v is None:
                continue
            due_iso = v["due"].isoformat().replace("+00:00", "Z")
            try:
                post = buffer.create_post(ch["id"], text_for(svc, caps), v["url"], due_iso, metadata_for(svc, caps))
                results.append({"service": svc, "format": v["format"], "slot": s, "ok": True, "post_id": post.get("id")})
            except buffer.BufferError as e:
                results.append({"service": svc, "format": v["format"], "slot": s, "ok": False, "error": str(e)[:400]})
    print(json.dumps(results, indent=1))

    state["history"].append({
        "index": idx, "slug": slug, "post_day": day.isoformat(),
        "file": videos[0]["file"], "due": videos[0]["due"].isoformat(),   # kept for older tooling
        "scheduled_at": now.isoformat(),
        "videos": [{**v, "due": v["due"].isoformat()} for v in videos],
        "results": results,
    })
    if any(r["ok"] for r in results):
        state["next_index"] = idx + 1
    save_state(state)
    git("add", "state/state.json")
    git("commit", "-q", "-m", f"state: slot {idx} {slug}")
    git("push", "-q", "origin", BRANCH)
    if not all(r["ok"] for r in results):
        raise SystemExit("some channels failed — see results above")


if __name__ == "__main__":
    main()
