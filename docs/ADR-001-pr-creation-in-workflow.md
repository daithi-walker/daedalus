# ADR-001: Move PR creation into the Temporal workflow

**Status:** Accepted  
**Author:** David Walker  
**Date:** 2026-05-20  

---

## Context

PR creation currently happens in `run_task.py` - the CLI wrapper - after the Temporal workflow returns:

```
Temporal workflow ends
  → run_task.py pushes branch (git push)
  → run_task.py calls gh pr create
  → PR URL printed to stdout
```

The workflow itself never sees the PR URL. This boundary prevents any post-PR behaviour from being implemented inside the workflow - specifically, running the `pr_reviewer` agent on the resulting PR and feeding findings back to the implementer before declaring done.

## Options considered

**Option A - Keep PR creation in `run_task.py`, pass URL back via Signal**  
After `run_task.py` creates the PR, send the URL to the still-running workflow via a Temporal Signal. The workflow pauses to wait for the signal before proceeding to the review loop.

*Problem:* The workflow currently completes before `run_task.py` creates the PR. Keeping the workflow alive to wait for an external signal adds coordination complexity and a new failure mode (workflow hangs if the signal never arrives).

**Option B - Trigger a second workflow after PR creation**  
`run_task.py` creates the PR as today, then submits a separate `PRReviewWorkflow` with the URL. `PRReviewWorkflow` already exists.

*Problem:* The fix commits from the review loop need to land on the open PR branch. A second workflow would need to know the branch name, push credentials, and the original repo path - all state that already lives in the first workflow. Passing it all across a workflow boundary is fragile and makes the audit trail harder to follow.

**Option C - Move PR creation into the workflow (chosen)**  
Add a `push_and_create_pr` Temporal activity that runs `git push` and `gh pr create`, returns the PR URL as a string. The orchestrator calls this activity after `pr_author` completes. `run_task.py` is simplified - it submits the workflow, streams the result, and prints the PR URL from the result payload.

## Decision

**Option C.** PR creation is logically part of the pipeline - it is the terminal action that publishes the agent's work. It belongs inside the durable workflow for the same reasons the other phases do: retryability, auditability, and access to workflow state (repo path, branch name, ticket ID).

## Consequences

- `push_and_create_pr` becomes a new activity in `src/activities.py`. It is skipped when `remote_url` is empty (local/sandbox runs).
- `OrchestratorWorkflow` gains the PR URL as an intermediate value, enabling the post-PR review loop (see backlog: `post-pr-review-loop`).
- `run_task.py` is simplified - the push/PR creation block (~20 lines) is removed.
- The `workflow_completed` event payload gains a `pr_url` field, which the Slack notifier already handles (`activities.py:470`).
- ADO support: `push_and_create_pr` must handle both GitHub (`gh pr create`) and ADO (`az repos pr create`) using the existing provider detection pattern in `src/providers/`.

## Related

- Backlog: `move-pr-creation-to-workflow` (implements this decision)
- Backlog: `post-pr-review-loop` (depends on this decision)
- `src/providers/` - existing GitHub/ADO provider abstraction
- `run_task.py:143-163` - code to be removed
