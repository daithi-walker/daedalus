---
title: Push commits to remote before creating PR
state: To Do
repo: daedalus
type: bug
priority: P2
---

## Summary

`push_and_create_pr` creates the PR before the branch commits are confirmed on the remote. In `run_task.py`, `_clone_repo` checks out the base branch and creates the agent branch at that point - so the remote sees the branch at the base branch tip before any agent commits exist. When `push_and_create_pr` later pushes, there is a window where the PR exists but points to an empty branch. In practice the push succeeds, but it is ordering-fragile and causes confusion when reviewing a PR immediately after creation.

## Acceptance Criteria

- The git push must complete successfully before `create_pr` / `ensure_pr` is called
- If the push fails, the activity must raise (not silently create an empty PR)
- A PR must never be created pointing to a branch at the base branch tip
- Existing tests pass

## Plan

- In `push_and_create_pr`, the push already runs before `ensure_pr` - verify `check=True` is set and that push failure propagates as an exception rather than being swallowed.
- Check whether the branch is being pre-created (e.g. `git push origin agent_branch` during clone in `run_task.py`) and if so remove that step - the branch should only exist on remote after the commits are pushed.
- Add a post-push check: `git ls-remote origin <branch>` must return the expected commit SHA before proceeding to PR creation.
