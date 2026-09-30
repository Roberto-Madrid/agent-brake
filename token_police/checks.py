"""Deterministic checks copied from repeated fleet gates. No model calls and no secret values."""
import os
import subprocess
from pathlib import Path
from .controls import run_bounded
from .ledger import Invalid, integer


SECRET_NAMES = {'.env', 'id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519', 'credentials.json', 'secrets.json'}
SECRET_SUFFIXES = ('.pem', '.p12', '.pfx', '.key')
SKIP_DIRS = {'.git', 'node_modules', '.venv', '__pycache__'}


def gate_exit(command, directory, limit=12000, timeout=60):
    """Record an exit code. Do not decide whether the owner should block or retry."""
    result = run_bounded(command, directory, limit, timeout)
    code = result['exit_code']
    output = {}
    for name, item in result['output'].items():
        output[name] = {k: item[k] for k in ('bytes', 'truncated', 'path')}
    return dict(check='gate_exit', exit_code=code, timed_out=result['timed_out'], elapsed_ms=result['elapsed_ms'],
                verdict='pass' if code == 0 else 'fail', judgment='not_automated', output=output,
                billing_savings='unknown')


def diffstat(root, path_cap=20):
    """Return a capped path list and shortstat. Never return a patch body."""
    integer(path_cap, 'path_cap')
    if not 1 <= path_cap <= 200:
        raise Invalid('path cap must be 1..200')
    root = Path(root).resolve()

    def git(*args):
        return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)

    if git('rev-parse', '--is-inside-work-tree').returncode != 0:
        return dict(check='diffstat', verdict='unknown', reason='not_a_git_checkout', paths=[], billing_savings='unknown')
    names = git('diff', '--name-only', 'HEAD')
    untracked = git('ls-files', '--others', '--exclude-standard')
    if names.returncode != 0 or untracked.returncode != 0:
        return dict(check='diffstat', verdict='unknown', reason='git_diff_failed', billing_savings='unknown')
    paths = []
    for line in (names.stdout + '\n' + untracked.stdout).splitlines():
        if line and line not in paths:
            paths.append(line)
    short = git('diff', '--shortstat', 'HEAD')
    omitted = max(0, len(paths) - path_cap)
    return dict(check='diffstat', verdict='over_cap' if omitted else 'within_cap', path_count=len(paths),
                path_cap=path_cap, paths=paths[:path_cap], omitted=omitted,
                shortstat=(short.stdout.strip() or None) if short.returncode == 0 else None,
                billing_savings='unknown')


def secret_filename(name):
    lower = name.lower()
    return lower in SECRET_NAMES or lower.startswith('.env.') or lower.endswith(SECRET_SUFFIXES)


def secret_names(root, limit=50, max_seen=5000):
    """List suspicious filenames under a project root. Do not open those files."""
    integer(limit, 'limit')
    integer(max_seen, 'max_seen')
    if not 1 <= limit <= 200 or not 1 <= max_seen <= 20000:
        raise Invalid('secret-names limit must be 1..200 and max_seen 1..20000')
    root = Path(root).resolve()
    if not root.is_dir() or root == Path(root.anchor):
        raise Invalid('secret-names root must be a project directory')
    found = []
    seen = 0
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not (Path(dirpath) / d).is_symlink()]
        for name in filenames:
            seen += 1
            if seen > max_seen:
                truncated = True
                break
            path = Path(dirpath) / name
            if path.is_symlink() or not secret_filename(name):
                continue
            found.append(str(path.relative_to(root)))
            if len(found) >= limit:
                truncated = True
                break
        if truncated:
            break
    return dict(check='secret_names', names=found, truncated=truncated, values_read=False, billing_savings='unknown')


def skill_budget(path, max_words=349):
    """Count words. The package invariant rejects a skill at 350 words or more."""
    integer(max_words, 'max_words')
    if not 1 <= max_words <= 5000:
        raise Invalid('max_words must be 1..5000')
    file = Path(path)
    data = file.read_bytes()
    if len(data) > 1024 * 1024:
        raise Invalid('skill file exceeds 1 MiB')
    words = len(data.decode('utf-8', errors='replace').split())
    return dict(check='skill_budget', path=str(file.resolve()), words=words, max_words=max_words,
                over=words > max_words, billing_savings='unknown')
