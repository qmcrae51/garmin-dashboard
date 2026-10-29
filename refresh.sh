#!/bin/bash
# Pull new Garmin data, rebuild the dashboard and open it.
set -e
cd "$(dirname "$0")"
python3 pull.py
python3 build.py
python3 commander.py
python3 coach.py
python3 brain.py
python3 plan.py
python3 insights.py
python3 hub.py

# Publish the pages to GitHub Pages (your key and data/ are in .gitignore and never uploaded)
git add -A
if ! git diff --cached --quiet; then
  git commit -q -m "Refresh dashboards $(date '+%Y-%m-%d %H:%M')"
  git push -q && echo "Published: https://qmcrae51.github.io/garmin-dashboard/"
fi

# --quiet is used by the 6 am schedule: rebuild and publish without opening browser tabs
if [ "$1" != "--quiet" ]; then
  open index.html progress.html dashboard.html commander.html coach.html brain.html plan.html
fi
