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


STOP = set("""a an the i i'm im me my you your you're it it's its is was were be been to of and or but so
that this in on at for with about just not no now then than as if when what why how do did does dont don't
didn't feel felt feeling really still all some one more like""".split())


def _content(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z']+", text.lower().replace("’", "'")) if w not in STOP and len(w) > 2}


def overlap(say: str, reply: str) -> float:
    """Share of the reply's content words that were already in the user's line (0 = all new)."""
    r = _content(reply)
    return len(r & _content(say)) / len(r) if r else 1.0


def gate(reply: str, say: str = "") -> str | None:
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
    if say and overlap(say, reply) > 0.34:
        return f"restates the user ({overlap(say, reply):.0%} reused words)"
    return None


JUDGE_URL = "https://models.github.ai/inference/chat/completions"
JUDGE_MODEL = os.environ.get("MNEMA_JUDGE_MODEL", "openai/gpt-4.1-mini")
JUDGE_PROMPT = """You rate replies from a journaling companion. The user wrote one message; the companion replied.
Rate how much the reply ADDS beyond the user's message:
1 = restates or summarises what the user said, in other words
2 = mostly restatement with a generic comment
3 = a small new angle, but predictable
4 = names something specific the user did not say (what stung, what it meant, what they were protecting)
5 = a sharp, specific, non-obvious insight a thoughtful friend would offer
Answer with the digit only."""


JUDGE_ERROR = ""


def judge(say: str, reply: str) -> int | None:
    """1–5 from a small model on GitHub Models (free in Actions). None when unavailable."""
    global JUDGE_ERROR
    JUDGE_ERROR = ""
    tok = os.environ.get("GITHUB_TOKEN")
    if not tok:
        JUDGE_ERROR = "no GITHUB_TOKEN"
        return None
    body = {"model": JUDGE_MODEL, "temperature": 0,
            "messages": [{"role": "system", "content": JUDGE_PROMPT},
                         {"role": "user", "content": f"User: {say}\nReply: {reply}"}]}
    req = urllib.request.Request(JUDGE_URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            txt = json.loads(r.read())["choices"][0]["message"]["content"]
        m = re.search(r"[1-5]", txt)
        return int(m.group(0)) if m else None
    except urllib.error.HTTPError as e:
        JUDGE_ERROR = f"HTTP {e.code}: {e.read()[:300]!r}"
    except Exception as e:  # noqa: BLE001
        JUDGE_ERROR = repr(e)[:300]
    print(f"[judge] unavailable: {JUDGE_ERROR}")
    return None


def score(say: str, reply: str) -> float:
    """Higher is better: new words dominate; mild preference for 15–45 words."""
    n = len(reply.split())
    return (1 - overlap(say, reply)) - (0.004 * max(0, n - 45)) - (0.01 * max(0, 15 - n))


def fetch(cid: str, tries: int = 5, dest: Path = CONVOS) -> Path:
    say = dict(scenarios())[cid]
    token = _token()
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    attempts = []
    best = None
    for _ in range(tries):
        code, start = _req("/checkin/start", {"language": "en", "with_opening": False, "today": today}, token)
        if code != 200:
            raise ConvoError(f"/checkin/start HTTP {code} {str(start)[:200]}")
        code, msg = _req("/checkin/message", {"session_id": start["session_id"], "transcript": say, "today": today}, token)
        if code != 200:
            raise ConvoError(f"/checkin/message HTTP {code} {str(msg)[:200]}")
        reply = (msg.get("reply") or "").strip()
        why = gate(reply, say)
        j = judge(say, reply) if why is None else None
        if why is None and j is not None and j < 4:
            why = f"judge {j}/5: mostly restates the user"
        if why is None and j is None and os.environ.get("MNEMA_REQUIRE_JUDGE", "1") == "1":
            why = "judge unavailable; not posting unjudged replies"
        sc = round((j or 0) + score(say, reply), 3)
        attempts.append({"reply": reply, "session_id": start["session_id"], "rejected": why,
                         "judge": j, "score": sc, **({"judge_error": JUDGE_ERROR} if j is None else {})})
        if why is None and (best is None or sc > best["score"]):
            best = attempts[-1]
        if best is not None and (best["judge"] == 5 or (best["judge"] is None and best["score"] >= 0.8)):
            break                      # good enough; no need to keep sampling
    if best is None:
        if dest != CONVOS:              # samples: keep the evidence so failures can be read from the repo
            dest.mkdir(parents=True, exist_ok=True)
            (dest / f"{today}-{cid}-FAILED.json").write_text(
                json.dumps({"id": cid, "say": say, "attempts": attempts}, indent=1, ensure_ascii=False) + "\n")
        raise ConvoError(f"{cid}: no reply passed the gate: {[a['rejected'] for a in attempts]}")
    reply, start = best["reply"], {"session_id": best["session_id"]}
    dest.mkdir(parents=True, exist_ok=True)
    rec = {"id": cid, "say": say, "reply": reply, "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
           "endpoint": API + "/checkin/message", "session_id": start["session_id"], "attempts": attempts,
           "note": ("reply is verbatim backend output; first line written by the account owner; "
                    "best of the attempts below (judge score + word overlap), none edited")}
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
