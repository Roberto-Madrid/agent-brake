#!/bin/sh
# Hook bootstrap: preserve stdin, use no shell eval, require Python 3.10+.
set -u
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd) || exit 2
state=${TOKEN_POLICE_HOME:-${PLUGIN_DATA:-${CLAUDE_PLUGIN_DATA:-${HOME}/.token-police}}}
probe='import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'
if [ -n "${TOKEN_POLICE_PYTHON:-}" ]; then
    if "$TOKEN_POLICE_PYTHON" -c "$probe" </dev/null >/dev/null 2>&1; then
        exec "$TOKEN_POLICE_PYTHON" "$root/scripts/tp.py" "$@"
    fi
    echo 'Token Police: TOKEN_POLICE_PYTHON must name a Python 3.10+ executable.' >&2
    exit 2
fi
if [ -f "$state/python-path" ]; then
    IFS= read -r interpreter < "$state/python-path" || interpreter=''
    if [ -n "$interpreter" ] && "$interpreter" -c "$probe" </dev/null >/dev/null 2>&1; then
        exec "$interpreter" "$root/scripts/tp.py" "$@"
    fi
    echo 'Token Police: configured Python is unavailable; rerun scripts/setup.py.' >&2
    exit 2
fi
for interpreter in python3 python; do
    if command -v "$interpreter" >/dev/null 2>&1 && "$interpreter" -c "$probe" </dev/null >/dev/null 2>&1; then
        exec "$interpreter" "$root/scripts/tp.py" "$@"
    fi
done
if command -v py >/dev/null 2>&1 && py -3 -c "$probe" </dev/null >/dev/null 2>&1; then
    exec py -3 "$root/scripts/tp.py" "$@"
fi
echo 'Token Police: Python 3.10+ required. Run scripts/setup.py with a supported interpreter.' >&2
exit 2
