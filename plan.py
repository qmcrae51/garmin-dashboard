"""Build plan.html: a 26-week, research-based marathon plan with paces from your current fitness (VDOT).

Paces come from the latest time trial in config.json ("training" -> "time_trials"); until there is one,
from your best recent 5 km split, discounted for the months of light running.
Re-run after every checkpoint and every pace in the plan updates.
"""
import datetime as dt
import json
import math
import os

from build import ROOT, TODAY, day, load

OUT = os.path.join(ROOT, "plan.html")

# ---------------------------------------------------------------- Daniels & Gilbert VDOT model
_A, _B, _C = 0.000104, 0.182258, -4.60


def _vo2(v):  # ml/kg/min at v metres/min
    return _C + _B * v + _A * v * v


def _frac(t):  # fraction of VO2max sustainable for t minutes
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t) + 0.2989558 * math.exp(-0.1932605 * t)


def vdot(metres, minutes):
    return _vo2(metres / minutes) / _frac(minutes)


def race_minutes(v, metres):
    lo, hi = 5.0, 900.0
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if vdot(metres, mid) > v else (lo, mid)
    return mid


def speed_at(v, fraction):  # metres/min at a fraction of VDOT
    return (-_B + math.sqrt(_B * _B - 4 * _A * (_C - fraction * v))) / (2 * _A)


def pace(m_per_min):
    s = 1000 / m_per_min * 60
    return f"{int(s // 60)}:{int(round(s % 60)) % 60:02d}"


def hms(minutes):
    s = round(minutes * 60)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def paces(v):
    m = 42195 / race_minutes(v, 42195)
    i = speed_at(v, 0.975)
    return {
        "E": f"{pace(speed_at(v, 0.70))}–{pace(speed_at(v, 0.62))}",
        "M": pace(m), "T": pace(speed_at(v, 0.88)), "I": pace(i),
        "R": pace(i * 1.07),
        "HM": pace(21097.5 / race_minutes(v, 21097.5)),
    }


# ---------------------------------------------------------------- the plan
# Each week: phase, easy km per easy day, Q1 (Tue), Q2 (Thu, None = easy + strides), long run.
# Quality entries are (kind, title, km). Paces in braces are filled from the current VDOT.
S = ("strides", "Easy {E} + 6×20 s strides: fast but relaxed, walk back to recover", None)
TT5 = ("test", "CHECKPOINT · 5 km time trial: 2 km easy + 4 strides, 5 km all-out on a flat route, 1 km easy", 8)
TT10 = ("test", "CHECKPOINT · 10 km time trial: 2 km easy + 4 strides, 10 km all-out, 1 km easy", 13)


def q(kind, title, km):
    return (kind, title, km)


WEEKS = [
    # n, phase, easy, Q1, Q2, (long km, long note)
    (1, "Base", 2.5, (*S[:2], 3.5), None, (6, "")),
    (2, "Base", 3, (*S[:2], 4), None, (6.5, "")),
    (3, "Base", 3, TT5, None, (6.5, "")),
    (4, "Base · down", 3, q("hills", "8×30 s hill sprints (steep, hard not all-out, walk down) inside an easy run", 5), None, (6, "")),
    (5, "Base", 4, q("threshold", "3×8 min @ T {T} with 2 min jog, plus warm-up and cool-down", 8), None, (9, "")),
    (6, "Base", 4.5, q("hills", "6×1 min uphill at a hard, controlled effort, jog down", 7), None, (10, "")),
    (7, "Base", 5, TT5, None, (11, "")),
    (8, "Base · down", 4, q("threshold", "20 min continuous @ T {T}, plus warm-up and cool-down", 9), None, (9, "")),
    (9, "Build", 5, q("intervals", "5×1 km @ I {I} with 3 min jog", 10), None, (13, "")),
    (10, "Build", 5.5, q("threshold", "4×1.6 km @ T {T} with 90 s jog", 10), q("hills", "8×30 s hill sprints inside an easy run", 7), (15, "last 15 min steady, just under T effort")),
    (11, "Build", 6, TT10, None, (16, "")),
    (12, "Build · down", 5.5, q("threshold", "4×1.6 km @ T {T} with 90 s jog", 10), None, (13, "")),
    (13, "Build", 6.5, q("intervals", "6×1 km @ I {I} with 2:30 jog", 11), q("threshold", "3×3 km @ T {T} with 2 min jog", 13), (18, "last 5 km @ M {M}")),
    (14, "Build", 6, q("intervals", "5×1.2 km @ I {I} with 3 min jog", 11), q("marathon", "8 km @ M {M} inside 12 km", 12), (14, "")),
    (15, "Half marathon", None, None, None, None),
    (16, "Recovery", 5, (*S[:2], 6), None, (12, "")),
    (17, "Marathon-specific", 5.5, q("threshold", "5×1.6 km @ T {T} with 90 s jog", 12), q("marathon", "10 km @ M {M} inside 14 km", 14), (20, "")),
    (18, "Marathon-specific", 6, q("intervals", "6×1 km @ I {I} with 2:30 jog", 11), q("marathon", "2×6 km @ M {M} with 1 km easy between", 16), (24, "last 6 km @ M {M}")),
    (19, "Marathon-specific", 6, TT10, None, (26, "")),
    (20, "Marathon-specific · down", 5, q("threshold", "4×1.6 km @ T {T} with 90 s jog", 10), q("marathon", "8 km @ M {M} inside 12 km", 12), (18, "")),
    (21, "Marathon-specific", 6, q("intervals", "5×1.2 km @ I {I} with 3 min jog", 11), q("marathon", "12 km @ M {M} inside 16 km", 16), (28, "practise race fuelling: 60–90 g carbs per hour")),
    (22, "Peak", 6.5, q("threshold", "3×3 km @ T {T} with 2 min jog", 13), None, (30, "3×5 km @ M {M} with 1 km easy between; full race-day fuelling and kit")),
    (23, "Taper", 5, q("intervals", "5×1 km @ I {I} with 2:30 jog", 10), q("marathon", "8 km @ M {M} inside 12 km", 12), (22, "")),
    (24, "Taper", 4.5, q("threshold", "3×1.6 km @ T {T} with 90 s jog", 9), q("marathon", "6 km @ M {M} inside 10 km", 10), (16, "")),
    (25, "Race week", None, None, None, None),
]
MIN_RUN_KM = 5
HEAT_BLOCK = {12, 13, 14, 21, 22, 23}  # 3-week heat blocks before the half and the marathon


