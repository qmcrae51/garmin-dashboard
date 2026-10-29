"""Read data/ and config.json, and write commander.html: a one-file "mission control" dashboard."""
import datetime as dt
import json
import math
import os

from build import DATA, ROOT, TODAY, day, hr_load, load, mean, sport, week_start

OUT = os.path.join(ROOT, "commander.html")
KM_PER_MI = 1.609344


def ewma(values, days):
    """Exponentially weighted average with the given time constant (the usual fitness/fatigue model)."""
    k, out, cur = 1 - math.exp(-1 / days), [], 0.0
    for v in values:
        cur += (v - cur) * k
        out.append(round(cur, 1))
    return out


def build():
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    acts = load("activities.json", [])
    daily = load("daily.json", {})
    sleep = load("sleep.json", {})
    hrv = load("hrv.json", {})
    fitness = load("fitness_age.json", {})
    state = load("state.json", {})

    since = dt.date.fromisoformat(state.get("since", (TODAY - dt.timedelta(days=365)).isoformat()))
    iso = [(since + dt.timedelta(days=i)).isoformat() for i in range((TODAY - since).days + 1)]
    last30 = iso[-30:]

    def series(fn, dates):
        return [fn(d) for d in dates]

    dget = lambda d, *path: _dig(daily.get(d) or {}, path)
    bb = series(lambda d: dget(d, "bodyBattery", "maxValue"), last30)
    rhr_all = series(lambda d: dget(d, "heartRate", "restingValue"), iso)
    stress = series(lambda d: dget(d, "stress", "avgLevel"), last30)
    sleep_h = series(lambda d: round(sleep[d]["sleepTimeSeconds"] / 3600, 2) if d in sleep else None, last30)
    hrv_v = series(lambda d: (hrv.get(d) or {}).get("lastNightAvg"), last30)

    # Fitness / fatigue / form from daily training load (Garmin's own load when present, else HR-zone load)
    garmin_load = any(a.get("activityTrainingLoad") for a in acts)
    by_day = {}
    for a in acts:
        if sport(a["activityType"]["typeKey"]) == "Golf":
            continue
        val = a.get("activityTrainingLoad") if garmin_load else hr_load(a)
        d = a["startTimeLocal"][:10]
        by_day[d] = by_day.get(d, 0) + (val or 0)
    loads = [round(by_day.get(d, 0), 1) for d in iso]
    ctl, atl = ewma(loads, 42), ewma(loads, 7)
    tsb = [round(c - a, 1) for c, a in zip(ctl, atl)]
    n = 120

    # weekly run miles, 16 weeks
    weeks = [week_start(TODAY) - dt.timedelta(weeks=i) for i in range(15, -1, -1)]
    wk = {w: 0.0 for w in weeks}
    for a in acts:
        if sport(a["activityType"]["typeKey"]) == "Run":
            w = week_start(day(a["startTimeLocal"]))
            if w in wk:
                wk[w] += (a.get("distance") or 0) / 1000 / KM_PER_MI

    log = [{
        "d": a["startTimeLocal"][:16], "type": a["activityType"]["typeKey"].replace("_", " "),
        "sport": sport(a["activityType"]["typeKey"]), "name": a.get("activityName") or "",
        "mi": round((a.get("distance") or 0) / 1000 / KM_PER_MI, 2), "min": round((a.get("duration") or 0) / 60, 1),
        "hr": a.get("averageHR") and round(a["averageHR"]),
        "load": round(a.get("activityTrainingLoad") or hr_load(a)),
    } for a in acts[:7]]

    # latest readings
    def latest(vals):
        for v in reversed(vals):
            if v is not None:
                return v
        return None
    rhr7 = mean(rhr_all[-8:-1])
    rhr_now = latest(rhr_all[-2:])
    sleep_last = latest(sleep_h[-2:])
    bb_now = latest(bb[-2:])
    stress_now = latest(stress[-2:])
    stress_avg = mean(stress)
    last_run = max((day(a["startTimeLocal"]) for a in acts if sport(a["activityType"]["typeKey"]) == "Run"), default=None)
    race = min((r for r in cfg["races"] if day(r["date"]) >= TODAY), key=lambda r: r["date"], default=None)

    # system alert: score each signal by how far off it is today, report the worst
    alerts = []
    if rhr_now and rhr7 and rhr_now - rhr7 >= 3:
        alerts.append((rhr_now - rhr7, f"Resting heart rate is {rhr_now} bpm, {rhr_now - rhr7:.0f} above your 7-day average of {rhr7:.0f}: you may be tired, stressed or getting sick, so keep today easy."))
    if sleep_last is not None and sleep_last < 6.5:
        alerts.append(((7 - sleep_last) * 4, f"You slept {int(sleep_last)}h {round(sleep_last % 1 * 60):02d}m last night, well short of 7 hours: plan an early night."))
    if bb_now is not None and bb_now < 50:
        alerts.append(((50 - bb_now) / 4, f"Body Battery only charged to {bb_now} overnight, so you're starting the day low on energy."))
    if tsb[-1] < -25:
        alerts.append((-tsb[-1] / 4, f"Form is {tsb[-1]:.0f}: fatigue is well above fitness, so a recovery day would help."))
    if last_run and (TODAY - last_run).days >= 5:
        alerts.append(((TODAY - last_run).days / 1.5, f"It's been {(TODAY - last_run).days} days since your last run, with {(day(race['date']) - TODAY).days if race else '?'} days to race day."))
    if stress_now and stress_avg and stress_now - stress_avg >= 10:
        alerts.append(((stress_now - stress_avg) / 3, f"Stress averaged {stress_now} yesterday, {stress_now - stress_avg:.0f} points above your 30-day norm."))
    alert = max(alerts)[1] if alerts else "All systems nominal: nothing is out of range today."

    payload = {
        "synced": state.get("last_pull", dt.datetime.now().isoformat(timespec="seconds")).replace("T", " ")[:16],
        "race": race and {"name": race["name"], "date": race["date"], "days": (day(race["date"]) - TODAY).days},
        "total": len(acts),
        "dates30": last30,
        "tiles": {
            "bb": {"now": bb_now, "series": bb},
            "hrv": {"series": hrv_v, "now": latest(hrv_v),
                    "baseline": (hrv.get(max(hrv)) or {}).get("baseline") if hrv else None},
            "rhr": {"now": rhr_now, "avg7": rhr7 and round(rhr7, 1), "series": rhr_all[-30:]},
            "sleep": {"now": sleep_last, "score": None, "series": sleep_h},
            "stress": {"now": stress_now, "avg": stress_avg and round(stress_avg), "series": stress},
            "fitness": {"age": fitness.get("fitnessAge") and round(fitness["fitnessAge"], 1),
                        "real": fitness.get("chronologicalAge"),
                        "best": fitness.get("achievableFitnessAge") and round(fitness["achievableFitnessAge"], 1)},
        },
        "pmc": {"dates": iso[-n:], "ctl": ctl[-n:], "atl": atl[-n:], "tsb": tsb[-n:], "load": loads[-n:],
                "source": "Garmin training load" if garmin_load else "heart-rate-zone load (your watch doesn't report Garmin training load)"},
        "weeks": {"labels": [w.isoformat() for w in weeks], "mi": [round(wk[w], 1) for w in weeks]},
        "log": log,
        "alert": alert,
    }
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    with open(OUT, "w") as f:
        f.write(TEMPLATE.replace("__DATA__", data))
    print(f"Mission control written: {OUT}")


