---
title: Self-repair loop
state: To Do
repo: daedalus
priority: P1
---

## Summary

When the reviewer agent issues a `block` verdict, the orchestrator retries the implementer with the original prompt unchanged. The implementer has no idea why it was blocked and tends to reproduce the same mistake. This leads to exhausting all retry attempts without making progress.

The fix is to pass the reviewer's findings back through a replanning step. The planner should receive both the original goal and the reviewer's block reason, then emit a targeted fix task rather than re-running the full implementation prompt.

## Acceptance Criteria

- After a `block` verdict, the orchestrator invokes a new planner activity whose prompt includes the reviewer's `reason` field.
- The replanner emits a single focused fix task (not a full multi-task plan) that addresses the specific finding(s).
- The implementer receives the fix task prompt with the reviewer findings inline.
- The retry counter is separate from the block counter - a block does not consume an implementation retry.
- If the replanner itself is blocked or produces an invalid plan, the workflow transitions to `hitl_required` rather than looping indefinitely.
- Existing tests for the happy path and HITL path continue to pass.

## Plan

- Add a `replan_after_block` activity (or reuse `run_claude_task` with a new agent type `fixer`) that takes the original goal + reviewer output and returns a targeted fix prompt.
- In `OrchestratorWorkflow.run`, replace the direct retry on `block` with: call replan → run implementer with result → run reviewer → if still blocked after N attempts, signal HITL.
- Update `agents/planner.md` instructions to include a section on targeted fix planning when a reviewer block reason is provided.
- Add a `block_count` field to `WorkflowStatus` alongside `retry_count`.
- Add tests: block → replan → fix path; block → replan → still blocked → HITL path.
