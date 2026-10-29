"""Daily insights shared by the home page and progress.html: plan check, readiness, easy-run discipline,
and whether you are on track for the 3:00 marathon."""
import datetime as dt
import json
import os
import statistics

from build import ROOT, TODAY, day, hr_load, load, sport
from commander import ewma
import plan

OUT = os.path.join(ROOT, "progress.html")
HARD = {"threshold", "intervals", "hills", "marathon", "test", "race"}
EASY_KINDS = {"easy", "strides"}
GOOD, WARN, BAD = "good", "warning", "critical"


def zone_seconds(a):
    return [a.get(f"hrTimeInZone_{z}") or 0 for z in range(1, 6)]


def above_cap(a):
    """Share of the run's heart-rate time at or above the easy cap (the zone 3 floor)."""
    z = zone_seconds(a)
    total = sum(z)
    return round(sum(z[2:]) / total * 100) if total > 60 else None


def is_easy_day(d):
    return d["kind"] in EASY_KINDS or (d["kind"] == "long" and "@" not in d["title"])


# ---------------------------------------------------------------- readiness
def readiness(date, daily, sleep, loads_by_day):
    """Green / amber / red for one morning from resting HR, sleep, Body Battery and the load ramp."""
    iso = date.isoformat()
    rec = daily.get(iso) or {}
    factors = []

    rhr = (rec.get("heartRate") or {}).get("restingValue")
    base = [(daily.get((date - dt.timedelta(days=i)).isoformat()) or {}).get("heartRate", {}).get("restingValue")
            for i in range(1, 29)]
    base = [b for b in base if b]
    if rhr and len(base) >= 7:
        normal = statistics.median(base)
        diff = rhr - normal
        lvl = GOOD if diff <= 2 else WARN if diff < 5 else BAD
        factors.append({"k": "Resting HR", "v": f"{rhr} bpm", "note": f"{diff:+.0f} vs your normal {normal:.0f}", "lvl": lvl, "w": 35})

    s = (sleep.get(iso) or {}).get("sleepTimeSeconds")
    if s:
        h = s / 3600
        lvl = GOOD if h >= 7 else WARN if h >= 6 else BAD
        factors.append({"k": "Sleep", "v": f"{int(h)}h {round(h % 1 * 60):02d}m", "note": "7 h+ is the target", "lvl": lvl, "w": 25})

    bb = (rec.get("bodyBattery") or {}).get("maxValue")
    if bb is not None:
        lvl = GOOD if bb >= 50 else WARN if bb >= 25 else BAD
        factors.append({"k": "Body Battery", "v": f"{bb}", "note": "overnight charge", "lvl": lvl, "w": 20})

    acute = sum(loads_by_day.get((date - dt.timedelta(days=i)).isoformat(), 0) for i in range(1, 8))
    chronic = sum(loads_by_day.get((date - dt.timedelta(days=i)).isoformat(), 0) for i in range(1, 29)) / 4
    if chronic or acute:
        ratio = acute / max(chronic, 200)  # floor stops a tiny base from flagging every run
        lvl = GOOD if ratio <= 1.3 else WARN if ratio <= 1.5 else BAD
        factors.append({"k": "Load ramp", "v": f"{ratio:.2f}×", "note": "last 7 days vs your 4-week average", "lvl": lvl, "w": 20})

    if not factors:
        return None
    pts = {GOOD: 100, WARN: 60, BAD: 20}
    score = round(sum(pts[f["lvl"]] * f["w"] for f in factors) / sum(f["w"] for f in factors))
    lvl = GOOD if score >= 75 else WARN if score >= 50 else BAD
    if any(f["k"] == "Resting HR" and f["lvl"] == BAD for f in factors):
        lvl = BAD  # the plan's rule: resting HR 5+ above normal means no hard work
    return {"date": iso, "score": score, "lvl": lvl, "factors": factors}


