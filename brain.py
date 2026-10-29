"""Read data/ and config.json, and write brain.html: your training as a glowing 3D graph in an "athlete OS"."""
import datetime as dt
import json
import os

from build import ROOT, TODAY, day, hr_load, load, mean, sport, week_start
from commander import KM_PER_MI, ewma

OUT = os.path.join(ROOT, "brain.html")


def kind(type_key):
    """Sport bucket for colouring nodes."""
    if "run" in type_key:
        return "run"
    if "cycl" in type_key or "bik" in type_key or "ride" in type_key:
        return "bike"
    if "strength" in type_key or "weight" in type_key or "lift" in type_key:
        return "lift"
    if "swim" in type_key:
        return "swim"
    return "other"


def hm(h):
    return f"{int(h)}h {round(h % 1 * 60):02d}m"


def build():
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    acts = sorted(load("activities.json", []), key=lambda a: a["startTimeLocal"])
    daily = load("daily.json", {})
    sleep = load("sleep.json", {})
    hrv = load("hrv.json", {})
    state = load("state.json", {})
    race = min((r for r in cfg["races"] if day(r["date"]) >= TODAY), key=lambda r: r["date"], default=None)

    # --- graph: activities hang off their week; weeks chain from first workout to today
    first_week = week_start(day(acts[0]["startTimeLocal"])) if acts else week_start(TODAY)
    n_weeks = (week_start(TODAY) - first_week).days // 7 + 1
    week_labels = [(first_week + dt.timedelta(weeks=i)).isoformat() for i in range(n_weeks)]
    nodes = []
    for a in acts:
        d = day(a["startTimeLocal"])
        nodes.append({
            "id": a["activityId"], "w": (week_start(d) - first_week).days // 7,
            "k": kind(a["activityType"]["typeKey"]),
            "type": "golf" if a["activityType"]["typeKey"] == "walking" else a["activityType"]["typeKey"].replace("_", " "),
            "name": a.get("activityName") or "", "d": a["startTimeLocal"][:16],
            "min": round((a.get("duration") or 0) / 60, 1),
            "mi": round((a.get("distance") or 0) / 1000 / KM_PER_MI, 2),
            "hr": a.get("averageHR") and round(a["averageHR"]),
        })
    runs = [n for n in nodes if n["k"] == "run"]
    longest = max(runs, key=lambda n: n["mi"]) if runs else None
    counts = {}
    for n in nodes:
        counts[n["k"]] = counts.get(n["k"], 0) + 1

    # --- vitals (only what this watch actually records)
    since = dt.date.fromisoformat(state.get("since", (TODAY - dt.timedelta(days=365)).isoformat()))
    iso = [(since + dt.timedelta(days=i)).isoformat() for i in range((TODAY - since).days + 1)]
    dig = lambda d, a, b: ((daily.get(d) or {}).get(a) or {}).get(b)
    bb = next((dig(d, "bodyBattery", "maxValue") for d in reversed(iso[-2:]) if dig(d, "bodyBattery", "maxValue") is not None), None)
    rhr = [dig(d, "heartRate", "restingValue") for d in iso]
    rhr_now = next((v for v in reversed(rhr[-2:]) if v is not None), None)
    rhr7 = mean(rhr[-8:-1])
    last_sleep = max((d for d in sleep if sleep[d].get("sleepTimeSeconds")), default=None)
    sleep_h = sleep[last_sleep]["sleepTimeSeconds"] / 3600 if last_sleep and (TODAY - day(last_sleep)).days <= 1 else None
    hrv_last = hrv.get(max(hrv)) if hrv else None

    by_day = {}
    for a in acts:
        if a["activityType"]["typeKey"] != "walking":  # golf rounds aren't training
            d = a["startTimeLocal"][:10]
            by_day[d] = by_day.get(d, 0) + (a.get("activityTrainingLoad") or hr_load(a))
    ctl, atl = ewma([by_day.get(d, 0) for d in iso], 42), ewma([by_day.get(d, 0) for d in iso], 7)
    form = ctl[-1] - atl[-1]

    wk_mi = {}
    for n in runs:
        wk_mi[n["w"]] = wk_mi.get(n["w"], 0) + n["mi"]
    this_w = n_weeks - 1
    mi_now = wk_mi.get(this_w, 0)
    mi_avg = sum(wk_mi.get(this_w - i, 0) for i in range(1, 5)) / 4

    def lvl(good, warn):
        return "good" if good else "warn" if warn else "bad"

    vitals = []
    if bb is not None:
        vitals.append({"k": "Body Battery", "v": f"{bb}", "u": "/100", "s": lvl(bb >= 70, bb >= 40), "note": "overnight charge"})
    if hrv_last and hrv_last.get("lastNightAvg") and hrv_last.get("baseline"):
        v, b = hrv_last["lastNightAvg"], hrv_last["baseline"]
        vitals.append({"k": "HRV", "v": f"{v}", "u": "ms", "s": lvl(b["balancedLow"] <= v <= b["balancedUpper"], v >= b["balancedLow"] * 0.9),
                       "note": f"baseline {b['balancedLow']}–{b['balancedUpper']}"})
    if sleep_h is not None:
        vitals.append({"k": "Sleep", "v": hm(sleep_h), "u": "", "s": lvl(sleep_h >= 7, sleep_h >= 6), "note": "last night"})
    if rhr_now is not None and rhr7:
        diff = rhr_now - rhr7
        vitals.append({"k": "Resting HR", "v": f"{rhr_now}", "u": "bpm", "s": lvl(diff < 3, diff < 5), "note": f"{diff:+.0f} vs 7-day avg"})
    vitals.append({"k": "Training form", "v": f"{form:+.0f}", "u": "", "s": lvl(-10 <= form <= 15, -25 <= form), "note": f"fitness {ctl[-1]:.0f} · fatigue {atl[-1]:.0f}"})
    vitals.append({"k": "Miles this week", "v": f"{mi_now:.1f}", "u": "mi", "s": lvl(mi_now >= mi_avg, mi_now >= mi_avg / 2), "note": f"4-wk avg {mi_avg:.1f}"})

    # --- directives: score each candidate, keep the top 3
    zones = [0.0] * 5
    for a in acts:
        if a["activityType"]["typeKey"] != "walking" and (TODAY - day(a["startTimeLocal"])).days < 28:
            for i in range(5):
                zones[i] += (a.get(f"hrTimeInZone_{i + 1}") or 0)
    easy = (zones[0] + zones[1]) / sum(zones) if sum(zones) else None
    runs14 = len({n["d"][:10] for n in runs if (TODAY - day(n["d"])).days < 14})
    cands = []
    if rhr_now and rhr7 and rhr_now - rhr7 >= 3:
        cands.append((10, f"Keep today easy: resting HR is {rhr_now - rhr7:+.0f} bpm. Run 30–40 min in zone 2, or rest."))
    if sleep_h is not None and sleep_h < 7:
        cands.append((8, f"Get to bed early: only {hm(sleep_h)} of sleep last night."))
    if bb is not None and bb < 40:
        cands.append((7, f"Low battery ({bb}/100): skip intensity today."))
    if form < -25:
        cands.append((9, "Take a recovery day: fatigue is well above fitness."))
    if easy is not None and easy < 0.6:
        cands.append((6, f"Slow down: only {easy:.0%} of the last 4 weeks was easy. Run most miles in zone 2."))
    if runs14 < 4:
        cands.append((5, f"Rebuild the habit: {runs14} runs in 2 weeks. Aim for 3 runs this week."))
    if mi_now < mi_avg:
        cands.append((4, f"{mi_avg - mi_now:.1f} more miles this week to match your 4-week average."))
    if race:
        cands.append((3, f"{(day(race['date']) - TODAY).days} days to the {race['name'].lower()}: lock in a long run each weekend."))
    cands.append((1, "Train as planned: all systems nominal."))
    directives = [t for _, t in sorted(cands, key=lambda c: -c[0])[:3]]

    # --- command deck responses
    good = sum(v["s"] == "good" for v in vitals)
    recovery = (f"{good} of {len(vitals)} vitals in range. " +
                " · ".join(f"{v['k']} {v['v']} {v['u']}".strip() for v in vitals[:4]) +
                (". Verdict: go easy today." if any(v["s"] == "bad" for v in vitals) else ". Verdict: cleared to train."))
    hours = sum(n["min"] for n in nodes if n["w"] == this_w and n["type"] != "golf") / 60
    sessions = sum(1 for n in nodes if n["w"] == this_w and n["type"] != "golf")
    recap = f"This week: {sessions} session{'' if sessions == 1 else 's'}, {mi_now:.1f} run miles, {hm(hours)} of training (golf excluded). 4-week average is {mi_avg:.1f} mi."
    long8 = max((n["mi"] for n in runs if (TODAY - day(n["d"])).days < 56), default=0)
    race_week = (f"{race['name']} on {day(race['date']).strftime('%b %-d')}: race week starts "
                 f"{(day(race['date']) - dt.timedelta(days=6)).strftime('%b %-d')}. Longest run in the last 8 weeks: "
                 f"{long8:.1f} mi of {race['distance_km'] / KM_PER_MI:.1f}.") if race else "No upcoming race in config.json."

    payload = {
        "race": race and {"name": race["name"], "date": race["date"]},
        "weeks": week_labels, "nodes": nodes, "longest": longest and longest["id"], "counts": counts,
        "vitals": vitals, "directives": directives,
        "deck": {"recovery": recovery, "plan": " ".join(f"{i + 1}. {d}" for i, d in enumerate(directives)),
                 "race": race_week, "recap": recap},
    }
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    with open(OUT, "w") as f:
        f.write(TEMPLATE.replace("__DATA__", data))
    print(f"Athlete OS written: {OUT}")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Athlete OS</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600;800&display=swap" rel="stylesheet">
