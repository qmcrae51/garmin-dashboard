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
open dashboard.html commander.html coach.html brain.html plan.html