def advice(lvl, d, week):
    """What to do today given readiness and the planned session."""
    if d is None:
        return "No session planned."
    kind, km = d["kind"], d["km"]
    if kind == "rest":
        return "Rest day. Walk, stretch, sleep." if lvl != BAD else "Rest day, and a good one to have: your body is asking for it."
    if lvl == GOOD:
        return "All systems green. Run it as planned."
    later = [x for x in week["days"] if x["date"] > d["date"] and x["kind"] in ("easy",) and x["dow"] != "Sun"]
    if lvl == WARN:
        if kind in HARD:
            return ("Amber. Do the session but hold back: cut one rep, and switch to easy if your heart rate runs "
                    "5+ bpm higher than usual at the same pace.")
        if kind == "long":
            return "Amber. Run the full distance, but keep every km easy and take walk breaks if needed."
        return "Amber. Easy as planned; skip the strides if your legs feel heavy."
    if kind == "race":
        return "Red, on race day. Start conservatively and only push after halfway if you feel good."
    if kind == "long":
        return "Red. Skip the long run: rest or 5 km very easy today, and pick the long runs back up next weekend."
    if kind in HARD:
        move = (f" Move this session to {dt.date.fromisoformat(later[0]['date']).strftime('%A')} if you're green by then, otherwise drop it this week."
                if later else " Drop this session this week.")
        return f"Red. Swap it: rest or 5 km very easy today.{move}"
    return "Red. Rest, or 5 km very easy with walk breaks."


# ---------------------------------------------------------------- fitness from heart rate vs pace
def hr_fitness(a, rest, peak):
    """VO2max estimate from one steady run: %HR reserve ≈ %VO2 reserve (Swain & Leutholtz)."""
    if not ("run" in a["activityType"]["typeKey"] and a.get("averageHR") and (a.get("distance") or 0) > 2000
            and a["duration"] >= 1200):
        return None
    if (a.get("elevationGain") or 0) / (a["distance"] / 1000) > 40:  # very hilly, or a bad altimeter reading
        return None
    f = (a["averageHR"] - rest) / (peak - rest)
    if not 0.6 <= f <= 0.93:
        return None
    return (plan._vo2(a["distance"] / (a["duration"] / 60)) - 3.5) / f + 3.5


def short(minutes):
    return plan.hms(minutes).removeprefix("0:")


def pace_str(sec_per_km):
    return f"{int(sec_per_km // 60)}:{int(round(sec_per_km % 60)) % 60:02d}"


