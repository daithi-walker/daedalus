# Daedalus Roadmap

Daedalus can already plan, implement, test, review, and raise a PR autonomously. The items below are what's needed before it's ready to work on itself - and to be genuinely useful across a team.

---

## Done

- **Standalone git root check** - `_assert_git_root()` detects monorepo subdirectory footguns and fails fast with a clear error.
- **Scaffolding file exclusion** - `CLAUDE.md`, `_context.md`, `standards/`, `PR_DESCRIPTION.md`, and `__pycache__` are never committed to the target repo.
- **Provider abstraction** - `GitProvider` ABC with `GitHubProvider` (`gh`) and `ADOProvider` (`az repos`), auto-detected from remote URL.
- **Rename: Forge → Daedalus** - Docker images, code, docs, and CLI updated.
- **Architecture diagram** - Mermaid diagrams in `docs/architecture.md`.
- **PR review agent** - `make review PR=42` runs the multi-agent pr_reviewer skill (GitHub-only) against any PR and outputs a structured findings report.
- **SDLC audit trail (partial)** - every commit carries `Authored-By-Agent: daedalus/<type>` and `Intent-Ref: <ticket_id>` trailers for audit trail traceability. Agent context files (`CLAUDE.md`, `standards/`) are excluded from agent commits by design.

---

## P1 - Correctness and reliability

These are gaps that cause silent failures or wrong output.

### Self-repair loop
**Problem:** When the reviewer blocks, Daedalus retries the implementer with the same prompt. It has no mechanism to diagnose *why* the block happened and replan. In practice, it tends to reproduce the same mistake.

**Goal:** After a `block` verdict, feed the reviewer's findings back into a replanning step. The planner should produce a targeted fix task rather than re-running the original implementation blindly.

### Work on an existing branch
**Problem:** Daedalus is greenfield-only. It can't pick up a PR that's already in flight, fix reviewer feedback on a branch it didn't create, or resume after a partial run on a repo with uncommitted agent changes.

**Goal:** Accept an optional `base_branch` input. When set, create the agent worktree from that branch rather than HEAD, and push back to it rather than creating a new one.

### Post-PR review loop
**Problem:** The `pr_reviewer` agent outputs findings as a markdown report, but nothing picks them up and acts on them. For agent-raised PRs, a human must read the report and manually request fixes.

**Goal:** After `pr_author` raises the PR, run `pr_reviewer` on the resulting GitHub PR. Feed any high-confidence findings back to the implementer as a fix task. If the implementer addresses all findings, push an updated commit to the open PR branch. This closes the loop without requiring human intervention for straightforward review issues.

---

## P2 - Capability

Things Daedalus can't do yet that would meaningfully expand what it's useful for.

### Iterative improvement mode
**Problem:** Daedalus is a one-shot pipeline. There's no way to say "run it again on the same repo with a follow-up goal" and have it build on the previous branch rather than starting over.

**Goal:** A `--continue` mode that finds the last agent branch, checks it out, and runs the pipeline from a specified phase (e.g. skip planner, go straight to implementer).

### Planner reads test state
**Problem:** The planner reads the repo but doesn't know whether tests are currently passing or failing before it starts. It can produce a task graph that assumes a green baseline when the repo is already broken.

**Goal:** Run `pytest --tb=no -q` (or equivalent) in a read-only container before planning. Pass the result to the planner so it can factor in existing failures.

### Security and architect agents activated
**Problem:** `security` and `architect` agent definitions exist but the planner rarely invokes them - it has no strong signal for when to do so.

**Goal:** Document the trigger conditions clearly in the planner agent instructions. Consider making a security review mandatory for any task that touches auth, permissions, or external I/O.

### Parallel task workspace sharing
**Problem:** Agents in parallel tasks run in fully isolated worktrees. They can't see each other's in-progress output, so parallel implementation tasks risk conflicting edits.

**Goal:** For parallel tasks, either enforce a no-overlap file constraint checked at plan time, or serialize tasks that touch the same files even if the plan marks them parallel.

### Enhanced reviewer agent (parallel sub-agents + provider-agnostic fetch)
**Problem:** The `reviewer` agent in the OrchestratorWorkflow loop does a single-pass review. Its `block` verdicts lack the confidence and depth of the pr_reviewer skill's 6-agent parallel approach. Additionally, `pr_reviewer.md` and `pr_reviewer_ado.md` are nearly identical - the only difference is which CLI they use to fetch PR metadata. The review logic is duplicated.

