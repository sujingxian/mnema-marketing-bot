"""Write Buffer account diagnostics to state/diag.json and push (readable via the raw URL).

No secrets are written — only organization/channel ids, services and the CreatePostInput schema.
"""
from __future__ import annotations

import io
import json
import subprocess
import contextlib
import datetime as dt
from pathlib import Path

from . import buffer

ROOT = Path(__file__).resolve().parent.parent


def main():
    out = {"at": dt.datetime.now(dt.timezone.utc).isoformat()}
    try:
        out["organizations"] = buffer.organizations()
        out["channels"] = buffer.channels(out["organizations"][0]["id"])
    except Exception as e:  # noqa: BLE001
        out["error_channels"] = str(e)[:2000]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            buffer.schema()
        out["schema"] = buf.getvalue()
    except Exception as e:  # noqa: BLE001
        out["error_schema"] = str(e)[:2000]
    p = ROOT / "state" / "diag.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in out.items() if k != "schema"}, indent=1))
    subprocess.run(["git", "add", str(p)], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "diag: buffer account"], cwd=ROOT, check=False)
    subprocess.run(["git", "push", "-q", "origin", "HEAD"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
