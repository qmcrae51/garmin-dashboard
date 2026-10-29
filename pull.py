"""Download your Garmin history into data/ as JSON.

  python3 pull.py          last 12 months the first time, then only what's new
  python3 pull.py --full   your whole history (a few more minutes)

Re-running only fetches new data (plus the last few days, which Garmin may
still be filling in).
"""
import datetime as dt
import json
import os
import sys

import garmin_api as g

DATA = g.DATA
STATE_FILE = os.path.join(DATA, "state.json")
TODAY = dt.date.today()
OVERLAP_DAYS = 3


def load(name, default):
    path = os.path.join(DATA, name)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def save(name, obj):
    path = os.path.join(DATA, name)
    with open(path + ".tmp", "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(path + ".tmp", path)


def progress(label, done, total):
    total = max(total, 1)
    filled = int(30 * done / total)
    sys.stdout.write(f"\r  {label:<16} [{'#' * filled}{'.' * (30 - filled)}] {done}/{total}")
    sys.stdout.flush()
    if done >= total:
        sys.stdout.write("\n")


def chunks(start, end, days):
    out, cur = [], start
    while cur <= end:
        stop = min(cur + dt.timedelta(days=days - 1), end)
        out.append((cur, stop))
        cur = stop + dt.timedelta(days=1)
    return out


def fetch_range(make_path, extract, start, end):
    """Fetch one date range, halving it whenever the response is too big (HTTP 500)."""
    try:
        return extract(g.get(make_path(start, end)))
    except g.GarminError as e:
        if e.status != 500:
            raise
        if start == end:
            print(f"\n  (skipped {start}: Garmin couldn't return it)")
            return []
        mid = start + (end - start) // 2
        return (fetch_range(make_path, extract, start, mid)
                + fetch_range(make_path, extract, mid + dt.timedelta(days=1), end))


def pull_by_date(label, filename, make_path, extract, date_key, chunk_days, since):
    """Download a dated dataset into a {date: item} file, starting where it left off."""
    store = load(filename, {})
    start = since
    if store:
        last = dt.date.fromisoformat(max(store))
        start = max(since, last - dt.timedelta(days=OVERLAP_DAYS))
        earliest = dt.date.fromisoformat(min(store))
        if since < earliest - dt.timedelta(days=chunk_days):
            start = since  # history was extended (e.g. --full): go back further
    ranges = chunks(start, TODAY, chunk_days)
    for i, (a, b) in enumerate(ranges):
        for item in fetch_range(make_path, extract, a, b) or []:
            key = date_key(item)
            if key:
                store[key] = item
        progress(label, i + 1, len(ranges))
    save(filename, store)
    return store


def pull_activities(since, full=False):
    store = {str(a["activityId"]): a for a in load("activities.json", [])}
    known = set(store)
    start, new = 0, 0
    while True:
        page = g.get(f"/activitylist-service/activities/search/activities?start={start}&limit=20") or []
        fresh = [a for a in page if str(a["activityId"]) not in known]
        for a in page:
            store[str(a["activityId"])] = a
        new += len(fresh)
        sys.stdout.write(f"\r  {'Activities':<16} {len(store)} saved ({new} new)")
        sys.stdout.flush()
        oldest = page[-1]["startTimeLocal"][:10] if page else ""
        if len(page) < 20 or (not fresh and not full) or (not full and oldest < since.isoformat()):
            break
        start += 20
    print()
    acts = sorted(store.values(), key=lambda a: a["startTimeLocal"], reverse=True)
    save("activities.json", acts)
    return acts


def main():
    os.makedirs(DATA, exist_ok=True)
    state = load("state.json", {})
    if "--full" in sys.argv:
        since = dt.date(2000, 1, 1)
    elif "since" in state:
        since = dt.date.fromisoformat(state["since"])
    else:
        since = TODAY - dt.timedelta(days=365)

    print("Connecting to Garmin...")
    g.get_token()
    print("Downloading (read-only)...")

    acts = pull_activities(since, full=since.year == 2000)
    if since.year == 2000:  # full history: begin daily data at your first activity
        first = acts[-1]["startTimeLocal"][:10] if acts else TODAY.isoformat()
        since = dt.date.fromisoformat(first)
    state["since"] = min(since.isoformat(), state.get("since", "9999"))
    since = dt.date.fromisoformat(state["since"])

    daily = pull_by_date(
        "Daily summaries", "daily.json",
        lambda a, b: f"/usersummary-service/v2/dailysummaries?startDate={a}&endDate={b}",
        lambda r: (r or {}).get("data", []),
        lambda x: x.get("calendarDate"), 60, since)

    sleep = pull_by_date(
        "Sleep", "sleep.json",
        lambda a, b: f"/sleep-service/sleep/dailySleepSummariesByDate?startDate={a}&endDate={b}",
        lambda r: [x for x in (r or []) if (x.get("sleepTimeSeconds") or 0) > 0],
        lambda x: x.get("calendarDate"), 31, since)

    hrv = pull_by_date(
        "HRV", "hrv.json",
        lambda a, b: f"/hrv-service/hrv/daily/{a}/{b}",
        lambda r: (r or {}).get("hrvSummaries", []),
        lambda x: x.get("calendarDate"), 365, since)

    weight = pull_by_date(
        "Weight", "weight.json",
        lambda a, b: f"/weight-service/weight/range/{a}/{b}",
        lambda r: (r or {}).get("dailyWeightSummaries", []),
        lambda x: x.get("summaryDate"), 365, since)

    try:
        save("fitness_age.json", g.get(f"/fitnessage-service/fitnessage/v2/{TODAY}") or {})
        save("hr_zones.json", g.get("/biometric-service/heartRateZones/v2") or [])
    except g.GarminError as e:
        print(f"  (fitness age / HR zones unavailable: {e})")

    state["last_pull"] = dt.datetime.now().isoformat(timespec="seconds")
    save("state.json", state)

    dates = [a["startTimeLocal"][:10] for a in acts]
    print("\nDone.")
    print(f"  Activities: {len(acts)}" + (f"  ({min(dates)} to {max(dates)})" if dates else ""))
    print(f"  Days with daily summaries: {len(daily)}")
    print(f"  Nights of sleep: {len(sleep)}")
    print(f"  Days with HRV: {len(hrv)}")
    print(f"  Days with a weigh-in: {len(weight)}")
    print(f"  History covered: {state['since']} to {TODAY}")


if __name__ == "__main__":
    try:
        main()
    except g.GarminError as e:
        print(f"\nStopped: {e}")
        sys.exit(1)
