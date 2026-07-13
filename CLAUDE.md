# Daedalus

Multi-agent coding workflow orchestrated by Temporal and Claude Code. Plans, implements, tests, reviews, and raises pull requests autonomously against any Git repository.

## Repository structure

```
src/
  workflows.py      - OrchestratorWorkflow: plan → execute task graph → changelog → PR
  activities.py     - run_claude_task, publish_event: run Claude in Docker, commit results
  models.py         - TaskInput, TaskResult, OrchestratorInput, ReviewResult dataclasses
  worker.py         - Temporal worker entrypoint
  providers/        - PR creation: GitHubProvider, ADOProvider, get_provider() auto-detect
agents/
  *.md              - Per-agent CLAUDE.md instructions (planner, implementer, qa, reviewer, etc.)
  default.md        - Generic fallback CLAUDE.md copied into agent workspaces
  standards/        - Coding and testing standards copied into every agent workspace
tests/
  test_system.py    - 72 feature tests covering pipeline logic (no Temporal or Docker required)
run_task.py         - CLI: clone repo, submit workflow, stream result, push branch, open PR
Makefile            - build, build-qa, server, worker, run, status, steer, resume, abandon
```

## How agents run

Each agent is an isolated Claude Code process inside Docker (`daedalus:latest` or `daedalus-qa:latest`). Before launch, Daedalus:

1. Creates a git worktree of the target repo at a temp path
2. Copies `agents/<type>.md` (or `agents/default.md`) as `CLAUDE.md` into the worktree
3. Copies `agents/standards/*.md` into `standards/`
4. Writes `_context.md` with goal and prior task results
5. Runs `docker run ... claude --allowedTools <tools> -p <prompt> --yes`
6. Commits agent output - excluding `CLAUDE.md`, `_context.md`, `standards/`, `PR_DESCRIPTION.md`, `__pycache__`
7. Cleans up the worktree and branch

## Agent types

| Agent | Tools | Role |
|---|---|---|
| `planner` | Read | Reads repo, produces JSON task graph |
| `implementer` | Read, Write, Edit, MultiEdit | Makes code changes |
| `qa` | Read, Write, Edit, Bash(pytest/flask/pip/curl) | Writes and runs tests |
| `reviewer` | Read | Reviews code; verdict: pass / advisory / block |
| `security` | Read | Security-focused review |
| `architect` | Read | Architecture review |
| `changelog` | Read, Write, Edit | Updates CHANGELOG.md, bumps version |
| `pr_author` | Read, Write | Writes PR_DESCRIPTION.md |
| `pr_reviewer` | Read, Agent, Bash(gh) | Reviews any GitHub PR; tiered findings report |
| `pr_reviewer_ado` | Read, Agent, Bash(az repos, git) | Reviews any ADO PR using `az repos pr show` + `git diff` |

## Running tests

```bash
uv run --with pytest --with temporalio python3 -m pytest tests/ -v
```

All tests run without Temporal, Docker, or network. Add tests for any new pipeline logic.

## Merging agent PRs

Always merge agent PRs with a **regular merge commit** (`gh pr merge --merge`), never squash or rebase.

Each agent commit carries `Authored-By-Agent: daedalus/<type>` and `Intent-Ref` trailers that form the SDLC §8 audit trail. Squashing collapses them into a single commit and removes them from `git log` on main - they become unrecoverable except from GitHub's PR history.

```bash
gh pr merge <number> --merge
```

## Backlog

Tickets live in `backlog/*.md`. Files prefixed with `_` (e.g. `_template.md`) are ignored by Daedalus.

**Adding a ticket** - copy `backlog/_template.md` to `backlog/<slug>.md` and fill it in:

| Field | Values | Notes |
|---|---|---|
| `title` | string | Short imperative phrase |
| `state` | `To Do` | Use `To Do` for new items |
| `repo` | alias from `repos.yaml` | e.g. `daedalus` |
| `type` | `bug` / `feature` | `bug` = broken behaviour; `feature` = new capability |
| `priority` | `P1` / `P2` / `P3` | P1 = blocking, P3 = nice-to-have |

The `## Summary` and `## Acceptance Criteria` sections are required. `## Plan` is optional.

**Running a ticket:**

```bash
make backlog ITEM=<slug>          # e.g. make backlog ITEM=self-repair-loop
```

**Clearing completed tickets** - once the work merges, either delete the file or set `state: Done`. Files with state `Done`, `Closed`, `Resolved`, or `Removed` will be rejected by `check_quality` if accidentally re-run.

## Worker restarts after code changes

The Temporal worker (`src/worker.py`) is a long-running process. It does **not** hot-reload. After merging changes to any of the following, the worker must be restarted before new workflows will use the updated code:

- `src/activities.py` - new or modified activities
- `src/workflows.py` - new or modified workflow logic
- `src/models.py` - dataclass changes (`TaskResult`, `TaskInput`, etc.)

**In-flight workflows** started before the restart will attempt to replay against the new code. If a new field was added to a dataclass without a default value, replay will raise `AttributeError` and the workflow will fail. Always add default values (e.g. `field: str = ""`) to dataclass fields on serialized types.

Restart the worker:
```bash
pkill -f "src.worker" && make worker
```

In Kubernetes / Docker Compose, a rolling restart handles this automatically.

## What NOT to break

- `asyncio.shield` in `_run_with_heartbeat` - prevents pipe corruption on 30s heartbeat ticks
- The git scaffolding exclusions in `_git_commit` - `CLAUDE.md`, `_context.md`, `standards/`, `PR_DESCRIPTION.md`, `__pycache__` must never land in target repos
- `_assert_git_root` - `repo_path` must be a git root, not a subdirectory
- `patch.object(activities, ...)` in tests - do not use `importlib.reload`
