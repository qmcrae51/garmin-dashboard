"""Read data/ and config.json, and write coach.html: the screen a coach opens before messaging an athlete."""
import datetime as dt
import json
import os

from build import ROOT, TODAY, day, hr_load, load, mean, sport, week_start
from commander import KM_PER_MI, ewma

OUT = os.path.join(ROOT, "coach.html")
ZONE_LABELS = ["Recovery", "Base", "Tempo", "Threshold", "VO2 Max"]


def effect_label(a):
    """Garmin's own label when present, else an estimate from where the heart rate sat."""
    if a.get("trainingEffectLabel"):
        return a["trainingEffectLabel"].replace("_", " ").title(), False
    z = [a.get(f"hrTimeInZone_{i}") or 0 for i in range(1, 6)]
    total = sum(z)
    if not total:
        return None, True
    # the highest zone holding at least 20% of the session sets its character
    top = max((i for i in range(5) if z[i] / total >= 0.2), default=0)
    return ZONE_LABELS[top], True


def build():
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    acts = load("activities.json", [])
    daily = load("daily.json", {})
    sleep = load("sleep.json", {})
    hrv = load("hrv.json", {})
    state = load("state.json", {})

    since = dt.date.fromisoformat(state.get("since", (TODAY - dt.timedelta(days=365)).isoformat()))
    iso = [(since + dt.timedelta(days=i)).isoformat() for i in range((TODAY - since).days + 1)]
    name = next((a.get("ownerFullName") for a in acts if a.get("ownerFullName")), "Athlete")
    race = min((r for r in cfg["races"] if day(r["date"]) >= TODAY), key=lambda r: r["date"], default=None)

    # weekly volume, 10 weeks
    weeks = [week_start(TODAY) - dt.timedelta(weeks=i) for i in range(9, -1, -1)]
    mi = {w: 0.0 for w in weeks}
    hrs = {w: 0.0 for w in weeks}
    for a in acts:
        s = sport(a["activityType"]["typeKey"])
        w = week_start(day(a["startTimeLocal"]))
        if w not in mi or s == "Golf":
            continue
        hrs[w] += (a.get("duration") or 0) / 3600
        if s == "Run":
            mi[w] += (a.get("distance") or 0) / 1000 / KM_PER_MI

    # flags
    rhr = [((daily.get(d) or {}).get("heartRate") or {}).get("restingValue") for d in iso]
    rhr_now = next((v for v in reversed(rhr[-2:]) if v is not None), None)
    rhr7 = mean(rhr[-8:-1])
    last_sleep_day = max((d for d in sleep if sleep[d].get("sleepTimeSeconds")), default=None)
    sleep_h = sleep[last_sleep_day]["sleepTimeSeconds"] / 3600 if last_sleep_day else None
    loads = {}
    for a in acts:
        if sport(a["activityType"]["typeKey"]) != "Golf":
            d = a["startTimeLocal"][:10]
            loads[d] = loads.get(d, 0) + (a.get("activityTrainingLoad") or hr_load(a))
    series = [loads.get(d, 0) for d in iso]
    ctl, atl = ewma(series, 42), ewma(series, 7)
    form = ctl[-1] - atl[-1]
    hrv_last = hrv.get(max(hrv)) if hrv else None

    flags = []
    if hrv_last and hrv_last.get("lastNightAvg") and hrv_last.get("baseline"):
        v, b = hrv_last["lastNightAvg"], hrv_last["baseline"]
        lo, hi = b.get("balancedLow"), b.get("balancedUpper")
        level = "green" if lo <= v <= hi else ("red" if v < lo * 0.9 else "amber")
        flags.append({"key": "HRV", "level": level, "text": f"HRV {v} ms vs baseline {lo}–{hi} ms"})
    else:
        flags.append({"key": "HRV", "level": "none", "text": "HRV not recorded: this watch doesn't measure it overnight"})
    if sleep_h is not None:
        level = "green" if sleep_h >= 7 else "amber" if sleep_h >= 6 else "red"
        flags.append({"key": "Sleep", "level": level, "text": f"Slept {int(sleep_h)}h {round(sleep_h % 1 * 60):02d}m last night" + (" (on target)" if level == "green" else " (under 7 h)")})
    else:
        flags.append({"key": "Sleep", "level": "none", "text": "No sleep recorded last night"})
    if rhr_now is not None and rhr7:
        diff = rhr_now - rhr7
        level = "red" if diff >= 5 else "amber" if diff >= 3 else "green"
        flags.append({"key": "Resting HR", "level": level, "text": f"Resting HR {rhr_now} bpm, {diff:+.0f} vs 7-day avg {rhr7:.0f}"})
    else:
        flags.append({"key": "Resting HR", "level": "none", "text": "No resting HR today"})
    level = "red" if form < -25 else "amber" if form < -10 or form > 15 else "green"
    meaning = ("heavy fatigue" if form < -25 else "carrying fatigue" if form < -10
               else "fresh, but fitness is slipping" if form > 15 else "balanced")
    flags.append({"key": "Form", "level": level, "text": f"Form {form:+.0f} (fitness {ctl[-1]:.0f}, fatigue {atl[-1]:.0f}): {meaning}"})

    # last 8 sessions (golf is not training)
    sessions = []
    for a in [a for a in acts if sport(a["activityType"]["typeKey"]) != "Golf"][:8]:
        label, est = effect_label(a)
        m = (a.get("distance") or 0) / 1000 / KM_PER_MI
        sessions.append({
            "d": a["startTimeLocal"][:16], "type": a["activityType"]["typeKey"].replace("_", " "),
            "name": a.get("activityName") or "", "mi": round(m, 2) if m >= 0.1 else None,
            "min": round((a.get("duration") or 0) / 60), "hr": a.get("averageHR") and round(a["averageHR"]),
            "te": label, "est": est,
        })

    # intensity, last 28 days
    zones = [0.0] * 5
    for a in acts:
        if sport(a["activityType"]["typeKey"]) != "Golf" and (TODAY - day(a["startTimeLocal"])).days < 28:
            for i in range(5):
                zones[i] += (a.get(f"hrTimeInZone_{i + 1}") or 0) / 60
    zones = [round(z) for z in zones]

    # drafted note
    first = name.split()[0]
    by = {f["key"]: f for f in flags}
    lines = [f"Morning {first},", ""]
    if by["Resting HR"]["level"] in ("red", "amber"):
        lines.append(f"Your resting heart rate is up this morning ({rhr_now} bpm vs your usual {rhr7:.0f}). "
                     "That's often fatigue, stress or something coming on, so let's keep today easy: "
                     "30–40 minutes in zone 2, or take a rest day if you feel run down.")
    elif by["Form"]["level"] == "red":
        lines.append("You're carrying a lot of fatigue right now. Let's make today a recovery day.")
    else:
        lines.append("Your numbers look steady this morning, so you're good to train as planned.")
    if by["Sleep"]["level"] == "green":
        lines.append(f"Good sleep last night ({int(sleep_h)}h {round(sleep_h % 1 * 60):02d}m). Keep that up.")
    elif by["Sleep"]["level"] in ("amber", "red"):
        lines.append("Sleep was short last night. Aim to be in bed early tonight.")
    total = sum(zones)
    easy = (zones[0] + zones[1]) / total if total else None
    if easy is not None and easy < 0.7:
        lines.append(f"Over the last 4 weeks only {easy:.0%} of your training time was easy (zones 1–2). "
                     "To build toward February, slow most runs down so you can chat, and keep one session a week for hard work.")
    lines += ["", "Let me know how you feel after today's session.", "Coach"]

    payload = {
        "name": name, "initials": "".join(p[0] for p in name.split()[:2]).upper(),
        "race": race and {"name": race["name"], "date": race["date"], "days": (day(race["date"]) - TODAY).days},
        "synced": state.get("last_pull", "").replace("T", " ")[:16],
        "weeks": {"labels": [w.isoformat() for w in weeks], "mi": [round(mi[w], 1) for w in weeks], "hrs": [round(hrs[w], 2) for w in weeks]},
        "flags": flags, "sessions": sessions, "zones": zones, "note": "\n".join(lines),
    }
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    with open(OUT, "w") as f:
        f.write(TEMPLATE.replace("__DATA__", data))
    print(f"Coach view written: {OUT}")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Coach View</title>
