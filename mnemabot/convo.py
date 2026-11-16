"""Real-conversation posts: one first-person line → Mnema's real, unedited reply → chat video.

The reply is fetched live from the production backend with a dedicated bot account
(secret MNEMA_BOT_LOGIN = "email:password"), and saved verbatim with its request to
content/convos/<date>-<id>.json before anything is rendered. Nothing in the reply is ever
rewritten: a reply that fails the quality gate is discarded and a fresh session is tried.

    python -m mnemabot.convo fetch c07          # fetch + save (needs the secret)
    python -m mnemabot.convo render <json> out.mp4
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

from . import gfx
from .gfx import H, W, inter, mono, play

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ROOT / "content" / "convo_scenarios.md"
CONVOS = ROOT / "content" / "convos"
API = os.environ.get("MNEMA_API", "https://backend-lively-butterfly-3415.fly.dev/api").rstrip("/")

# Lines the companion prompt already bans; if one slips through we don't post it.
BANNED_OPENERS = re.compile(r"^\s*(i hear|it sounds|that sounds|that must|i'?m sorry|i can imagine|i understand)", re.I)


class ConvoError(RuntimeError):
    pass


# ---------------------------------------------------------------- scenarios
def scenarios() -> list[tuple[str, str]]:
    out = []
    for raw in SCENARIOS.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^- (c\d+) \| (.+)$", raw.strip())
        if m:
            out.append((m.group(1), m.group(2).strip()))
    return out


# ---------------------------------------------------------------- backend
def _req(path, body=None, token=None, method="POST"):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", "User-Agent": "mnema-marketing-bot"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:  # noqa: BLE001
            return e.code, {}


def _token() -> str:
    login = os.environ.get("MNEMA_BOT_LOGIN", "")
    if ":" not in login:
        raise ConvoError("MNEMA_BOT_LOGIN secret is not set (format email:password)")
    email, password = login.split(":", 1)
    code, data = _req("/auth/login", {"email": email, "password": password})
    if code == 200:
        return data.get("accessToken") or data["access_token"]
    if code in (400, 401, 404):
        code, data = _req("/auth/register", {"email": email, "password": password, "first_name": "Content",
                                             "last_name": "Bot", "preferred_name": "Sam"})
        if code in (200, 201):
            return data.get("accessToken") or data["access_token"]
    raise ConvoError(f"login failed: HTTP {code} {str(data)[:200]}")


def gate(reply: str) -> str | None:
    """Return a reason to reject, or None if the reply can be posted as-is."""
    words = len(reply.split())
    if words < 10:
        return f"too short ({words} words)"
    if words > 75:
        return f"too long for a short ({words} words)"
    if BANNED_OPENERS.search(reply):
        return "canned opener"
    if "mnema" in reply.lower():
        return "mentions the app"
    return None


def fetch(cid: str, tries: int = 3, dest: Path = CONVOS) -> Path:
    say = dict(scenarios())[cid]
    token = _token()
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    attempts = []
    for _ in range(tries):
        code, start = _req("/checkin/start", {"language": "en", "with_opening": False, "today": today}, token)
        if code != 200:
            raise ConvoError(f"/checkin/start HTTP {code} {str(start)[:200]}")
        code, msg = _req("/checkin/message", {"session_id": start["session_id"], "transcript": say, "today": today}, token)
        if code != 200:
            raise ConvoError(f"/checkin/message HTTP {code} {str(msg)[:200]}")
        reply = (msg.get("reply") or "").strip()
        why = gate(reply)
        attempts.append({"reply": reply, "rejected": why})
        if why is None:
            break
    else:
        raise ConvoError(f"{cid}: no reply passed the gate: {attempts}")
    dest.mkdir(parents=True, exist_ok=True)
    rec = {"id": cid, "say": say, "reply": reply, "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
           "endpoint": API + "/checkin/message", "session_id": start["session_id"], "attempts": attempts,
           "note": "reply is verbatim backend output; first line written by the account owner"}
    p = dest / f"{today}-{cid}.json"
    p.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n")
    return p


def used_ids() -> set[str]:
    return {json.loads(p.read_text())["id"] for p in CONVOS.glob("*.json")} if CONVOS.exists() else set()


def next_id() -> str:
    used = used_ids()
    ids = [c for c, _ in scenarios()]
    fresh = [c for c in ids if c not in used]
    if not fresh:
        raise ConvoError("all scenarios used — add more lines to content/convo_scenarios.md")
    return fresh[0]


# ---------------------------------------------------------------- render
INK = (18, 17, 16)
PAPER = (246, 243, 238)
DIM = (150, 145, 136)
ME_BG = (58, 56, 52)
AI_BG = (246, 243, 238)
AI_TX = (24, 24, 22)
GREEN = (120, 160, 132)
SAFE_TOP, SAFE_BOTTOM = 300, H - 520
LEFT, RIGHT = 96, W - 150


def _lines(text, font, max_w):
    return gfx.wrap(text, font, max_w)


def _bubble(lines, font, bg, fg, pad=(34, 26), radius=34, upto_words=None):
    asc, desc = font.getmetrics()
    lh = int((asc + desc) * 1.28)
    tw = max(font.getlength(l) for l in lines)
    w, h = int(tw + pad[0] * 2), int(lh * len(lines) + pad[1] * 2 - (lh - asc - desc))
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius, fill=bg)
    shown = 0
    for i, l in enumerate(lines):
        words = l.split()
        if upto_words is not None:
            take = max(0, min(len(words), upto_words - shown))
            shown += len(words)
            l = " ".join(words[:take])
        d.text((pad[0], pad[1] + i * lh), l, font=font, fill=fg)
    return img


def build(rec: dict, out: Path, music: Path) -> Path:
    say, reply = rec["say"], rec["reply"]
    # size text so both bubbles fit the safe area
    for size in (60, 56, 52, 48, 45, 42, 39, 36):
        f = inter(size, "Medium")
        me_l = _lines(say, f, 690)
        ai_l = _lines(reply, f, 690)
        me = _bubble(me_l, f, ME_BG, PAPER)
        ai_full = _bubble(ai_l, f, AI_BG, AI_TX)
        head_h = 170
        total = head_h + me.height + 50 + 70 + ai_full.height
        if total <= SAFE_BOTTOM - SAFE_TOP - 90:
            break
    head = gfx.text_block(["I told my AI journal:"], play(70, "SemiBold"), PAPER, width=W)
    tag = gfx.text_block(["REAL REPLY · UNEDITED"], mono(28), DIM, width=W)
    foot = gfx.text_block(["Mnema · voice journal · App Store"], mono(28), GREEN, width=W)
    icon = gfx.icon(60)
    n_words = len(reply.split())

    y0 = SAFE_TOP + max(0, (SAFE_BOTTOM - SAFE_TOP - 90 - total) // 2)
    me_xy = (RIGHT - me.width, y0 + head_h)
    ai_y = me_xy[1] + me.height + 50 + 70
    ai_xy = (LEFT + 80, ai_y)
    dots_t0, reply_t0 = 1.2, 2.0
    wps = 3.3
    reply_end = reply_t0 + n_words / wps
    duration = reply_end + 2.6

    base = Image.new("RGBA", (W, H), INK + (255,))
    base.alpha_composite(tag, (0, SAFE_TOP - 70))
    base.alpha_composite(head, (0, y0))
    base.alpha_composite(me, me_xy)               # the confession is on the very first frame (cover)

    cache: dict[int, Image.Image] = {}

    def frame(t):
        img = base.copy()
        if t >= dots_t0:
            img.alpha_composite(icon, (LEFT, ai_y + 6))
        if dots_t0 <= t < reply_t0:
            dots = Image.new("RGBA", (150, 84), (0, 0, 0, 0))
            dd = ImageDraw.Draw(dots)
            dd.rounded_rectangle((0, 0, 149, 83), 34, fill=AI_BG)
            for i in range(3):
                k = 0.5 + 0.5 * __import__("math").sin(t * 9 - i * 0.9)
                c = int(150 - 60 * k)
                dd.ellipse((35 + i * 36 - 9, 42 - 9 - 5 * k, 35 + i * 36 + 9, 42 + 9 - 5 * k), fill=(c, c, c))
            img.alpha_composite(dots, ai_xy)
        if t >= reply_t0:
            k = min(n_words, int((t - reply_t0) * wps) + 1)
            if k not in cache:
                cache[k] = _bubble(ai_l, f, AI_BG, AI_TX, upto_words=k)
            img.alpha_composite(cache[k], ai_xy)
        if t >= reply_end + 0.3:
            a = min(1.0, (t - reply_end - 0.3) / 0.4)
            gfx.paste_fade(img, foot, (0, SAFE_BOTTOM - 40), a)
        return img

    return gfx.encode(frame, duration, out, music, crf=18)


def captions(rec: dict) -> dict:
    say = rec["say"]
    short = say if len(say) <= 70 else say[:67].rsplit(" ", 1)[0] + "…"
    tags = "#journaling #aijournal #overthinking #selfawareness #feelings"
    return {
        "tiktok": f"I typed this into the journal app I'm building. The reply is unedited. What would you have said? {tags}",
        "youtube_title": f"I told my AI journal: “{short}” #shorts"[:100],
        "youtube_desc": (f"Me: {say}\n\nMnema (real reply, unedited): {rec['reply']}\n\n"
                         "Mnema is a voice journal: talk for two minutes and it writes the entry. On the App Store."),
        "instagram": (f"I told my AI journal: “{say}”\n\nThis is the reply, unedited. "
                      f"It's not allowed to say “that sounds hard”.\n\nMnema is on the App Store — link in bio.\n\n{tags}"),
        "x": f"Me: “{short}”\nMy journal app, unedited: “{rec['reply'][:150]}”",
        "pinned": ("This is Mnema, the voice journal I'm building. You talk for a couple of minutes, it writes the entry, "
                   "and it remembers what you told it last week. First 7 days free on the App Store, link in bio."),
    }


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "fetch":
        print(fetch(sys.argv[2] if len(sys.argv) > 2 else next_id()))
    elif cmd == "sample":
        # try the next N scenarios without using them up: records + videos go to samples/convos/
        import subprocess
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        used = used_ids()
        ids = [c for c, _ in scenarios() if c not in used][:n]
        out_dir = ROOT / "samples" / "convos"
        for cid in ids:
            try:
                p = fetch(cid, dest=out_dir)
                rec = json.loads(p.read_text())
                print(f"{cid}: {rec['say']!r}\n  → {rec['reply']!r}\n  attempts: {rec['attempts']}")
                build(rec, out_dir / f"convo-{cid}.mp4", gfx.ASSETS / "audio" / "02-talk-to-journal.m4a")
            except ConvoError as e:
                print(f"{cid}: FAILED {e}")
        subprocess.run(["git", "add", "samples/convos"], cwd=ROOT, check=False)
        subprocess.run(["git", "commit", "-q", "-m", "samples: real conversations"], cwd=ROOT, check=False)
        subprocess.run(["git", "pull", "-q", "--rebase"], cwd=ROOT, check=False)
        subprocess.run(["git", "push", "-q", "origin", "HEAD"], cwd=ROOT, check=True)
    elif cmd == "render":
        rec = json.loads(Path(sys.argv[2]).read_text())
        build(rec, Path(sys.argv[3]), gfx.ASSETS / "audio" / "02-talk-to-journal.m4a")
