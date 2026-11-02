"""Replace an already-scheduled slot with a fresh render (same due time, same channels).

    python -m mnemabot.replace --index 0
Deletes the slot's Buffer posts, re-renders with the current template, re-schedules, updates state.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from . import buffer, plan
from .run_daily import (ROOT, VIDEOS, REPO, BRANCH, load_state, save_state, render, git, wait_public,
                        metadata_for, text_for, SERVICES)


def _delete_mutation():
    """Find the delete-post mutation and its argument shape from the live schema."""
    q = """{ __type(name: "Mutation") { fields { name args { name type { name kind ofType { name kind } } } } } }"""
    fields = buffer.gql(q)["__type"]["fields"]
    f = next(x for x in fields if x["name"].lower() == "deletepost")
    arg = f["args"][0]
    tname = arg["type"]["name"] or arg["type"]["ofType"]["name"]
    if tname and tname.endswith("Input"):
        t = buffer.gql('query($n:String!){ __type(name:$n){ inputFields { name } } }', {"n": tname})["__type"]
        key = next(x["name"] for x in t["inputFields"] if x["name"] in ("id", "postId"))
        return f["name"], arg["name"], tname + "!", lambda pid: {key: pid}
    return f["name"], arg["name"], (tname or "PostId") + "!", lambda pid: pid


def delete_post(pid: str):
    name, argname, gtype, wrap = _delete_mutation()
    q = f"mutation D($v: {gtype}) {{ {name}({argname}: $v) {{ __typename }} }}"
    return buffer.gql(q, {"v": wrap(pid)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=int, required=True)
    a = ap.parse_args()
    state = load_state()
    h = next(x for x in state["history"] if x["index"] == a.index)
    entry = plan.calendar()[a.index] if a.index < len(plan.calendar()) else None
    # slot 0 was scheduled before products were paused; recover the entry from the slug
    if entry is None or plan.slug(entry) != h["slug"]:
        num = int(h["slug"].split("-")[1])
        entry = {"kind": "emotion", "key": num}
    caps = plan.captions(entry)
    due = dt.datetime.fromisoformat(h["due"])

    fname = h["file"].replace(".mp4", "-v2.mp4")
    out = VIDEOS / fname
    render(entry, out, a.index)
    git("add", str(out.relative_to(ROOT)))
    git("commit", "-q", "-m", f"video: {fname} (replacement)")
    git("push", "-q", "origin", BRANCH)
    url = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/videos/{fname}"
    wait_public(url)

    deleted = []
    for r in h["results"]:
        if r.get("post_id"):
            try:
                delete_post(r["post_id"])
                deleted.append({"service": r["service"], "deleted": r["post_id"]})
            except buffer.BufferError as e:
                deleted.append({"service": r["service"], "delete_error": str(e)[:300]})
    print(json.dumps(deleted, indent=1))

    results = []
    for ch in buffer.channels():
        svc = (ch.get("service") or "").lower()
        if svc not in SERVICES or ch.get("isQueuePaused"):
            continue
        try:
            post = buffer.create_post(ch["id"], text_for(svc, caps), url,
                                      due.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                                      metadata_for(svc, caps))
            results.append({"service": svc, "ok": True, "post_id": post.get("id")})
        except buffer.BufferError as e:
            results.append({"service": svc, "ok": False, "error": str(e)[:400]})
    print(json.dumps(results, indent=1))
    h.update(file=fname, results=results, replaced_at=dt.datetime.now(dt.timezone.utc).isoformat(),
             replaced=deleted)
    save_state(state)
    git("add", "state/state.json")
    git("commit", "-q", "-m", f"state: replaced slot {a.index}")
    git("push", "-q", "origin", BRANCH)
    if not all(r["ok"] for r in results):
        raise SystemExit("some channels failed")


if __name__ == "__main__":
    main()