<style>
:root {
  color-scheme: light;
  --side: #111417;
  --side-2: #1b2025;
  --side-text: #c9d1d8;
  --side-muted: #7b8792;
  --page: #f6f6f4;
  --card: #ffffff;
  --ink: #0b0b0b;
  --ink-2: #52514e;
  --muted: #898781;
  --line: #e7e6e1;
  --grid: #ecebe6;
  --axis: #c3c2b7;
  --accent: #2a78d6;
  --s1: #2a78d6;
  --s2: #eb6834;
  --good: #0ca30c;
  --warning: #fab219;
  --critical: #d03b3b;
  --good-ink: #006300;
}
* { box-sizing: border-box; }
html, body { margin: 0; }
body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--ink); background: var(--page); display: flex; min-height: 100vh; }

/* sidebar */
aside { width: 240px; flex: none; position: sticky; top: 0; height: 100vh; overflow-y: auto; background: var(--side); color: var(--side-text); padding: 20px 14px; display: flex; flex-direction: column; gap: 6px; }
.brand { font-weight: 700; letter-spacing: 0.04em; color: #fff; font-size: 15px; padding: 0 8px 16px; }
.side-lbl { font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--side-muted); padding: 8px 8px 4px; }
.ath { display: flex; align-items: center; gap: 10px; padding: 9px 8px; border-radius: 8px; cursor: pointer; }
.ath.on { background: var(--side-2); color: #fff; }
.av { width: 30px; height: 30px; border-radius: 50%; background: var(--accent); color: #fff; display: grid; place-items: center; font-weight: 700; font-size: 12px; flex: none; }
.ath .meta { font-size: 12px; color: var(--side-muted); }
.ath .cnt { margin-left: auto; font-size: 11px; font-weight: 700; background: var(--critical); color: #fff; border-radius: 10px; padding: 1px 7px; }
.invite { margin-top: 6px; background: transparent; border: 1px dashed #3a444c; color: var(--side-text); padding: 9px; border-radius: 8px; cursor: pointer; font: inherit; font-size: 14px; text-align: left; }
.invite:hover { border-color: var(--side-text); }

/* main */
main { flex: 1; min-width: 0; padding: 24px 28px 48px; }
.header { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; }
.header .av { width: 52px; height: 52px; font-size: 18px; }
.header h1 { font-size: 22px; margin: 0; }
.header .sub { color: var(--ink-2); font-size: 14px; margin-top: 3px; }
.header .sub b { color: var(--ink); }
.pill { margin-left: auto; display: inline-flex; align-items: center; gap: 8px; padding: 7px 14px; border-radius: 20px; font-weight: 600; font-size: 14px; border: 1px solid var(--line); background: var(--card); }
.pill i { width: 9px; height: 9px; border-radius: 50%; }
.cols { display: grid; gap: 16px; grid-template-columns: 1.25fr 1fr; }
.cols > * { min-width: 0; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 16px 18px; }
.card h2 { font-size: 14px; margin: 0 0 2px; }
.card .q { font-size: 13px; color: var(--muted); margin: 0 0 12px; }
.stack { display: grid; gap: 16px; align-content: start; }
.stack > * { min-width: 0; }
.flag > span:nth-child(3) { min-width: 0; }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.pair > * { min-width: 0; }
.mini-t { font-size: 12px; color: var(--ink-2); font-weight: 600; margin-bottom: 4px; }

/* flags */
.flag { display: flex; gap: 10px; align-items: flex-start; padding: 9px 0; border-bottom: 1px solid var(--grid); font-size: 14px; }
.flag:last-child { border-bottom: 0; }
.flag i { width: 10px; height: 10px; border-radius: 50%; margin-top: 4px; flex: none; }
.flag .k { font-weight: 600; min-width: 84px; }
.flag .st { margin-left: auto; font-size: 12px; color: var(--muted); white-space: nowrap; }

/* table */
table { width: 100%; border-collapse: collapse; font-size: 13.5px; font-variant-numeric: tabular-nums; }
th { text-align: right; font-size: 11px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; padding: 6px 8px; border-bottom: 1px solid var(--axis); }
td { text-align: right; padding: 8px; border-bottom: 1px solid var(--grid); white-space: nowrap; }
th:nth-child(-n+2), td:nth-child(-n+2) { text-align: left; }
td .nm { color: var(--muted); font-size: 12px; display: block; max-width: 220px; overflow: hidden; text-overflow: ellipsis; }
.te { display: inline-block; padding: 2px 8px; border-radius: 10px; background: #eef4fc; color: #184f95; font-size: 12px; font-weight: 600; }
.te.est::after { content: "*"; color: var(--muted); }
.tablewrap { overflow-x: auto; }
.fine { font-size: 12px; color: var(--muted); margin-top: 8px; }

/* zones */
.zbar { display: flex; gap: 2px; height: 26px; margin: 8px 0 10px; }
.zbar div { height: 100%; cursor: default; }
.zbar div:first-child { border-radius: 4px 0 0 4px; }
.zbar div:last-child { border-radius: 0 4px 4px 0; }
.zleg { display: grid; grid-template-columns: repeat(5, 1fr); gap: 6px; font-size: 12px; color: var(--ink-2); }
.zleg b { display: block; font-size: 15px; color: var(--ink); }
.easy { font-size: 28px; font-weight: 700; }
.easy small { font-size: 14px; color: var(--ink-2); font-weight: 500; }

/* note */
textarea { width: 100%; min-height: 230px; resize: vertical; border: 1px solid var(--line); border-radius: 8px; padding: 12px; font: inherit; font-size: 14px; line-height: 1.5; color: var(--ink); background: #fcfcfb; }
textarea:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
.send { margin-top: 10px; width: 100%; padding: 12px; border: 0; border-radius: 8px; background: var(--ink); color: #fff; font: inherit; font-weight: 600; font-size: 15px; cursor: pointer; }
.send:hover { background: #2a2a28; }

/* charts */
.chart { display: block; overflow: visible; touch-action: pan-y; }
.chart .gl { stroke: var(--grid); }
.chart .base { stroke: var(--axis); }
.chart .tk { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
#tip { position: fixed; z-index: 9; pointer-events: none; opacity: 0; transition: opacity .1s; background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; font-size: 13px; box-shadow: 0 6px 20px rgba(0,0,0,.12); min-width: 130px; }
#tip .t { font-size: 11px; color: var(--muted); margin-bottom: 3px; }
#tip .r { display: flex; justify-content: space-between; gap: 12px; }
#tip .r span { display: inline-flex; align-items: center; gap: 6px; color: var(--ink-2); }
.sw { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
#toast { position: fixed; bottom: 20px; left: 50%; transform: translate(-50%, 20px); opacity: 0; transition: .2s; background: var(--ink); color: #fff; padding: 12px 16px; border-radius: 8px; font-size: 14px; max-width: min(520px, calc(100vw - 32px)); z-index: 10; }
#toast.on { opacity: 1; transform: translate(-50%, 0); }

@media (max-width: 1000px) { .cols { grid-template-columns: 1fr; } }
@media (max-width: 720px) {
  body { flex-direction: column; }
  aside { width: auto; position: static; height: auto; flex-direction: row; flex-wrap: wrap; align-items: center; padding: 12px 16px; gap: 8px; }
  .brand { padding: 0 8px 0 0; }
  .side-lbl { display: none; }
  .ath .meta { display: none; }
  .invite { margin: 0 0 0 auto; padding: 6px 10px; }
  main { padding: 16px 16px 40px; }
  .pill { margin-left: 0; }
  .pair { grid-template-columns: 1fr; }
  .flag .st { display: none; }
}
</style>
</head>
<body>
<aside>
  <div class="brand">COACH VIEW</div>
  <div class="side-lbl">Athletes</div>
  <div class="ath on" id="me"></div>
  <button class="invite" id="invite">+ Invite athlete</button>
</aside>
<main>
  <div class="header" id="header"></div>
  <div class="cols">
    <div class="stack">
      <div class="card">
        <h2>Flags this morning</h2>
        <p class="q">Anything I should adjust before today's session?</p>
        <div id="flags"></div>
      </div>
      <div class="card">
        <h2>Weekly volume · last 10 weeks</h2>
        <p class="q">Is training load building steadily?</p>
        <div class="pair">
          <div><div class="mini-t">Run miles</div><div id="c-mi"></div></div>
          <div><div class="mini-t">Training hours (all sports, excl. golf)</div><div id="c-hrs"></div></div>
        </div>
      </div>
      <div class="card">
        <h2>Last 8 sessions</h2>
        <p class="q">What has the athlete actually done?</p>
        <div class="tablewrap" id="sessions"></div>
        <div class="fine">* Estimated from heart-rate zones: Garmin doesn't report a training effect label for this watch.</div>
      </div>
    </div>
    <div class="stack">
      <div class="card">
        <h2>Intensity · last 28 days</h2>
        <p class="q">Is enough of the training easy?</p>
        <div id="zones"></div>
      </div>
      <div class="card">
        <h2>Note to athlete</h2>
        <p class="q">Drafted from this morning's flags. Edit before sending.</p>
        <textarea id="note"></textarea>
        <button class="send" id="send">Send + update watch workout</button>
      </div>
    </div>
  </div>
</main>
<div id="tip"></div>
<div id="toast" role="status"></div>
<script>
const D = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const $ = (s) => document.querySelector(s);
const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const toDate = (s) => new Date(s.slice(0, 10) + "T00:00:00");
const md = (s) => { const d = toDate(s); return `${MON[d.getMonth()]} ${d.getDate()}`; };
const LEVEL = { red: ["var(--critical)", "Act"], amber: ["var(--warning)", "Watch"], green: ["var(--good)", "OK"], none: ["#c3c2b7", "No data"] };
const tip = $("#tip");
function showTip(html, e) {
  tip.innerHTML = html; tip.style.opacity = 1;
  const r = tip.getBoundingClientRect();
  let x = e.clientX + 14, y = e.clientY + 14;
  if (x + r.width > innerWidth - 8) x = e.clientX - r.width - 14;
  if (y + r.height > innerHeight - 8) y = e.clientY - r.height - 14;
  tip.style.left = Math.max(8, x) + "px"; tip.style.top = Math.max(8, y) + "px";
}
const hideTip = () => (tip.style.opacity = 0);
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("on"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("on"), 5000); }
function el(tag, a, p) { const e = document.createElementNS(NS, tag); for (const k in a) e.setAttribute(k, a[k]); if (p) p.appendChild(e); return e; }

/* header & sidebar */
const flagged = D.flags.filter((f) => f.level === "red" || f.level === "amber");
const worst = D.flags.some((f) => f.level === "red") ? "red" : flagged.length ? "amber" : "green";
$("#me").innerHTML = `<div class="av">${D.initials}</div><div><div>${D.name}</div><div class="meta">${D.race ? D.race.name + " · " + D.race.days + "d" : ""}</div></div>${flagged.length ? `<span class="cnt">${flagged.length}</span>` : ""}`;
const synced = D.synced ? `${md(D.synced)}, ${D.synced.slice(11)}` : "never";
$("#header").innerHTML = `<div class="av">${D.initials}</div>
  <div><h1>${D.name}</h1>
  <div class="sub">${D.race ? `<b>${D.race.name}</b> · ${md(D.race.date)}, ${D.race.date.slice(0, 4)} · <b>${D.race.days} days out</b> · ` : ""}Last Garmin sync ${synced}</div></div>
  <span class="pill"><i style="background:${LEVEL[worst][0]}"></i>${flagged.length} flag${flagged.length === 1 ? "" : "s"} today</span>`;

/* flags */
$("#flags").innerHTML = D.flags.map((f) => `<div class="flag"><i style="background:${LEVEL[f.level][0]}"></i><span class="k">${f.key}</span><span>${f.text}</span><span class="st">${LEVEL[f.level][1]}</span></div>`).join("");

/* weekly bars */
function bars(host, values, color, unit, fmt) {
  host.innerHTML = "";
  const W = host.clientWidth || 300, H = 170, m = { l: 30, r: 4, t: 8, b: 22 }, n = values.length;
  const raw = Math.max(1, ...values) / 4, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((x) => x * mag).find((s) => s >= raw), hi = Math.ceil(Math.max(1, ...values) / step) * step;
  const Y = (v) => H - m.b - (v / hi) * (H - m.t - m.b), band = (W - m.l - m.r) / n, bw = Math.max(3, band - 4);
  const svg = el("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, width: W, height: H }, host);
  for (let t = 0; t <= hi + 1e-9; t += step) {
    el("line", { x1: m.l, x2: W - m.r, y1: Y(t), y2: Y(t), class: t ? "gl" : "base" }, svg);
    const tx = el("text", { x: m.l - 5, y: Y(t) + 4, class: "tk", "text-anchor": "end" }, svg); tx.textContent = +t.toFixed(2);
  }
  values.forEach((v, i) => {
    const x = m.l + i * band + (band - bw) / 2, last = i === n - 1;
    if (v > 0) {
      const y = Y(v), r = Math.min(4, bw / 2, Y(0) - y);
      el("path", { d: `M${x},${Y(0)}V${y + r}Q${x},${y} ${x + r},${y}H${x + bw - r}Q${x + bw},${y} ${x + bw},${y + r}V${Y(0)}Z`, fill: color, opacity: last ? 1 : 0.75 }, svg);
    }
    if (i % 3 === (n - 1) % 3) { const tx = el("text", { x: x + bw / 2, y: H - 6, class: "tk", "text-anchor": "middle" }, svg); tx.textContent = last ? "This wk" : md(D.weeks.labels[i]); }
    const hit = el("rect", { x: m.l + i * band, y: m.t, width: band, height: H - m.t - m.b, fill: "transparent" }, svg);
    const show = (e) => { hit.setAttribute("fill", "rgba(0,0,0,0.04)"); showTip(`<div class="t">${last ? "This week" : "Week of " + md(D.weeks.labels[i])}</div><div class="r"><span><i class="sw" style="background:${color}"></i>${unit}</span><b>${fmt(v)}</b></div>`, e); };
    hit.addEventListener("pointermove", show); hit.addEventListener("pointerdown", show);
    hit.addEventListener("pointerleave", () => { hideTip(); hit.setAttribute("fill", "transparent"); });
  });
}
const hm = (h) => `${Math.floor(h)}h ${String(Math.round((h % 1) * 60)).padStart(2, "0")}m`;
function charts() {
  bars($("#c-mi"), D.weeks.mi, "var(--s1)", "Run", (v) => v.toFixed(1) + " mi");
  bars($("#c-hrs"), D.weeks.hrs, "var(--s2)", "Training", hm);
}

/* sessions */
$("#sessions").innerHTML = `<table><thead><tr><th>Date</th><th>Session</th><th>Dist / time</th><th>Avg HR</th><th>Training effect</th></tr></thead><tbody>${
  D.sessions.map((s) => `<tr><td>${md(s.d)}</td><td>${s.type}<span class="nm">${s.name}</span></td>
    <td>${s.mi != null ? s.mi.toFixed(2) + " mi" : s.min + " min"}${s.mi != null ? `<span class="nm" style="margin-left:auto">${s.min} min</span>` : ""}</td>
    <td>${s.hr ?? "—"}</td><td>${s.te ? `<span class="te${s.est ? " est" : ""}">${s.te}</span>` : "—"}</td></tr>`).join("")
}</tbody></table>`;

/* zones */
(function () {
  const z = D.zones, total = z.reduce((a, b) => a + b, 0);
  const ramp = ["#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#104281"];
  const names = ["Z1 Recovery", "Z2 Easy", "Z3 Aerobic", "Z4 Threshold", "Z5 Max"];
  if (!total) { $("#zones").innerHTML = `<p class="q">No heart-rate data in the last 28 days.</p>`; return; }
  const easy = Math.round(((z[0] + z[1]) / total) * 100);
  $("#zones").innerHTML = `<div class="easy">${easy}%<small> easy (zones 1–2)</small></div>
    <div class="zbar">${z.map((v, i) => (v ? `<div data-i="${i}" style="flex:${v};background:${ramp[i]}"></div>` : "")).join("")}</div>
    <div class="zleg">${z.map((v, i) => `<div><i class="sw" style="background:${ramp[i]}"></i> Z${i + 1}<b>${Math.round((v / total) * 100)}%</b>${v} min</div>`).join("")}</div>
    <p class="fine">${easy >= 75 ? "Good base: most training is easy." : "Most endurance plans aim for about 80% easy."}</p>`;
  document.querySelectorAll(".zbar div").forEach((d) => {
    const i = +d.dataset.i;
    d.addEventListener("pointermove", (e) => showTip(`<div class="t">${names[i]}</div><div class="r"><span>Time</span><b>${z[i]} min</b></div><div class="r"><span>Share</span><b>${Math.round((z[i] / total) * 100)}%</b></div>`, e));
    d.addEventListener("pointerleave", hideTip);
  });
})();

/* note & actions: this page is read-only, so "send" copies the note instead */
$("#note").value = D.note;
$("#send").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("#note").value); } catch (e) { $("#note").select(); document.execCommand("copy"); }
  toast("Note copied to your clipboard. Sending messages and changing watch workouts aren't connected: this dashboard is read-only.");
});
$("#invite").addEventListener("click", () => toast("Inviting athletes isn't set up yet: this dashboard only reads your own Garmin data."));

charts();
let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(charts, 150); });
addEventListener("scroll", hideTip, { passive: true });
</script>
</body>
</html>
"""

if __name__ == "__main__":
    build()
