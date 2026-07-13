---
title: Pass PR body via file reference instead of Temporal payload string
state: To Do
repo: daedalus
type: feature
priority: P2
---

## Summary

The pr_author agent currently returns its full PR description as a string in `TaskResult.output`, which is then passed through Temporal's event history and as a `push_and_create_pr` activity argument. Large PR descriptions cause asyncio stream buffer overflows and bloat the workflow history. The fix is to have pr_author write its output to a known file path and return only the path; `push_and_create_pr` reads the file directly.

## Acceptance Criteria

- `pr_author` writes the PR description to a file in the repo (e.g. `PR_DESCRIPTION.md`) and returns only a short confirmation string, not the full body.
- `push_and_create_pr` reads the PR body from the file path in the repo rather than from an argument.
- Temporal event history no longer contains the full PR description text.
- The `pr_body` parameter is removed from `push_and_create_pr`'s signature (or replaced with a file path).
- Existing tests updated to reflect the new interface; all tests pass.

## Plan

- In `OrchestratorWorkflow.run`, stop passing `pr_result.output` to `push_and_create_pr`; pass `input.repo_path` instead (already available).
- In `push_and_create_pr`, read `Path(repo_path) / "PR_DESCRIPTION.md"` for the body.
- Update `_git_commit` exclusions to ensure `PR_DESCRIPTION.md` is still excluded from commits (already the case).
- Update `agents/pr_author.md` instructions to confirm the agent should write to `PR_DESCRIPTION.md` (it likely already does).
