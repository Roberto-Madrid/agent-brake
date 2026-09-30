#!/usr/bin/env python3
"""Measure local hook overhead, including process startup; no model calls."""
import argparse
import json
import math
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--iterations", type=int, default=30)
args = p.parse_args()
if not 1 <= args.iterations <= 1000:
    p.error("iterations must be 1..1000")
script = Path(__file__).resolve().parent / "tp.py"
times = []
with tempfile.TemporaryDirectory(prefix="token-police-bench-") as state:
    for i in range(args.iterations):
        payload = {"hook_event_name": "PreToolUse", "session_id": "bench", "tool_use_id": str(i),
                   "tool_name": "Bash", "tool_input": {"command": "true"}}
        start = time.perf_counter()
        result = subprocess.run([sys.executable, str(script), "--home", state, "hook", "--host", "codex"],
                                input=json.dumps(payload), text=True, capture_output=True, check=True)
        times.append((time.perf_counter()-start)*1000)
        assert result.stdout == ""
times.sort()
print(json.dumps({"scenario": "synthetic_observe_pretool_including_startup", "iterations": len(times),
                  "python": platform.python_version(), "platform": platform.system(),
                  "p50_ms": round(statistics.median(times), 3), "p95_ms": round(times[math.ceil(.95*len(times))-1], 3),
                  "total_ms": round(sum(times), 3), "model_visible_output_bytes": 0, "llm_calls": 0}))
