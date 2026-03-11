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


def _run_cmd(cmd: list[str], cwd: Path) -> str:
    """Run a command and return stdout. Fatal on failure."""
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        _fatal(f"command failed: {' '.join(cmd)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def _git_fetch(repo: Path) -> None:
    _run_cmd(["git", "fetch", "origin"], cwd=repo)


def _list_prs(repo: Path) -> list[dict]:
    raw = _run_cmd(
        ["gh", "pr", "list", "--json",
         "number,headRefName,headRefOid,reviewDecision,reviews",
         "--limit", "100"],
        cwd=repo,
    )
    if not raw:
        return []
    return json.loads(raw)


def _load_state(state_file: Path) -> dict:
    if state_file.exists():
        return json.loads(state_file.read_text())
    return {}


def _save_state(state_file: Path, state: dict) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2))


def main() -> None:
    repo = _parse_args()
    state_dir = _get_state_dir()
    state_file = state_dir / "state.json"

    _git_fetch(repo)
    prs = _list_prs(repo)

    state = _load_state(state_file)
    is_first_run = len(state) == 0

    # Build current PR map
    current: dict[str, dict] = {}
    for pr in prs:
        key = str(pr["number"])
        reviews = pr.get("reviews") or []
        latest_review_id = reviews[-1]["id"] if reviews else None
        current[key] = {
            "branch": pr["headRefName"],
            "last_commit_sha": pr["headRefOid"],
            "last_review_id": latest_review_id,
            "review_loop_count": state.get(key, {}).get("review_loop_count", 0),
        }

    if is_first_run:
        _save_state(state_file, current)
        sys.exit(1)

    # Event detection comes in next task
    _save_state(state_file, current)
    sys.exit(1)


if __name__ == "__main__":
    main()
