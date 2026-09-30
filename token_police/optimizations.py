"""Explicit deterministic transformations; no arbitrary shell rewrites."""
import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from .governance import audit, enabled, intervention
from .ledger import Invalid, canonical, digest, integer


def source_bytes(root, filename, max_bytes=8*1024*1024):
    root = Path(root).resolve(strict=True)
    path = Path(filename).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise Invalid('source must be a file inside the explicit allowed root')
    # Reopen on every request: no cache access bypasses current file permissions.
    with path.open('rb') as stream:
        data = stream.read(max_bytes+1)
    if len(data) > max_bytes:
        raise Invalid('source exceeds 8 MiB; narrow the source with an existing tool')
    return path, data


def read_reference(ledger, root, filename, task, offset=0, lines=200, force=False, byte_offset=0):
    integer(offset,'offset'); integer(lines,'lines')
    integer(byte_offset,'byte_offset')
    if not 1 <= lines <= 1000:
        raise Invalid('lines must be 1..1000')
    if not enabled(ledger,'read_reference',task=task):
        raise Invalid('read_reference rule disabled or expired; use native read')
    path, data = source_bytes(root,filename)
    fingerprint = hashlib.sha256(data).hexdigest()
    rows = data.decode('utf-8',errors='replace').splitlines(keepends=True)
    fragment = ''.join(rows[offset:offset+lines])
    encoded = fragment.encode()
    if byte_offset > len(encoded):
        raise Invalid('byte_offset exceeds the selected fragment')
    # A continuation stays on the same line selection until every byte is returned.
    if byte_offset < len(encoded) and encoded[byte_offset] & 0xc0 == 0x80:
        raise Invalid('byte_offset must start at a UTF-8 character boundary')
    content = encoded[byte_offset:byte_offset+16000].decode('utf-8',errors='ignore')
    consumed = len(content.encode())
    truncated = byte_offset + consumed < len(encoded)
    with ledger.transaction():
        generation = ledger.db.execute('SELECT generation FROM context_generations WHERE task=?',(task,)).fetchone()
        generation = generation[0] if generation else 0
        epoch = ledger.db.execute("SELECT generation FROM context_generations WHERE task='*'").fetchone()
        epoch = epoch[0] if epoch else 0
        key = digest([str(Path(root).resolve()),str(path),task,generation,epoch,offset,lines,byte_offset])
        old = ledger.db.execute('SELECT * FROM read_cache WHERE id=?',(key,)).fetchone()
        hit = bool(old and old['fingerprint'] == fingerprint and not force)
        ledger.db.execute('INSERT OR REPLACE INTO read_cache VALUES (?,?,?,?)',(key,fingerprint,str(path),time.time()))
        intervention(ledger,digest([key,fingerprint,time.time_ns()]),task,'read_reference')
    result = dict(path=str(path),sha256=fingerprint,offset=offset,lines_returned=min(lines,max(0,len(rows)-offset)),
                  next_offset=offset if truncated else offset+lines if offset+lines < len(rows) else None,
                  next_byte_offset=byte_offset+consumed if truncated else None, byte_offset=byte_offset,
                  context_generation=generation, context_epoch=epoch,
                  partial=truncated or offset > 0 or offset+lines < len(rows),long_line_truncated=truncated,
                  reused=hit,billing_savings='unknown')
    if hit:
        result['instruction'] = 'Unchanged source already returned in this task; use --force after context loss.'
    else:
        result['content'] = content
    return result


def json_select(ledger, root, filename, pointer, task):
    if not enabled(ledger,'json_select',task=task):
        raise Invalid('json_select rule disabled or expired')
    path,data = source_bytes(root,filename)
    value = json.loads(data)
    if pointer and not pointer.startswith('/'):
        raise Invalid('JSON pointer must start with /')
    for part in pointer.split('/')[1:] if pointer else []:
        key = part.replace('~1','/').replace('~0','~')
        if isinstance(value,list):
            if not key.isdecimal() or len(key)>1 and key.startswith('0'):
                raise Invalid('invalid array index')
            try:
                value = value[int(key)]
            except IndexError as exc:
                raise Invalid('array index out of bounds') from exc
        elif isinstance(value,dict) and key in value:
            value=value[key]
        else:
            raise Invalid('JSON pointer does not exist')
    if len(canonical(value).encode()) > 16000:
        raise Invalid('selection exceeds 16000 bytes; choose a narrower pointer')
    with ledger.transaction():
        intervention(ledger,digest([task,str(path),pointer,time.time_ns()]),task,'json_select')
    return dict(value=value,source=str(path),pointer=pointer,source_sha256=hashlib.sha256(data).hexdigest(),
                partial=bool(pointer),billing_savings='unknown')


def cache_report(events):
    usage=[e for e in events if e['kind']=='usage']
    known=[e for e in usage if e['input_tokens'] is not None and e['cached_input_tokens'] is not None and e['cache_write_tokens'] is not None]
    total=sum(e['input_tokens'] for e in known)
    return dict(usage_events=len(usage),known_cache_events=len(known),
        cached_input_fraction=sum(e['cached_input_tokens'] for e in known)/total if total else None,
        cache_write_tokens=sum(e['cache_write_tokens'] for e in known) if known else None,
        recommendation='Preserve stable prefixes; compare billed cost before changing context.',
        automatic_prompt_rewrite=False,coverage_complete=bool(usage) and len(known)==len(usage))


def retention(ledger, days=30, apply=False):
    integer(days,'days')
    if days < 1:
        raise Invalid('retention must be at least one day')
    cutoff=time.time()-days*86400
    root=ledger.path.parent/'artifacts'
    candidates=[]
    if root.exists() and not root.is_symlink():
        for p in root.iterdir():
            if not p.is_symlink() and p.is_dir() and p.stat().st_mtime < cutoff:
                candidates.append(p)
    if apply:
        for path in candidates:
            shutil.rmtree(path)
        with ledger.transaction():
            ledger.db.execute('DELETE FROM read_cache WHERE created<?',(cutoff,))
            ledger.db.execute('DELETE FROM runtime WHERE created<?',(cutoff,))
            ledger.db.execute('DELETE FROM findings WHERE resolved=1 AND created<?',(cutoff,))
            audit(ledger,'retention.apply',dict(days=days,artifact_directories=len(candidates)))
    return dict(dry_run=not apply,artifact_directories=len(candidates),
                protected='usage, outcomes, admissions, interventions, skill evidence, rules and audit are retained')
