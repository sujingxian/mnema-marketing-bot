# mnema-marketing-bot

Daily promo videos for Mnema → TikTok / YouTube Shorts / Instagram Reels (/ X) via Buffer.

**This repo must stay public** so Buffer can fetch `raw.githubusercontent.com/.../videos/*.mp4`.
Never commit the Buffer API key. It is passed in as the `BUFFER_API_KEY` env var.

## Daily job
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
