---
title: Fix PR title using agent stdout instead of PR_DESCRIPTION.md
state: Done
repo: daedalus
type: bug
priority: P2
---

## Summary

Every PR raised by Daedalus gets a garbage title - the first line of the `pr_author` agent's stdout is used as the PR title instead of the actual PR title from `PR_DESCRIPTION.md`. The `pr_author` agent correctly writes `PR_DESCRIPTION.md` into the workspace, but `push_and_create_pr` in `activities.py` extracts the title from `pr_body` (which is the raw activity output string), not from the file. The result is titles like "`PR_DESCRIPTION.md` written to `/workspace/PR_DESCRIPTION.md`..." that require manual correction after every run.

## Acceptance Criteria

- PR titles on ADO and GitHub must be the first `#`-heading line from `PR_DESCRIPTION.md`, not the agent's stdout
- If `PR_DESCRIPTION.md` is absent or has no heading, fall back to the ticket ID
- The `pr_body` passed to `create_pr` / `ensure_pr` must be the full content of `PR_DESCRIPTION.md`, not the agent stdout
- Existing tests pass; new test covers title extraction from a `PR_DESCRIPTION.md`-style string

## Plan

- In `OrchestratorWorkflow`, the `pr_author` task result (`pr_result.output`) is currently passed directly to `push_and_create_pr` as `pr_body`. Instead, read `PR_DESCRIPTION.md` from `input.repo_path` after the pr_author task completes and pass that content as `pr_body`.
- Alternatively, have the `pr_author` agent print the PR title to stdout (structured) and write the body to the file - but reading the file is simpler and more reliable.
- The title extraction in `push_and_create_pr` (`first_line = pr_body.lstrip().splitlines()[0].lstrip("# ")`) will then work correctly since `PR_DESCRIPTION.md` starts with a `#` heading.
- Consider: `PR_DESCRIPTION.md` is written into the worktree and committed by `_git_commit` exclusions - check it is NOT excluded so it survives to be read. If it is excluded, read it before the commit step.
