#!/usr/bin/env python3
"""Run from a checkout/plugin bundle without installing dependencies."""
import sys
if sys.version_info < (3, 10):
    sys.exit('Token Police requires Python 3.10+; use scripts/launch.sh or a supported interpreter.')
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from token_police.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
