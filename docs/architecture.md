# Daedalus Architecture

## Pipeline overview

```mermaid
flowchart TD
    User([Developer]) -->|"make run GOAL=..."| CLI[run_task.py]
    CLI -->|"clone + submit OrchestratorWorkflow"| Temporal[(Temporal Server)]
    Temporal --> Worker[Worker Process]

    Worker --> Plan["Planner Agent<br/>read-only"]
    Plan -->|JSON task graph| Worker

    Worker --> Impl["Implementer Agent<br/>read + write"]
    Impl -->|commits code| Worker

    Worker --> QA["QA Agent<br/>read + write + bash"]
    QA -->|"commits tests, runs pytest"| Worker

    Worker --> Review{"Reviewer Agent<br/>read-only"}
    Review -->|pass / advisory| Worker
    Review -->|block| Impl

    Worker --> Changelog["Changelog Agent<br/>read + write"]
    Changelog -->|bumps version| Worker

    Worker --> PRAuthor["PR Author Agent<br/>read + write"]
    PRAuthor -->|writes PR_DESCRIPTION.md| Worker

    Worker -->|push branch| Remote[("Git Remote<br/>GitHub / ADO")]
    Remote -->|create PR| PR([Pull Request])
    PR --> User
```

## Agent isolation

Each agent runs as an isolated Claude Code process inside Docker:

```mermaid
flowchart LR
    Activity["run_claude_task<br/>activity"] -->|git worktree add| Worktree["/tmp/agent-xyz<br/>git worktree"]
    Activity -->|_populate_workspace| Worktree
    Worktree --> Docker["docker run daedalus:latest<br/>--allowedTools ...<br/>--yes -p prompt"]
    Docker -->|stdout| Activity
    Activity -->|"git add + reset scaffolding<br/>git commit"| Worktree
    Activity -->|git worktree remove| Cleanup[cleanup]
```

### What goes into the workspace

| File | Source | Committed? |
|---|---|---|
| All repo files | git worktree | Yes (if agent changes them) |
| `CLAUDE.md` | `agents/<type>.md` or `agents/default.md` | **No** - excluded |
| `_context.md` | workflow (goal + prior results) | **No** - excluded |
| `standards/*.md` | `agents/standards/` | **No** - excluded |
| `PR_DESCRIPTION.md` | pr_author agent | **No** - excluded |

## Workflow state machine

```mermaid
stateDiagram-v2
    [*] --> planning
    planning --> executing
    executing --> executing: next task
    executing --> awaiting_hitl: reviewer blocked N times
    awaiting_hitl --> executing: resume signal
    awaiting_hitl --> done: abandon signal
    executing --> changelog
    changelog --> authoring
    authoring --> done
    done --> [*]
```

## Signals and queries

| Signal / Query | Direction | Purpose |
|---|---|---|
| `steer(text)` | → workflow | Inject guidance into next agent turn |
| `resume(decision)` | → workflow | Unblock HITL pause: `"resume"` or `"abandon"` |
| `status()` | ← workflow | Returns phase, current_task, blocked_reason, current_sha |

## LLM credential flow (pluggable backend)

The model backend is selected by environment; the container receives whatever credentials the chosen provider needs. The workflow and agent code are identical across backends.

```mermaid
flowchart LR
    Anthropic["Anthropic API<br/>ANTHROPIC_API_KEY"] -->|env-selected| Container[Docker container]
    Vertex["Google Vertex AI<br/>SA key / ADC"] -->|env-selected| Container
    Bedrock["AWS Bedrock<br/>(roadmap)"] -.->|env-selected| Container
    Container --> Claude[claude CLI]
    Claude --> Model[Claude model]
```
