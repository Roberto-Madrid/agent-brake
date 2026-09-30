"""Validated, immutable, idempotent usage events. No prompts or API calls."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class Invalid(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def integer(value, name, nullable=False):
    if value is None and nullable:
        return None
    if type(value) is not int or value < 0:
        raise Invalid(f"{name} must be a nonnegative integer")
    return value


def label(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise Invalid(f"{name} must be a nonempty string of at most 256 characters")
    return value


def validate(raw):
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise Invalid("event requires schema_version=1")
    base = {"schema_version", "event_id", "task_id", "workload", "cohort", "kind"}
    usage = {"actor", "purpose", "model", "input_tokens", "cached_input_tokens",
             "cache_write_tokens", "output_tokens", "cost_microusd", "cost_source", "elapsed_ms"}
    outcome = {"status", "evidence", "rework_count", "task_elapsed_ms", "human_ms"}
    metadata = {"project_id", "request_id", "parent_request_id", "rule_id", "rule_version", "policy_version", "pricing_version", "pricing_basis"}
    kind = raw.get("kind")
    if kind not in ("usage", "outcome"):
        raise Invalid("kind must be usage or outcome")
    extra = raw.keys() - base - metadata - (usage if kind == "usage" else outcome)
    if extra:
        raise Invalid(f"unknown event fields: {','.join(sorted(extra))}")
    e = {"schema_version": 1, "kind": kind}
    for key in ("event_id", "task_id", "workload", "cohort"):
        e[key] = label(raw.get(key), key)
    for key in metadata:
        if key in raw:
            e[key] = label(raw[key], key)
    if kind == "usage":
        e.update(actor=raw.get("actor", "worker"), purpose=raw.get("purpose", "execution"))
        if e["actor"] not in ("worker", "governor") or e["purpose"] not in ("execution", "overhead"):
            raise Invalid("invalid actor or purpose")
        if e["purpose"] == "overhead" and e["actor"] != "governor":
            raise Invalid("overhead requires actor=governor")
        e["model"] = label(raw.get("model", "unknown"), "model")
        for key in ("input_tokens", "output_tokens", "cost_microusd", "elapsed_ms"):
            e[key] = integer(raw.get(key), key, nullable=True)
        for key in ("cached_input_tokens", "cache_write_tokens"):
            e[key] = integer(raw.get(key), key, nullable=True)
        if e["input_tokens"] is not None:
            cached = (e["cached_input_tokens"] or 0) + (e["cache_write_tokens"] or 0)
            if cached > e["input_tokens"]:
                raise Invalid("cache tokens exceed inclusive input_tokens")
        e["cost_source"] = raw.get("cost_source")
        if e["cost_source"] not in (None, "billed", "estimated"):
            raise Invalid("cost_source must be billed, estimated, or null")
        if (e["cost_source"] is None) != (e["cost_microusd"] is None):
            raise Invalid("cost and cost_source must both be present or both null")
    else:
        e["status"] = raw.get("status")
        if e["status"] not in ("accepted", "failed"):
            raise Invalid("outcome status must be accepted or failed")
        e["evidence"] = label(raw.get("evidence"), "evidence")
        e["rework_count"] = integer(raw.get("rework_count", 0), "rework_count")
        for key in ("task_elapsed_ms", "human_ms"):
            if key in raw:
                e[key] = integer(raw[key], key, nullable=True)
    return e


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS events (
          event_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, workload TEXT NOT NULL,
          cohort TEXT NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS event_task ON events(task_id);
        CREATE INDEX IF NOT EXISTS event_cohort ON events(workload,cohort);
        CREATE UNIQUE INDEX IF NOT EXISTS one_outcome ON events(task_id) WHERE kind='outcome';
        CREATE TABLE IF NOT EXISTS cursors (source TEXT PRIMARY KEY, offset INTEGER,
          identity TEXT, prefix TEXT, prefix_length INTEGER);
        CREATE TABLE IF NOT EXISTS reservations (id TEXT PRIMARY KEY, task_id TEXT,
          estimate INTEGER, status TEXT, event_id TEXT);
        CREATE TABLE IF NOT EXISTS tools (id TEXT PRIMARY KEY, session TEXT, name TEXT,
          fingerprint TEXT, status TEXT, output_bytes INTEGER, created REAL);
        CREATE INDEX IF NOT EXISTS tools_session ON tools(session);
        CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS findings (id TEXT PRIMARY KEY, code TEXT, data TEXT,
          created REAL, resolved INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS runtime (id INTEGER PRIMARY KEY, operation TEXT, elapsed_ms REAL);
        CREATE TABLE IF NOT EXISTS scan_state (policy TEXT PRIMARY KEY, last_row INTEGER);
        """)
        self.path.chmod(0o600)
        from .governance import initialize
        initialize(self)

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def _add(self, raw):
        e = validate(raw)
        encoded = canonical(e)
        old = self.db.execute("SELECT data FROM events WHERE event_id=?", (e["event_id"],)).fetchone()
        if old:
            if old["data"] != encoded:
                raise Invalid("event ID conflict: immutable event has different content")
            return False
        previous = self.db.execute("SELECT workload,cohort FROM events WHERE task_id=? LIMIT 1",
                                   (e["task_id"],)).fetchone()
        if previous and (previous["workload"], previous["cohort"]) != (e["workload"], e["cohort"]):
            raise Invalid("task identity cannot cross workloads or cohorts")
        task = self.db.execute("SELECT project,workload,cohort FROM tasks WHERE id=?", (e["task_id"],)).fetchone()
        if task and (e.get("project_id"), e["workload"], e["cohort"]) != tuple(task):
            raise Invalid("registered task identity mismatch; include project_id")
        try:
            self.db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)",
                            (e["event_id"], e["task_id"], e["workload"], e["cohort"], e["kind"], encoded))
        except sqlite3.IntegrityError as exc:
            raise Invalid("task already has a final outcome; use a new task ID for a new trial") from exc
        self.db.execute("INSERT INTO event_times VALUES (?,?)", (e["event_id"], time.time()))
        if e['kind'] == 'usage':
            self.db.execute('INSERT INTO usage_index VALUES (?,?,?,?,?)', (e['event_id'],e.get('project_id'),e['task_id'],e['actor'],e['cost_microusd']))
        return True

    def add(self, raw):
        with self.transaction():
            return self._add(raw)

    def ingest(self, path, normalize=lambda x: x, batch=10000):
        """Commit events and cursor together. Defer incomplete trailing lines."""
        source = Path(path).resolve()
        added = duplicate = lines = 0
        with source.open("rb") as stream, self.transaction():
            stat = source.stat()
            identity = f"{stat.st_dev}:{stat.st_ino}"
            old = self.db.execute("SELECT * FROM cursors WHERE source=?", (str(source),)).fetchone()
            offset = 0
            if old and old["identity"] == identity and stat.st_size >= old["offset"]:
                prefix = hashlib.sha256(stream.read(old["prefix_length"])).hexdigest()
                if prefix == old["prefix"]:
                    offset = old["offset"]
            stream.seek(offset)
            while lines < batch:
                start = stream.tell()
                line = stream.readline(2 * 1024 * 1024 + 1)
                if not line:
                    break
                if len(line) > 2 * 1024 * 1024:
                    raise Invalid("input line exceeds 2 MiB; export structured usage without message content")
                if not line.endswith(b"\n"):
                    stream.seek(start)
                    break
                lines += 1
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                    event = normalize(raw)
                except (ValueError, KeyError, TypeError) as exc:
                    raise Invalid(f"invalid usage record at byte {start}: {type(exc).__name__}") from exc
                if event is None:
                    continue
                if self._add(event):
                    added += 1
                else:
                    duplicate += 1
            offset = stream.tell()
            plen = min(offset, 4096)
            stream.seek(0)
            prefix = hashlib.sha256(stream.read(plen)).hexdigest()
            self.db.execute("INSERT OR REPLACE INTO cursors VALUES (?,?,?,?,?)",
                            (str(source), offset, identity, prefix, plen))
        return {"added": added, "duplicates": duplicate, "lines": lines, "offset": offset}

    def events(self, workload, cohort):
        return [json.loads(r[0]) for r in self.db.execute(
            "SELECT data FROM events WHERE workload=? AND cohort=? ORDER BY event_id", (workload, cohort))]

    def find(self, code, key, data):
        identity = digest([code, key])
        self.db.execute("INSERT OR IGNORE INTO findings(id,code,data,created) VALUES (?,?,?,?)",
                        (identity, code, canonical(data), time.time()))
        return identity

    def findings(self, limit=3):
        return [{"id": r["id"], "code": r["code"], **json.loads(r["data"])} for r in self.db.execute(
            "SELECT * FROM findings WHERE resolved=0 ORDER BY created LIMIT ?", (limit,))]

    def reserve(self, identity, task_id, estimate, cap):
        label(identity, "reservation ID")
        label(task_id, "task ID")
        integer(estimate, "estimate")
        integer(cap, "cap")
        with self.transaction():
            old = self.db.execute("SELECT * FROM reservations WHERE id=?", (identity,)).fetchone()
            if old:
                if (old["task_id"], old["estimate"]) != (task_id, estimate):
                    raise Invalid("reservation ID conflict")
                return {"decision": "REPLAY", "status": old["status"], "dispatch": False}
            events = [json.loads(r[0]) for r in self.db.execute(
                "SELECT data FROM events WHERE task_id=? AND kind='usage'", (task_id,))]
            if any(e["cost_microusd"] is None for e in events):
                return {"decision": "HOLD", "reason": "unknown_task_cost", "dispatch": False}
            spent = sum(e["cost_microusd"] for e in events)
            reserved = self.db.execute("SELECT COALESCE(SUM(estimate),0) FROM reservations WHERE task_id=? AND status='active'",
                                       (task_id,)).fetchone()[0]
            if spent + reserved + estimate > cap:
                return {"decision": "HOLD", "reason": "budget", "dispatch": False}
            self.db.execute("INSERT INTO reservations VALUES (?,?,?,'active',NULL)", (identity, task_id, estimate))
            return {"decision": "ALLOW", "dispatch": True, "reserved_microusd": estimate}

    def settle(self, identity, raw):
        event = validate(raw)
        if event["kind"] != "usage":
            raise Invalid("settlement requires usage")
        with self.transaction():
            old = self.db.execute("SELECT * FROM reservations WHERE id=?", (identity,)).fetchone()
            if not old or old["task_id"] != event["task_id"] or old["status"] == "released":
                raise Invalid("missing, released, or mismatched reservation")
            if old["status"] == "settled" and old["event_id"] != event["event_id"]:
                raise Invalid("reservation already settled with another event")
            other = self.db.execute("SELECT id FROM reservations WHERE event_id=? AND id!=?",
                                    (event["event_id"], identity)).fetchone()
            if other:
                raise Invalid("usage event already settles another reservation")
            self._add(event)
            self.db.execute("UPDATE reservations SET status='settled',event_id=? WHERE id=?", (event["event_id"], identity))
        return {"status": "settled", "over_estimate": event["cost_microusd"] is not None and event["cost_microusd"] > old["estimate"]}

    def release(self, identity):
        with self.transaction():
            old = self.db.execute("SELECT status FROM reservations WHERE id=?", (identity,)).fetchone()
            if not old or old[0] == "settled":
                raise Invalid("missing or settled reservation")
            self.db.execute("UPDATE reservations SET status='released' WHERE id=?", (identity,))
        return {"status": "released"}
