"""One-time YouTube OAuth for mnemabot.yt_analytics — prints the refresh token to paste into the
repo's Actions secrets. Standard library only; run it on your own computer, not in CI.

    python3 scripts/yt_auth.py

Before running (10 minutes, all free):
  1. https://console.cloud.google.com → New project (any name).
  2. APIs & Services → Library → enable "YouTube Data API v3" and "YouTube Analytics API".
  3. APIs & Services → OAuth consent screen → External → fill the app name + your email →
     Audience: click **Publish app** (otherwise the refresh token expires after 7 days).
     Scopes / verification: skip. You will see an "unverified app" warning when signing in —
     it is your own app; click Advanced → Go to … → Continue.
  4. Credentials → Create credentials → OAuth client ID → Application type **Desktop app**.
     Copy the Client ID and Client secret; this script asks for them.
Then put YT_CLIENT_ID, YT_CLIENT_SECRET and the printed YT_REFRESH_TOKEN into
GitHub → repo → Settings → Secrets and variables → Actions → New repository secret.
"""
from __future__ import annotations

import http.server
import json
import secrets
import socket
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from getpass import getpass

SCOPES = "https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/yt-analytics.readonly"


def main() -> int:
    cid = input("Client ID: ").strip()
    sec = getpass("Client secret (hidden): ").strip()
    if not cid or not sec:
        print("need both values")
        return 1

    with socket.socket() as s:                 # pick a free loopback port
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    redirect = f"http://127.0.0.1:{port}/"
    state = secrets.token_urlsafe(16)
    got: dict = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] == state and "code" in q:
                got["code"] = q["code"][0]
                msg = "Done — you can close this tab and go back to the terminal."
            else:
                msg = "Missing code; go back to the terminal and try again."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(msg.encode())

        def log_message(self, *a):          # keep the terminal clean
            pass

    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()

    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": SCOPES,
        "access_type": "offline", "prompt": "consent", "state": state,
    })
    print("\nOpening the Google sign-in page (sign in with the channel's Google account)…")
    if not webbrowser.open(url):
        print("Open this URL yourself:\n", url)
    while "code" not in got:
        threading.Event().wait(0.2)

    body = urllib.parse.urlencode({"code": got["code"], "client_id": cid, "client_secret": sec,
                                   "redirect_uri": redirect, "grant_type": "authorization_code"}).encode()
    with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=body)) as r:
        tok = json.loads(r.read())
    if "refresh_token" not in tok:
        print("No refresh token returned. Remove the app's access at https://myaccount.google.com/permissions and run again.")
        return 1
    print("\nAdd these three secrets to GitHub → Settings → Secrets and variables → Actions:\n")
    print(f"  YT_CLIENT_ID      = {cid}")
    print(f"  YT_CLIENT_SECRET  = (the client secret you just entered)")
    print(f"  YT_REFRESH_TOKEN  = {tok['refresh_token']}\n")
    print("Then run the 'weekly-analytics' workflow once by hand (Actions → weekly-analytics → Run workflow).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
