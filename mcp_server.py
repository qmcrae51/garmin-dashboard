"""A read-only Garmin connector for the Claude desktop app (an MCP server over stdio, standard library only).

The app starts this script; each tool runs mcp_tools.py in a fresh process. Your API key stays in .env.local,
is only read by garmin_api.py, and is never sent to Claude.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

TOOLS = [
    {"name": "today", "description": "Today's planned marathon-plan session, readiness score (resting HR, sleep, Body Battery, load ramp) with advice, and readiness for the last 14 days.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "plan_week", "description": "One week of the 26-week marathon plan with runs, gym and sauna, plus current training paces. Defaults to this week.",
     "inputSchema": {"type": "object", "properties": {"week": {"type": "integer", "description": "Plan week number, 0-25"},
                                                      "date": {"type": "string", "description": "A date (YYYY-MM-DD) inside the week"}}}},
    {"name": "progress", "description": "Marathon prediction vs the 3:00 goal, checkpoint targets and results, plan compliance, and easy-run heart-rate discipline.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "activities", "description": "Garmin activities from the last N days with distance, pace, heart rate, cadence and HR zone minutes. 'walking' activities are golf.",
     "inputSchema": {"type": "object", "properties": {"days": {"type": "integer", "default": 14},
                                                      "kind": {"type": "string", "enum": ["run", "ride", "golf", "other"]}}}},
    {"name": "vitals", "description": "Daily resting HR, sleep (total, deep, REM), Body Battery, stress and steps for the last N days.",
     "inputSchema": {"type": "object", "properties": {"days": {"type": "integer", "default": 7}}}},
    {"name": "sync", "description": "Download the newest data from Garmin (read-only; takes up to a minute). Data also refreshes automatically at 6 am.",
     "inputSchema": {"type": "object", "properties": {}}},
]
READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
for t in TOOLS:
    t["annotations"] = READ_ONLY


def call(name, args):
    p = subprocess.run([sys.executable, os.path.join(ROOT, "mcp_tools.py"), name, json.dumps(args or {})],
                       cwd=ROOT, capture_output=True, text=True, timeout=660)
    if p.returncode != 0:
        err = (p.stderr.strip().splitlines() or ["unknown error"])[-1]
        return {"content": [{"type": "text", "text": f"Error: {err}"}], "isError": True}
    return {"content": [{"type": "text", "text": p.stdout}]}


def reply(msg_id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": msg_id}
    msg.update({"error": error} if error else {"result": result})
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method, msg_id = msg.get("method"), msg.get("id")
        if msg_id is None:  # notifications need no answer
            continue
        if method == "initialize":
            reply(msg_id, {"protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                           "capabilities": {"tools": {}},
                           "serverInfo": {"name": "garmin", "version": "1.0"},
                           "instructions": "Read-only access to Quinton's Garmin data and marathon plan (km, races: half Feb 14 2027, marathon Apr 25 2027, goal 3:00). Call sync first if the data may be stale."})
        elif method == "tools/list":
            reply(msg_id, {"tools": TOOLS})
        elif method == "tools/call":
            params = msg.get("params", {})
            if params.get("name") not in {t["name"] for t in TOOLS}:
                reply(msg_id, error={"code": -32602, "message": f"Unknown tool {params.get('name')}"})
            else:
                try:
                    reply(msg_id, call(params["name"], params.get("arguments")))
                except subprocess.TimeoutExpired:
                    reply(msg_id, {"content": [{"type": "text", "text": "Error: timed out"}], "isError": True})
        elif method == "ping":
            reply(msg_id, {})
        else:
            reply(msg_id, error={"code": -32601, "message": f"Method not found: {method}"})


if __name__ == "__main__":
    main()
