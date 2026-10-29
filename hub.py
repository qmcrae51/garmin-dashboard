"""Write index.html (a home page linking every dashboard) and the iPhone home-screen icon."""
import datetime as dt
import math
import os
import struct
import zlib

ROOT = os.path.dirname(os.path.abspath(__file__))
PAGES = [
    ("dashboard.html", "J.A.R.V.I.S.", "Race countdowns, vitals, trends and records"),
    ("plan.html", "Training plan", "26 weeks to the marathon, with today's workout"),
    ("commander.html", "Mission control", "Fitness, fatigue and form, plus today's alert"),
    ("coach.html", "Coach view", "Morning flags and a note from your coach"),
    ("brain.html", "Athlete OS", "Every workout as a glowing 3D graph"),
]


def icon(path, size=180):
    """Arc-reactor icon drawn pixel by pixel, saved as a PNG with only the standard library."""
    cx = cy = (size - 1) / 2
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            d = math.hypot(x - cx, y - cy) / size
            r, g, b = 6, 12, 20
            glow = max(0.0, 1 - d / 0.5) ** 3
            r, g, b = r + 20 * glow, g + 120 * glow, b + 160 * glow
            for radius, width, k in ((0.36, 0.022, 0.8), (0.25, 0.03, 1.0), (0.1, 0.1, 1.0)):
                a = max(0.0, 1 - abs(d - radius) / width) if radius > 0.1 else max(0.0, 1 - d / radius)
                r, g, b = r + (95 - r) * a * k, g + (224 - g) * a * k, b + (255 - b) * a * k
            row += bytes(min(255, int(c)) for c in (r, g, b))
        rows.append(bytes(row))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def build():
    if not os.path.exists(os.path.join(ROOT, "apple-touch-icon.png")):
        icon(os.path.join(ROOT, "apple-touch-icon.png"))
    cards = "".join(
        f'<a class="card" href="{f}"><span class="t">{t}</span><span class="d">{d}</span><span class="go">›</span></a>'
        for f, t, d in PAGES if os.path.exists(os.path.join(ROOT, f)))
    stamp = dt.datetime.now().strftime("%b %-d, %H:%M")
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<meta name="apple-mobile-web-app-title" content="Training">
<meta name="theme-color" content="#050a10">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="icon" href="apple-touch-icon.png">
<title>Training HQ</title>
<style>
:root {{ color-scheme: dark; --bg: #050a10; --card: #0c1622; --hud: #5fe0ff; --text: #e6f6ff; --muted: #7d93a3; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; min-height: 100vh; background: radial-gradient(900px 500px at 20% -10%, rgba(26,156,203,.22), transparent 60%), var(--bg);
  color: var(--text); font-family: -apple-system, system-ui, sans-serif; padding: max(24px, env(safe-area-inset-top)) 16px 32px; }}
.wrap {{ max-width: 560px; margin: 0 auto; }}
h1 {{ font-size: 13px; letter-spacing: .32em; color: var(--hud); margin: 8px 0 4px; text-shadow: 0 0 14px rgba(95,224,255,.5); }}
.sub {{ color: var(--muted); font-size: 13px; margin-bottom: 22px; }}
.card {{ display: grid; grid-template-columns: 1fr auto; gap: 2px 12px; padding: 16px 18px; margin-bottom: 12px; border-radius: 14px;
  background: var(--card); border: 1px solid rgba(95,224,255,.16); color: inherit; text-decoration: none; }}
.card:active {{ background: #12202f; }}
.t {{ font-size: 18px; font-weight: 600; }}
.d {{ grid-column: 1; color: var(--muted); font-size: 14px; }}
.go {{ grid-column: 2; grid-row: 1 / 3; align-self: center; color: var(--hud); font-size: 26px; }}
</style>
</head>
<body><div class="wrap">
<h1>TRAINING HQ</h1>
<div class="sub">Updated {stamp}</div>
{cards}
</div></body>
</html>
"""
    with open(os.path.join(ROOT, "index.html"), "w") as f:
        f.write(html)
    print("Home page written: index.html")


if __name__ == "__main__":
    build()
