"""Tests for pr-pilot's git_poll.py script."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "git_poll.py"


def test_missing_repo_arg(tmp_path: Path) -> None:
    """Exit 2 when no repo path argument is provided."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        env={"KLIR_CRON_STATE_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 2
    assert "usage" in result.stderr.lower() or "repo" in result.stderr.lower()


def test_nonexistent_repo(tmp_path: Path) -> None:
    """Exit 2 when repo path does not exist."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "/nonexistent/repo"],
        capture_output=True,
        text=True,
        env={"KLIR_CRON_STATE_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 2
    assert "not found" in result.stderr.lower() or "does not exist" in result.stderr.lower()


def test_missing_state_dir_env(tmp_path: Path) -> None:
    """Exit 2 when KLIR_CRON_STATE_DIR is not set."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 2
    assert "KLIR_CRON_STATE_DIR" in result.stderr


def _make_git_repo(tmp_path: Path) -> Path:
    """Create a git repo with a remote origin for testing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin",
         "https://github.com/test/test.git"],
        check=True, capture_output=True,
    )
    return repo


def test_first_run_creates_baseline_state(tmp_path: Path) -> None:
    """First run creates state.json with current PRs, emits no events."""
    repo = _make_git_repo(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    # Mock gh to return one open PR
    mock_gh = tmp_path / "gh"
    mock_gh.write_text(
        '#!/bin/sh\n'
        'if [ "$1" = "pr" ] && [ "$2" = "list" ]; then\n'
        '  echo \'[{"number":1,"headRefName":"feat/foo","headRefOid":"abc123",'
        '"reviewDecision":"","reviews":[]}]\'\n'
        'fi\n'
    )
    mock_gh.chmod(0o755)

    # Mock git fetch to no-op
    mock_git = tmp_path / "git"
    mock_git.write_text("#!/bin/sh\nexit 0\n")
    mock_git.chmod(0o755)

    env = {
        "KLIR_CRON_STATE_DIR": str(state_dir),
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '/usr/bin')}",
        "HOME": str(tmp_path),
    }

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(repo)],
        capture_output=True, text=True, env=env,
    )

    assert result.returncode == 1
    state_file = state_dir / "state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert "1" in state
    assert state["1"]["last_commit_sha"] == "abc123"
