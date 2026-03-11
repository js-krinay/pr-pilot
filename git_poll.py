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
import tempfile
from pathlib import Path
from typing import NoReturn


def _fatal(msg: str) -> NoReturn:
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
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=120)
    except subprocess.TimeoutExpired:
        _fatal(f"command timed out after 120s: {' '.join(cmd)}")
    if result.returncode != 0:
        _fatal(f"command failed: {' '.join(cmd)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def _git_fetch(repo: Path) -> None:
    _run_cmd(["git", "fetch", "origin"], cwd=repo)


def _list_prs(repo: Path) -> list[dict]:
    raw = _run_cmd(
        [
            "gh",
            "pr",
            "list",
            "--json",
            "number,headRefName,headRefOid,reviewDecision,reviews",
            "--limit",
            "100",
        ],
        cwd=repo,
    )
    if not raw:
        return []
    try:
        prs = json.loads(raw)
    except json.JSONDecodeError as e:
        _fatal(f"failed to parse PR list JSON from gh: {e}\nraw output: {raw[:500]}")
    if not isinstance(prs, list):
        _fatal(f"expected JSON array from gh pr list, got {type(prs).__name__}")
    return prs


def _load_state(state_file: Path) -> dict | None:
    """Load state from file. Returns None if file does not exist (first run)."""
    if not state_file.exists():
        return None
    try:
        text = state_file.read_text()
    except OSError as e:
        _fatal(f"failed to read state file {state_file}: {e}")
    if not text.strip():
        return None
    try:
        state = json.loads(text)
    except json.JSONDecodeError as e:
        _fatal(f"corrupted state file {state_file}: {e}")
    if not isinstance(state, dict):
        _fatal(f"state file {state_file} contains {type(state).__name__}, expected object")
    return state


def _save_state(state_file: Path, state: dict) -> None:
    """Atomically write state to file via tmp + os.replace."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(state, indent=2)
    try:
        fd, tmp = tempfile.mkstemp(dir=state_file.parent, suffix=".tmp")
        try:
            os.write(fd, data.encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, state_file)
    except OSError as e:
        _fatal(f"failed to write state file {state_file}: {e}")


def main() -> None:
    repo = _parse_args()
    state_dir = _get_state_dir()
    state_file = state_dir / "state.json"

    _git_fetch(repo)
    prs = _list_prs(repo)

    state = _load_state(state_file)
    is_first_run = state is None
    if is_first_run:
        state = {}

    # Build current PR map, skipping malformed entries
    current: dict[str, dict] = {}
    for pr in prs:
        try:
            number = pr["number"]
            head_ref = pr["headRefName"]
            head_oid = pr["headRefOid"]
        except KeyError as e:
            print(f"warning: skipping PR with missing field {e}", file=sys.stderr)
            continue
        key = str(number)
        reviews = pr.get("reviews") or []
        latest_review_id = reviews[-1].get("id") if reviews else None
        current[key] = {
            "branch": head_ref,
            "last_commit_sha": head_oid,
            "last_review_id": latest_review_id,
            "review_loop_count": state.get(key, {}).get("review_loop_count", 0),
        }

    if is_first_run:
        _save_state(state_file, current)
        sys.exit(1)

    events: list[dict] = []

    # Index PRs by number for O(1) lookup
    pr_by_key: dict[str, dict] = {str(p["number"]): p for p in prs if "number" in p}

    for key, cur in current.items():
        prev = state.get(key)
        old_sha = prev.get("last_commit_sha") if prev else None

        if cur["last_commit_sha"] != old_sha:
            events.append(
                {
                    "type": "new_commits",
                    "pr": int(key),
                    "branch": cur["branch"],
                    "old_sha": old_sha,
                    "new_sha": cur["last_commit_sha"],
                }
            )

        if prev is None:
            continue

        has_new_review = cur["last_review_id"] is not None and cur["last_review_id"] != prev.get(
            "last_review_id"
        )
        if not has_new_review:
            continue

        latest_review = (pr_by_key[key].get("reviews") or [{}])[-1]
        if latest_review.get("state") != "CHANGES_REQUESTED":
            continue

        loop_count = prev.get("review_loop_count", 0) + 1
        cur["review_loop_count"] = loop_count
        author = latest_review.get("author")
        reviewer = author.get("login", "unknown") if isinstance(author, dict) else "unknown"
        events.append(
            {
                "type": "changes_requested",
                "pr": int(key),
                "branch": cur["branch"],
                "review_id": cur["last_review_id"],
                "reviewer": reviewer,
                "body": latest_review.get("body", ""),
                "loop_count": loop_count,
            }
        )

    for key, prev in state.items():
        if key not in current:
            events.append(
                {
                    "type": "pr_closed",
                    "pr": int(key),
                    "branch": prev["branch"],
                }
            )

    if not events:
        _save_state(state_file, current)
        sys.exit(1)

    # Print events BEFORE saving state — if output fails, state stays unchanged
    # so events are re-detected on next run
    output = json.dumps({"repo": str(repo), "events": events}, indent=2)
    try:
        print(output)
        sys.stdout.flush()
    except OSError as e:
        _fatal(f"failed to write events to stdout: {e}")

    _save_state(state_file, current)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"unexpected error: {e}", file=sys.stderr)
        sys.exit(2)