def _dig(obj, path):
    for p in path:
        obj = (obj or {}).get(p)
    return obj


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Garmin Mission Control</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@500;700&display=swap" rel="stylesheet">
<style>
:root {
  color-scheme: dark;
  --bg: #050607;
  --panel: rgba(14, 17, 20, 0.92);
  --line: #1c2329;
  --grid: #161b20;
  --text: #e8edf0;
  --text-2: #a3adb5;
  --muted: #66727c;
  --green: #39ff88;
  --cyan: #29e7ff;
  --amber: #ffb020;
  --red: #ff4d5e;
  --violet: #b47bff;
  --mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  --sans: "Inter", system-ui, -apple-system, sans-serif;
}
* { box-sizing: border-box; }
html, body { margin: 0; }
body {
  background-color: var(--bg);
  background-image: radial-gradient(rgba(255,255,255,0.07) 1px, transparent 1px);
  background-size: 22px 22px;
  color: var(--text); font-family: var(--sans); min-height: 100vh;
}
.wrap { max-width: 1320px; margin: 0 auto; padding: 18px 24px 48px; }
.lbl { font-family: var(--mono); font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted); }

/* top bar */
.top { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 28px; padding: 14px 18px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); }
.title { font-family: var(--mono); font-weight: 700; font-size: 16px; letter-spacing: 0.2em; }
.title b { color: var(--green); }
.live { display: inline-flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 12px; letter-spacing: 0.14em; color: var(--green); }
.live i { width: 9px; height: 9px; border-radius: 50%; background: var(--green); box-shadow: 0 0 0 0 rgba(57,255,136,0.7); animation: pulse 1.8s infinite; }
@keyframes pulse { 70% { box-shadow: 0 0 0 9px rgba(57,255,136,0); } 100% { box-shadow: 0 0 0 0 rgba(57,255,136,0); } }
.stat { display: flex; flex-direction: column; gap: 2px; }
.stat .v { font-family: var(--mono); font-size: 18px; font-weight: 700; }
.top .spacer { flex: 1; }

