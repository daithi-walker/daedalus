# Daedalus

Multi-agent coding workflow orchestrated by [Temporal](https://temporal.io) and [Claude Code](https://claude.ai/code).

Point Daedalus at any Git repository with a goal, and it plans, implements, tests, reviews, and raises a pull request - autonomously.

## Design principles

Daedalus is built to be **infrastructure-agnostic** - nothing in the pipeline is tied to a specific cloud, model vendor, or Git host:

- **Orchestration: Temporal.** Durable, replayable workflow state - a crashed worker resumes from the last completed step. Runs against a local Temporal server (Docker Compose) today, or Temporal Cloud.
- **Execution: containers, on any cloud.** Each agent runs as an isolated container in a dedicated git worktree. It runs on a laptop with Docker today and is designed to run as Kubernetes Jobs on any cluster - **AWS, GCP, or Azure** - so orchestration and execution stay independent of the underlying cloud.
- **LLM-agnostic.** The model backend is selected purely by environment: the Anthropic API directly, or Claude on **Google Vertex AI** today, with **AWS Bedrock** and other backends a small adapter change. No provider is baked into the workflow logic.
- **Git-host-agnostic.** GitHub and Azure DevOps are supported through a `GitProvider` abstraction; GitLab and others are a one-adapter addition.

See the [roadmap](ROADMAP.md) for the provider-abstraction and cloud-native deployment tracks.

## Docs

| Document | What's in it |
|---|---|
| [Architecture](docs/architecture.md) | Pipeline diagram, agent isolation model, workflow state machine, pluggable LLM credential flow |
| [ADR-001](docs/ADR-001-pr-creation-in-workflow.md) | Decision: move PR creation into the Temporal workflow |
| [ROADMAP](ROADMAP.md) | Done items, P1-P5 improvements |
| [Vision](docs/vision.md) | Forward-looking design: parallel execution, staged reviews, dynamic routing, knowledge grounding, operational intelligence |
| [Agent instructions](agents/) | Per-agent `CLAUDE.md` files - edit these to change agent behaviour |
| [Standards](agents/standards/) | Coding and testing standards injected into every agent workspace |

## How it works

```
Goal
 └─► Planner      - reads the repo, produces a task graph
      └─► Implementer - makes the code changes
           └─► QA         - writes and runs tests (Flask test client, pytest)
                └─► Reviewer   - checks code and test coverage; blocks → re-run
                     └─► Changelog  - bumps version, updates CHANGELOG.md
                          └─► PR Author  - writes the PR description
                               └─► Push & PR  - pushes branch, opens pull request
```

Each agent runs as an isolated Claude Code process inside Docker, in a dedicated git worktree. Agents commit their work so every step is recoverable. The workflow is durable - if the worker crashes mid-run, Temporal retries from the last completed activity.

### Signals and control

While a workflow runs you can:

```bash
# Inject guidance into the next agent turn
make steer WF_ID=<id> TEXT="Focus on error handling, not performance"

# Check live status
make status WF_ID=<id>

# Resume or abandon a HITL-paused workflow
make resume WF_ID=<id>
make abandon WF_ID=<id>
```

## Prerequisites

- Docker
- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (for dependency management)
- A running Temporal server (`make server` starts one via Docker Compose)
- Claude credentials (Vertex AI or Anthropic API - see below)

## Setup

### 1. Clone and install

```bash
git clone git@github.com:daithi-walker/daedalus.git
cd daedalus
uv venv .venv
uv pip install -e ".[test]"
```

### 2. Configure credentials

Copy `.env.example` to `.env` and fill in values:

```bash
cp .env.example .env
```

The backend is selected entirely by environment - the workflow and agent code are identical across providers.

**Option A - Anthropic API (simplest)**

```env
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-6
```

**Option B - Google Vertex AI (Claude on GCP)**

```env
CLAUDE_CODE_USE_VERTEX=1
ANTHROPIC_VERTEX_PROJECT_ID=your-gcp-project-id
CLOUD_ML_REGION=global             # or whichever region has Claude enabled
CLAUDE_MODEL=claude-sonnet-4-6
VERTEX_SA_KEY_PATH=/path/to/your/application_default_credentials.json
```

The SA key path can be your ADC credentials (`~/.config/gcloud/application_default_credentials.json` after `gcloud auth application-default login`), or a service account key JSON file.

Switching backends is just setting or unsetting `CLAUDE_CODE_USE_VERTEX` - no code edits required. **AWS Bedrock** (`CLAUDE_CODE_USE_BEDROCK`) is supported by the underlying Claude Code runtime and is a small adapter addition in `_build_docker_cmd` - see the [roadmap](ROADMAP.md).

### 3. Build the Docker image

```bash
make build        # main agent image
make build-qa     # QA agent image (includes pytest + Flask)
```

### 4. Start Temporal

```bash
make server       # starts Temporal + UI via docker-compose
```

Temporal UI: http://localhost:8080

### 5. Start the worker

```bash
make worker
```

Always use `make worker` - it loads `.env` and uses the correct Python from `.venv`.

## After a reboot

```bash
make server   # restart Temporal + Postgres
make worker   # restart the worker (in a separate terminal)
```

The worker must be restarted after any changes to `src/activities.py`, `src/workflows.py`, or `src/models.py` - it does not hot-reload.

## Running a workflow

### From a ticket file

The preferred way to submit work. Daedalus reads a Markdown ticket file, validates it, and derives the goal from the ticket content.

1. Copy `repos.example.yml` to `repos.yaml` (gitignored) and fill in your repos:

```yaml
# repos.yaml  - copy from repos.example.yml, never commit this file
my-api:
  url: git@github.com:your-org/your-api.git
  base_branch: main
  git_exclude:            # optional: patterns added to .git/info/exclude
    - "**/__pycache__/"
    - "*.pyc"

legacy-service:
  url: https://user:PAT@dev.azure.com/org/project/_git/legacy-service
  base_branch: develop
  changelog: false        # skip changelog agent if repo has no CHANGELOG.md
```

Each key is the short alias used in ticket frontmatter and on the CLI. See `repos.example.yml` for the full field reference.

2. Add a `repo:` field to your ticket frontmatter:

```markdown
---
ado_id: 123
title: Refactor pipeline scripts
state: To Do
repo: my-service
---
```

3. Set `DAEDALUS_TICKETS_DIR` in `.env` to the directory containing your ticket files.

4. Run:

```bash
make run-ticket TICKET=123
```

Daedalus will validate the ticket quality gate, build the goal from the ticket content, clone the mapped repo, run the full pipeline, and raise a PR.

Pass `FORCE=1` to skip the quality gate. Pass `REPO_URL=...` to override the repos.yaml lookup for a one-off run.

### Against a remote repo (ad-hoc)

```bash
TARGET_REPO_URL=git@github.com:you/your-repo.git make run \
  GOAL="Add input validation and error handling to the API endpoints"
```

Daedalus will:
1. Clone the repo into a temp directory
2. Run the full pipeline
3. Push an `agent/run-<timestamp>` branch
4. Open a pull request automatically

### Against a local repo

```python
# run directly
import asyncio
from run_task import main

asyncio.run(main(
    "Add type hints to all public functions",
    repo_path="/path/to/your/repo"
))
```

### Using the sandbox (no repo needed)

Drop files into `sandbox/` and run:

```bash
make run GOAL="Refactor sandbox/target.py: extract helper functions and add docstrings"
```

## Agent pipeline

| Agent | Tools | Role |
|---|---|---|
| `planner` | Read | Reads repo, produces JSON task graph |
| `implementer` | Read, Write, Edit, MultiEdit | Makes code changes |
| `qa` | Read, Write, Edit, Bash(pytest, flask, curl) | Writes and runs tests |
| `reviewer` | Read | Reviews code and tests; verdict: pass / advisory / block |
| `security` | Read | Security-focused review (optional, invoked by planner) |
| `architect` | Read | Architecture review (optional, invoked by planner) |
| `changelog` | Read, Write, Edit | Updates CHANGELOG.md, bumps version |
| `pr_author` | Read, Write | Writes PR description |
| `pr_reviewer` | Read, Agent, Bash(gh) | Reviews any GitHub PR; outputs a tiered findings report |
| `pr_reviewer_ado` | Read, Agent, Bash(az repos, git) | Reviews any ADO PR using `az repos pr show` + `git diff` |

Agent behaviour is defined in `agents/<name>.md`. Edit these files to change how each agent works - no code changes needed.

Coding, security, and testing standards are in `agents/standards/`. These are copied into each agent's workspace at runtime.

## Reviewing a PR

### GitHub

```bash
# Set GITHUB_TOKEN in .env (personal access token with repo read access)
make review PR=42
make review PR=42 REPO=my-org/my-repo   # specify repo explicitly
```

### Azure DevOps

```bash
# Set AZURE_DEVOPS_EXT_PAT in .env (PAT with Code Read + Pull Request Read scope)
python run_pr_review.py 456 --repo-url https://dev.azure.com/org/project/_git/repo
```

Both paths run a 6-parallel-reviewer pipeline (convention compliance, deep contextual review, surface scan, historical context, previous PR feedback, code comment compliance), score each finding by confidence, and output a tiered markdown report. No comments are posted automatically.

## Slack / webhook notifications

```env
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
EVENT_WEBHOOK_URL=https://your-endpoint.com/events     # optional generic webhook
TEMPORAL_UI_URL=http://localhost:8233                  # link in Slack messages
```

Daedalus emits lifecycle events: `workflow_started`, `phase_changed`, `task_completed`, `hitl_required`, `workflow_completed`, `workflow_failed`.

## Running tests

```bash
.venv/bin/python3 -m pytest tests/ -v
```

Tests cover the core pipeline logic - no Temporal server or Docker required.

## Known limitations

- Each agent runs in isolation - agents in parallel tasks cannot share a live workspace
- Docker must be running on the worker host; remote workers need Docker-in-Docker or a socket mount
- Temporal server must be reachable from the worker (`TEMPORAL_ADDRESS` in `.env`)
- The worker uses `.venv/bin/python3` - do not start it with system Python (macOS system Python 3.13 has broken SSL)
