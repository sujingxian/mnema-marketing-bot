"""Minimal Buffer GraphQL client (https://api.buffer.com, personal API key).

    python -m mnemabot.buffer channels     # list connected channels
    python -m mnemabot.buffer schema       # dump CreatePostInput / metadata input types
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

API = "https://api.buffer.com"


class BufferError(RuntimeError):
    pass


def _key() -> str:
    k = os.environ.get("BUFFER_API_KEY", "").strip()
    if not k:
        raise BufferError("BUFFER_API_KEY is not set")
    return k


def gql(query: str, variables: dict | None = None) -> dict:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(API, data=body, method="POST", headers={
        "Authorization": f"Bearer {_key()}",
        "Content-Type": "application/json",
        "User-Agent": "mnema-marketing-bot/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise BufferError(f"HTTP {e.code}: {e.read()[:500]!r}")
    if data.get("errors"):
        raise BufferError(json.dumps(data["errors"])[:1500])
    return data["data"]


def organizations() -> list[dict]:
    return gql("query { account { organizations { id name } } }")["account"]["organizations"]


def channels(org_id: str | None = None) -> list[dict]:
    org_id = org_id or organizations()[0]["id"]
    q = """query Channels($input: ChannelsInput!) {
      channels(input: $input) { id name displayName service isQueuePaused }
    }"""
    return gql(q, {"input": {"organizationId": org_id}})["channels"]


def create_post(channel_id: str, text: str, video_url: str, due_at_iso: str,
                metadata: dict | None = None, thumb_ms: int = 1500) -> dict:
    q = """mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess { post { id dueAt status } }
        ... on MutationError { message }
      }
    }"""
    inp = {
        "channelId": channel_id,
        "text": text,
        "schedulingType": "automatic",
        "needsApproval": False,
        "mode": "customScheduled",
        "dueAt": due_at_iso,
        "assets": [{"video": {"url": video_url, "metadata": {"thumbnailOffset": thumb_ms}}}],
    }
    if metadata:
        inp["metadata"] = metadata
    res = gql(q, {"input": inp})["createPost"]
    if "message" in res and "post" not in res:
        raise BufferError(res["message"])
    return res["post"]


def _dump_type(name: str):
    q = """query T($n: String!) { __type(name: $n) { name kind
      inputFields { name type { kind name ofType { kind name ofType { kind name ofType { name } } } } }
      enumValues { name } } }"""
    return gql(q, {"n": name})["__type"]


def schema():
    seen, todo = set(), ["CreatePostInput"]
    while todo:
        n = todo.pop(0)
        if n in seen or not n:
            continue
        seen.add(n)
        t = _dump_type(n)
        if not t:
            continue
        print(json.dumps(t, indent=1))
        for f in t.get("inputFields") or []:
            ty = f["type"]
            while ty and ty.get("ofType") and not ty.get("name"):
                ty = ty["ofType"]
            nm = ty.get("name") if ty else None
            if nm and nm not in ("String", "Int", "Boolean", "Float", "ID", "DateTime"):
                todo.append(nm)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "channels"
    if cmd == "channels":
        print(json.dumps(channels(), indent=1))
    elif cmd == "orgs":
        print(json.dumps(organizations(), indent=1))
    elif cmd == "schema":
        schema()