/* panels */
.grid { display: grid; gap: 14px; margin-top: 14px; }
.tiles { grid-template-columns: repeat(6, 1fr); }
.bottom { grid-template-columns: 1.1fr 1.5fr 1fr; }
.grid > * { min-width: 0; }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; position: relative; }
.tile { border-top: 2px solid var(--accent); }
.tile .big { font-family: var(--mono); font-size: 34px; font-weight: 700; margin-top: 8px; line-height: 1; }
.tile .big small { font-size: 13px; color: var(--text-2); font-weight: 400; margin-left: 4px; }
.tile .sub { font-family: var(--mono); font-size: 12px; color: var(--text-2); margin-top: 8px; min-height: 30px; line-height: 1.35; }
.tile .na { font-family: var(--mono); font-size: 15px; color: var(--muted); margin-top: 14px; }
.spark { display: block; width: 100%; height: 40px; margin-top: 8px; overflow: visible; touch-action: pan-y; }
h2 { font-family: var(--mono); font-size: 12px; letter-spacing: 0.16em; text-transform: uppercase; margin: 0; font-weight: 500; }
.head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 6px 16px; margin-bottom: 10px; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; font-family: var(--mono); font-size: 12px; color: var(--text-2); }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.sw { width: 12px; height: 3px; border-radius: 2px; display: inline-block; }
.sw.box { height: 10px; width: 10px; }
.note { font-family: var(--mono); font-size: 11px; color: var(--muted); margin-top: 6px; }
.chart { display: block; overflow: visible; touch-action: pan-y; }
.chart .gl { stroke: var(--grid); }
.chart .zero { stroke: #3a444c; }
.chart .tk { fill: var(--muted); font-family: var(--mono); font-size: 11px; }
.chart .cross { stroke: var(--text-2); stroke-dasharray: 3 3; }

/* log */
.log { width: 100%; border-collapse: collapse; font-family: var(--mono); font-size: 12.5px; }
.log th { text-align: right; color: var(--muted); font-weight: 400; font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase; padding: 4px 6px; border-bottom: 1px solid var(--line); }
.log td { text-align: right; padding: 7px 6px; border-bottom: 1px solid var(--grid); white-space: nowrap; }
.log th:nth-child(-n+2), .log td:nth-child(-n+2) { text-align: left; }
.log td.t { color: var(--text-2); }
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 7px; }

/* alert */
.alert { border: 1px solid rgba(255,176,32,0.55); background: linear-gradient(180deg, rgba(255,176,32,0.12), rgba(255,176,32,0.03)); box-shadow: 0 0 24px rgba(255,176,32,0.12) inset; }
.alert h2 { color: var(--amber); display: flex; align-items: center; gap: 8px; }
.alert h2::before { content: "▲"; font-size: 11px; }
.alert p { font-size: 19px; line-height: 1.4; margin: 14px 0 0; font-weight: 500; }

