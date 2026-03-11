"""Tests for pr-pilot's git_poll.py script."""

from __future__ import annotations

import json
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
