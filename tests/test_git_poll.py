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
        ["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/test/test.git"],
        check=True,
        capture_output=True,
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
        "#!/bin/sh\n"
        'if [ "$1" = "pr" ] && [ "$2" = "list" ]; then\n'
        '  echo \'[{"number":1,"headRefName":"feat/foo","headRefOid":"abc123",'
        '"reviewDecision":"","reviews":[]}]\'\n'
        "fi\n"
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
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    state_file = state_dir / "state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert "1" in state
    assert state["1"]["last_commit_sha"] == "abc123"


def test_detects_new_commits(tmp_path: Path) -> None:
    """Detects new commits on a tracked PR."""
    repo = _make_git_repo(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "1": {
                    "branch": "feat/foo",
                    "last_commit_sha": "old_sha",
                    "last_review_id": None,
                    "review_loop_count": 0,
                }
            }
        )
    )

    mock_gh = tmp_path / "gh"
    mock_gh.write_text(
        "#!/bin/sh\n"
        'echo \'[{"number":1,"headRefName":"feat/foo","headRefOid":"new_sha",'
        '"reviewDecision":"","reviews":[]}]\'\n'
    )
    mock_gh.chmod(0o755)
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
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert len(output["events"]) == 1
    evt = output["events"][0]
    assert evt["type"] == "new_commits"
    assert evt["pr"] == 1
    assert evt["old_sha"] == "old_sha"
    assert evt["new_sha"] == "new_sha"


def test_detects_changes_requested(tmp_path: Path) -> None:
    """Detects a new changes_requested review."""
    repo = _make_git_repo(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "1": {
                    "branch": "feat/foo",
                    "last_commit_sha": "abc123",
                    "last_review_id": None,
                    "review_loop_count": 0,
                }
            }
        )
    )

    mock_gh = tmp_path / "gh"
    mock_gh.write_text(
        "#!/bin/sh\n"
        'echo \'[{"number":1,"headRefName":"feat/foo","headRefOid":"abc123",'
        '"reviewDecision":"CHANGES_REQUESTED",'
        '"reviews":[{"id":"rev_1","state":"CHANGES_REQUESTED",'
        '"author":{"login":"reviewer-bot"},"body":"Fix auth.py:34"}]}]\'\n'
    )
    mock_gh.chmod(0o755)
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
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    evt = output["events"][0]
    assert evt["type"] == "changes_requested"
    assert evt["review_id"] == "rev_1"
    assert evt["loop_count"] == 1


def test_detects_pr_closed(tmp_path: Path) -> None:
    """Detects a PR that was previously tracked but is no longer open."""
    repo = _make_git_repo(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "1": {
                    "branch": "feat/foo",
                    "last_commit_sha": "abc123",
                    "last_review_id": None,
                    "review_loop_count": 0,
                }
            }
        )
    )

    mock_gh = tmp_path / "gh"
    mock_gh.write_text('#!/bin/sh\necho "[]"\n')
    mock_gh.chmod(0o755)
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
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    evt = output["events"][0]
    assert evt["type"] == "pr_closed"
    assert evt["pr"] == 1


def test_no_changes_exits_1(tmp_path: Path) -> None:
    """Exit 1 when nothing has changed since last poll."""
    repo = _make_git_repo(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "1": {
                    "branch": "feat/foo",
                    "last_commit_sha": "abc123",
                    "last_review_id": None,
                    "review_loop_count": 0,
                }
            }
        )
    )

    mock_gh = tmp_path / "gh"
    mock_gh.write_text(
        "#!/bin/sh\n"
        'echo \'[{"number":1,"headRefName":"feat/foo","headRefOid":"abc123",'
        '"reviewDecision":"","reviews":[]}]\'\n'
    )
    mock_gh.chmod(0o755)
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
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 1
    assert result.stdout.strip() == ""


def test_multiple_events(tmp_path: Path) -> None:
    """Multiple events across PRs are all reported."""
    repo = _make_git_repo(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    (state_dir / "state.json").write_text(
        json.dumps(
            {
                "1": {
                    "branch": "feat/foo",
                    "last_commit_sha": "old_sha",
                    "last_review_id": None,
                    "review_loop_count": 0,
                },
                "2": {
                    "branch": "feat/bar",
                    "last_commit_sha": "bar_sha",
                    "last_review_id": None,
                    "review_loop_count": 0,
                },
            }
        )
    )

    # PR 1 has new SHA, PR 2 is gone
    mock_gh = tmp_path / "gh"
    mock_gh.write_text(
        "#!/bin/sh\n"
        'echo \'[{"number":1,"headRefName":"feat/foo","headRefOid":"new_sha",'
        '"reviewDecision":"","reviews":[]}]\'\n'
    )
    mock_gh.chmod(0o755)
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
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    types = {e["type"] for e in output["events"]}
    assert "new_commits" in types
    assert "pr_closed" in types
    assert len(output["events"]) == 2