**Goal:** Rewrite the `reviewer` agent instructions to use the same parallel sub-agent pattern (convention compliance, deep contextual review, surface scan, historical context, previous PR feedback, comment compliance) with confidence scoring. At the same time, extract the PR data fetch into a provider-specific pre-activity (`fetch_pr_context`) that normalises PR metadata into a common structure before the single shared `pr_reviewer` agent runs. Eliminates the GitHub/ADO duplication and makes adding future providers (GitLab, etc.) a one-function change.

### Complete audit trail - Validated-By trailer
**Problem:** Commits carry `Authored-By-Agent` and `Intent-Ref` trailers but not `Validated-By`. The SDLC §8 governance spec requires the audit trail to include which agents validated a change and their conclusion, not just who authored it.

**Goal:** After the reviewer agent runs, append a `Validated-By: daedalus/reviewer@<verdict>` trailer to the implementer's commit (or add it as a separate note commit). When the pr_reviewer runs post-merge, append its verdict similarly. This completes the intent → authoring → validation → outcome chain in the git history, making it directly parseable for compliance reporting.

### Per-repo agent configuration
**Problem:** Agent instructions (`agents/<type>.md`) and standards files are global - every repo gets the same prompts. There's no way to give one repo a stricter reviewer, add a domain-specific agent (e.g. a migration-safety checker), or include project-specific standards (e.g. PHI data policy, RBAC rules) without touching the framework itself.

**Goal:** Extend `repos.yaml` to support per-repo agent overrides and additional standards:

```yaml
my-repo:
  url: https://...
  agents:
    reviewer: path/to/custom-reviewer.md   # replaces agents/reviewer.md for this repo
    extra: [migration-safety]              # additional agent types the planner can invoke
  standards:
    - path/to/hipaa.md                     # appended to standards/ for every agent run
```

`_populate_workspace` reads these at activity execution time - no changes to workflow logic. This makes Daedalus genuinely multi-tenant: framework defaults apply everywhere, repo-level config overrides where needed.

### Additional ticket sources
**Problem:** `run_ticket.py` reads from local markdown files in a specific ADO-derived format. Teams using other issue trackers (Jira, Linear, GitHub Issues) have no equivalent entry point.

**Goal:** A `fetch_ticket.py` script (or family of scripts) that pulls issues from external systems and writes them as the standard markdown format into `FORGE_TICKETS_DIR`. Each source adapter handles field mapping - e.g. Jira custom fields for acceptance criteria, Linear description body. Once fetched, the rest of the pipeline is unchanged. Initial targets: Jira, Linear, GitHub Issues.

---

## P3 - Observability and UX

Things that make Daedalus easier to operate and debug.

### Slack threading
**Problem:** Each workflow lifecycle event (started, task completed, phase changed, HITL, done) posts a separate top-level Slack message. A single workflow run can flood a channel with 10+ messages.

**Goal:** Use `chat.postMessage` with a bot token (replacing the incoming webhook) so the first event per workflow creates a thread, and all subsequent events for the same workflow are posted as replies. This requires a `SLACK_BOT_TOKEN` env var and storing the first message's `ts` in workflow state.

**Note:** ADO pr_reviewer is also a P3 item - `az repos pr show/list` instead of `gh pr`, plus `az` CLI in the Docker image.

### Retry budget visibility
**Problem:** When Temporal exhausts retries on an activity, the error (`activity StartToClose timeout`) is opaque. There's no easy way to know how many attempts were made or why each failed.

**Goal:** Log retry count and failure reason to the event stream on each attempt. Emit a `task_failed` event to Slack/webhook with the last error.

### Mid-run workspace inspection
**Problem:** There's no way to see what an agent has written to its workspace while it's running. Debugging a hung or misbehaving agent means waiting for it to finish (or time out).

**Goal:** Expose a `inspect` signal that snapshots the current workspace file list and last N lines of stdout to the workflow query interface.

### Structured activity logs
**Problem:** Worker logs are unstructured print/logger output mixed across activities. Correlating a log line back to a specific task and workflow ID requires grepping.

**Goal:** Add `workflow_id` and `task_id` to every log line emitted inside an activity. Consider shipping logs to a structured sink (Cloud Logging, Datadog) alongside the Slack events.

