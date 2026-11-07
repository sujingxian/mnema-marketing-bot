"""Weekly pull of per-video YouTube Shorts metrics → analytics/youtube.csv (+ a per-format summary).

The same file is posted to TikTok, Instagram and YouTube, and YouTube is the only one of the three
with a free analytics API — so YouTube's average view duration / percentage is the automatic
measurement for the format test. TikTok and Instagram numbers come from screenshots read by the
Monday routine.

    python -m mnemabot.yt_analytics            # needs YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN
    python -m mnemabot.yt_analytics --days 45  # look further back (default 35)

One-time setup: scripts/yt_auth.py prints the refresh token; put the three values in the repo's
Actions secrets. Standard library only, no Google SDK.

YouTube Analytics lags about 2–3 days, so the most recent videos always show low numbers; the
summary only counts videos published ≥ 3 days before the pull.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state" / "state.json"
OUT_CSV = ROOT / "analytics" / "youtube.csv"
OUT_MD = ROOT / "analytics" / "youtube_by_format.md"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DATA = "https://www.googleapis.com/youtube/v3"
ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
MATCH_WINDOW = dt.timedelta(minutes=25)   # Buffer publishes within a few minutes of the due time
SETTLE_DAYS = 3


def access_token() -> str:
    cid, sec, rt = (os.environ.get(k, "").strip() for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))
    if not (cid and sec and rt):
        raise SystemExit("YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN not set — skipping YouTube analytics")
    body = urllib.parse.urlencode({"client_id": cid, "client_secret": sec, "refresh_token": rt,
                                   "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body), timeout=30) as r:
        return json.loads(r.read())["access_token"]


def get(url: str, params: dict, tok: str) -> dict:
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}",
                                 headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{url}: HTTP {e.code} {e.read()[:300]!r}") from None


def recent_videos(tok: str, days: int) -> list[dict]:
    ch = get(f"{DATA}/channels", {"part": "contentDetails", "mine": "true"}, tok)
    uploads = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    out, page = [], None
    while True:
        params = {"part": "snippet,contentDetails", "playlistId": uploads, "maxResults": 50}
        if page:
            params["pageToken"] = page
        res = get(f"{DATA}/playlistItems", params, tok)
        for it in res.get("items", []):
            pub = dt.datetime.fromisoformat(it["contentDetails"]["videoPublishedAt"].replace("Z", "+00:00"))
            if pub < cutoff:
                return out
            out.append({"id": it["contentDetails"]["videoId"], "title": it["snippet"]["title"], "published_at": pub})
        page = res.get("nextPageToken")
        if not page:
            return out


def metrics(tok: str, ids: list[str], start: dt.date, end: dt.date) -> dict[str, dict]:
    out = {}
    for i in range(0, len(ids), 200):
        chunk = ids[i:i + 200]
        res = get(ANALYTICS, {
            "ids": "channel==MINE", "startDate": start.isoformat(), "endDate": end.isoformat(),
            "metrics": "views,averageViewDuration,averageViewPercentage,likes,comments,shares",
            "dimensions": "video", "filters": "video==" + ",".join(chunk), "maxResults": 200, "sort": "-views",
        }, tok)
        cols = [c["name"] for c in res.get("columnHeaders", [])]
        for row in res.get("rows", []):
            rec = dict(zip(cols, row))
            out[rec["video"]] = rec
    return out


def posted_videos() -> list[dict]:
    """Every YouTube post the bot scheduled, with its format and slot (from state.json)."""
    if not STATE.exists():
        return []
    posts = []
    for h in json.loads(STATE.read_text()).get("history", []):
        videos = h.get("videos") or [{"format": "legacy", "slot": 2, "file": h.get("file"), "due": h.get("due")}]
        by_slot = {v["slot"]: v for v in videos}
        for r in h.get("results", []):
            if r.get("service") != "youtube" or not r.get("ok"):
                continue
            v = by_slot.get(r.get("slot", 2))
            if not v:
                continue
            posts.append({"slug": h["slug"], "post_day": h.get("post_day") or v["file"][:10],
                          "format": v["format"], "slot": v["slot"], "file": v["file"],
                          "due": dt.datetime.fromisoformat(v["due"])})
    return posts


def match(videos: list[dict], posts: list[dict]) -> None:
    """Attach slug/format/slot to each YouTube video by publish time (same-day titles are identical)."""
    free = list(posts)
    for v in sorted(videos, key=lambda x: x["published_at"]):
        best = min(free, key=lambda p: abs(p["due"] - v["published_at"]), default=None)
        if best and abs(best["due"] - v["published_at"]) <= MATCH_WINDOW:
            v.update(slug=best["slug"], post_day=best["post_day"], format=best["format"], slot=best["slot"])
            free.remove(best)
        else:
            v.update(slug="", post_day=v["published_at"].date().isoformat(), format="", slot="")


def summary(rows: list[dict], now: dt.datetime) -> str:
    settled = [r for r in rows if r["format"] and (now - r["published_at"]).days >= SETTLE_DAYS]
    by_fmt: dict[str, list[dict]] = {}
    for r in settled:
        by_fmt.setdefault(r["format"], []).append(r)
    lines = [f"# YouTube Shorts by format — pulled {now.date().isoformat()}", "",
             f"Videos published ≥ {SETTLE_DAYS} days ago only (Analytics lags). Same files as TikTok / Instagram.", "",
             "| format | videos | avg view % | avg view s | views/video | likes | comments |", "|---|---:|---:|---:|---:|---:|---:|"]
    for fmt, rs in sorted(by_fmt.items(), key=lambda kv: -statistics.mean(float(r["avg_view_pct"] or 0) for r in kv[1])):
        lines.append(f"| {fmt} | {len(rs)} | {statistics.mean(float(r['avg_view_pct'] or 0) for r in rs):.1f}% "
                     f"| {statistics.mean(float(r['avg_view_duration_s'] or 0) for r in rs):.1f} "
                     f"| {statistics.mean(float(r['views'] or 0) for r in rs):.0f} "
                     f"| {sum(int(r['likes'] or 0) for r in rs)} | {sum(int(r['comments'] or 0) for r in rs)} |")
    if not by_fmt:
        lines.append("| — | 0 | | | | | |")
    lines += ["", "Top 5 videos by average view %:", ""]
    for r in sorted(settled, key=lambda r: -float(r["avg_view_pct"] or 0))[:5]:
        lines.append(f"- {r['post_day']} {r['slug']} [{r['format']} slot {r['slot']}] — "
                     f"{float(r['avg_view_pct'] or 0):.0f}% · {float(r['avg_view_duration_s'] or 0):.1f}s · {r['views']} views")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=35)
    args = ap.parse_args()
    try:
        tok = access_token()
    except SystemExit as e:
        print(e)
        return 0
    now = dt.datetime.now(dt.timezone.utc)
    videos = recent_videos(tok, args.days)
    if not videos:
        print("no uploads in window")
        return 0
    match(videos, posted_videos())
    m = metrics(tok, [v["id"] for v in videos], now.date() - dt.timedelta(days=args.days + 1), now.date())
    rows = []
    for v in videos:
        r = m.get(v["id"], {})
        rows.append({
            "video_id": v["id"], "published_at": v["published_at"], "title": v["title"],
            "post_day": v["post_day"], "slug": v["slug"], "format": v["format"], "slot": v["slot"],
            "views": r.get("views", 0), "avg_view_duration_s": r.get("averageViewDuration", 0),
            "avg_view_pct": r.get("averageViewPercentage", 0), "likes": r.get("likes", 0),
            "comments": r.get("comments", 0), "shares": r.get("shares", 0), "fetched_at": now.isoformat(timespec="seconds"),
        })
    OUT_CSV.parent.mkdir(exist_ok=True)
    with OUT_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow({**r, "published_at": r["published_at"].isoformat(timespec="seconds")})
    OUT_MD.write_text(summary(rows, now))
    print(OUT_MD.read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
