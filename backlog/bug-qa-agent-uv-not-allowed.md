---
title: QA agent cannot run uv - tests always unverified
state: Done
repo: daedalus
type: bug
priority: P1
---

## Summary

Every PR raised by Daedalus includes a "QA agent could not run the test suite" note. The QA agent's allowed Bash commands do not include `uv`, so `uv run --with pytest ...` is blocked by Claude Code's permission system. Tests are never executed during the pipeline - the QA agent can only write tests, not verify them.

This is a silent quality gap: PRs are raised with unverified test results on every run.

## Acceptance Criteria

- The QA agent can run `uv run --with pytest --with temporalio python3 -m pytest tests/ -v` without hitting a permission denial.
- `_ALLOWED_TOOLS` for `AgentType.qa` in `src/activities.py` is updated to include `uv` in the Bash allowlist (or the full command is permitted).
- `agents/qa.md` documents the exact test command the agent should run.
- After the fix, PR descriptions include actual test results (pass/fail count) rather than "QA could not run the suite."

## Plan

- In `src/activities.py`, update `_ALLOWED_TOOLS[AgentType.qa]` to include `uv` alongside `pytest`, `flask`, `pip`, `curl`.
- In `agents/qa.md`, add an explicit instruction: "Run the full test suite with `uv run --with pytest --with temporalio python3 -m pytest tests/ -v` and report results."
- Verify the Docker image has `uv` installed (`daedalus-qa:latest` uses a different Dockerfile - check `Dockerfile.qa`).
