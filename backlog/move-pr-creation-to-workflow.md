---
title: Move PR creation into the Temporal workflow
state: To Do
repo: daedalus
priority: P1
---

## Summary

PR creation (`git push` + `gh pr create`) currently happens in `run_task.py` after the Temporal workflow returns. This means the workflow never has the PR URL and cannot act on it. Per ADR-001, PR creation must move into the workflow as a durable activity so that downstream pipeline phases (e.g. post-PR review loop) can use the URL.

See `docs/ADR-001-pr-creation-in-workflow.md` for the full decision record.

## Acceptance Criteria

- Add activity `push_and_create_pr(repo_path: str, remote_url: str, agent_branch: str, ticket_id: str) -> str` in `src/activities.py`. It runs `git push origin <agent_branch> --force` then creates a PR using the appropriate provider (`gh pr create` for GitHub, `az repos pr create` for ADO) using `PR_DESCRIPTION.md` as the body. Returns the PR URL as a string. Uses the existing provider detection pattern from `src/providers/`.
- `push_and_create_pr` is a no-op (returns `""`) when `remote_url` is empty - local and sandbox runs are unaffected.
- `OrchestratorWorkflow.run` calls `push_and_create_pr` after `pr_author` completes. The returned PR URL is included in the `workflow_completed` event payload as `pr_url` (the Slack notifier already handles this field).
- The push/PR creation block is removed from `run_task.py` (currently lines ~143-163). `run_task.py` prints the PR URL from the workflow result payload instead.
- All existing tests continue to pass. Add a unit test for `push_and_create_pr` that mocks `subprocess.run` and asserts the correct commands are called for GitHub and ADO.

## Plan

- Add `push_and_create_pr` to `src/activities.py` and register it on the worker in `src/worker.py`.
- Update `OrchestratorWorkflow.run` in `src/workflows.py` to call it after pr_author, store the URL in `result_payload`.
- Remove push/PR block from `run_task.py`; print URL from result payload.
- Add tests.
