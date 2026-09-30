"""Deterministic comparisons; missing data never becomes a claimed saving."""
from decimal import Decimal, ROUND_CEILING
from .ledger import Invalid, integer


def price(event, rates):
    """Inclusive canonical input. Rates are USD / million tokens; no live defaults."""
    counts = [event.get(k) for k in ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens")]
    if any(x is None for x in counts):
        return None
    total, output, cached, written = counts
    for value in counts:
        integer(value, "token count")
    if total < cached + written:
        raise Invalid("cache tokens exceed input")
    units = {"input": total - cached - written, "output": output, "cache_read": cached, "cache_write": written}
    result = Decimal(0)
    for key, count in units.items():
        if not count:
            continue
        if key not in rates:
            return None
        rate = Decimal(str(rates[key]))
        if not rate.is_finite() or rate < 0:
            raise Invalid("invalid price rate")
        result += count * rate
    return int(result.to_integral_value(rounding=ROUND_CEILING))


def summarize(events):
    usage = [e for e in events if e["kind"] == "usage"]
    outcomes = [e for e in events if e["kind"] == "outcome"]
    accepted = sum(e["status"] == "accepted" for e in outcomes)
    execution_tasks = {e["task_id"] for e in usage if e["purpose"] == "execution"}
    outcome_tasks = {e["task_id"] for e in outcomes}
    result = {"usage_events": len(usage), "accepted": accepted, "failed": len(outcomes) - accepted,
              "open_tasks": len(execution_tasks - outcome_tasks), "outcomes_without_usage": len(outcome_tasks - execution_tasks),
              "rework": sum(e["rework_count"] for e in outcomes),
              "estimated_cost_events": sum(e["cost_source"] == "estimated" for e in usage)}
    for field in ("input_tokens", "output_tokens", "cost_microusd", "elapsed_ms"):
        values = [e[field] for e in usage]
        missing = sum(v is None for v in values)
        result[field] = None if missing or not values else sum(values)
        result[f"missing_{field}"] = missing
    gov = [e for e in usage if e["actor"] == "governor"]
    result["governor_cost_microusd"] = None if any(e["cost_microusd"] is None for e in gov) else sum(e["cost_microusd"] for e in gov)
    result["governor_cost_fraction"] = result["governor_cost_microusd"] / result["cost_microusd"] if result["cost_microusd"] and result["governor_cost_microusd"] is not None else None
    result["cost_per_accepted_microusd"] = result["cost_microusd"] / accepted if accepted and result["cost_microusd"] is not None else None
    n = len(outcomes)
    result["acceptance_rate"] = accepted / n if n else None
    result["rework_per_task"] = result["rework"] / n if n else None
    return result


def compare(before, after, minimum=5, attested=False):
    integer(minimum, "minimum")
    if minimum < 1:
        raise Invalid("minimum must be positive")
    b, a = summarize(before), summarize(after)
    gaps = []
    if not attested:
        gaps.append("coverage_and_comparability_not_attested")
    for name, group in (("baseline", b), ("treatment", a)):
        if group["accepted"] < minimum:
            gaps.append(f"{name}_sample_too_small")
        if group["cost_microusd"] is None:
            gaps.append(f"{name}_cost_unknown")
        if group["open_tasks"] or group["outcomes_without_usage"]:
            gaps.append(f"{name}_outcomes_incomplete")
    net = None
    if b["cost_per_accepted_microusd"] is not None and a["cost_microusd"] is not None and a["accepted"]:
        net = round(b["cost_per_accepted_microusd"] * a["accepted"] - a["cost_microusd"], 3)
    quality = (a["acceptance_rate"] is not None and b["acceptance_rate"] is not None
               and (a["acceptance_rate"] < b["acceptance_rate"] or a["rework_per_task"] > b["rework_per_task"]))
    status = "insufficient_evidence" if gaps else "quality_regression" if quality else "estimated_net_positive" if net > 0 else "no_observed_benefit"
    return {"status": status, "estimated_net_savings_microusd": net if not gaps else None,
            "baseline": b, "treatment": a, "quality_regression": quality, "gaps": gaps,
            "causal_proof": False, "accounting": "All logged governor/setup costs are already included once in cohort totals."}


def skill_payback(candidate):
    keys = ("expected_uses", "saved_units_per_use", "load_units_per_use", "build_units", "maintenance_units")
    for key in keys:
        integer(candidate.get(key), key)
    net = candidate["expected_uses"] * (candidate["saved_units_per_use"] - candidate["load_units_per_use"]) - candidate["build_units"] - candidate["maintenance_units"]
    eligible = all(candidate.get(k) is True for k in ("stable_workflow", "needs_judgment", "no_existing_fit"))
    return {"verdict": "candidate_for_validation" if eligible and net > 0 else "defer_or_use_simpler_mechanism",
            "estimated_net_units": net, "unit": candidate.get("unit", "unspecified"), "auto_create": False}
