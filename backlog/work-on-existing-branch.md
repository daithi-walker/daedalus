---
title: Work on an existing branch
state: To Do
repo: daedalus
priority: P1
---

## Summary

Daedalus is greenfield-only. It always creates a new agent branch from HEAD (or a specified base commit). It cannot pick up a PR that's already in flight, apply reviewer feedback to a branch it didn't create, or resume work after a partial run. This prevents using Daedalus to fix review feedback on human-authored PRs or to continue a failed agent run.

## Acceptance Criteria

- `OrchestratorInput` accepts an optional `base_branch` field.
- When `base_branch` is set, the agent worktree is created from that branch rather than HEAD.
- Agent commits are pushed back to `base_branch` rather than creating a new branch.
- `run_task.py` accepts a `--base-branch` CLI flag.
- `run_ticket.py` passes `base_branch` through from `repos.yaml` or the `--base-branch` CLI flag.
- `_assert_git_root` still runs correctly when a base branch is provided.
- Existing default behaviour (no `base_branch` → create new branch from HEAD) is unchanged.

## Plan

- Add `base_branch: str = ""` to `OrchestratorInput` and `TaskInput`.
- In `_run_with_git`, when `input.base_commit` is empty and `base_branch` is set, use it as the worktree base ref.
- After the agent commits, push the worktree branch back to the remote's `base_branch` ref instead of raising a PR from a new branch.
- Update `run_task.py` to accept `--base-branch` and pass it through.
- Add a `make continue` Makefile target: `make continue GOAL="..." BASE_BRANCH=agent/some-pr`.
