---
title: Consolidate run_*.py scripts into a src/cli package
state: To Do
repo: daedalus
type: feature
priority: P3
---

## Summary

Three entry-point scripts (`run_task.py`, `run_ticket.py`, `run_pr_review.py`) live at the repo root alongside `Makefile`, `docker-compose.yml`, and documentation. As a `src/`-layout project, CLI logic belongs inside the package. Consolidating them into `src/cli/` keeps the root clean and makes the entry points installable via `pyproject.toml` console scripts.

## Acceptance Criteria

- `run_task.py`, `run_ticket.py`, and `run_pr_review.py` are moved to `src/cli/task.py`, `src/cli/ticket.py`, and `src/cli/pr_review.py`.
- `pyproject.toml` defines `[project.scripts]` console script entry points:
  - `daedalus-run = "src.cli.task:main"`
  - `daedalus-ticket = "src.cli.ticket:main"`
  - `daedalus-review = "src.cli.pr_review:main"`
- `Makefile` targets (`run`, `run-ticket`, `review`) updated to invoke the new entry points via `uv run`.
- The old root-level scripts are deleted.
- All existing `make` targets continue to work.
- `CLAUDE.md` and `README.md` updated to reference the new paths.

## Plan

- Create `src/cli/__init__.py` and move each script, wrapping the top-level code in a `main()` function if not already done.
- Add `[project.scripts]` to `pyproject.toml`.
- Update `Makefile` targets.
- Update docs references.
- Run existing tests to confirm no regressions (tests import from `src.*`, not from root scripts, so impact is minimal).
