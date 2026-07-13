---
title: Split tests/test_system.py into per-concern test files
state: Done
repo: daedalus
type: feature
priority: P3
---

## Summary

`tests/test_system.py` is 932 lines covering seven distinct test classes. As the pipeline grows, a single monolithic test file becomes slow to scan, and failures are harder to triage when unrelated test groups share the same file. Mirroring `src/` structure in `tests/` is standard practice and makes it obvious where to add tests for new code.

## Acceptance Criteria

- `tests/test_system.py` is split into focused files, e.g.:
  - `tests/test_workflows.py` - `TestParsePlan`, `TestParseReview`, `TestTopoSort`, `TestBuildContext`, `TestOrchestratorWorkflow`
  - `tests/test_activities.py` - `TestBuildDockerCmd`, `TestPopulateWorkspace`, `TestAssertGitRoot`, `TestPushAndCreatePR`
  - `tests/test_ticket.py` - already exists; absorb any ticket-related tests from `test_system.py`
- The original `tests/test_system.py` is deleted.
- `tests/conftest.py` retains shared fixtures.
- All existing tests pass; test count is unchanged.
- `pytest tests/ -v` output groups failures by file, making triage faster.

## Plan

- Identify which test classes belong in which file by mapping them to their tested `src/` module.
- Move classes; update imports in each new file.
- Verify no duplicate fixture definitions across files.
- Run `uv run --with pytest --with temporalio python3 -m pytest tests/ -v` to confirm.
