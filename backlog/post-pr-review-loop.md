---
title: Post-PR review loop
state: To Do
repo: daedalus
priority: P1
---

## Summary

After `pr_author` raises a PR, nothing reviews it automatically. The `pr_reviewer` agent exists as a standalone tool but is never called on agent-raised PRs. High-confidence findings require a human to read the report and manually request fixes.

This ticket adds an automated round-trip: run `pr_reviewer` on the newly raised PR, feed high-confidence findings back to the implementer as a fix task, push the fix commit to the open PR branch, and complete.

**Prerequisite:** `move-pr-creation-to-workflow` must be merged first. This ticket assumes `push_and_create_pr` activity exists and that `OrchestratorWorkflow` has the PR URL after `pr_author` completes.

## Acceptance Criteria

- Add `post_review: bool = True` to `OrchestratorInput` in `src/models.py`.
- After `push_and_create_pr` returns a URL, if `post_review` is True, extract the PR number from the URL and run `PRReviewWorkflow` as a child workflow (it already exists in `src/workflows.py`).
- Parse the `PRReviewWorkflow` markdown output for findings with confidence ≥ 80. The report includes a table with a `Confidence` column - extract rows where the value is ≥ 80.
- If high-confidence findings exist: run one `implementer` task via `run_claude_task` with the findings as the fix prompt, `repo_path=input.repo_path`, and `base_commit=self._current_sha`. After the implementer commits, push the fix commit to the same open PR branch by calling `push_and_create_pr` (or a simpler `git push` activity if no new PR should be created).
- If no high-confidence findings: skip the fix step and complete normally.
- The loop runs at most once - do not re-review after the fix.
- `workflow_completed` event includes `post_review_fix: true | false`.
- Add `--no-post-review` flag to `run_task.py` (sets `post_review=False`).
- Add tests: (a) findings present → fix task runs; (b) no findings → fix task skipped; (c) `post_review=False` → reviewer not called.

## Plan

- Add `post_review` to `OrchestratorInput` in `src/models.py`.
- In `OrchestratorWorkflow.run`, after `push_and_create_pr`, add the conditional review loop.
- Add confidence parsing helper for the pr_reviewer markdown report.
- Add `--no-post-review` to `run_task.py`.
- Add tests.
