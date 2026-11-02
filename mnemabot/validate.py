"""Check the script library before pushing a new batch.

    python3 -m mnemabot.validate            # exit 1 on problems
Prints how many scripts are still unposted (queue depth).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mnemabot.emotion import parse_series, production_order, EXCLUDE, GENERATED  # noqa: E402

BANNED = re.compile(r"\b(therap\w*|diagnos\w*|disorder|depression|ptsd|adhd|bipolar|amygdala|dopamine|cortisol|"
                    r"suicid\w*|self-harm|medicat\w*|cure[sd]?)\b", re.I)
REQUIRED = ("hook", "turn", "name", "line", "do")


def main() -> int:
    items = parse_series()
    problems = []
    names = {}
    for n, it in items.items():
        for k in REQUIRED:
            if n not in EXCLUDE and not it.get(k):
                problems.append(f"#{n} {it['emotion']}: missing {k.upper()}")
        if not it.get("color"):
            problems.append(f"#{n}: no cluster header above it (needs '# CLUSTER x · NAME  `#hex`')")
        key = it["emotion"].lower()
        if key in names:
            problems.append(f"#{n} duplicates emotion '{it['emotion']}' (#{names[key]})")
        names[key] = n
        if n > 60:
            text = " ".join(str(it.get(k, "")) for k in REQUIRED + ("loop",))
            if BANNED.search(text):
                problems.append(f"#{n}: banned clinical word: {BANNED.search(text).group(0)}")
            for k in REQUIRED:
                if len(str(it.get(k, "")).split()) > 26:
                    problems.append(f"#{n}: {k.upper()} longer than 26 words")
    # numbering in generated files must be unique and > 60
    seen = set()
    for g in sorted(GENERATED.glob("*.md")) if GENERATED.exists() else []:
        for m in re.finditer(r"^### (\d+) ", g.read_text(encoding="utf-8"), re.M):
            v = int(m.group(1))
            if v <= 60 or v in seen:
                problems.append(f"{g.name}: bad/duplicate number {v}")
            seen.add(v)
    state = ROOT / "state" / "state.json"
    posted = 0
    if state.exists():
        posted = json.loads(state.read_text()).get("next_index", 0)
    order = production_order(items)
    print(json.dumps({"scripts": len(items), "postable": len(order), "posted": posted,
                      "unposted": max(0, len(order) - posted), "next_number": max(items) + 1}))
    for p in problems:
        print("PROBLEM:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
