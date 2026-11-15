"""The Garmin connector's tools. Each call runs in a fresh process (see mcp_server.py), so "today" and the
data are always current. Read-only: nothing here can change your Garmin account.

Usage: python3 mcp_tools.py <tool> '<json arguments>'  ->  prints one JSON result
"""
import datetime as dt
import json
import subprocess
import sys

from build import ROOT, TODAY, load, sport


def _hm(seconds):
    return f"{int(seconds // 3600)}h {int(seconds % 3600 // 60):02d}m" if seconds else None


def today():
    """Today's planned session, readiness, and advice."""
    import insights
    a = insights.analyze()
    t = next((d for d in a["days"] if d["date"] == TODAY.isoformat()), None)
    return {"date": TODAY.isoformat(), "data_updated": a["built"], "plan_today": t, "readiness": a["readiness"],
            "easy_pace_per_km": a["paces"]["E"], "easy_hr_cap": a["cap"],
            "readiness_last_14_days": [h and {"date": h["date"], "score": h["score"], "level": h["lvl"]} for h in a["history"]]}


def plan_week(week=None, date=None):
    """One week of the marathon plan (by week number, or the week containing a date; default this week)."""
    import plan
    P = plan.compute()
    when = date or TODAY.isoformat()
    w = (next((x for x in P["weeks"] if x["n"] == int(week)), None) if week is not None
         else next((x for x in P["weeks"] if x["start"] <= when < (dt.date.fromisoformat(x["start"]) + dt.timedelta(days=7)).isoformat()), None))
    if not w:
        return {"error": "No plan week found. The plan runs weeks 0-25, Oct 26 2026 to Apr 25 2027."}
    return {"week": w, "paces_per_km": P["paces"], "vdot": P["vdot"], "fitness_source": P["source"]}


def progress():
    """Marathon prediction, the 3:00 path, checkpoints and easy-run discipline."""
    import insights
    a = insights.analyze()
    return {k: a[k] for k in ("vdot", "source", "goalVdot", "predictM", "status", "gapV", "checkpoints", "compliance",
                              "capPaceNow", "capPaceThen", "weeklyCap", "easyRuns", "race")}


def activities(days=14, kind=None):
    """Activities from the last N days (kind: run, ride, golf, other)."""
    since = (TODAY - dt.timedelta(days=int(days))).isoformat()
    out = []
    for a in load("activities.json", []):
        if a["startTimeLocal"][:10] < since:
            continue
        s = sport(a["activityType"]["typeKey"])
        if kind and s.lower() != kind.lower():
            continue
        km = (a.get("distance") or 0) / 1000
        out.append({
            "start": a["startTimeLocal"], "sport": s, "type": a["activityType"]["typeKey"], "name": a.get("activityName"),
            "km": round(km, 2), "duration_min": round(a["duration"] / 60, 1),
            "pace_per_km": (f"{int(a['duration'] / km // 60)}:{int(a['duration'] / km % 60):02d}" if km > 0.5 and s == "Run" else None),
            "avg_hr": a.get("averageHR"), "max_hr": a.get("maxHR"), "cadence": a.get("averageRunningCadenceInStepsPerMinute"),
            "elevation_gain_m": a.get("elevationGain"),
            "hr_zone_minutes": [round((a.get(f"hrTimeInZone_{z}") or 0) / 60, 1) for z in range(1, 6)],
        })
    return {"since": since, "count": len(out), "activities": sorted(out, key=lambda x: x["start"], reverse=True)}


def vitals(days=7):
    """Daily resting HR, sleep, Body Battery, stress and steps for the last N days."""
    daily, sleep, weight = load("daily.json", {}), load("sleep.json", {}), load("weight.json", {})
    out = []
    for i in range(int(days) - 1, -1, -1):
        d = (TODAY - dt.timedelta(days=i)).isoformat()
        r, s = daily.get(d) or {}, sleep.get(d) or {}
        out.append({
            "date": d, "resting_hr": (r.get("heartRate") or {}).get("restingValue"),
            "sleep": _hm(s.get("sleepTimeSeconds")), "deep": _hm(s.get("deepSleepSeconds")), "rem": _hm(s.get("remSleepSeconds")),
            "body_battery_high": (r.get("bodyBattery") or {}).get("maxValue"), "body_battery_low": (r.get("bodyBattery") or {}).get("minValue"),
            "stress_avg": (r.get("stress") or {}).get("avgLevel"), "steps": ((r.get("movement") or {}).get("steps") or {}).get("value"),
        })
    return {"days": out, "note": "This watch does not record HRV or sleep scores."}


def sync():
    """Download the latest data from Garmin (read-only) into the local data folder."""
    p = subprocess.run([sys.executable, "pull.py"], cwd=ROOT, capture_output=True, text=True, timeout=600)
    lines = [l for l in (p.stdout + p.stderr).splitlines() if l.strip()]
    return {"ok": p.returncode == 0, "log": lines[-10:]}


TOOLS = {"today": today, "plan_week": plan_week, "progress": progress, "activities": activities, "vitals": vitals, "sync": sync}

if __name__ == "__main__":
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    real_stdout, sys.stdout = sys.stdout, sys.stderr  # keep stray prints out of the result
    result = TOOLS[sys.argv[1]](**args)
    real_stdout.write(json.dumps(result, default=str))
