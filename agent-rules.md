# PR Pilot — Agent Rules

Recommended CLAUDE.md snippets for agents participating in the pipeline.
Copy the relevant section into each agent's CLAUDE.md.

## Main Agent

Add to `~/.klir/CLAUDE.md`:

```markdown
## PR Pilot Orchestration

When the pr-pilot skill activates (via cron or /pr-pilot):
- Follow the skill's event handling rules exactly
- Delegate to executor/reviewer agents via the agent bus — never implement directly
- On escalation, wake the human with the PR URL and reason
- Update SHAREDMEMORY.md with current feature/PR status
```

## Executor Agent

Add to `~/.klir/agents/executor/CLAUDE.md`:

```markdown
## PR Pilot Execution

When delegated work from pr-pilot:
- Work in the worktree path provided in the delegation message
- Use TDD when possible: write failing test, implement, verify, commit
- Use conventional commits: feat(), fix(), test(), refactor()
- When fixing review feedback: parse file:line references from the review body,
  fix the exact issues cited, commit with fix(review): prefix
- Push to the same branch when done — the poller picks up the new commit
- Never escalate directly — the main agent handles escalation based on loop count
```

## Reviewer Agent

Add to `~/.klir/agents/reviewer/CLAUDE.md`:

```markdown
## PR Pilot Review

When delegated a PR review from pr-pilot:
- Run all 6 PR Review Toolkit analyzers on the PR
- Severity classification:
  - Critical: security vulnerabilities, data loss, broken core logic
  - High: missing error handling, untested paths, type safety holes
  - Medium: magic numbers, unclear naming, missing edge cases
  - Low: style suggestions, minor simplifications
- Critical or High issues → request changes with specific file:line references
- Medium or Low only → approve with inline comments
- Clean → approve
- Post review directly via: gh pr review {pr_number} --approve (or --request-changes --body "...")
- Never approve PRs with critical or high severity issues
```
