#!/usr/bin/env python3
"""Poll GitHub PRs for new commits and review status changes.

Reads state from $KLIR_CRON_STATE_DIR/state.json.
Outputs events as JSON to stdout.

Exit codes:
  0 — events found
  1 — nothing new
  2 — error
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _fatal(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def _parse_args() -> Path:
    if len(sys.argv) < 2:
        _fatal("usage: git_poll.py <repo-path>")
    repo = Path(sys.argv[1])
    if not repo.is_dir():
        _fatal(f"repo not found: {repo}")
    return repo


def _get_state_dir() -> Path:
    raw = os.environ.get("KLIR_CRON_STATE_DIR")
    if not raw:
        _fatal("KLIR_CRON_STATE_DIR not set")
    return Path(raw)


def main() -> None:
    repo = _parse_args()
    state_dir = _get_state_dir()
    # Placeholder — next tasks add fetch, PR listing, and event detection
    sys.exit(1)


if __name__ == "__main__":
    main()
