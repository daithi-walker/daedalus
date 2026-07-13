---
title: Split src/activities.py into focused submodules
state: To Do
repo: daedalus
type: feature
priority: P3
---

## Summary

`src/activities.py` is 517 lines and growing. It currently mixes four distinct concerns: Docker/Claude execution, git worktree management, PR push-and-create, and Slack/webhook event publishing. As new activities are added (e.g. orphaned container cleanup, uv test runner), this file will become hard to navigate and test in isolation.

## Acceptance Criteria

- `src/activities.py` is split into a `src/activities/` package with focused submodules, e.g.:
  - `run.py` - `run_claude_task`, `_run_with_git`, `_run_ephemeral`, `_run_with_heartbeat`
  - `git.py` - `_git_commit`, `_git`, `_assert_git_root`, worktree helpers
  - `pr.py` - `push_and_create_pr`
  - `events.py` - `publish_event`, Slack/webhook helpers
  - `__init__.py` - re-exports all `@activity.defn` functions so existing imports (`from .activities import run_claude_task, push_and_create_pr, publish_event`) continue to work unchanged
- `src/worker.py` and `src/workflows.py` require no import changes.
- All existing tests continue to pass.

## Plan

- Create `src/activities/` directory with `__init__.py` that re-exports the public activity functions.
- Move each group of functions into its submodule; update internal imports within the package.
- Delete the old `src/activities.py`.
- Run `uv run --with pytest --with temporalio python3 -m pytest tests/ -v` to confirm no regressions.