def gym_for(n, phase):
    if n <= 4:
        return {"Mon": "A", "Thu": "B"}, "Foundation: 2–3 sets of 8–10, moderate weight, learn the movements"
    if n in (15, 25):
        return ({"Mon": "A-lite"} if n == 15 else {}), ("Race week: no lifting" if n == 25 else "Race week: one light session Monday")
    if n in (23, 24):
        return {"Mon": "A-lite"}, "Taper: one session, half the sets, same weights"
    extra = {"Fri": "C"} if "down" not in phase and n < 22 else {}
    return {"Mon": "A", "Thu": "B", **extra}, ("Down week: cut sets by a third" if "down" in phase else "Strength & power: heavy and explosive, low reps")


def sauna_for(n):
    if n <= 2:
        return {"Mon": 15, "Wed": 15}
    if n == 15:
        return {"Mon": 20, "Wed": 15}
    if n == 25:
        return {"Mon": 15, "Wed": 15}
    if n in HEAT_BLOCK:
        return {"Mon": 30, "Wed": 30, "Fri": 25, "Sat": 25}
    return {"Mon": 25, "Wed": 25, "Sat": 20}


def build_weeks(start):
    weeks = []
    days_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for n, phase, easy, q1, q2, long in WEEKS:
        monday = start + dt.timedelta(weeks=n - 1)
        days = {}
        if n == 15:
            days = {
                "Mon": ("easy", "Easy {E}", 6), "Tue": ("threshold", "3×1 km @ T {T} with 2 min jog", 8),
                "Wed": ("easy", "Easy {E}", 6), "Thu": ("strides", "Easy {E} + 4 strides", 5),
                "Fri": ("rest", "Rest", 0), "Sat": ("easy", "Shake-out: 5 km very easy", 5),
                "Sun": ("race", "HALF MARATHON · CHECKPOINT. Start at {HM}/km; if you feel good, pick it up after 15 km", 23.1),
            }
        elif n == 25:
            days = {
                "Mon": ("easy", "Easy {E}", 5), "Tue": ("marathon", "3×1.6 km @ M {M} + 4 strides", 8),
                "Wed": ("easy", "Easy {E}", 5), "Thu": ("strides", "Easy {E} + 4 strides", 5),
                "Fri": ("rest", "Rest · carb-load starts (10–12 g/kg/day)", 0), "Sat": ("easy", "Shake-out: 5 km very easy · carb-load", 5),
                "Sun": ("race", "MARATHON. Goal pace set from your checkpoints; fuel 60–90 g carbs per hour", 42.2),
            }
        else:
            days["Mon"] = ("easy", "Easy {E}", easy)
            days["Tue"] = (q1[0], q1[1], q1[2])
            days["Wed"] = ("easy", "Easy {E}", round(easy * 1.2 * 2) / 2)
            days["Thu"] = (q2[0], q2[1], q2[2]) if q2 else ("strides", "Easy {E} + 6×20 s strides", easy)
            days["Fri"] = ("rest", "Rest", 0)
            days["Sat"] = ("easy", "Easy {E}", max(2.5, round(easy * 0.8 * 2) / 2))
            note = f" · {long[1]}" if long[1] else ""
            days["Sun"] = ("long", f"Long run {long[0]} km, easy{note}", long[0])
        # every run is at least MIN_RUN_KM
        days = {d: (k, t, max(MIN_RUN_KM, km) if km else km) for d, (k, t, km) in days.items()}
        gym, gym_note = gym_for(n, phase)
        sauna = sauna_for(n)
        weeks.append({
            "n": n, "start": monday.isoformat(), "phase": phase, "gymNote": gym_note, "heat": n in HEAT_BLOCK,
            "days": [{"dow": d, "date": (monday + dt.timedelta(days=i)).isoformat(), "kind": days[d][0],
                      "title": days[d][1], "km": days[d][2], "gym": gym.get(d), "sauna": sauna.get(d)}
                     for i, d in enumerate(days_order)],
        })
        weeks[-1]["km"] = round(sum(x["km"] or 0 for x in weeks[-1]["days"]), 1)
    return weeks


