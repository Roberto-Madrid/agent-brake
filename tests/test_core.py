import concurrent.futures
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

from token_police.adapters import normalizer
from token_police.cli import main
from token_police.controls import DEFAULTS, hook, run_bounded, scan
from token_police.ledger import Invalid, Ledger, validate
from token_police.metrics import compare, price, skill_payback


def usage(identity="u1", task="t1", cohort="baseline", cost=1000, **kw):
    return dict(schema_version=1, event_id=identity, task_id=task, workload="lint", cohort=cohort,
                kind="usage", cost_microusd=cost, cost_source=None if cost is None else "billed",
                input_tokens=100, output_tokens=20, cached_input_tokens=0, cache_write_tokens=0, **kw)


def outcome(identity="o1", task="t1", cohort="baseline", status="accepted", rework=0):
    return dict(schema_version=1, event_id=identity, task_id=task, workload="lint", cohort=cohort,
                kind="outcome", status=status, evidence="test-suite:passed" if status == "accepted" else "test-suite:failed",
                rework_count=rework)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.ledger = Ledger(self.home / "ledger.db")

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def test_duplicate_receipt_is_not_billed_twice(self):
        self.assertTrue(self.ledger.add(usage()))
        self.assertFalse(self.ledger.add(usage()))
        self.assertEqual(len(self.ledger.events("lint", "baseline")), 1)
        with self.assertRaises(Invalid):
            self.ledger.add(usage(cost=2000))

    def test_task_cohort_and_final_outcome_are_immutable(self):
        self.ledger.add(usage())
        with self.assertRaises(Invalid):
            self.ledger.add(usage("u2", cohort="treatment"))
        self.ledger.add(outcome())
        with self.assertRaises(Invalid):
            self.ledger.add(outcome("o2", status="failed"))

    def test_cursor_partial_line_duplicate_and_rotation(self):
        path = self.home / "events.jsonl"
        path.write_text(json.dumps(usage()) + "\n" + json.dumps(usage("u2")))
        self.assertEqual(self.ledger.ingest(path)["added"], 1)
        self.assertEqual(self.ledger.ingest(path)["added"], 0)
        with path.open("a") as stream:
            stream.write("\n")
        self.assertEqual(self.ledger.ingest(path)["added"], 1)
        path.write_text(json.dumps(usage("u3")) + "\n")
        self.assertEqual(self.ledger.ingest(path)["added"], 1)
        path.write_text(json.dumps(usage()) + "\n")
        self.assertEqual(self.ledger.ingest(path)["duplicates"], 1)

    def test_malformed_batch_rolls_back_cursor_and_events(self):
        path = self.home / "events.jsonl"
        path.write_text(json.dumps(usage()) + "\n{invalid}\n")
        with self.assertRaises(Invalid):
            self.ledger.ingest(path)
        self.assertEqual(self.ledger.events("lint", "baseline"), [])
        self.assertEqual(self.ledger.db.execute("SELECT COUNT(*) FROM cursors").fetchone()[0], 0)

    def test_unknown_cost_cannot_pass_monetary_guard(self):
        self.ledger.add(usage(cost=None))
        result = self.ledger.reserve("r1", "t1", 1, 50000)
        self.assertEqual(result["reason"], "unknown_task_cost")

    def test_reservation_replay_and_settlement_count_once(self):
        self.assertTrue(self.ledger.reserve("r1", "t1", 500, 1000)["dispatch"])
        self.assertFalse(self.ledger.reserve("r1", "t1", 500, 1000)["dispatch"])
        self.assertFalse(self.ledger.reserve("r2", "t1", 600, 1000)["dispatch"])
        self.ledger.settle("r1", usage(cost=400))
        self.ledger.settle("r1", usage(cost=400))
        self.assertTrue(self.ledger.reserve("r2", "t1", 600, 1000)["dispatch"])
        self.assertFalse(self.ledger.reserve("r3", "t1", 1, 1000)["dispatch"])
        with self.assertRaises(Invalid):
            self.ledger.settle("r2", usage(cost=400))

    def test_concurrent_reservations_cannot_each_spend_full_budget(self):
        path = self.home / "ledger.db"
        def reserve(i):
            db = Ledger(path)
            try:
                return db.reserve(f"r{i}", "task", 60, 100)["dispatch"]
            finally:
                db.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(reserve, range(8)))
        self.assertEqual(sum(results), 1)

    def test_release_requires_unsettled_reservation(self):
        self.ledger.reserve("r1", "t1", 100, 100)
        self.ledger.release("r1")
        self.assertFalse(self.ledger.reserve("r1", "t1", 100, 100)["dispatch"])
        with self.assertRaises(Invalid):
            self.ledger.settle("r1", usage())

    def test_scan_is_incremental_and_findings_deduplicated(self):
        event = usage()
        event["input_tokens"] = 100000
        self.ledger.add(event)
        self.assertEqual(scan(self.ledger, DEFAULTS)["scanned"], 1)
        self.assertEqual(scan(self.ledger, DEFAULTS)["scanned"], 0)
        self.assertEqual(len(self.ledger.findings()), 1)


