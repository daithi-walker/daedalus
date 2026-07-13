# Changelog

All notable changes to Daedalus will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.3.0] - 2026-05-21

### Added
- `probe_tests` activity in `src/activities.py` runs `pytest --tb=no -q` in a read-only Docker container before the planner; parses pass/fail counts and failing test names from stdout; 2-minute `start_to_close_timeout`, no retries
- `ProbeResult` dataclass in `src/models.py` (fields: `passed`, `failed`, `failing_tests`, `timed_out=False`) carries the probe outcome through the workflow
- `probe_tests: bool = True` field on `OrchestratorInput` lets callers opt out for repos without pytest
- `OrchestratorWorkflow` calls `probe_tests` before the planner when `input.probe_tests` is `True`; appends a `## Test baseline` section to the planner prompt with exit code, summary line, and failing test names; treats timeout as "baseline unknown" and continues
- `task_completed` event for the planner phase now includes `baseline_tests_passed` and `baseline_tests_failed` counts
- `TestProbeTests` class in `tests/test_activities.py` (3 tests) and corresponding workflow coverage in `tests/test_workflows.py`; 132/132 tests pass

## [0.2.2] - 2026-05-21

### Fixed
- PR titles on GitHub and ADO no longer show the `pr_author` agent's stdout; `_run_with_git` now reads `PR_DESCRIPTION.md` from the worktree (only for `pr_author` tasks) and stores it in `TaskResult.pr_description`, which `OrchestratorWorkflow` passes to `push_and_create_pr` as `pr_body`; falls back to the ticket ID when the file is absent or empty
- `PR_DESCRIPTION.md` capture is gated on `agent_type == pr_author` so other agents cannot accidentally populate the field

### Added
- `pr_description: str` field on `TaskResult` in `src/models.py` carries the captured `PR_DESCRIPTION.md` content through to the workflow
- `TestPrDescriptionCapture` in `tests/test_git_integration.py` verifies `_run_with_git` captures the file; `TestBasebranchFlowthrough` covers title extraction from a markdown heading and the empty-body ticket-ID fallback

## [0.2.1] - 2026-05-20

### Changed
- Split `tests/test_system.py` (932 lines, seven test classes) into focused files mirroring `src/` structure: `tests/test_workflows.py` (`TestParsePlan`, `TestParseReview`, `TestTopoSort`, `TestBuildContext`, `TestOrchestratorWorkflow`), `tests/test_activities.py` (`TestAllowedToolsRouting`, `TestBuildDockerCmd`, `TestPopulateWorkspace`, `TestAssertGitRoot`, `TestPushAndCreatePR`), and `tests/test_ticket.py` (absorbs ticket-related classes); original `tests/test_system.py` deleted; all 109 tests pass unchanged

## [0.2.0] - 2026-05-20

### Added
- `push_and_create_pr(repo_path, remote_url, agent_branch, ticket_id, pr_body) -> str` activity in `src/activities.py`: runs `git push origin <agent_branch> --force` then creates a PR via the detected provider, returning the PR URL; returns `""` as a no-op when `remote_url` is empty so local and sandbox runs are unaffected
- `push_and_create_pr` registered on the Temporal worker in `src/worker.py`
- Unit tests for `push_and_create_pr` in `tests/test_system.py` covering GitHub and ADO provider paths and the empty-`remote_url` no-op case

### Changed
- `OrchestratorWorkflow.run` in `src/workflows.py` now calls `push_and_create_pr` as a durable activity after `pr_author` completes, passing `pr_result.output` as the PR body; the returned PR URL is included in the `workflow_completed` event payload as `pr_url`
- `run_task.py` no longer performs `git push` / `gh pr create` directly; it reads `pr_url` from the workflow result payload

## [0.1.4] - 2026-05-20

### Fixed
- `load_ticket` in `src/ticket.py`: replaced hand-rolled `line.partition(":")` frontmatter parser with `yaml.safe_load`; YAML-quoted values such as `'42'` are now parsed as `"42"` instead of `"'42'"`; bare integers are cast to `str` when constructing a `Ticket`

## [0.1.3] - 2026-05-20

### Fixed
- `find_ticket` in `src/ticket.py`: removed redundant `direct = Path(ticket_id)` variable; `candidate` (already computed via `expanduser()`) is now used for the `.md` suffix check throughout the function

### Added
- Test in `tests/test_ticket.py` covering the relative-path resolution branch in `find_ticket` - passes a bare filename with `tickets_dir` set to the containing directory and asserts the resolved path is returned

## [0.1.2] - 2026-05-20

### Added
- `test_load_ticket_ado_format` in `tests/test_ticket.py` exercises the ADO frontmatter parsing path and asserts `ado_id` is parsed correctly

### Fixed
- `find_ticket` in `src/ticket.py`: relative `.md` filenames are now resolved against `tickets_dir` before falling back to the bare path; uses `is_file()` instead of `exists()`; adds `expanduser()` support

### Changed
- Reordered imports in `tests/test_ticket.py` so stdlib (`pathlib`) precedes third-party (`pytest`), consistent with `test_system.py` and `conftest.py`

## [0.1.1] - 2026-05-20

### Added
- Unit tests for backlog system: `find_ticket` direct `.md` path resolution (exists and missing), `build_goal` with and without `ado_id`, `check_quality` for a backlog ticket, and `load_ticket` parsing of backlog-format frontmatter

### Fixed
- `find_ticket` now raises `FileNotFoundError` for a `.md` path that does not exist, rather than falling through to the glob search
- `build_goal` no longer includes `(ADO #)` in the goal title when `ado_id` is empty

## [0.1.0] - 2026-05-19

### Added
- Multi-agent pipeline: Planner, Implementer, QA, Reviewer, Security, Architect, Changelog, PR Author
- Temporal-orchestrated workflow with durable execution and retry semantics
- Git worktree isolation - each agent runs in a dedicated branch
- Docker-based agent sandboxing with per-agent tool allowlists
- Provider-agnostic Claude credentials: Anthropic API or Vertex AI, controlled via `.env`
- HITL pause/resume via Temporal signals (`make resume`, `make abandon`)
- Mid-flight steering injection (`make steer`)
- Slack and generic webhook lifecycle notifications
- Sandbox mode - run against `sandbox/` without a target repo
- 64-test suite covering core pipeline logic (no Temporal or Docker required)
