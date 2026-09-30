#!/usr/bin/env python3
"""Synthetic, isolated end-to-end smoke test. Does not call a model."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="token-police-demo-") as state:
    def run(*args):
        completed = subprocess.run([sys.executable, str(root / "scripts/tp.py"), "--home", state, *args], capture_output=True, text=True, check=True)
        return json.loads(completed.stdout)
    imported = run("ingest", str(root / "examples/usage.jsonl"))
    replay = run("ingest", str(root / "examples/usage.jsonl"))
    assert imported["added"] == 21 and replay["added"] == 0
    unknown = run("compare", "--workload", "synthetic-log-review")
    assert unknown["status"] == "insufficient_evidence"
    comparison = run("compare", "--workload", "synthetic-log-review", "--attest-complete")
    assert comparison["estimated_net_savings_microusd"] == 125000
    # Same worker improvement becomes net negative when setup is expensive.
    extra = {"schema_version": 1, "event_id": "more-setup", "task_id": "more-setup", "workload": "synthetic-log-review",
             "cohort": "treatment", "kind": "usage", "actor": "governor", "purpose": "overhead",
             "cost_microusd": 200000, "cost_source": "billed"}
    file = Path(state) / "overhead.json"
    file.write_text(json.dumps(extra))
    run("record", str(file))
    expensive = run("compare", "--workload", "synthetic-log-review", "--attest-complete")
    assert expensive["status"] == "no_observed_benefit"
    print(json.dumps({"fixture": "synthetic_only", "normal_net_microusd": comparison["estimated_net_savings_microusd"],
                      "expensive_governor_net_microusd": expensive["estimated_net_savings_microusd"],
                      "duplicate_import_added": replay["added"], "llm_calls": 0}))
