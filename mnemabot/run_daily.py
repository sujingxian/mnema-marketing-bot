"""Daily job (runs in GitHub Actions): render the next video, publish it to the repo, schedule it on every Buffer channel.

    python -m mnemabot.run_daily               # full run (needs BUFFER_API_KEY secret + contents:write)
    python -m mnemabot.run_daily --dry-run     # render + print captions, no git / Buffer
    python -m mnemabot.run_daily --index 7     # force a calendar slot

State lives in state/state.json (committed), so every fresh session picks up where the last left off.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

from . import plan, emotion, emotion_v2, feature, buffer

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state" / "state.json"
VIDEOS = ROOT / "videos"
AUDIO = sorted((ROOT / "assets" / "audio").glob("*.m4a"))
REPO = "sujingxian/mnema-marketing-bot"
BRANCH = "main"
POST_TIME_ET = (19, 30)        # 7:30pm US Eastern — the guide's 19:00–22:00 window
KEEP_DAYS = 21                 # delete repo videos older than this (Buffer has fetched them long before)
SERVICES = {"tiktok", "youtube", "instagram", "twitter", "x"}


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"next_index": 0, "history": []}


def save_state(s: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1, ensure_ascii=False) + "\n")


def next_post_time(now_utc: dt.datetime, history: list | None = None) -> dt.datetime:
    """Next 19:30 ET at least 90 min away, and never on an ET day that already has a post."""
    et = ZoneInfo("America/New_York")
    local = now_utc.astimezone(et)
    cand = local.replace(hour=POST_TIME_ET[0], minute=POST_TIME_ET[1], second=0, microsecond=0)
    if cand - local < dt.timedelta(minutes=90):
        cand += dt.timedelta(days=1)
    used = set()
    for h in history or []:
        if any(r.get("ok") for r in h.get("results", [])):
            used.add(dt.datetime.fromisoformat(h["due"]).astimezone(et).date())
    while cand.date() in used:
        cand += dt.timedelta(days=1)
    return cand.astimezone(dt.timezone.utc)


def render(entry: dict, out: Path, idx: int) -> Path:
    audio = AUDIO[idx % len(AUDIO)]
    if entry["kind"] == "emotion":
        return emotion_v2.build(emotion.parse_series()[entry["key"]], out, audio)
    if entry["key"] == "same-thing":
        shutil.copy(ROOT / "content" / "prerendered" / "same-thing.mp4", out)
        return out
    return feature.build(entry["key"], out, audio)


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
    due = next_post_time(now, state["history"])
    fname = f"{due.astimezone(ZoneInfo('America/New_York')).date().isoformat()}-{slug}.mp4"
    out = VIDEOS / fname

    print(f"slot {idx}: {slug} → {fname}, due {due.isoformat()}")
    render(entry, out, idx)
    print(json.dumps(caps, indent=1, ensure_ascii=False))
    if args.dry_run:
        return

    # publish video file (raw URL needs a public repo)
    cleanup_old()
    git("add", str(out.relative_to(ROOT)))
    git("commit", "-q", "-m", f"video: {fname}")
    git("push", "-q", "origin", BRANCH)
    url = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/videos/{fname}"
    wait_public(url)

    results = []
    for ch in buffer.channels():
        svc = (ch.get("service") or "").lower()
        if svc not in SERVICES or ch.get("isQueuePaused"):
            continue
        try:
            post = buffer.create_post(ch["id"], text_for(svc, caps), url,
                                      due.isoformat().replace("+00:00", "Z"), metadata_for(svc, caps))
            results.append({"service": svc, "ok": True, "post_id": post.get("id")})
        except buffer.BufferError as e:
            results.append({"service": svc, "ok": False, "error": str(e)[:400]})
    print(json.dumps(results, indent=1))

    state["history"].append({"index": idx, "slug": slug, "file": fname, "due": due.isoformat(),
                             "scheduled_at": now.isoformat(), "results": results})
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