def week0(start):
    """The days left before week 1."""
    monday = start - dt.timedelta(weeks=1)
    plan = {"Mon": ("rest", "—", 0), "Tue": ("rest", "—", 0), "Wed": ("rest", "Rest (resting HR was up)", 0),
            "Thu": ("easy", "Easy {E}, or rest if resting HR is still 5+ above normal", 5), "Fri": ("rest", "Rest", 0),
            "Sat": ("easy", "Easy {E}", 5), "Sun": ("easy", "Easy {E}", 5)}
    days = [{"dow": d, "date": (monday + dt.timedelta(days=i)).isoformat(), "kind": plan[d][0], "title": plan[d][1],
             "km": plan[d][2], "gym": "intro" if d == "Fri" else None, "sauna": 15 if d == "Sat" else None}
            for i, d in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])]
    return {"n": 0, "start": monday.isoformat(), "phase": "Return to run", "gymNote": "Intro: bodyweight session to learn the movements",
            "heat": False, "days": days, "km": sum(x["km"] for x in days)}


def build():
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    tr = cfg.setdefault("training", {})
    race_day = day(tr.get("marathon", "2027-04-25"))
    start = day(tr.get("plan_start", "2026-11-02"))
    acts = load("activities.json", [])
    zones = load("hr_zones.json", [])

    # current fitness
    tts = sorted(tr.get("time_trials", []), key=lambda t: t["date"])
    if tts:
        t = tts[-1]
        parts = [float(x) for x in t["time"].split(":")]  # "MM:SS" or "H:MM:SS"
        minutes = sum(p * 60 ** (len(parts) - 2 - i) for i, p in enumerate(parts))
        v = vdot(t["distance_km"] * 1000, minutes)
        source = f"{t['distance_km']:g} km in {t['time']} on {t['date']}"
    else:
        best = None
        for a in acts:
            f5 = a.get("fastestSplit_5000")
            if ("run" in a["activityType"]["typeKey"] and "treadmill" not in a["activityType"]["typeKey"]
                    and f5 and (TODAY - day(a["startTimeLocal"])).days <= 365
                    and f5 >= 0.7 * (a["duration"] / (a["distance"] / 1000)) * 5):
                best = min(best or 1e9, f5)
        raw = vdot(5000, best / 60) if best else 38
        v = raw - 2
        source = (f"provisional: best 5 km split {int(best // 60)}:{int(best % 60):02d} (VDOT {raw:.1f}) minus 2 for recent light training"
                  if best else "provisional estimate")
    v = round(v, 1)
    P = paces(v)
    goal_v = vdot(42195, 180)

    weeks = [week0(start)] + build_weeks(start)
    for w in weeks:
        for d in w["days"]:
            d["title"] = d["title"].format(**P)

    # actual running per day from Garmin
    actual = {}
    for a in acts:
        if "run" in a["activityType"]["typeKey"]:
            d = a["startTimeLocal"][:10]
            actual[d] = round(actual.get(d, 0) + (a.get("distance") or 0) / 1000, 2)
    for w in weeks:
        w["actual"] = round(sum(actual.get(d["date"], 0) for d in w["days"]), 1)
        for d in w["days"]:
            d["done"] = actual.get(d["date"])

    zr = next((z for z in zones if z.get("sport") == "RUNNING"), zones[0] if zones else None)
    easy_cap = zr["zone3Floor"] if zr else None

    ladder = [{"hm": hms(t), "v": round(vdot(21097.5, t), 1), "m": hms(race_minutes(vdot(21097.5, t), 42195))}
              for t in (86, 90, 95, 100, 105, 110)]
    sub3 = {"5K": hms(race_minutes(goal_v, 5000)), "10K": hms(race_minutes(goal_v, 10000)),
            "HM": hms(race_minutes(goal_v, 21097.5))}

    payload = {
        "today": TODAY.isoformat(), "race": race_day.isoformat(), "vdot": v, "source": source, "paces": P,
        "predict": {"5K": hms(race_minutes(v, 5000)), "10K": hms(race_minutes(v, 10000)),
                    "HM": hms(race_minutes(v, 21097.5)), "M": hms(race_minutes(v, 42195))},
        "goalVdot": round(goal_v, 1), "sub3": sub3, "ladder": ladder, "easyCap": easy_cap,
        "weeks": weeks,
    }
    data = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    with open(os.path.join(ROOT, "plan_template.html")) as f:
        html = f.read().replace("__DATA__", data)
    with open(OUT, "w") as f:
        f.write(html)
    print(f"Training plan written: {OUT}  (VDOT {v}, marathon prediction {payload['predict']['M']})")


if __name__ == "__main__":
    build()
