"""Import final usage receipts. No provider SDK, network, or guessed pricing."""
from .ledger import Invalid, validate, digest, label
from .metrics import price


def normalizer(format_name, task=None, workload=None, cohort=None, actor="worker", rates=None):
    if format_name == "canonical":
        return validate
    if not all((task, workload, cohort)):
        raise Invalid("provider imports require --task, --workload, --cohort")
    pricing_version = digest(rates) if rates else None
    pricing_basis = 'operator-supplied-rate-map'
    if rates and 'models' in rates:
        if set(rates) != {'version','effective_date','source_url','models'}:
            raise Invalid('versioned rates require version, effective_date, source_url, models')
        from datetime import date
        date.fromisoformat(rates['effective_date'])
        label(rates['version'], 'pricing version')
        if not isinstance(rates['source_url'], str) or not rates['source_url'].startswith('https://'):
            raise Invalid('pricing source requires an HTTPS URL')
        pricing_version = rates['version'] + ':' + digest(rates)
        label(pricing_version, 'pricing version with digest')
        pricing_basis = rates['effective_date'] + ':' + rates['source_url']
        label(pricing_basis, 'pricing basis')
        rates = rates['models']
    if rates is not None and not isinstance(rates, dict):
        raise Invalid('rates must be an object')

    def convert(raw):
        if format_name == 'otel':
            # An envelope or batch can hide charges. Skipping it would advance the
            # cursor and make that spend look absent.
            if any(k in raw for k in ('resourceSpans','scopeSpans','resource_spans','scope_spans','instrumentationLibrarySpans','spans')):
                raise Invalid('otel adapter does not accept raw OTLP envelopes or span batches; pass one flattened final span per line')
            attrs = raw.get('attributes', {})
            if not isinstance(attrs, dict):
                raise Invalid('otel adapter expects a flattened attribute map')
            if attrs.get('token_police.aggregate') is True:
                raise Invalid('aggregate parent span rejected; export only the final charge span')
            has_usage = any(k in attrs for k in ('gen_ai.usage.input_tokens','gen_ai.usage.output_tokens'))
            has_cost = any(k in attrs for k in ('token_police.cost_microusd','token_police.cost_source'))
            if not has_usage and not has_cost:
                return None
            if not raw.get('trace_id') or not raw.get('span_id'):
                raise Invalid('otel final span requires trace_id and span_id')
            e = dict(schema_version=1,kind='usage',event_id=f"otel:{raw['trace_id']}:{raw['span_id']}",
                task_id=task,workload=workload,cohort=cohort,actor=actor,purpose='execution',
                model=attrs.get('gen_ai.response.model',attrs.get('gen_ai.request.model','unknown')),
                input_tokens=attrs.get('gen_ai.usage.input_tokens'),output_tokens=attrs.get('gen_ai.usage.output_tokens'),
                cached_input_tokens=attrs.get('token_police.cached_input_tokens'),
                cache_write_tokens=attrs.get('token_police.cache_write_tokens'),
                cost_microusd=attrs.get('token_police.cost_microusd'),cost_source=attrs.get('token_police.cost_source'))
            e=validate(e)
            if e['cost_microusd'] is None and rates and e['model'] in rates:
                cost=price(e,rates[e['model']])
                if cost is not None:
                    e.update(cost_microusd=cost,cost_source='estimated',pricing_version=pricing_version,pricing_basis=pricing_basis)
            return e
        if format_name == "claude":
            if raw.get("type") != "assistant":
                return None
            msg = raw.get("message", {})
        else:
            msg = raw
        usage = msg.get("usage")
        if not isinstance(usage, dict) or not msg.get("id"):
            raise Invalid("final provider receipt requires id and usage")
        e = dict(schema_version=1, kind="usage", event_id=f"{format_name}:{msg['id']}", task_id=task,
                 workload=workload, cohort=cohort, actor=actor, purpose="execution", model=msg.get("model", "unknown"))
        if format_name in ("anthropic", "claude"):
            plain = usage.get("input_tokens")
            cached = usage.get("cache_read_input_tokens")
            written = usage.get("cache_creation_input_tokens")
            e.update(input_tokens=None if any(v is None for v in (plain,cached,written)) else plain + cached + written,
                     cached_input_tokens=cached, cache_write_tokens=written, output_tokens=usage.get("output_tokens"))
        elif format_name == "openai":
            responses = "input_tokens" in usage
            detail = usage.get("input_tokens_details" if responses else "prompt_tokens_details") or {}
            e.update(input_tokens=usage.get("input_tokens" if responses else "prompt_tokens"),
                     output_tokens=usage.get("output_tokens" if responses else "completion_tokens"),
                     cached_input_tokens=detail.get("cached_tokens"),
                     cache_write_tokens=detail.get("cache_write_tokens", 0))
        else:
            raise Invalid("unsupported format")
        e = validate(e)
        if rates and e["model"] in rates:
            cost = price(e, rates[e["model"]])
            if cost is not None:
                e.update(cost_microusd=cost, cost_source="estimated",pricing_version=pricing_version,pricing_basis=pricing_basis)
        return e
    return convert
