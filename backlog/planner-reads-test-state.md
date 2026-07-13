---
title: Planner reads test state before planning
state: Done
repo: daedalus
priority: P2
---

## Summary

The planner reads the repo but doesn't know whether tests are currently passing or failing before it produces a task graph. If the repo has a broken baseline, the planner assumes green and produces a plan that may be invalid or mask existing failures. The implementer then inherits broken tests that aren't its fault.

Run a test probe in a read-only container before the planner activity. Pass the result (pass/fail counts, failing test names) to the planner so it can adjust its plan accordingly - e.g. fix existing failures first, or include a note that the baseline is broken.

## Acceptance Criteria

- A new `probe_tests` activity runs `pytest --tb=no -q` (or equivalent) in a read-only Docker container before the planner.
- The probe result (exit code, summary line, list of failing tests) is included in the planner's prompt as a `## Test baseline` section.
- If the probe times out (default 2 min), the planner is still called - the timeout is treated as "baseline unknown".
- The probe container has no write access to the workspace (read-only volume mount).
- `OrchestratorInput` accepts `probe_tests: bool = True` to opt out (e.g. for repos without pytest).
- The `task_completed` event for the planner phase includes `baseline_tests_passed: int` and `baseline_tests_failed: int`.

## Plan

- Add `probe_tests` activity in `activities.py` that builds a docker command with the workspace mounted read-only and runs `pytest --tb=no -q`.
- Parse the pytest output to extract pass/fail counts and failing test names.
- In `OrchestratorWorkflow`, call `probe_tests` before the planner activity when `input.probe_tests` is True.
- Append the probe result to the planner prompt in `build_planner_prompt` (or inline in the workflow).
- Add a 2-minute `start_to_close_timeout` and no retries for the probe activity.