#tip { position: fixed; z-index: 9; pointer-events: none; opacity: 0; transition: opacity .1s; background: #0b0e11; border: 1px solid #2c363e; border-radius: 6px; padding: 8px 10px; font-family: var(--mono); font-size: 12px; min-width: 150px; box-shadow: 0 6px 24px rgba(0,0,0,.6); }
#tip .t { color: var(--muted); font-size: 11px; letter-spacing: .1em; margin-bottom: 4px; text-transform: uppercase; }
#tip .r { display: flex; justify-content: space-between; gap: 14px; }
#tip .r span { display: inline-flex; align-items: center; gap: 6px; color: var(--text-2); }

@media (max-width: 1100px) { .tiles { grid-template-columns: repeat(3, 1fr); } .bottom { grid-template-columns: 1fr 1fr; } .bottom .alert { grid-column: 1 / -1; } }
@media (max-width: 640px) {
  .wrap { padding: 12px 16px 40px; }
  .tiles { grid-template-columns: 1fr 1fr; }
  .bottom { grid-template-columns: 1fr; }
  .tile .big { font-size: 28px; }
  .top .spacer { display: none; }
  .logwrap { overflow-x: auto; }
}
@media (prefers-reduced-motion: reduce) { .live i { animation: none; } }
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="title">GARMIN <b>//</b> MISSION CONTROL</div>
    <div class="live"><i></i>GARMIN LIVE</div>
    <div class="spacer"></div>
    <div class="stat"><span class="lbl">Last sync</span><span class="v" id="sync"></span></div>
    <div class="stat"><span class="lbl" id="race-lbl">Goal race</span><span class="v" id="race" style="color:var(--cyan)"></span></div>
    <div class="stat"><span class="lbl">Activities</span><span class="v" id="total"></span></div>
  </div>

  <div class="grid tiles" id="tiles"></div>

  <div class="panel" style="margin-top:14px">
    <div class="head">
      <h2>Fitness / Fatigue / Form · last 120 days</h2>
      <div class="legend">
        <span><i class="sw" style="background:var(--cyan)"></i>Fitness (42-day)</span>
        <span><i class="sw" style="background:var(--amber)"></i>Fatigue (7-day)</span>
        <span><i class="sw box" style="background:var(--green)"></i>Form +</span>
        <span><i class="sw box" style="background:var(--red)"></i>Form −</span>
      </div>
    </div>
    <div id="pmc"></div>
    <div class="note" id="pmc-note"></div>
  </div>

  <div class="grid bottom">
    <div class="panel">
      <div class="head"><h2>Weekly run miles · 16 wk</h2></div>
      <div id="weeks"></div>
    </div>
    <div class="panel">
      <div class="head"><h2>Activity log · last 7</h2></div>
      <div class="logwrap" id="log"></div>
    </div>
    <div class="panel alert">
      <h2>System alert</h2>
      <p id="alert"></p>
    </div>
  </div>
</div>
<div id="tip"></div>
<script>
const D = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const $ = (s) => document.querySelector(s);
const tip = $("#tip");
const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const toDate = (s) => new Date(s.slice(0, 10) + "T00:00:00");
const md = (s) => { const d = toDate(s); return `${MON[d.getMonth()]} ${d.getDate()}`; };
const hm = (h) => `${Math.floor(h)}h ${String(Math.round((h % 1) * 60)).padStart(2, "0")}m`;
const SPORT = { Run: "var(--cyan)", Ride: "var(--amber)", Golf: "var(--violet)", Other: "var(--text-2)" };

function el(tag, a, p) { const e = document.createElementNS(NS, tag); for (const k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; }
function text(p, x, y, s, anchor) { const t = el("text", { x, y, class: "tk", "text-anchor": anchor || "start" }, p); t.textContent = s; }
function showTip(html, e) {
  tip.innerHTML = html; tip.style.opacity = 1;
  const r = tip.getBoundingClientRect();
  let x = e.clientX + 14, y = e.clientY + 14;
  if (x + r.width > innerWidth - 8) x = e.clientX - r.width - 14;
  if (y + r.height > innerHeight - 8) y = e.clientY - r.height - 14;
  tip.style.left = Math.max(8, x) + "px"; tip.style.top = Math.max(8, y) + "px";
}
const hideTip = () => (tip.style.opacity = 0);
const row = (c, n, v) => `<div class="r"><span><i class="sw" style="background:${c}"></i>${n}</span><b>${v}</b></div>`;
function ticks(lo, hi, n) {
  const raw = (hi - lo || 1) / n, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw), out = [];
  for (let v = Math.floor(lo / step) * step; v <= Math.ceil(hi / step) * step + 1e-9; v += step) out.push(+v.toFixed(4));
  return out;
}

