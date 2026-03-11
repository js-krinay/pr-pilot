---
name: pr-pilot
description: >
  Polls GitHub PRs for new commits and review status, then routes work
  to executor and reviewer agents. Activates on cron ticks that detect
  git changes. Use /pr-pilot to manually check status or trigger a
  review cycle.
argument-hint: "[status|check <repo-path>]"
allowed-tools: Bash(git *), Bash(gh *), Bash(python *)
---

# PR Pilot

Orchestrates PR lifecycle across executor and reviewer agents.
The cron system triggers `git_poll.py` periodically. This skill
tells you what to do with the results.

## Running the Poller

```bash
python ${CLAUDE_SKILL_DIR}/git_poll.py <repo-path>
```

Requires `KLIR_CRON_STATE_DIR` env var (set automatically by klir cron).
Outputs JSON with detected events. Exit 0 = events found, 1 = nothing new.

## Handling Events

Parse the JSON output. For each event:

### `new_commits`

A tracked PR has new commits pushed.

1. Create a worktree: `git worktree add /tmp/pr-pilot-{pr} origin/{branch}`
2. Delegate to the **reviewer** agent via agent bus:
   "Review PR #{pr} in {repo}. Branch: {branch}.
   Run all 6 PR Review Toolkit analyzers.
   If critical/high issues, request changes on the PR with file:line references.
   If clean or low-severity only, approve."
3. The reviewer posts its review directly on the GitHub PR.

### `changes_requested`

A reviewer has requested changes on a PR.

1. Check `loop_count` against the max review loops (from cron prompt, default 3).
2. If under max: delegate to the **executor** agent via agent bus:
   "PR #{pr} has review feedback. Branch: {branch}.
   Worktree: /tmp/pr-pilot-{pr}.
   Fix these issues: {body}
   Commit with prefix fix(review):, then push to the same branch."
3. If at or over max: send a **wake message** to the human:
   "⚠️ PR #{pr} needs attention. Exceeded {loop_count} review fix loops. {pr_url}"

### `pr_closed`

A previously tracked PR was merged or closed.

1. Clean up worktree if it exists: `git worktree remove /tmp/pr-pilot-{pr} --force`
2. If merged, optionally notify: "✅ PR #{pr} ({branch}) merged."

## Manual Usage

### `/pr-pilot status`

Read state files from `$KLIR_CRON_STATE_DIR/*/state.json` and report
which PRs are being tracked, their current SHA, review loop count, and
last poll time.

### `/pr-pilot check <repo-path>`

Run `git_poll.py` for a specific repo immediately (outside cron schedule)
and handle any events found.

## Cron Setup

To watch a repo, add a cron job to `~/.klir/cron_jobs.json`:

```json
{
  "id": "pr-pilot-myproject",
  "schedule": "*/30 * * * * *",
  "task_folder": "/path/to/project",
  "agent_instruction": "Run python ${CLAUDE_SKILL_DIR}/git_poll.py /path/to/project. If events found, handle per the pr-pilot skill. Max 3 review fix loops before escalating to human.",
  "enabled": true
}
```

Adjust `schedule` for polling frequency. Adjust the max loop count in
the prompt per project.

## What This Skill Does NOT Do

- No CI execution — your git hooks (lefthook/pre-commit/husky) handle that
- No commit hook management — Claude Code handles that natively
- No direct agent-to-agent routing — the poller is the single source of truth
