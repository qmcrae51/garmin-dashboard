"""Read data/ and config.json, and write dashboard.html (one self-contained file)."""
import datetime as dt
import json
import os
import statistics

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "dashboard.html")
TODAY = dt.date.today()
LB_PER_G = 1 / 453.592


def load(name, default):
    path = os.path.join(DATA, name)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def day(s):
    return dt.date.fromisoformat(s[:10])


def week_start(d):
    return d - dt.timedelta(days=d.weekday())


def sport(type_key):
    if "run" in type_key:
        return "Run"
    if type_key == "walking" or "golf" in type_key:
        return "Golf"
    if "cycl" in type_key or "biking" in type_key or "ride" in type_key:
        return "Ride"
    return "Other"


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def rolling(values, n, min_count=1):
    out = []
    for i in range(len(values)):
        window = [v for v in values[max(0, i - n + 1): i + 1] if v is not None]
        out.append(round(statistics.fmean(window), 2) if len(window) >= min_count else None)
    return out


def hr_load(a):
    """Zone-weighted minutes (Edwards TRIMP): a minute in zone 4 counts 4x a minute in zone 1."""
    return sum((a.get(f"hrTimeInZone_{z}") or 0) / 60 * z for z in range(1, 6))


def build():
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    acts = load("activities.json", [])
    daily = load("daily.json", {})
    sleep = load("sleep.json", {})
    hrv = load("hrv.json", {})
    weight = load("weight.json", {})
    fitness = load("fitness_age.json", {})
    state = load("state.json", {})

    since = dt.date.fromisoformat(state.get("since", (TODAY - dt.timedelta(days=365)).isoformat()))
    dates = [since + dt.timedelta(days=i) for i in range((TODAY - since).days + 1)]
    iso = [d.isoformat() for d in dates]

    # --- activities -------------------------------------------------------
    sessions = []
    for a in acts:
        d = day(a["startTimeLocal"])
        sessions.append({
            "d": d, "sport": sport(a["activityType"]["typeKey"]),
            "type": a["activityType"]["typeKey"], "name": a.get("activityName") or "",
            "km": (a.get("distance") or 0) / 1000, "min": (a.get("duration") or 0) / 60,
            "elev": a.get("elevationGain") or 0, "hr": a.get("averageHR"),
            "load": hr_load(a), "zones": [(a.get(f"hrTimeInZone_{z}") or 0) / 60 for z in range(1, 6)],
            "f1k": a.get("fastestSplit_1000"), "fmi": a.get("fastestSplit_1609"), "f5k": a.get("fastestSplit_5000"),
        })
    runs = [s for s in sessions if s["sport"] == "Run"]

    # --- weeks --------------------------------------------------------------
    this_week = week_start(TODAY)
    weeks = [this_week - dt.timedelta(weeks=i) for i in range(25, -1, -1)]
    sports = ["Run", "Ride", "Golf", "Other"]
    wk = {w: {s: {"km": 0, "min": 0, "n": 0} for s in sports} for w in weeks}
    for s in sessions:
        w = week_start(s["d"])
        if w in wk:
            cell = wk[w][s["sport"]]
            cell["km"] += s["km"]
            cell["min"] += s["min"]
            cell["n"] += 1
    week_rows = {
        "labels": [w.isoformat() for w in weeks],
        "run_km": [round(wk[w]["Run"]["km"], 1) for w in weeks],
        "hours": {s: [round(wk[w][s]["min"] / 60, 2) for w in weeks] for s in sports},
    }
    prior = weeks[-5:-1]
    compare = []
    for s in sports:
        now = wk[this_week][s]
        avg = {k: statistics.fmean(wk[w][s][k] for w in prior) for k in ("km", "min", "n")}
        if now["n"] or avg["n"]:
            compare.append({"sport": s, "now": now, "avg": avg})

    # --- daily trends -------------------------------------------------------
    load_by_day = {}
    for s in sessions:
        if s["sport"] != "Golf":  # golf rounds are walking, not training
            load_by_day[s["d"].isoformat()] = load_by_day.get(s["d"].isoformat(), 0) + s["load"]
    loads = [round(load_by_day.get(d, 0), 1) for d in iso]
    acute = rolling(loads, 7, 7)
    chronic = rolling(loads, 28, 28)
    rhr = [(daily.get(d) or {}).get("heartRate", {}).get("restingValue") for d in iso]
    sleep_h = [round(sleep[d]["sleepTimeSeconds"] / 3600, 2) if d in sleep else None for d in iso]
    hrv_v = [(hrv.get(d) or {}).get("lastNightAvg") for d in iso]
    steps = [((daily.get(d) or {}).get("movement") or {}).get("steps", {}).get("value") for d in iso]

    # --- runs & pace ---------------------------------------------------------
    pace_runs = sorted([r for r in runs if r["km"] >= 1.5 and r["min"] > 0], key=lambda r: r["d"])
    pace = [round(r["min"] * 60 / r["km"]) for r in pace_runs]
    pace_avg = rolling(pace, 6, 3)
    run_list = [{"d": r["d"].isoformat(), "km": round(r["km"], 2), "pace": p, "avg": a,
                 "hr": r["hr"], "name": r["name"], "tread": "treadmill" in r["type"]}
                for r, p, a in zip(pace_runs, pace, pace_avg)]

    # --- weight ------------------------------------------------------------
    wpts = {}
    for d, w in weight.items():
        g = (w.get("latestWeight") or {}).get("weight")
        if g:
            wpts[d] = round(g * LB_PER_G, 1)
    for e in cfg.get("weight_log_lb", []):
        wpts[e["date"]] = e["lb"]
    weights = [{"d": d, "lb": wpts[d]} for d in sorted(wpts)]

    # --- intensity mix (last 28 days) ---------------------------------------
    recent = [s for s in sessions if (TODAY - s["d"]).days < 28 and s["sport"] != "Golf"]
    zone_min = [round(sum(s["zones"][z] for s in recent)) for z in range(5)]

    # --- records -------------------------------------------------------------
    def best(key, pool, fn=min):
        c = [r for r in pool if r.get(key)]
        return fn(c, key=lambda r: r[key]) if c else None

    records = []
    lr = best("km", runs, max)
    if lr:
        records.append({"label": "Longest run", "value": f"{lr['km']:.1f} km", "d": lr["d"].isoformat(), "note": lr["name"]})
    outdoor = [r for r in runs if "treadmill" not in r["type"] and r["km"] >= 1]
    for key, label, km in (("f1k", "Fastest 1 km", 1), ("fmi", "Fastest mile", 1.609), ("f5k", "Fastest 5 km", 5)):
        sane = [r for r in outdoor if r.get(key) and r["km"] >= km
                and r[key] >= 0.7 * r["min"] * 60 / r["km"] * km]
        r = best(key, sane)
        if r:
            records.append({"label": label, "value": f"{int(r[key] // 60)}:{int(r[key] % 60):02d}", "d": r["d"].isoformat(), "note": r["name"]})
    long_pace = [r for r in pace_runs if r["km"] >= 10]
    if long_pace:
        r = min(long_pace, key=lambda r: r["min"] / r["km"])
        s = r["min"] * 60 / r["km"]
        records.append({"label": "Fastest 10 km+ pace", "value": f"{int(s // 60)}:{int(s % 60):02d} /km", "d": r["d"].isoformat(), "note": f"{r['km']:.1f} km"})
    all_weeks = {}
    for r in runs:
        w = week_start(r["d"])
        all_weeks[w] = all_weeks.get(w, 0) + r["km"]
    if all_weeks:
        w = max(all_weeks, key=all_weeks.get)
        records.append({"label": "Biggest running week", "value": f"{all_weeks[w]:.1f} km", "d": w.isoformat(), "note": "week of"})
    r = best("elev", [r for r in outdoor if r["km"] >= 3 and r["elev"] / r["km"] < 60], max)
    if r:
        records.append({"label": "Most climbing", "value": f"{r['elev']:.0f} m", "d": r["d"].isoformat(), "note": f"{r['km']:.1f} km run"})
    if load_by_day:
        d = max(load_by_day, key=load_by_day.get)
        records.append({"label": "Hardest day (load)", "value": f"{load_by_day[d]:.0f}", "d": d, "note": "zone-weighted min"})
    top_runs = [{"d": r["d"].isoformat(), "km": round(r["km"], 2), "min": round(r["min"], 1), "hr": r["hr"], "name": r["name"]}
                for r in sorted(runs, key=lambda r: r["km"], reverse=True)[:5]]

    # --- headline numbers & briefing ----------------------------------------
    week_km = wk[this_week]["Run"]["km"]
    avg4_km = statistics.fmean(wk[w]["Run"]["km"] for w in prior)
    rhr7 = mean(rhr[-7:])
    rhr_prev = mean(rhr[-37:-30])
    sleep7 = mean(sleep_h[-7:])
    acwr = (acute[-1] / chronic[-1]) if acute[-1] and chronic[-1] else None
    runs28 = len({r["d"] for r in runs if (TODAY - r["d"]).days < 28})
    last_run = max((r["d"] for r in runs), default=None)
    cur_weight = weights[-1] if weights else None

    hour = dt.datetime.now().hour
    greet = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    lines = []
    first_race = min((r for r in cfg["races"] if day(r["date"]) >= TODAY), key=lambda r: r["date"], default=None)
    if first_race:
        lines.append(f"{(day(first_race['date']) - TODAY).days} days until the {first_race['name'].lower()}.")
    if avg4_km:
        pct = week_km / avg4_km * 100
        lines.append(f"{week_km:.1f} km run this week, {pct:.0f}% of your 4-week average of {avg4_km:.1f} km.")
    else:
        lines.append(f"{week_km:.1f} km run this week.")
    if rhr7 and rhr_prev:
        diff = rhr7 - rhr_prev
        trend = "holding steady" if abs(diff) < 1 else ("down" if diff < 0 else "up") + f" {abs(diff):.0f} bpm on last month"
        lines.append(f"Resting heart rate is {rhr7:.0f} bpm, {trend}.")
    if sleep7:
        h, m = int(sleep7), round((sleep7 % 1) * 60)
        lines.append(f"You've averaged {h}h {m:02d}m of sleep this week." + (" I'd recommend more, Sir." if sleep7 < 7 else ""))
    if runs28 < 8:
        lines.append(f"{runs28} runs in the last 4 weeks. Three a week would build your base for February.")

    payload = {
        "generated": dt.datetime.now().strftime("%b %d, %Y %H:%M"),
        "today": TODAY.isoformat(),
        "greeting": greet, "briefing": lines,
        "races": cfg["races"], "weightGoal": cfg["weight_goal_lb"],
        "tiles": {
            "weekKm": round(week_km, 1), "avg4Km": round(avg4_km, 1),
            "rhr7": rhr7 and round(rhr7), "rhrPrev": rhr_prev and round(rhr_prev),
            "sleep7": sleep7 and round(sleep7, 2),
            "acute": acute[-1], "chronic": chronic[-1], "acwr": acwr and round(acwr, 2),
            "runs28": runs28, "lastRun": last_run and last_run.isoformat(),
            "fitnessAge": fitness.get("fitnessAge") and round(fitness["fitnessAge"], 1),
            "age": fitness.get("chronologicalAge"),
            "achievableAge": fitness.get("achievableFitnessAge") and round(fitness["achievableFitnessAge"], 1),
            "weight": cur_weight,
        },
        "weeks": week_rows, "compare": compare,
        "daily": {"dates": iso, "load": loads, "acute": acute, "chronic": chronic,
                  "rhr": rhr, "rhr7": rolling(rhr, 7, 3), "sleep": sleep_h, "sleep7": rolling(sleep_h, 7, 3),
                  "hrv": hrv_v, "steps": steps},
        "hasHrv": any(v for v in hrv_v),
        "runs": run_list, "weights": weights, "zones": zone_min,
        "records": records, "topRuns": top_runs,
    }
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    with open(os.path.join(ROOT, "template.html")) as f:
        html = f.read().replace("__DATA__", data)
    with open(OUT, "w") as f:
        f.write(html)
    print(f"Dashboard written: {OUT}")


if __name__ == "__main__":
    build()
