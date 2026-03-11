"""Tests for pr-pilot's git_poll.py script."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "git_poll.py"

PR_STATE_TEMPLATE = {
    "branch": "feat/foo",
    "last_commit_sha": "abc123",
    "last_review_id": None,
    "review_loop_count": 0,
}


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


def _write_mock_scripts(
    tmp_path: Path, gh_output: str, *, git_exit_code: int = 0, gh_exit_code: int = 0
) -> None:
    """Write mock gh and git scripts into tmp_path."""
    mock_gh = tmp_path / "gh"
    if gh_exit_code != 0:
        mock_gh.write_text(f"#!/bin/sh\necho 'gh error' >&2\nexit {gh_exit_code}\n")
    else:
        mock_gh.write_text(f"#!/bin/sh\necho '{gh_output}'\n")
    mock_gh.chmod(0o755)

    mock_git = tmp_path / "git"
    if git_exit_code != 0:
        mock_git.write_text(f"#!/bin/sh\necho 'git error' >&2\nexit {git_exit_code}\n")
    else:
        mock_git.write_text("#!/bin/sh\nexit 0\n")
    mock_git.chmod(0o755)


def _make_env(tmp_path: Path, state_dir: Path) -> dict[str, str]:
    """Build the environment dict for running the script."""
    return {
        "KLIR_CRON_STATE_DIR": str(state_dir),
        "PATH": f"{tmp_path}:{os.environ.get('PATH', '/usr/bin')}",
        "HOME": str(tmp_path),
    }


def _run_script(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run git_poll.py against the given repo."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(repo)],
        capture_output=True,
        text=True,
        env=env,
    )


def _write_state(state_dir: Path, state: dict) -> None:
    """Write a state.json file into the state directory."""
    (state_dir / "state.json").write_text(json.dumps(state))


def _pr_json(
    number: int = 1,
    branch: str = "feat/foo",
    sha: str = "abc123",
    reviews: list | None = None,
) -> str:
    """Build a single-PR JSON string for the mock gh script."""
    pr = {
        "number": number,
        "headRefName": branch,
        "headRefOid": sha,
        "reviewDecision": "",
        "reviews": reviews or [],
    }
    return json.dumps([pr])


def _multi_pr_json(*prs: dict) -> str:
    """Build a multi-PR JSON string."""
    result = []
    for pr in prs:
        result.append(
            {
                "number": pr.get("number", 1),
                "headRefName": pr.get("branch", "feat/foo"),
                "headRefOid": pr.get("sha", "abc123"),
                "reviewDecision": pr.get("reviewDecision", ""),
                "reviews": pr.get("reviews", []),
            }
        )
    return json.dumps(result)


def _setup_test(
    tmp_path: Path,
    gh_output: str,
    state: dict | None = None,
    *,
    git_exit_code: int = 0,
    gh_exit_code: int = 0,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Common setup: create repo, mocks, optional state, run script, return result."""
    repo = _make_git_repo(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    if state is not None:
        _write_state(state_dir, state)

    _write_mock_scripts(tmp_path, gh_output, git_exit_code=git_exit_code, gh_exit_code=gh_exit_code)
    env = _make_env(tmp_path, state_dir)
    return _run_script(repo, env), state_dir


# --- Argument validation tests ---


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


# --- Command failure tests ---


def test_git_fetch_failure_exits_2(tmp_path: Path) -> None:
    """Exit 2 when git fetch fails."""
    result, _ = _setup_test(tmp_path, gh_output="[]", git_exit_code=1)

    assert result.returncode == 2
    assert "command failed" in result.stderr.lower()


def test_gh_pr_list_failure_exits_2(tmp_path: Path) -> None:
    """Exit 2 when gh pr list fails."""
    result, _ = _setup_test(tmp_path, gh_output="", gh_exit_code=1)

    assert result.returncode == 2
    assert "command failed" in result.stderr.lower()


# --- First run / baseline tests ---


def test_first_run_creates_baseline_state(tmp_path: Path) -> None:
    """First run creates state.json with current PRs, emits no events."""
    result, state_dir = _setup_test(tmp_path, gh_output=_pr_json())

    assert result.returncode == 1
    state = json.loads((state_dir / "state.json").read_text())
    assert "1" in state
    assert state["1"]["last_commit_sha"] == "abc123"


# --- Event detection tests ---


def test_detects_new_commits(tmp_path: Path) -> None:
    """Detects new commits on a tracked PR."""
    result, _ = _setup_test(
        tmp_path,
        gh_output=_pr_json(sha="new_sha"),
        state={"1": {**PR_STATE_TEMPLATE, "last_commit_sha": "old_sha"}},
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert len(output["events"]) == 1
    evt = output["events"][0]
    assert evt["type"] == "new_commits"
    assert evt["pr"] == 1
    assert evt["old_sha"] == "old_sha"
    assert evt["new_sha"] == "new_sha"


def test_detects_new_pr_between_polls(tmp_path: Path) -> None:
    """New PR appearing between polls emits new_commits with old_sha=null."""
    gh_output = _multi_pr_json(
        {"number": 1, "sha": "abc123"},
        {"number": 2, "branch": "feat/bar", "sha": "new_pr_sha"},
    )
    result, _ = _setup_test(
        tmp_path,
        gh_output=gh_output,
        state={"1": PR_STATE_TEMPLATE},
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    new_pr_events = [e for e in output["events"] if e["pr"] == 2]
    assert len(new_pr_events) == 1
    evt = new_pr_events[0]
    assert evt["type"] == "new_commits"
    assert evt["old_sha"] is None
    assert evt["new_sha"] == "new_pr_sha"


def test_detects_changes_requested(tmp_path: Path) -> None:
    """Detects a new changes_requested review."""
    reviews = [
        {
            "id": "rev_1",
            "state": "CHANGES_REQUESTED",
            "author": {"login": "reviewer-bot"},
            "body": "Fix auth.py:34",
        }
    ]
    result, _ = _setup_test(
        tmp_path,
        gh_output=_pr_json(reviews=reviews),
        state={"1": PR_STATE_TEMPLATE},
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    evt = output["events"][0]
    assert evt["type"] == "changes_requested"
    assert evt["review_id"] == "rev_1"
    assert evt["loop_count"] == 1


def test_approved_review_does_not_emit_event(tmp_path: Path) -> None:
    """APPROVED review does NOT emit a changes_requested event."""
    reviews = [
        {
            "id": "rev_1",
            "state": "APPROVED",
            "author": {"login": "reviewer-bot"},
            "body": "LGTM",
        }
    ]
    result, _ = _setup_test(
        tmp_path,
        gh_output=_pr_json(reviews=reviews),
        state={"1": PR_STATE_TEMPLATE},
    )

    assert result.returncode == 1
    assert result.stdout.strip() == ""


def test_review_loop_counter_increments(tmp_path: Path) -> None:
    """Review loop counter increments across successive polls."""
    reviews = [
        {
            "id": "rev_3",
            "state": "CHANGES_REQUESTED",
            "author": {"login": "reviewer-bot"},
            "body": "Still broken",
        }
    ]
    result, state_dir = _setup_test(
        tmp_path,
        gh_output=_pr_json(reviews=reviews),
        state={
            "1": {
                **PR_STATE_TEMPLATE,
                "last_review_id": "rev_2",
                "review_loop_count": 2,
            }
        },
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    evt = [e for e in output["events"] if e["type"] == "changes_requested"][0]
    assert evt["loop_count"] == 3

    # Verify saved state also has incremented counter
    saved = json.loads((state_dir / "state.json").read_text())
    assert saved["1"]["review_loop_count"] == 3


def test_detects_pr_closed(tmp_path: Path) -> None:
    """Detects a PR that was previously tracked but is no longer open."""
    result, _ = _setup_test(
        tmp_path,
        gh_output="[]",
        state={"1": PR_STATE_TEMPLATE},
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    evt = output["events"][0]
    assert evt["type"] == "pr_closed"
    assert evt["pr"] == 1
    assert evt["branch"] == "feat/foo"
    assert "merged" not in evt


# --- Edge case tests ---


def test_no_changes_exits_1(tmp_path: Path) -> None:
    """Exit 1 when nothing has changed since last poll."""
    result, _ = _setup_test(
        tmp_path,
        gh_output=_pr_json(),
        state={"1": PR_STATE_TEMPLATE},
    )

    assert result.returncode == 1
    assert result.stdout.strip() == ""


def test_multiple_events(tmp_path: Path) -> None:
    """Multiple events across PRs are all reported."""
    state = {
        "1": {**PR_STATE_TEMPLATE, "last_commit_sha": "old_sha"},
        "2": {**PR_STATE_TEMPLATE, "branch": "feat/bar", "last_commit_sha": "bar_sha"},
    }
    result, _ = _setup_test(
        tmp_path,
        gh_output=_pr_json(sha="new_sha"),
        state=state,
    )

    assert result.returncode == 0
    output = json.loads(result.stdout)
    types = {e["type"] for e in output["events"]}
    assert "new_commits" in types
    assert "pr_closed" in types
    assert len(output["events"]) == 2


def test_empty_state_after_all_prs_closed_is_not_first_run(tmp_path: Path) -> None:
    """After all PRs close, empty state file is NOT treated as first run."""
    repo = _make_git_repo(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    # Write empty state (all PRs previously closed)
    _write_state(state_dir, {})

    # New PR appears
    _write_mock_scripts(tmp_path, _pr_json(number=5, sha="brand_new"))
    env = _make_env(tmp_path, state_dir)
    result = _run_script(repo, env)

    # Should emit new_commits event, NOT silently baseline
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert len(output["events"]) == 1
    evt = output["events"][0]
    assert evt["type"] == "new_commits"
    assert evt["pr"] == 5
    assert evt["old_sha"] is None


def test_corrupt_state_file_exits_2(tmp_path: Path) -> None:
    """Exit 2 when state.json contains invalid JSON."""
    repo = _make_git_repo(tmp_path)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "state.json").write_text("{broken json")

    _write_mock_scripts(tmp_path, _pr_json())
    env = _make_env(tmp_path, state_dir)
    result = _run_script(repo, env)

    assert result.returncode == 2
    assert "corrupted state file" in result.stderr.lower()