class AccountingTests(unittest.TestCase):
    def groups(self):
        b = [validate(usage()), validate(outcome())]
        a = [validate(usage("a1", "a", "treatment", 500)), validate(outcome("a2", "a", "treatment"))]
        return b, a

    def test_overhead_can_reverse_apparent_savings(self):
        b, a = self.groups()
        a.append(validate(usage("g1", "setup", "treatment", 600, actor="governor", purpose="overhead")))
        result = compare(b, a, minimum=1, attested=True)
        self.assertEqual(result["estimated_net_savings_microusd"], -100)
        self.assertEqual(result["status"], "no_observed_benefit")

    def test_successful_comparison_is_estimate_not_causal_proof(self):
        b, a = self.groups()
        result = compare(b, a, minimum=1, attested=True)
        self.assertEqual(result["estimated_net_savings_microusd"], 500)
        self.assertFalse(result["causal_proof"])

    def test_unknown_money_blocks_claim(self):
        b, a = self.groups()
        a[0]["cost_microusd"] = a[0]["cost_source"] = None
        result = compare(b, a, 1, True)
        self.assertIsNone(result["estimated_net_savings_microusd"])

    def test_quality_loss_blocks_positive_verdict(self):
        b, a = self.groups()
        a += [validate(usage("f1", "f", "treatment", 1)), validate(outcome("f2", "f", "treatment", "failed"))]
        self.assertEqual(compare(b, a, 1, True)["status"], "quality_regression")

    def test_untested_or_incomplete_work_cannot_claim_savings(self):
        b, a = self.groups()
        self.assertEqual(compare(b, a, 1, False)["status"], "insufficient_evidence")
        self.assertEqual(compare(b, a[:1], 1, True)["status"], "insufficient_evidence")

    def test_rework_regression_blocks_verdict(self):
        b, a = self.groups()
        a[-1]["rework_count"] = 1
        self.assertEqual(compare(b, a, 1, True)["status"], "quality_regression")

    def test_failed_baseline_tasks_are_included_in_cost(self):
        b, a = self.groups()
        b += [validate(usage("f1", "f", cost=1000)), validate(outcome("f2", "f", status="failed"))]
        self.assertEqual(compare(b, a, 1, True)["baseline"]["cost_per_accepted_microusd"], 2000)

    def test_cached_input_not_charged_again_at_full_price(self):
        self.assertEqual(price(dict(input_tokens=1000, output_tokens=100, cached_input_tokens=800, cache_write_tokens=0),
                               dict(input=2, output=10, cache_read=.2)), 1560)

    def test_anthropic_cache_components_are_normalized(self):
        receipt = {"id": "a", "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "cache_creation_input_tokens": 20, "output_tokens": 5}}
        event = normalizer("anthropic", "t", "w", "c")(receipt)
        self.assertEqual(event["input_tokens"], 120)

    def test_openai_reasoning_not_added_to_output_twice(self):
        event = normalizer("openai", "t", "w", "c")({"id": "x", "usage": {"input_tokens": 200, "output_tokens": 100, "output_tokens_details": {"reasoning_tokens": 70}}})
        self.assertEqual(event["output_tokens"], 100)
        self.assertIsNone(event["cost_microusd"])

    def test_validation_rejects_negative_boolean_and_impossible_cache(self):
        for update in ({"input_tokens": -1}, {"input_tokens": True}, {"cached_input_tokens": 101}, {"cost_microusd": 1.5}):
            with self.subTest(update=update), self.assertRaises(Invalid):
                validate({**usage(), **update})

    def test_skill_economics_do_not_auto_create(self):
        c = dict(expected_uses=2, saved_units_per_use=10, load_units_per_use=5, build_units=50,
                 maintenance_units=0, stable_workflow=True, needs_judgment=True, no_existing_fit=True)
        result = skill_payback(c)
        self.assertFalse(result["auto_create"])
        self.assertEqual(result["estimated_net_units"], -40)


class ControlsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.ledger = Ledger(self.home / "db")

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def event(self, identity="c1", **kw):
        return dict(hook_event_name="PreToolUse", session_id="s1", tool_use_id=identity,
                    tool_name="Read", tool_input={"file_path": "example.txt", "offset": 17}, **kw)

    def test_observation_never_changes_tool_input_or_emits_context(self):
        self.assertIsNone(hook(self.ledger, self.event(), DEFAULTS, "claude"))

    def test_native_read_bound_retains_other_arguments_and_permissions(self):
        output = hook(self.ledger, self.event(), {**DEFAULTS, "mode": "enforce"}, "claude")["hookSpecificOutput"]
        self.assertEqual(output["updatedInput"]["offset"], 17)
        self.assertEqual(output["updatedInput"]["limit"], 200)
        self.assertNotIn("permissionDecision", output)
        self.assertIn("partial", output["additionalContext"])

    def test_codex_does_not_receive_unsupported_native_read_rewrite(self):
        self.assertIsNone(hook(self.ledger, self.event(), {**DEFAULTS, "mode": "enforce"}, "codex"))

    def test_call_cap_and_hook_replay(self):
        conf = {**DEFAULTS, "mode": "enforce", "max_session_tool_calls": 1}
        a = hook(self.ledger, self.event(), conf, "claude")
        self.assertEqual(hook(self.ledger, self.event(), conf, "claude"), a)
        b = hook(self.ledger, self.event("c2"), conf, "claude")
        self.assertEqual(b["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_same_call_id_changed_input_rejected(self):
        hook(self.ledger, self.event(), DEFAULTS, "claude")
        e = self.event()
        e["tool_input"]["offset"] = 99
        with self.assertRaises(Invalid):
            hook(self.ledger, e, DEFAULTS, "claude")

    def test_repeated_failure_flags_without_blocking(self):
        for i in range(3):
            e = self.event(str(i))
            e["hook_event_name"] = "PostToolUseFailure"
            self.assertIsNone(hook(self.ledger, e, DEFAULTS, "claude"))
        self.assertEqual(self.ledger.findings()[0]["code"], "repeated_failure")

    def test_full_output_preserved_and_error_status_retained(self):
        result = run_bounded([sys.executable, "-c", "import sys; print('x'*20000); print('failure',file=sys.stderr); sys.exit(7)"], self.home, 1024)
        self.assertEqual(result["exit_code"], 7)
        self.assertTrue(result["output"]["stdout"]["truncated"])
        self.assertGreater(Path(result["output"]["stdout"]["path"]).stat().st_size, 20000)
        self.assertIn("failure", result["output"]["stderr"]["preview"])

    def test_timeout_is_explicit(self):
        result = run_bounded([sys.executable, "-c", "import time;time.sleep(10)"], self.home, timeout=1)
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["exit_code"], 124)

    def test_cli_clean_hook_has_zero_stdout(self):
        script = Path(__file__).parents[1] / "scripts/tp.py"
        result = subprocess.run([sys.executable, str(script), "--home", str(self.home), "hook", "--host", "claude"],
                                input=json.dumps(self.event()), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_malformed_observe_hook_reports_without_blocking(self):
        script = Path(__file__).parents[1] / "scripts/tp.py"
        result = subprocess.run([sys.executable, str(script), "--home", str(self.home), "hook", "--host", "claude"],
                                input="{}", text=True, capture_output=True)
        # Observation failures must not block the underlying task.
        self.assertEqual(result.returncode, 0)
        result = subprocess.run([sys.executable, str(script), "--home", str(self.home), "hook", "--host", "claude"],
                                input='{"hook_event_name":"PreToolUse"}', text=True, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("hook error", result.stderr)
        self.assertNotIn("allow", result.stdout)


if __name__ == "__main__":
    unittest.main()
