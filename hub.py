"""Write index.html (a home page linking every dashboard) and the iPhone home-screen icon."""
import datetime as dt
import json
import math
import os
import struct
import zlib

import insights

ROOT = os.path.dirname(os.path.abspath(__file__))
PAGES = [
    ("progress.html", "On track for 3:00?", "Predicted marathon, checkpoints and easy-run discipline"),
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
    a = insights.analyze()
    data = json.dumps({k: a[k] for k in ("built", "today", "race", "readiness", "history", "days", "checkpoints",
                                         "predictM", "paces", "cap", "vdot", "goalVdot")},
                      separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.replace("__CARDS__", cards).replace("__DATA__", data)
    with open(os.path.join(ROOT, "index.html"), "w") as f:
        f.write(html)
    print("Home page written: index.html")


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<meta name="apple-mobile-web-app-title" content="Training">
<meta name="theme-color" content="#050a10">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="icon" href="apple-touch-icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700&family=Rajdhani:wght@400;500;600;700&display=swap" rel="stylesheet">
<title>Training HQ</title>
<style>
:root { color-scheme: dark; --bg: #050a10; --card: #0c1622; --card2: #0f1d2c; --hud: #5fe0ff; --hud-dim: rgba(95,224,255,.16);
  --text: #e6f6ff; --text-2: #9fb6c6; --muted: #6c8191; --grid: #16283a;
  --good: #0ca30c; --warning: #fab219; --serious: #ec835a; --critical: #d03b3b;
  --display: "Orbitron", system-ui, sans-serif; --body: "Rajdhani", -apple-system, system-ui, sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; background: radial-gradient(900px 500px at 20% -10%, rgba(26,156,203,.22), transparent 60%), var(--bg);
  color: var(--text); font-family: var(--body); font-size: 16px; padding: max(20px, env(safe-area-inset-top)) 16px 32px; }
.wrap { max-width: 560px; margin: 0 auto; }
h1 { font-family: var(--display); font-size: 13px; letter-spacing: .32em; color: var(--hud); margin: 8px 0 2px; text-shadow: 0 0 14px rgba(95,224,255,.5); }
.sub { color: var(--muted); font-size: 14px; margin-bottom: 18px; }
.box { background: var(--card); border: 1px solid var(--hud-dim); border-radius: 14px; padding: 16px 18px; margin-bottom: 14px; }
.k { font-family: var(--display); font-size: 10px; letter-spacing: .2em; color: var(--hud); text-transform: uppercase; margin-bottom: 8px; display: flex; flex-wrap: wrap; gap: 2px 10px; justify-content: space-between; }
.k span { white-space: nowrap; }
.k span:last-child { color: var(--muted); }
.wo { font-size: 22px; font-weight: 600; line-height: 1.2; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.chip { padding: 3px 10px; border: 1px solid var(--hud-dim); border-radius: 20px; font-size: 14px; color: var(--text-2); }
.chip b { color: var(--text); font-weight: 600; }
.chip.ok { border-color: rgba(12,163,12,.5); }
.advice { margin-top: 14px; padding: 10px 12px; border-radius: 10px; background: var(--card2); border-left: 3px solid var(--lc, var(--hud)); font-size: 16px; line-height: 1.35; }
.advice .tag { font-family: var(--display); font-size: 10px; letter-spacing: .2em; color: var(--lc); display: block; margin-bottom: 3px; }
.result { margin-top: 12px; font-size: 16px; line-height: 1.4; }
.ic { display: inline-grid; place-items: center; width: 18px; height: 18px; border-radius: 50%; font-size: 12px; font-weight: 700; color: #050a10; background: var(--lc); vertical-align: -3px; margin-right: 4px; }
.ready { display: grid; grid-template-columns: auto 1fr; gap: 16px; align-items: center; }
.score { width: 92px; height: 92px; }
.score .big { font-family: var(--display); font-weight: 700; font-size: 26px; fill: var(--text); }
.score .lab { font-family: var(--display); font-size: 9px; letter-spacing: .18em; fill: var(--muted); }
.f { display: grid; grid-template-columns: 1fr auto; gap: 0 10px; padding: 5px 0; border-bottom: 1px solid var(--grid); min-width: 0; }
.f:last-child { border-bottom: 0; }
.f .n { font-weight: 600; } .f .v { text-align: right; font-weight: 600; }
.f .s { grid-column: 1 / 3; color: var(--muted); font-size: 14px; }
.strip { display: grid; grid-template-columns: repeat(14, 1fr); gap: 3px; margin-top: 12px; }
.strip i { height: 14px; border-radius: 3px; background: var(--grid); }
.strip-l { display: flex; justify-content: space-between; color: var(--muted); font-size: 13px; margin-top: 4px; }
.week { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; text-align: center; }
.day { padding: 6px 0 8px; border-radius: 8px; background: var(--card2); min-width: 0; }
.day.now { outline: 1px solid var(--hud); }
.day .dw { font-family: var(--display); font-size: 9px; letter-spacing: .12em; color: var(--muted); }
.day .km { font-weight: 600; font-size: 15px; margin: 2px 0 4px; }
.day .st { font-size: 15px; height: 20px; }
.wsum { margin-top: 10px; color: var(--text-2); font-size: 15px; }
.track .row { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }
.track .big { font-family: var(--display); font-size: 24px; font-weight: 700; }
.track .goal { color: var(--muted); }
.track p { margin: 10px 0 0; color: var(--text-2); line-height: 1.4; }
.track a, .more { color: var(--hud); text-decoration: none; }
.card { display: grid; grid-template-columns: 1fr auto; gap: 2px 12px; padding: 14px 18px; margin-bottom: 10px; border-radius: 14px;
  background: var(--card); border: 1px solid rgba(95,224,255,.16); color: inherit; text-decoration: none; }
.card:active { background: #12202f; }
.t { font-size: 18px; font-weight: 600; }
.d { grid-column: 1; color: var(--muted); font-size: 14px; }
.go { grid-column: 2; grid-row: 1 / 3; align-self: center; color: var(--hud); font-size: 26px; }
.sec { font-family: var(--display); font-size: 10px; letter-spacing: .3em; color: var(--muted); margin: 22px 0 10px; }
</style>
</head>
<body><div class="wrap">
<h1>TRAINING HQ</h1>
<div class="sub" id="sub"></div>
<div id="today"></div>
<div id="ready"></div>
<div id="week"></div>
<div id="track"></div>
<div class="sec">ALL SCREENS</div>
__CARDS__
</div>
<script>
const D = __DATA__;
const LVL = { good: ["var(--good)", "✓", "GO"], warning: ["var(--warning)", "!", "CAUTION"], critical: ["var(--critical)", "✕", "RECOVER"] };
const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const md = s => new Date(s + "T12:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
const wd = s => new Date(s + "T12:00").toLocaleDateString("en-US", { weekday: "long" });
const now = new Date(), today = iso(now);
const hour = now.getHours();
document.getElementById("sub").textContent =
  `Good ${hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening"}, Sir · ${wd(today)}, ${md(today)} · Garmin data ${md(D.built.slice(0, 10))} ${D.built.slice(11)}`;

const t = D.days.find(d => d.date === today);
const R = D.readiness && D.readiness.date === today ? D.readiness : null;

// ---- today
(() => {
  const el = document.getElementById("today");
  if (!t) { el.innerHTML = `<div class="box"><div class="k"><span>Today</span></div><div class="wo">No plan day found for today.</div></div>`; return; }
  const hard = ["threshold", "intervals", "hills", "marathon", "test", "race"].includes(t.kind);
  const chips = [];
  if (t.km) chips.push(`<span class="chip"><b>${t.km} km</b></span>`);
  if (t.km && !hard) chips.push(`<span class="chip">Easy <b>${D.paces.E}</b>/km</span>`, `<span class="chip">HR under <b>${D.cap}</b></span>`);
  if (t.gym) chips.push(`<span class="chip${t.gymDone ? " ok" : ""}">Gym <b>${t.gym}</b>${t.gymDone ? " ✓" : ""}</span>`);
  if (t.sauna) chips.push(`<span class="chip">Sauna <b>${t.sauna} min</b></span>`);
  let result = "";
  if (t.ran) {
    const st = t.status === "done" ? "good" : t.status === "short" ? "warning" : "good";
    const cap = t.capOk === undefined ? "" : t.capOk
      ? ` · <b>${t.above}%</b> above ${D.cap} bpm, nicely easy`
      : ` · <b>${t.above}%</b> above ${D.cap} bpm: too hard for an easy day`;
    result = `<div class="result" style="--lc:${LVL[st][0]}"><span class="ic">${LVL[st][1]}</span>${t.status === "short" ? "Short" : t.status === "extra" ? "Extra run" : "Done"}: <b>${t.ran} km</b> at ${t.pace}/km, avg HR ${t.hr}${cap}</div>`;
  }
  let adv = "";
  if (!t.ran && R) adv = `<div class="advice" style="--lc:${LVL[R.lvl][0]}"><span class="tag">${LVL[R.lvl][2]}</span>${t.advice}</div>`;
  else if (!t.ran && t.km) adv = `<div class="advice"><span class="tag" style="color:var(--hud)">READINESS</span>Waiting for this morning's Garmin sync (6 am). Check resting HR before a hard session.</div>`;
  el.innerHTML = `<div class="box"><div class="k"><span>Today · ${md(today)}</span><span>Week ${t.week} · ${t.phase}</span></div>
    <div class="wo">${t.kind === "rest" ? "Rest" : t.title}</div><div class="chips">${chips.join("")}</div>${result}${adv}</div>`;
})();

// ---- readiness
(() => {
  const el = document.getElementById("ready");
  const r = R || D.readiness;
  if (!r) return;
  const [c, , lab] = LVL[r.lvl];
  const circ = 2 * Math.PI * 38;
  const rows = r.factors.map(f => `<div class="f" style="--lc:${LVL[f.lvl][0]}"><span class="n"><span class="ic">${LVL[f.lvl][1]}</span>${f.k}</span><span class="v">${f.v}</span><span class="s">${f.note}</span></div>`).join("");
  const missing = ["Resting HR", "Sleep", "Body Battery"].filter(k => !r.factors.some(f => f.k === k));
  const strip = D.history.map(h => h ? `<i style="background:${LVL[h.lvl][0]};opacity:${h.date === r.date ? 1 : .55}" title="${md(h.date)}: ${h.score} · ${LVL[h.lvl][2]}"></i>` : `<i title="no data"></i>`).join("");
  el.innerHTML = `<div class="box"><div class="k"><span>Readiness</span><span>${r.date === today ? "this morning" : "as of " + md(r.date)}</span></div>
    <div class="ready"><svg class="score" viewBox="0 0 92 92"><circle cx="46" cy="46" r="38" fill="none" stroke="var(--grid)" stroke-width="7"/>
      <circle cx="46" cy="46" r="38" fill="none" stroke="${c}" stroke-width="7" stroke-linecap="round" stroke-dasharray="${circ * r.score / 100} ${circ}" transform="rotate(-90 46 46)"/>
      <text class="big" x="46" y="50" text-anchor="middle">${r.score}</text><text class="lab" x="46" y="66" text-anchor="middle">${lab}</text></svg>
      <div>${rows}</div></div>
    ${missing.length ? `<div class="strip-l" style="margin-top:8px"><span>${missing.join(", ")} not synced yet; left out of the score.</span></div>` : ""}
    <div class="strip">${strip}</div><div class="strip-l"><span>14 days ago</span><span>today</span></div></div>`;
})();

// ---- this week
(() => {
  if (!t) return;
  const wk = D.days.filter(d => d.week === t.week);
  const icon = { done: ["var(--good)", "✓"], short: ["var(--warning)", "◐"], missed: ["var(--critical)", "✕"], extra: ["var(--hud)", "+"],
                 rest: ["var(--muted)", "–"], pending: ["var(--hud)", "●"], upcoming: ["var(--muted)", "○"] };
  const cells = wk.map(d => {
    const [c, s] = icon[d.status];
    const warn = d.capOk === false ? `<div style="font-size:11px;color:var(--warning)">HR high</div>` : "";
    return `<div class="day${d.date === today ? " now" : ""}" title="${d.title}"><div class="dw">${d.dow.toUpperCase()}</div><div class="km">${d.km || "–"}</div><div class="st" style="color:${c}">${s}</div>${warn}</div>`;
  }).join("");
  const due = wk.filter(d => d.km && ["done", "short", "missed"].includes(d.status));
  const done = due.filter(d => d.status === "done").length;
  const kmPlan = wk.reduce((s, d) => s + (d.km || 0), 0), kmRan = wk.reduce((s, d) => s + (d.ran || 0), 0);
  const easy = wk.filter(d => d.capOk !== undefined);
  const easyOk = easy.filter(d => d.capOk).length;
  document.getElementById("week").innerHTML = `<div class="box"><div class="k"><span>This week · W${t.week}</span><span>${t.phase}</span></div>
    <div class="week">${cells}</div>
    <div class="wsum">${due.length ? `<b>${done} of ${due.length}</b> runs done so far` : "No runs due yet"} · <b>${kmRan.toFixed(1)}</b> of ${kmPlan.toFixed(1)} km${easy.length ? ` · easy runs under ${D.cap} bpm: <b>${easyOk} of ${easy.length}</b>` : ""}</div>
    <div class="wsum" style="color:var(--muted);font-size:13px">✓ done · ◐ short · ✕ missed · + extra · ● today · ○ upcoming</div></div>`;
})();

// ---- on track
(() => {
  const next = D.checkpoints.find(c => c.date >= today);
  const last = [...D.checkpoints].reverse().find(c => c.date < today && c.result && c.result.status === "ok");
  const strip = s => s.replace(/^0:/, "");
  let p = "";
  if (next) p += `Next checkpoint <b>${wd(next.date)} ${md(next.date)}</b>: ${next.name}. On the 3:00 path: <b>${next.target}</b>. Your fitness now: ${next.now}.`;
  if (last) p += ` Last: ${last.name} in <b>${strip(last.result.time)}</b> (path ${last.target}).`;
  document.getElementById("track").innerHTML = `<div class="box track"><div class="k"><span>On track for 3:00?</span><span>${Math.round((new Date(D.race + "T12:00") - now) / 864e5)} days</span></div>
    <div class="row"><span><span class="big">${D.predictM.replace(/:\\d\\d$/, "")}</span> <span class="goal">predicted</span></span><span class="goal">goal <b style="color:var(--text)">3:00</b></span></div>
    <p>${p}</p><p><a href="progress.html">See the trend and every checkpoint ›</a></p></div>`;
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