def analyze():
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    P = plan.compute()
    acts = load("activities.json", [])
    daily = load("daily.json", {})
    sleep = load("sleep.json", {})
    zones = load("hr_zones.json", [])
    zr = next((z for z in zones if z.get("sport") == "RUNNING"), zones[0] if zones else {})
    rest, peak, cap = zr.get("restingHeartRateUsed", 47), zr.get("maxHeartRateUsed", 185), P["easyCap"] or 143

    runs = sorted((a for a in acts if "run" in a["activityType"]["typeKey"]), key=lambda a: a["startTimeLocal"])
    runs_by_day = {}
    for a in runs:
        runs_by_day.setdefault(a["startTimeLocal"][:10], []).append(a)
    strength_days = {a["startTimeLocal"][:10] for a in acts if "strength" in a["activityType"]["typeKey"]}
    loads = {}
    for a in acts:
        if sport(a["activityType"]["typeKey"]) != "Golf":
            loads[a["startTimeLocal"][:10]] = loads.get(a["startTimeLocal"][:10], 0) + hr_load(a)

    plan_days = {d["date"]: (d, w) for w in P["weeks"] for d in w["days"]}

    # ---- plan check for every planned day up to today
    def check(d):
        rs = runs_by_day.get(d["date"], [])
        km = sum((a.get("distance") or 0) for a in rs) / 1000
        out = {"date": d["date"], "dow": d["dow"], "kind": d["kind"], "title": d["title"], "km": d["km"],
               "gym": d["gym"], "sauna": d["sauna"], "ran": round(km, 1) if rs else None,
               "gymDone": d["date"] in strength_days}
        if rs:
            secs = sum(a["duration"] for a in rs)
            hrs = [a["averageHR"] for a in rs if a.get("averageHR")]
            out["pace"] = pace_str(secs / km) if km else None
            out["hr"] = round(statistics.fmean(hrs)) if hrs else None
            tot = sum(sum(zone_seconds(a)) for a in rs)
            out["above"] = round(sum(sum(zone_seconds(a)[2:]) for a in rs) / tot * 100) if tot > 60 else None
        if day(d["date"]) > TODAY:
            out["status"] = "upcoming"
        elif d["km"]:
            if not rs:
                out["status"] = "pending" if d["date"] == TODAY.isoformat() else "missed"
            else:
                out["status"] = "done" if km >= 0.85 * d["km"] or km >= d["km"] - 1 else "short"
        else:
            out["status"] = "extra" if rs else "rest"
        if rs and is_easy_day(d) and out.get("above") is not None:
            out["capOk"] = out["above"] <= 10
        return out

    week_days = {}
    for w in P["weeks"]:
        week_days[w["n"]] = [check(d) for d in w["days"]]

    # ---- readiness, today and the last 14 mornings
    ready_today = readiness(TODAY, daily, sleep, loads)
    history = [readiness(TODAY - dt.timedelta(days=i), daily, sleep, loads) for i in range(13, -1, -1)]

    # advice for each day of this week and next (the page picks the right day by the phone's date)
    tw = next((w for w in P["weeks"] if w["start"] <= TODAY.isoformat() < (day(w["start"]) + dt.timedelta(days=7)).isoformat()), None)
    week_ids = [tw["n"]] if tw else []
    if tw and tw["n"] + 1 in week_days:
        week_ids.append(tw["n"] + 1)
    elif not tw and P["weeks"]:
        week_ids = [P["weeks"][0]["n"]]
    days_out = []
    for n in week_ids:
        w = next(x for x in P["weeks"] if x["n"] == n)
        for c, d in zip(week_days[n], w["days"]):
            c["week"], c["phase"] = n, w["phase"]
            c["advice"] = advice(ready_today["lvl"] if ready_today else GOOD, d, w)
            days_out.append(c)

    # ---- easy-run discipline: every run before the plan, planned easy runs after
    start = P["weeks"][1]["start"] if len(P["weeks"]) > 1 else P["weeks"][0]["start"]
    easy_runs = []
    for a in runs:
        dd = a["startTimeLocal"][:10]
        pd = plan_days.get(dd)
        if pd and dd >= start and not (is_easy_day(pd[0]) or pd[0]["kind"] == "rest"):
            continue
        pct = above_cap(a)
        if pct is None or a["distance"] < 2000:
            continue
        easy_runs.append({"date": dd, "km": round(a["distance"] / 1000, 1), "pace": pace_str(a["duration"] / (a["distance"] / 1000)),
                          "hr": a.get("averageHR") and round(a["averageHR"]), "above": pct,
                          "secs": sum(zone_seconds(a)), "aboveSecs": sum(zone_seconds(a)[2:]),
                          "label": pd[0]["kind"] if pd and dd >= start else "before plan"})
    weekly_cap = []
    for i in range(15, -1, -1):
        ws = TODAY - dt.timedelta(days=TODAY.weekday()) - dt.timedelta(weeks=i)
        we = ws + dt.timedelta(days=7)
        rs = [r for r in easy_runs if ws.isoformat() <= r["date"] < we.isoformat()]
        tot = sum(r["secs"] for r in rs)
        weekly_cap.append({"w": ws.isoformat(), "pct": round(sum(r["aboveSecs"] for r in rs) / tot * 100) if tot else None,
                           "n": len(rs)})

    # ---- fitness trend: 6-week median of the heart-rate estimate, calibrated to the plan's VDOT
    est = [(day(a["startTimeLocal"]), e) for a in runs if (e := hr_fitness(a, rest, peak))]
    weeks = []
    first = TODAY - dt.timedelta(days=TODAY.weekday()) - dt.timedelta(weeks=51)
    for i in range(52):
        we = first + dt.timedelta(weeks=i, days=6)
        win = [e for d, e in est if we - dt.timedelta(days=42) < d <= we]
        weeks.append({"w": (first + dt.timedelta(weeks=i)).isoformat(), "raw": round(statistics.median(win), 2) if len(win) >= 3 else None})
    anchor = P["anchor"] or TODAY.isoformat()
    ref = [w["raw"] for w in weeks if w["raw"] is not None and w["w"] <= anchor]
    offset = (P["vdot"] - ref[-1]) if ref else 0
    for w in weeks:
        w["v"] = round(w["raw"] + offset, 1) if w["raw"] is not None else None
        w["m"] = round(plan.race_minutes(w["v"], 42195), 1) if w["v"] else None

    # pace at the easy cap, now vs 8 weeks ago (uncalibrated: this one is about efficiency)
    def cap_pace(v):
        if v is None:
            return None
        vo2 = 3.5 + (cap - rest) / (peak - rest) * (v - 3.5)
        return round(1000 / plan.speed_at(vo2, 1.0) * 60)
    raws = [w["raw"] for w in weeks]
    cap_now = next((cap_pace(r) for r in reversed(raws) if r), None)
    cap_then = next((cap_pace(r) for r in reversed(raws[:-8]) if r), None)

    # ---- the 3:00 path: a straight line in VDOT from the plan start to race day
    tr = cfg.get("training", {})
    p0, p1 = day(P["weeks"][1]["start"] if len(P["weeks"]) > 1 else TODAY.isoformat()), day(P["race"])
    v0, v1 = tr.get("path_start_vdot", P["vdot"]), plan.vdot(42195, 180)

    def path_v(d):
        t = min(1, max(0, (d - p0).days / (p1 - p0).days))
        return v0 + (v1 - v0) * t

    path = [{"d": (p0 + dt.timedelta(weeks=i)).isoformat(), "v": round(path_v(p0 + dt.timedelta(weeks=i)), 2),
             "m": round(plan.race_minutes(path_v(p0 + dt.timedelta(weeks=i)), 42195), 1)}
            for i in range((p1 - p0).days // 7 + 1)] + [{"d": p1.isoformat(), "v": v1, "m": 180.0}]

    checkpoints = []
    for w in P["weeks"]:
        for d in w["days"]:
            if d["kind"] not in ("test", "race"):
                continue
            metres = 42195 if d["km"] > 40 else 21097.5 if d["kind"] == "race" else 10000 if "10 km" in d["title"] else 5000
            name = {42195: "Marathon", 21097.5: "Half marathon", 10000: "10 km time trial", 5000: "5 km time trial"}[metres]
            found = next((c for c in P["checkpoints"] if c["date"] == d["date"]), None)
            checkpoints.append({
                "date": d["date"], "name": name, "metres": metres,
                "target": short(plan.race_minutes(path_v(day(d["date"])), metres)),
                "now": short(plan.race_minutes(P["vdot"], metres)),
                "result": found,
            })
    for t in tr.get("time_trials", []):
        for c in checkpoints:
            if c["date"] == t["date"] and not (c["result"] and c["result"].get("status") == "ok"):
                c["result"] = {"status": "ok", "time": t["time"], "vdot": round(plan.vdot(t["distance_km"] * 1000, plan.to_minutes(t["time"])), 1),
                               "manual": True}

    for c in checkpoints:
        if c["result"] and c["result"].get("status") == "ok":
            c["resultM"] = round(plan.race_minutes(c["result"]["vdot"], 42195), 1)

    # status vs the path, judged from the latest real reading
    gap_v = P["vdot"] - path_v(day(P["anchor"])) if P["anchor"] else None
    status = None
    if gap_v is not None:
        status = GOOD if gap_v >= -0.3 else WARN if gap_v >= -1.5 else BAD

    # compliance since the plan started
    done = [c for n, cs in week_days.items() if n >= 1 for c in cs if c["status"] in ("done", "short", "missed")]
    capped = [c for n, cs in week_days.items() if n >= 1 for c in cs if "capOk" in c]

    return {
        "built": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "today": TODAY.isoformat(), "race": P["race"],
        "vdot": P["vdot"], "source": P["source"], "anchor": P["anchor"], "goalVdot": P["goalVdot"], "pathStart": v0,
        "predictM": P["predict"]["M"], "predictMin": round(plan.race_minutes(P["vdot"], 42195), 1),
        "paces": P["paces"], "cap": cap, "status": status, "gapV": gap_v and round(gap_v, 1),
        "readiness": ready_today, "history": history, "days": days_out,
        "weeks": weeks, "path": path, "checkpoints": checkpoints,
        "easyRuns": easy_runs[-12:][::-1], "weeklyCap": weekly_cap,
        "capPaceNow": cap_now and pace_str(cap_now), "capPaceThen": cap_then and pace_str(cap_then),
        "compliance": {"runs": len([c for c in done if c["status"] == "done"]), "planned": len(done),
                       "capOk": len([c for c in capped if c["capOk"]]), "capped": len(capped)},
    }


def build():
    data = json.dumps(analyze(), separators=(",", ":")).replace("</", "<\\/")
    with open(os.path.join(ROOT, "progress_template.html")) as f:
        html = f.read().replace("__DATA__", data)
    with open(OUT, "w") as f:
        f.write(html)
    print(f"Progress page written: {OUT}")


if __name__ == "__main__":
    build()