<style>
:root {
  color-scheme: dark;
  --bg: #07040d;
  --text: #ece6f5;
  --text-2: #a99fbd;
  --muted: #6e6482;
  --line: rgba(196, 160, 255, 0.14);
  --panel: rgba(16, 10, 28, 0.62);
  --gold: #f5c451;
  --green: #3dff9a;
  --red: #ff5a6e;
  --run: #3dff9a;
  --bike: #4d8dff;
  --lift: #f5c451;
  --swim: #2fd9e8;
  --other: #8a8f98;
  --mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; }
body {
  font-family: var(--mono); color: var(--text); overflow: hidden;
  background: radial-gradient(ellipse 80% 70% at 50% 45%, #1e0f38 0%, #0d0619 55%, var(--bg) 100%);
}
#stars { position: fixed; inset: 0; z-index: 0; }
.floor {
  position: fixed; left: -50%; right: -50%; bottom: -10%; height: 60%; z-index: 0; pointer-events: none;
  background-image: linear-gradient(rgba(196,160,255,0.22) 1px, transparent 1px), linear-gradient(90deg, rgba(196,160,255,0.22) 1px, transparent 1px);
  background-size: 60px 60px;
  transform: perspective(500px) rotateX(72deg); transform-origin: bottom center;
  -webkit-mask-image: linear-gradient(to top, #000 0%, transparent 85%); mask-image: linear-gradient(to top, #000 0%, transparent 85%);
}
.os { position: relative; z-index: 1; height: 100vh; display: grid; grid-template-rows: auto 1fr; }

/* top bar */
.top { display: flex; align-items: center; gap: 22px; padding: 12px 20px; border-bottom: 1px solid var(--line); background: rgba(7,4,13,0.5); backdrop-filter: blur(6px); }
.logo { display: flex; align-items: center; gap: 10px; font-weight: 800; letter-spacing: 0.3em; font-size: 14px; }
.logo i { width: 10px; height: 10px; border-radius: 50%; background: var(--gold); box-shadow: 0 0 12px var(--gold); }
.status { font-size: 11px; letter-spacing: 0.14em; color: var(--text-2); display: flex; gap: 16px; flex-wrap: wrap; }
.status b { color: var(--green); font-weight: 600; }
.status .g { color: var(--gold); }
.clock { margin-left: auto; font-size: 15px; letter-spacing: 0.12em; color: var(--gold); font-variant-numeric: tabular-nums; }

/* layout */
.main { display: grid; grid-template-columns: 300px 1fr 280px; min-height: 0; }
.rail { padding: 16px; display: flex; flex-direction: column; gap: 14px; overflow-y: auto; min-height: 0; }
.box { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 14px; backdrop-filter: blur(4px); }
.lbl { font-size: 10px; letter-spacing: 0.22em; text-transform: uppercase; color: var(--muted); }
.north .big { font-size: 64px; font-weight: 800; color: var(--gold); line-height: 1; margin-top: 8px; text-shadow: 0 0 24px rgba(245,196,81,0.45); }
.north .big small { font-size: 14px; font-weight: 400; color: var(--text-2); margin-left: 6px; text-shadow: none; }
.north .sub { font-size: 12px; color: var(--text-2); margin-top: 6px; }
.vital { display: grid; grid-template-columns: 10px 1fr auto; gap: 4px 10px; align-items: baseline; padding: 8px 0; border-bottom: 1px solid var(--line); }
.vital:last-child { border-bottom: 0; }
.vital i { width: 8px; height: 8px; border-radius: 50%; align-self: center; }
.vital .k { font-size: 12px; color: var(--text-2); }
.vital .v { font-size: 17px; font-weight: 600; text-align: right; }
.vital .v small { font-size: 11px; color: var(--muted); font-weight: 400; margin-left: 3px; }
.vital .n { grid-column: 2 / 4; font-size: 10.5px; color: var(--muted); margin-top: -2px; }
.good { color: var(--green); } .warn { color: var(--gold); } .bad { color: var(--red); }
ol.dir { margin: 8px 0 0; padding: 0; list-style: none; counter-reset: d; }
ol.dir li { counter-increment: d; display: grid; grid-template-columns: 22px 1fr; gap: 6px; padding: 7px 0; font-size: 12.5px; line-height: 1.45; border-bottom: 1px solid var(--line); }
ol.dir li:last-child { border-bottom: 0; }
ol.dir li::before { content: counter(d, decimal-leading-zero); color: var(--gold); font-weight: 600; }

/* center */
.center { position: relative; min-width: 0; min-height: 0; }
#graph { position: absolute; inset: 0; width: 100%; height: 100%; cursor: grab; touch-action: none; }
#graph.drag { cursor: grabbing; }
.callout { position: absolute; pointer-events: none; min-width: 190px; padding: 10px 12px; border: 1px solid var(--gold); border-radius: 8px; background: rgba(20, 12, 4, 0.82); box-shadow: 0 0 22px rgba(245,196,81,0.25); font-size: 12px; }
.callout .t { color: var(--gold); font-size: 10px; letter-spacing: 0.2em; margin-bottom: 4px; }
.callout .nm { font-weight: 600; font-size: 13px; margin-bottom: 4px; }
.callout .row { display: flex; justify-content: space-between; gap: 14px; color: var(--text-2); }
.callout .row b { color: var(--text); font-weight: 600; }
.primary { position: absolute; left: 50%; bottom: 18px; transform: translateX(-50%); text-align: center; pointer-events: none; }
.primary .lbl { color: var(--gold); }
.primary .count { font-size: 30px; font-weight: 800; letter-spacing: 0.08em; margin-top: 4px; font-variant-numeric: tabular-nums; text-shadow: 0 0 18px rgba(245,196,81,0.4); }
.primary .count span { color: var(--muted); font-weight: 300; font-size: 16px; margin: 0 4px 0 2px; }
.hint { position: absolute; top: 12px; left: 50%; transform: translateX(-50%); font-size: 10px; letter-spacing: 0.18em; color: var(--muted); pointer-events: none; white-space: nowrap; }

/* right rail */
.deck { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 10px; }
.deck button, .newchat { font-family: var(--mono); font-size: 11.5px; color: var(--text); background: rgba(196,160,255,0.06); border: 1px solid var(--line); border-radius: 8px; padding: 10px 8px; cursor: pointer; text-align: left; transition: border-color .15s, background .15s; }
.deck button:hover, .newchat:hover { border-color: var(--gold); background: rgba(245,196,81,0.08); }
.deck button span { display: block; color: var(--gold); font-size: 15px; margin-bottom: 3px; }
.newchat { width: 100%; text-align: center; border-style: dashed; color: var(--gold); }
.out { margin-top: 10px; font-size: 12px; line-height: 1.5; color: var(--text-2); min-height: 54px; border-left: 2px solid var(--gold); padding-left: 10px; }
.out b { color: var(--text); }
.search { width: 100%; font-family: var(--mono); font-size: 12.5px; color: var(--text); background: rgba(7,4,13,0.6); border: 1px solid var(--line); border-radius: 8px; padding: 10px; }
.search:focus { outline: 1px solid var(--gold); }
.found { font-size: 11px; color: var(--muted); margin-top: 6px; min-height: 14px; }
#legend > div { display: flex; align-items: center; gap: 8px; padding: 5px 0; font-size: 12.5px; }
.legend i { width: 10px; height: 10px; border-radius: 50%; box-shadow: 0 0 8px currentColor; }
.legend b { margin-left: auto; font-weight: 600; }
#tip { position: fixed; z-index: 9; pointer-events: none; opacity: 0; background: rgba(12,7,22,0.95); border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; font-size: 12px; min-width: 170px; }
#tip .t { color: var(--muted); font-size: 10.5px; margin-bottom: 3px; }
#tip .r { display: flex; justify-content: space-between; gap: 14px; color: var(--text-2); }
#tip .r b { color: var(--text); }

@media (max-width: 1100px) { .main { grid-template-columns: 260px 1fr; } .right { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); } body { overflow: auto; } .os { height: auto; } .center { min-height: 560px; } }
@media (max-width: 720px) {
  .top { flex-wrap: wrap; gap: 8px 16px; padding: 10px 16px; }
  .main { grid-template-columns: 1fr; }
  .center { order: -1; min-height: 70vh; }
  .rail { padding: 12px 16px; }
  .right { grid-template-columns: 1fr; }
  .primary .count { font-size: 22px; }
  .hint { display: none; }
}
</style>
</head>
<body>
<canvas id="stars"></canvas>
<div class="floor"></div>
<div class="os">
  <div class="top">
    <div class="logo"><i></i>ATHLETE · OS</div>
    <div class="status"><span>CORE <b>IDLE</b></span><span>GARMIN <b>ONLINE</b></span><span><span class="g" id="nnodes"></span> NODES</span></div>
    <div class="clock" id="clock"></div>
  </div>
  <div class="main">
    <div class="rail left">
      <div class="box north">
        <div class="lbl">North Star</div>
        <div class="big" id="ns-days"></div>
        <div class="sub" id="ns-sub"></div>
      </div>
      <div class="box">
        <div class="lbl">Body vitals</div>
        <div id="vitals"></div>
      </div>
      <div class="box">
        <div class="lbl">Directives · today</div>
        <ol class="dir" id="dirs"></ol>
      </div>
    </div>
    <div class="center">
      <canvas id="graph"></canvas>
      <div class="hint">DRAG TO ROTATE · HOVER A NODE</div>
      <div class="callout" id="callout"></div>
      <div class="primary">
        <div class="lbl">Primary directive · days to the start line</div>
        <div class="count" id="count"></div>
      </div>
    </div>
    <div class="rail right">
      <div class="box">
        <div class="lbl">Command deck</div>
        <div class="deck">
          <button data-c="recovery"><span>◎</span>Recovery check</button>
          <button data-c="plan"><span>▤</span>Plan today</button>
          <button data-c="watch"><span>⌚</span>Send to watch</button>
          <button data-c="race"><span>⚑</span>Race week</button>
          <button data-c="recap"><span>↺</span>Weekly recap</button>
          <button data-c="coach"><span>✉</span>Ask my coach</button>
        </div>
        <div class="out" id="out">Select a command.</div>
      </div>
      <button class="newchat" id="newchat">+ new OS chat</button>
      <div class="box">
        <div class="lbl">Search nodes</div>
        <input class="search" id="search" placeholder="run, golf, Oct, Ottawa…" style="margin-top:10px" autocomplete="off">
        <div class="found" id="found"></div>
      </div>
      <div class="box legend">
        <div class="lbl" style="padding:0 0 4px">Legend</div>
        <div id="legend"></div>
      </div>
    </div>
  </div>
</div>
<div id="tip"></div>
<script>
const D = __DATA__;
const $ = (s) => document.querySelector(s);
const COLORS = { run: "#3dff9a", bike: "#4d8dff", lift: "#f5c451", swim: "#2fd9e8", other: "#8a8f98" };
const NAMES = { run: "Run", bike: "Bike", lift: "Lift", swim: "Swim", other: "Other" };
const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const fmtD = (s) => { const d = new Date(s.slice(0, 10) + "T00:00:00"); return `${MON[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`; };
const hm = (m) => `${Math.floor(m / 60)}h ${String(Math.round(m % 60)).padStart(2, "0")}m`;
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------- static rails ---------- */
$("#nnodes").textContent = D.nodes.length + D.weeks.length;
const raceDay = D.race ? new Date(D.race.date + "T00:00:00") : null;
function tick() {
  const now = new Date();
  $("#clock").textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  if (raceDay) {
    let s = Math.max(0, Math.floor((raceDay - now) / 1000));
    const d = Math.floor(s / 86400); s %= 86400;
    const h = Math.floor(s / 3600); s %= 3600;
    const m = Math.floor(s / 60); s %= 60;
    const p = (x) => String(x).padStart(2, "0");
    $("#count").innerHTML = `${d}<span>d</span>${p(h)}<span>h</span>${p(m)}<span>m</span>${p(s)}<span>s</span>`;
    $("#ns-days").innerHTML = `${Math.round((raceDay - new Date(now.toDateString())) / 864e5)}<small>days</small>`;
  }
}
tick(); setInterval(tick, 1000);
$("#ns-sub").textContent = D.race ? `${D.race.name} · ${fmtD(D.race.date)}` : "Set a race in config.json";
$("#vitals").innerHTML = D.vitals.map((v) => `<div class="vital"><i style="background:var(--${v.s === "good" ? "green" : v.s === "warn" ? "gold" : "red"})"></i><span class="k">${v.k}</span><span class="v ${v.s}">${v.v}<small>${v.u}</small></span><span class="n">${v.note} · ${v.s === "good" ? "good" : v.s === "warn" ? "watch" : "off"}</span></div>`).join("");
$("#dirs").innerHTML = D.directives.map((d) => `<li><span>${d}</span></li>`).join("");
$("#legend").innerHTML = Object.keys(COLORS).filter((k) => D.counts[k]).map((k) => `<div style="color:${COLORS[k]}"><i style="background:${COLORS[k]}"></i><span style="color:var(--text)">${NAMES[k]}${k === "other" ? " (golf, yoga…)" : ""}</span><b style="color:var(--text)">${D.counts[k]}</b></div>`).join("");

/* command deck: computed answers; anything that would change data or send messages isn't connected */
const DECK = {
  recovery: D.deck.recovery, plan: D.deck.plan, race: D.deck.race, recap: D.deck.recap,
  watch: "Not connected: this OS reads your Garmin data but can't change your watch.",
  coach: "Opening your coach view (coach.html)…",
};
document.querySelectorAll(".deck button").forEach((b) => b.addEventListener("click", () => {
  const c = b.dataset.c;
  $("#out").innerHTML = `<b>${b.textContent.slice(1).trim()}</b> › ${DECK[c]}`;
  if (c === "coach") window.open("coach.html", "_blank");
}));
$("#newchat").addEventListener("click", () => { $("#out").innerHTML = "<b>New OS chat</b> › Chat isn't available in this offline file. Ask Claude in the Claude app."; });

/* ---------- star field ---------- */
(function () {
  const c = $("#stars"), x = c.getContext("2d"), dpr = devicePixelRatio || 1;
  function draw() {
    c.width = innerWidth * dpr; c.height = innerHeight * dpr; c.style.width = innerWidth + "px"; c.style.height = innerHeight + "px";
    let seed = 7; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    for (let i = 0; i < 260; i++) {
      x.fillStyle = `rgba(230,220,255,${0.15 + rnd() * 0.5})`;
      const r = rnd() < 0.08 ? 1.4 : 0.7;
      x.beginPath(); x.arc(rnd() * c.width, rnd() * c.height * 0.75, r * dpr, 0, 6.29); x.fill();
    }
  }
  draw(); addEventListener("resize", draw);
})();

/* ---------- 3D graph ---------- */
const cv = $("#graph"), ctx = cv.getContext("2d");
const NW = D.weeks.length, R = 1;
function hash(n) { let h = Number(String(n).slice(-9)) || 1; return () => ((h = (h * 48271) % 2147483647) / 2147483647); }
const weeks = D.weeks.map((w, i) => {
  const t = NW > 1 ? i / (NW - 1) : 0.5;
  const th = Math.acos(1 - 2 * (0.04 + t * 0.92)), ph = t * Math.PI * 2 * 7;
  return { x: R * Math.sin(th) * Math.cos(ph), y: R * Math.cos(th), z: R * Math.sin(th) * Math.sin(ph), label: w, i };
});
const nodes = D.nodes.map((n) => {
  const r = hash(n.id), w = weeks[n.w];
  const out = 1.12 + r() * 0.16, jx = (r() - 0.5) * 0.16, jy = (r() - 0.5) * 0.16, jz = (r() - 0.5) * 0.16;
  return { ...n, x: w.x * out + jx, y: w.y * out + jy, z: w.z * out + jz, size: 1.6 + Math.sqrt(Math.max(n.min, 1)) * 0.55, color: COLORS[n.k] };
});
const longest = nodes.find((n) => n.id === D.longest);

// glow sprites per colour, drawn with additive blending
const sprites = {};
function sprite(color) {
  if (sprites[color]) return sprites[color];
  const s = document.createElement("canvas"); s.width = s.height = 64;
  const g = s.getContext("2d"), grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grd.addColorStop(0, "rgba(255,255,255,1)"); grd.addColorStop(0.18, color); grd.addColorStop(0.45, color + "55"); grd.addColorStop(1, color + "00");
  g.fillStyle = grd; g.fillRect(0, 0, 64, 64);
  return (sprites[color] = s);
}

let W = 0, H = 0, dpr = 1, yaw = 0.6, pitch = 0.32, drag = null, hover = null, query = "";
function resize() {
  dpr = devicePixelRatio || 1; W = cv.clientWidth; H = cv.clientHeight;
  cv.width = W * dpr; cv.height = H * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
function project(p) {
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
  const x1 = p.x * cy - p.z * sy, z1 = p.x * sy + p.z * cy;
  const y2 = p.y * cp - z1 * sp, z2 = p.y * sp + z1 * cp;
  const cam = 3.6, f = Math.min(W, H * 0.9) * 0.3 * cam, s = f / (cam - z2);
  return { sx: W / 2 + x1 * s, sy: H * 0.46 - y2 * s, z: z2, s: (cam / (cam - z2)) * Math.min(W, H) / 760 };
}
const match = (n) => !query || `${n.type} ${n.name} ${fmtD(n.d)} ${NAMES[n.k]}`.toLowerCase().includes(query);

function frame(t) {
  if (!drag && !reduced) yaw += 0.0016;
  ctx.clearRect(0, 0, W, H);
  ctx.globalCompositeOperation = "lighter";

  // core
  const o = project({ x: 0, y: 0, z: 0 }), cr = Math.min(W, H) * 0.32;
  let g = ctx.createRadialGradient(o.sx, o.sy, 0, o.sx, o.sy, cr);
  g.addColorStop(0, "rgba(255,240,200,0.55)"); g.addColorStop(0.12, "rgba(245,196,81,0.28)"); g.addColorStop(0.4, "rgba(150,90,255,0.10)"); g.addColorStop(1, "rgba(150,90,255,0)");
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(o.sx, o.sy, cr, 0, 6.29); ctx.fill();

  const pw = weeks.map(project);
  nodes.forEach((n) => (n.p = project(n)));

  // links: week → week spine, activity → week
  ctx.lineWidth = 1;
  for (let i = 1; i < pw.length; i++) {
    const a = pw[i - 1], b = pw[i], depth = (a.z + b.z) / 2;
    ctx.strokeStyle = `rgba(245,196,81,${0.12 + (depth + 1.3) * 0.12})`;
    ctx.beginPath(); ctx.moveTo(a.sx, a.sy); ctx.lineTo(b.sx, b.sy); ctx.stroke();
  }
  nodes.forEach((n) => {
    const w = pw[n.w], on = match(n);
    ctx.strokeStyle = n.color + (on ? "38" : "0c");
    ctx.beginPath(); ctx.moveTo(w.sx, w.sy); ctx.lineTo(n.p.sx, n.p.sy); ctx.stroke();
  });
  pw.forEach((w) => { ctx.fillStyle = `rgba(245,196,81,${0.25 + (w.z + 1.3) * 0.2})`; ctx.beginPath(); ctx.arc(w.sx, w.sy, 1.4, 0, 6.29); ctx.fill(); });

  // nodes, far to near
  [...nodes].sort((a, b) => a.p.z - b.p.z).forEach((n) => {
    const on = match(n), r = n.size * n.p.s * (n === hover ? 1.6 : 1);
    ctx.globalAlpha = on ? 0.55 + (n.p.z + 1.4) * 0.2 : 0.08;
    const sz = r * 5.5;
    ctx.drawImage(sprite(n.color), n.p.sx - sz / 2, n.p.sy - sz / 2, sz, sz);
  });
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = "source-over";

  // longest run ring + callout
  if (longest) {
    const p = longest.p, pulse = reduced ? 0 : Math.sin(t / 400) * 2;
    const rr = longest.size * p.s * 2.2 + 6 + pulse;
    ctx.strokeStyle = "#f5c451"; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(p.sx, p.sy, rr, 0, 6.29); ctx.stroke();
    ctx.setLineDash([3, 4]); ctx.beginPath(); ctx.arc(p.sx, p.sy, rr + 6, 0, 6.29); ctx.stroke(); ctx.setLineDash([]);
    const card = $("#callout"), cw = card.offsetWidth, ch = card.offsetHeight;
    let cx = p.sx + rr + 34, cyy = p.sy - ch - 20;
    if (cx + cw > W - 8) cx = p.sx - rr - 34 - cw;
    cyy = Math.max(30, Math.min(H - ch - 90, cyy));
    card.style.left = cx + "px"; card.style.top = cyy + "px";
    const ax = cx > p.sx ? cx : cx + cw, ay = cyy + ch / 2;
    ctx.strokeStyle = "rgba(245,196,81,0.7)"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(p.sx + (ax > p.sx ? rr : -rr) * 0.9, p.sy); ctx.lineTo(ax, ay); ctx.stroke();
  }
  // hover ring
  if (hover) {
    ctx.strokeStyle = hover.color; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(hover.p.sx, hover.p.sy, hover.size * hover.p.s * 2 + 6, 0, 6.29); ctx.stroke();
  }
  requestAnimationFrame(frame);
}
if (longest) {
  $("#callout").innerHTML = `<div class="t">◆ LONGEST RUN</div><div class="nm">${longest.name}</div>
    <div class="row"><span>Date</span><b>${fmtD(longest.d)}</b></div>
    <div class="row"><span>Distance</span><b>${longest.mi.toFixed(1)} mi</b></div>
    <div class="row"><span>Time</span><b>${(longest.min / 60).toFixed(2)} h</b></div>`;
} else $("#callout").style.display = "none";

/* interaction */
const tip = $("#tip");
function pick(e) {
  const r = cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
  let best = null, bd = 1e9;
  nodes.forEach((n) => {
    if (!n.p || !match(n)) return;
    const d = Math.hypot(n.p.sx - mx, n.p.sy - my), reach = Math.max(8, n.size * n.p.s * 2.2);
    if (d < reach && (d < bd || (best && n.p.z > best.p.z && d < reach))) { best = n; bd = d; }
  });
  return best;
}
cv.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, yaw, pitch, moved: false }; cv.setPointerCapture(e.pointerId); cv.classList.add("drag"); });
cv.addEventListener("pointermove", (e) => {
  if (drag) {
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
    yaw = drag.yaw + dx * 0.006; pitch = Math.max(-1.2, Math.min(1.2, drag.pitch + dy * 0.006));
    tip.style.opacity = 0; return;
  }
  hover = pick(e);
  if (!hover) { tip.style.opacity = 0; return; }
  const n = hover;
  tip.innerHTML = `<div class="t">${fmtD(n.d)} · ${n.d.slice(11)}</div><div style="color:${n.color};font-weight:600;margin-bottom:3px">${n.type}</div>
    <div class="r"><span>${n.name}</span></div>
    ${n.mi ? `<div class="r"><span>Distance</span><b>${n.mi.toFixed(2)} mi</b></div>` : ""}
    <div class="r"><span>Time</span><b>${hm(n.min)}</b></div>
    ${n.hr ? `<div class="r"><span>Avg HR</span><b>${n.hr} bpm</b></div>` : ""}
    <div class="r"><span>Week of</span><b>${fmtD(D.weeks[n.w]).replace(/, \d{4}$/, "")}</b></div>`;
  tip.style.opacity = 1;
  const tw = tip.offsetWidth, th = tip.offsetHeight;
  tip.style.left = Math.min(innerWidth - tw - 8, e.clientX + 14) + "px";
  tip.style.top = Math.min(innerHeight - th - 8, e.clientY + 14) + "px";
});
const endDrag = (e) => {
  if (drag && !drag.moved && e.pointerType !== "mouse") { hover = pick(e); }
  drag = null; cv.classList.remove("drag");
};
cv.addEventListener("pointerup", endDrag);
cv.addEventListener("pointercancel", endDrag);
cv.addEventListener("pointerleave", () => { hover = null; tip.style.opacity = 0; });
$("#search").addEventListener("input", (e) => {
  query = e.target.value.trim().toLowerCase();
  const n = nodes.filter(match).length;
  $("#found").textContent = query ? `${n} of ${nodes.length} nodes match` : "";
});

resize(); addEventListener("resize", resize);
requestAnimationFrame(frame);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    build()