/* ---- top bar ---- */
$("#sync").textContent = `${md(D.synced)} ${D.synced.slice(11)}`;
if (D.race) { $("#race-lbl").textContent = D.race.name; $("#race").textContent = `T-${D.race.days} days`; }
else $("#race").textContent = "—";
$("#total").textContent = D.total;

/* ---- tiles ---- */
function spark(host, values, color, fmt, name) {
  const pts = values.map((v, i) => [i, v]).filter((p) => p[1] != null);
  if (pts.length < 2) return;
  const W = 200, H = 40, lo = Math.min(...pts.map((p) => p[1])), hi = Math.max(...pts.map((p) => p[1]));
  const X = (i) => (i / (values.length - 1)) * W, Y = (v) => H - 4 - ((v - lo) / (hi - lo || 1)) * (H - 8);
  const svg = el("svg", { class: "spark", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none" }, host);
  let d = "", pen = false;
  values.forEach((v, i) => { if (v == null) { pen = false; return; } d += (pen ? "L" : "M") + X(i) + "," + Y(v); pen = true; });
  el("path", { d, fill: "none", stroke: color, "stroke-width": 2, "vector-effect": "non-scaling-stroke", "stroke-linejoin": "round", style: `filter:drop-shadow(0 0 3px ${color})` }, svg);
  const cross = el("line", { y1: 0, y2: H, stroke: "#55606a", "stroke-width": 1, "vector-effect": "non-scaling-stroke", opacity: 0 }, svg);
  const move = (e) => {
    const r = svg.getBoundingClientRect();
    const i = Math.round(((e.clientX - r.left) / r.width) * (values.length - 1));
    let best = null;
    for (let k = 0; k < values.length; k++) for (const j of [i - k, i + k]) if (best == null && values[j] != null) best = j;
    if (best == null) return;
    cross.setAttribute("x1", X(best)); cross.setAttribute("x2", X(best)); cross.setAttribute("opacity", 1);
    showTip(`<div class="t">${md(D.dates30[best])}</div>${row(color, name, fmt(values[best]))}`, e);
  };
  svg.addEventListener("pointermove", move); svg.addEventListener("pointerdown", move);
  svg.addEventListener("pointerleave", () => { hideTip(); cross.setAttribute("opacity", 0); });
}
function tile(label, accent, big, sub, series, fmt) {
  const t = document.createElement("div");
  t.className = "panel tile"; t.style.setProperty("--accent", accent);
  t.innerHTML = `<div class="lbl">${label}</div>${big}<div class="sub">${sub}</div>`;
  $("#tiles").appendChild(t);
  if (series) spark(t, series, accent, fmt, label);
}
const T = D.tiles;
tile("Body Battery", "var(--green)",
  T.bb.now != null ? `<div class="big">${T.bb.now}<small>/ 100</small></div>` : `<div class="na">NO SIGNAL</div>`,
  "Overnight charge peak", T.bb.series, (v) => v);
const hrvBase = T.hrv.baseline;
tile("HRV · last night", "var(--violet)",
  T.hrv.now != null ? `<div class="big">${T.hrv.now}<small>ms</small></div>` : `<div class="na">NOT RECORDED</div>`,
  T.hrv.now != null && hrvBase ? `Baseline ${hrvBase.balancedLow}–${hrvBase.balancedUpper} ms` : "Your watch doesn't measure overnight HRV",
  T.hrv.now != null ? T.hrv.series : null, (v) => `${v} ms`);
const rd = T.rhr.now != null && T.rhr.avg7 ? T.rhr.now - T.rhr.avg7 : null;
tile("Resting HR", "var(--red)",
  T.rhr.now != null ? `<div class="big">${T.rhr.now}<small>bpm</small></div>` : `<div class="na">NO SIGNAL</div>`,
  rd == null ? "" : `<span style="color:${rd > 2 ? "var(--red)" : rd < -2 ? "var(--green)" : "var(--text-2)"}">${rd > 0 ? "+" : ""}${rd.toFixed(1)}</span> vs 7-day avg ${T.rhr.avg7}`,
  T.rhr.series, (v) => `${v} bpm`);
tile("Sleep", "var(--cyan)",
  T.sleep.now != null ? `<div class="big">${Math.floor(T.sleep.now)}<small>h</small> ${String(Math.round((T.sleep.now % 1) * 60)).padStart(2, "0")}<small>m</small></div>` : `<div class="na">NO SIGNAL</div>`,
  T.sleep.score != null ? `Score ${T.sleep.score}` : "Score: not provided by your watch",
  T.sleep.series, hm);
tile("Stress", "var(--amber)",
  T.stress.now != null ? `<div class="big">${T.stress.now}<small>avg</small></div>` : `<div class="na">NO SIGNAL</div>`,
  T.stress.avg ? `30-day norm ${T.stress.avg} · ${T.stress.now <= 25 ? "resting" : T.stress.now <= 50 ? "low" : T.stress.now <= 75 ? "medium" : "high"}` : "",
  T.stress.series, (v) => v);
tile("Fitness age", "var(--violet)",
  T.fitness.age != null ? `<div class="big">${T.fitness.age}<small>yrs</small></div>` : `<div class="na">NO SIGNAL</div>`,
  T.fitness.age != null ? `Actual ${T.fitness.real} · achievable ${T.fitness.best}<br><span style="color:var(--muted)">No history: Garmin gives today's value only</span>` : "", null);

/* ---- fitness / fatigue / form ---- */
function pmc() {
  const host = $("#pmc"); host.innerHTML = "";
  const P = D.pmc, W = host.clientWidth || 900, H = W < 500 ? 240 : 280, m = { l: 36, r: 10, t: 10, b: 24 };
  const vals = [...P.ctl, ...P.atl, ...P.tsb];
  const tk = ticks(Math.min(0, ...vals), Math.max(...vals), 5);
  const lo = tk[0], hi = tk[tk.length - 1], n = P.dates.length;
  const X = (i) => m.l + (i / (n - 1)) * (W - m.l - m.r);
  const Y = (v) => H - m.b - ((v - lo) / (hi - lo)) * (H - m.t - m.b);
  const svg = el("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, width: W, height: H }, host);
  tk.forEach((t) => { el("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), class: t === 0 ? "zero" : "gl" }, svg); text(svg, m.l - 6, Y(t) + 4, t, "end"); });
  P.dates.forEach((d, i) => { if (d.slice(8) === "01") text(svg, X(i), H - 6, MON[toDate(d).getMonth()], "middle"); });
  const bw = Math.max(1, (W - m.l - m.r) / n - 1);
  P.tsb.forEach((v, i) => {
    if (!v) return;
    el("rect", { x: X(i) - bw / 2, width: bw, y: v > 0 ? Y(v) : Y(0), height: Math.abs(Y(v) - Y(0)), fill: v > 0 ? "var(--green)" : "var(--red)", opacity: 0.55 }, svg);
  });
  [["ctl", "var(--cyan)"], ["atl", "var(--amber)"]].forEach(([k, c]) => {
    el("path", { d: P[k].map((v, i) => (i ? "L" : "M") + X(i).toFixed(1) + "," + Y(v).toFixed(1)).join(""), fill: "none", stroke: c, "stroke-width": 2, "stroke-linejoin": "round", style: `filter:drop-shadow(0 0 3px ${c})` }, svg);
  });
  const cross = el("line", { y1: m.t, y2: H - m.b, class: "cross", opacity: 0 }, svg);
  const dots = ["var(--cyan)", "var(--amber)"].map((c) => el("circle", { r: 4, fill: c, stroke: "#050607", "stroke-width": 2, opacity: 0 }, svg));
  const hit = el("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" }, svg);
  const move = (e) => {
    const r = svg.getBoundingClientRect();
    const i = Math.max(0, Math.min(n - 1, Math.round((((e.clientX - r.left) * (W / r.width) - m.l) / (W - m.l - m.r)) * (n - 1))));
    cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i)); cross.setAttribute("opacity", 1);
    [P.ctl[i], P.atl[i]].forEach((v, k) => { dots[k].setAttribute("cx", X(i)); dots[k].setAttribute("cy", Y(v)); dots[k].setAttribute("opacity", 1); });
    const f = P.tsb[i];
    showTip(`<div class="t">${md(P.dates[i])}</div>${row("var(--cyan)", "Fitness", P.ctl[i].toFixed(1))}${row("var(--amber)", "Fatigue", P.atl[i].toFixed(1))}${row(f >= 0 ? "var(--green)" : "var(--red)", "Form", (f > 0 ? "+" : "") + f.toFixed(1))}${row("#55606a", "Day's load", P.load[i].toFixed(0))}`, e);
  };
  hit.addEventListener("pointermove", move); hit.addEventListener("pointerdown", move);
  hit.addEventListener("pointerleave", () => { hideTip(); cross.setAttribute("opacity", 0); dots.forEach((d) => d.setAttribute("opacity", 0)); });
  $("#pmc-note").textContent = `Load source: ${P.source}. Form above zero = fresh; well below zero = carrying fatigue.`;
}

/* ---- weekly miles ---- */
function weeks() {
  const host = $("#weeks"); host.innerHTML = "";
  const Wk = D.weeks, W = host.clientWidth || 380, H = 210, m = { l: 30, r: 6, t: 16, b: 22 }, n = Wk.mi.length;
  const tk = ticks(0, Math.max(1, ...Wk.mi), 4), hi = tk[tk.length - 1];
  const Y = (v) => H - m.b - (v / hi) * (H - m.t - m.b), band = (W - m.l - m.r) / n, bw = Math.max(3, band - 3);
  const svg = el("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, width: W, height: H }, host);
  tk.forEach((t) => { el("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), class: t ? "gl" : "zero" }, svg); text(svg, m.l - 6, Y(t) + 4, t, "end"); });
  Wk.mi.forEach((v, i) => {
    const x = m.l + i * band + (band - bw) / 2, last = i === n - 1;
    if (v > 0) {
      const h = Y(0) - Y(v), r = Math.min(3, bw / 2, h);
      el("path", { d: `M${x},${Y(0)}V${Y(v) + r}Q${x},${Y(v)} ${x + r},${Y(v)}H${x + bw - r}Q${x + bw},${Y(v)} ${x + bw},${Y(v) + r}V${Y(0)}Z`, fill: "var(--cyan)", opacity: last ? 1 : 0.6, style: last ? "filter:drop-shadow(0 0 5px var(--cyan))" : "" }, svg);
    }
    if (i % 4 === (n - 1) % 4) text(svg, x + bw / 2, H - 6, last ? "now" : md(Wk.labels[i]), "middle");
    const hit = el("rect", { x: m.l + i * band, y: m.t, width: band, height: H - m.t - m.b, fill: "transparent" }, svg);
    const show = (e) => { hit.setAttribute("fill", "rgba(255,255,255,0.04)"); showTip(`<div class="t">${last ? "This week" : "Week of " + md(Wk.labels[i])}</div>${row("var(--cyan)", "Run", v.toFixed(1) + " mi")}`, e); };
    hit.addEventListener("pointermove", show); hit.addEventListener("pointerdown", show);
    hit.addEventListener("pointerleave", () => { hideTip(); hit.setAttribute("fill", "transparent"); });
  });
}

/* ---- log & alert ---- */
$("#log").innerHTML = `<table class="log"><thead><tr><th>When</th><th>Type</th><th>Dist</th><th>Time</th><th>HR</th><th>Load</th></tr></thead><tbody>${
  D.log.map((a) => `<tr><td class="t">${md(a.d)} ${a.d.slice(11)}</td><td><i class="dot" style="background:${SPORT[a.sport]}"></i>${a.sport === "Golf" ? "golf (walk)" : a.type}</td><td>${a.mi ? a.mi.toFixed(2) + " mi" : "—"}</td><td>${a.min >= 60 ? hm(a.min / 60) : Math.round(a.min) + "m"}</td><td>${a.hr ?? "—"}</td><td>${a.load}</td></tr>`).join("")
}</tbody></table>`;
$("#alert").textContent = D.alert;

pmc(); weeks();
let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { pmc(); weeks(); }, 150); });
addEventListener("scroll", hideTip, { passive: true });
</script>
</body>
</html>
"""

if __name__ == "__main__":
    build()
