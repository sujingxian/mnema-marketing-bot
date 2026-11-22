"""App Store links and per-platform calls to action.

`ct` is Apple's campaign token: App Store Connect → Analytics → Sources → Campaigns shows
downloads per token, so each platform gets its own.
"""
APP_ID = "6797841775"
PROVIDER = "129251185"


def app_url(ct: str) -> str:
    return f"https://apps.apple.com/app/apple-store/id{APP_ID}?pt={PROVIDER}&ct={ct}&mt=8"


# TikTok personal accounts under 1,000 followers have no tappable bio link, so TikTok says "search".
CTA = {
    "tiktok": "Search “Mnema” on the App Store — free to try.",
    "instagram": "Mnema is free to try — link in bio 🔗",
    "youtube": f"Try Mnema free: {app_url('youtube')}",
    "x": f"Mnema, the journal that talks back: {app_url('x')}",
}
IG_BIO_URL = app_url("instagram")
TIKTOK_BIO_URL = app_url("tiktok")   # for when the account gets a tappable link