### Temporal UI link in terminal output
**Problem:** When you kick off a workflow from `make run`, you get the workflow ID but have to manually construct the Temporal UI URL.

**Goal:** Print the full Temporal UI link to stdout immediately after the workflow is submitted.

### Token usage per task
**Problem:** Claude Code doesn't expose token counts in its `--output-format text` output, so there's no visibility into how many tokens each agent task consumed. This makes it impossible to estimate cost per workflow, identify expensive tasks, or set budgets.

**Goal:** Capture token usage per agent run. Options: parse `--output-format json` (which includes `usage` fields) instead of text and extract the summary separately; or post-process the Claude API response headers if running without the CLI wrapper. Surface per-task input/output token counts in the `task_completed` event and aggregate totals in the `workflow_completed` event. Include in the Slack notification summary.

---

## P4 - Self-hosted operation

What's needed before Daedalus can run reliably on a shared team worker.

### Multi-worker support
**Problem:** The current design assumes a single worker process. Multiple workers would compete for the same Docker socket and could exhaust the host's resources if many workflows run concurrently.

**Goal:** Add a concurrency cap per worker (max N simultaneous Docker containers). Document how to run multiple workers safely.

### Credential rotation without restart
**Problem:** Vertex AI ADC credentials expire. When they do, all in-flight activities fail. The worker must be restarted with fresh credentials.

**Goal:** Detect credential expiry in the Docker command exit code/stderr and surface it as a retriable error with a clear message, rather than a generic Claude exit code failure.

### Worker health endpoint
**Problem:** There's no way to tell if the worker is alive and polling without checking Temporal UI.

**Goal:** Add a simple HTTP health endpoint to the worker process that reports whether it's connected to Temporal and how many activities are currently running.

---

## P4.5 - Platform configurability

Making Daedalus provider-agnostic so it works cleanly across different infrastructure stacks.

### Formal platform config layer
**Problem:** Provider choices (Git host, LLM backend, notification sink) are scattered across env vars with no single place to declare the platform a deployment targets. Adding a new provider means touching multiple files.

**Goal:** A `platform.yaml` (or `platforms/` directory) that declares the active providers for each axis:

```yaml
git:      ado          # ado | github | gitlab
llm:      anthropic    # anthropic | vertex | azure-openai
notify:   slack        # slack | teams | webhook | none
```

Each axis maps to an adapter in `src/providers/`. Env vars remain as overrides. The `repos.yaml` repo entries inherit the platform default and can override per-repo. This makes multi-tenant deployments explicit - one Daedalus worker serving GitHub repos for one client and ADO repos for another with no env var juggling.

---

## P5 - Cloud-native deployment

What's needed to run Daedalus as a managed service rather than a local process.

### Temporal Cloud
**Problem:** The self-hosted Temporal server (docker-compose) is a single point of failure and requires manual maintenance. Temporal Cloud provides a managed, HA namespace with no ops burden.

**Goal:** Parameterise the worker and client to connect to a Temporal Cloud namespace via mTLS. Document the namespace, certificate, and API key configuration. The worker container should work unchanged - only connection config differs.

### Kubernetes workers
**Problem:** The worker runs as a local process tied to a developer's machine. This doesn't scale and means workflows stall when the laptop is closed.

**Goal:** A Kubernetes deployment manifest (or Helm chart) for the Daedalus worker. Each worker pod needs access to a Docker socket (or a Docker-in-Kubernetes alternative such as Kaniko or sysbox) to run agent containers. Include resource limits, liveness probe wired to the health endpoint, and a horizontal pod autoscaler based on Temporal task queue backlog depth.

### Agent containers in Kubernetes
**Problem:** Agents currently run as Docker containers launched from the worker host. In a Kubernetes deployment, spawning sibling containers via the host Docker socket is a security concern.

**Goal:** Evaluate and implement a Kubernetes-native agent execution model - options include Kubernetes Jobs (one Job per agent task), sysbox-runc for nested containers, or replacing Docker with a direct Claude API call (removing the container layer entirely for simpler deployments).

---

## North star

Daedalus uses itself to extend Daedalus. A developer opens an issue describing a new capability, runs Daedalus pointed at the Daedalus repo, and the resulting PR is good enough to review and merge with minor edits.
