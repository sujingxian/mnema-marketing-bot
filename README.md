# mnema-marketing-bot

Daily promo videos for Mnema → TikTok / YouTube Shorts / Instagram Reels (/ X) via Buffer.

**This repo must stay public** so Buffer can fetch `raw.githubusercontent.com/.../videos/*.mp4`.
Never commit the Buffer API key. It is passed in as the `BUFFER_API_KEY` env var.

## Daily job
Runs in GitHub Actions (`.github/workflows/daily.yml`) at 20:17 UTC. Secret: `BUFFER_API_KEY`.
Manual: Actions → daily-post → Run workflow (mode `run` / `dry` / `diag`).

```
pip install -r requirements.txt      # + ffmpeg on PATH
BUFFER_API_KEY=... python -m mnemabot.run_daily
```
1. Picks the next slot from `mnemabot/plan.py` (4 emotion-series posts, then 1 product post; 66 slots).
2. Renders `videos/<ET date>-<slug>.mp4` (1080×1920, ~20–27s).
3. Commits + pushes the video, waits for the raw URL to go live.
4. Schedules it on every connected Buffer channel for 19:30 US Eastern.
5. Records the result in `state/state.json` and pushes. Videos older than 21 days are deleted.

`--dry-run` renders and prints captions only; `--index N` forces a slot.

## Content rules (from TIKTOK_SCRIPTS_EN.md / EMOTION_SERIES_EN.md)
- Emotion scripts: `content/EMOTION_SERIES_EN.md` (user's own copy). #43 Despair and #45 Grief are never auto-posted.
- Product videos only show real app screens (`assets/screens`) and the user's App Store headlines.
- No fabricated AI replies, no clinical / therapy claims.

## Buffer helpers
```
python -m mnemabot.buffer channels   # connected channels
python -m mnemabot.buffer schema     # CreatePostInput + metadata types (verify field names)
```

## Format test (since 2026-11-08)

Posts were watched for ~2 s on average (0–2 % completion) at 20–24 s, so the daily job now renders
the day's script in **three formats** (`mnemabot/formats/`) and posts them in three TikTok slots
(08:00 / 13:00 / 19:30 US Eastern); YouTube gets all three, Instagram the 13:00 one. Captions are
identical — the format is the only variable. `plan.ENABLED_FORMATS` + `plan.formats_for_day()` decide
the rotation; `state/state.json` records which format went out in which slot.

| code | look | voice |
|---|---|---|
| F1 `paper-voice` | paper, kinetic words, handwritten LINE (`emotion_v2`, short) | yes |
| F2 `ink-serif` | black quote card, Playfair, one beat per screen | music only |
| F3 `kinetic-bold` | black, Inter Black, words pop in with the voice | yes |

Add a renderer to `mnemabot/formats/`, register it in `FORMATS`, append its code to `ENABLED_FORMATS`.
`MNEMA_FORMAT=full` restores the old long F1 timeline (NAME + DO + proof card + end card).

## Weekly analytics

`.github/workflows/analytics.yml` (Sunday 21:30 UTC) runs `mnemabot.yt_analytics`, which pulls
views / average view duration / average view % per Short from the YouTube Analytics API, joins them to
the format via `state.json`, and writes `analytics/youtube.csv` + `analytics/youtube_by_format.md`.
YouTube is the measurement channel because it is the only one with a free analytics API.

Setup once: `python3 scripts/yt_auth.py` (instructions in the file), then add `YT_CLIENT_ID`,
`YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` as repository secrets. Without them the workflow exits quietly.
