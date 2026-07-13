# Daedalus Vision

Where Daedalus is headed beyond the current pipeline. These are design directions, not shipped features - the [ROADMAP](../ROADMAP.md) tracks what is actually in flight. Everything here builds on the same substrate: a durable Temporal workflow orchestrating isolated, per-agent-scoped containers, with human-in-the-loop via Signals. Nothing here is tied to a specific cloud, model vendor, or Git host.

## 1. Parallel execution and the merger agent

The current pipeline serializes agent work on a single commit chain - task B waits for task A. For a plan whose middle tasks are independent, wall-clock time is the sum of all tasks rather than the critical path.

**Pre-flight conflict prediction.** The planner already emits a `files` list per task. Before dispatching, the orchestrator schedules any two tasks that share a file sequentially, and runs tasks with non-overlapping file sets in parallel on separate branches from the same base commit. This eliminates most conflicts statically.

**The merger agent.** After each parallel batch, the orchestrator attempts a `git merge`. Clean merges fast-path. On conflict, a `merger` specialist (`Read` + `git` diff/merge tooling) receives both branches' intent, the conflict markers, and both task descriptions, resolves the files, and returns a merged commit - or escalates to HITL if uncertain. The merge graph is a DAG with no recursive merges: overlapping tasks were already serialized, so the merger only ever sees a single conflict level.

A `parallel` flag (default off) lets callers opt in. Parallelism is worth it when the planner produces ≥3 independent tasks, each runs long enough to beat merge overhead, and the test suite can validate the merge point.

## 2. Two-phase review: design gate + code gate

Architect and security agents currently run *after* implementation. A fundamentally bad design choice is expensive to fix once code exists - which is why human teams review designs *before* implementation.

```
planner → task graph
  ├─▶ [design gate - medium/high risk only]
  │     ├─▶ architect: reviews the plan + file list + org context
  │     └─▶ security:  reviews the plan for attack surface, credential flow, API shape
  │           └─▶ block → HITL or re-plan; pass → implement
  └─▶ implementer(s)
        └─▶ [code gate - always]
              ├─▶ reviewer: style, correctness, patterns
              ├─▶ security: injection, auth, secrets      [medium/high]
              ├─▶ red_team: active exploitation attempts   [high only]
              └─▶ qa:       run tests
```

The design gate blocks implementation if the plan is wrong; the code gate catches what emerged during implementation. Both are needed because plans don't capture every implementation choice. The planner gains `risk_class` and `change_type` fields to drive gate selection.

## 3. Complexity-based routing

Running the full agent suite for a one-line typo is wasteful; running only a code reviewer for a new auth flow is dangerous. The pipeline should match the risk of the change. The planner declares `risk_class`, and the orchestrator routes accordingly:

| risk_class | Design gate | Code reviewer | Security (code) | Red team | QA |
|---|---|---|---|---|---|
| low | - | ✓ | - | - | optional |
| medium | architect | ✓ | ✓ | - | ✓ |
| high | architect + security | ✓ | ✓ | ✓ | ✓ |

`change_type` refines this: `api_change` is at least medium; `security` is always high with red team; `breaking` is always high with HITL before the PR. Classification won't be perfect - the `steer()` Signal lets a human escalate mid-flight.

## 4. Dynamic routing on findings

Today the agent set and order are largely static; a finding can only trigger an implementer re-run or a HITL pause. Extending the review verdict with an `escalate` option turns the orchestrator into a router:

```json
{ "verdict": "escalate", "escalate_to": "security",
  "reason": "Unvalidated external URL construction - security must review", "findings": [...] }
```

On `escalate`, the orchestrator inserts the named agent at the current position with the findings as context. Examples: a reviewer that hits an unfamiliar crypto pattern escalates to security; QA failing on an import error escalates to a dependency-fix agent before re-running. Escalation depth is capped (an escalated agent cannot itself escalate) to keep cost bounded and the Temporal history interpretable - a single-hop model, not arbitrary agent spawning.

## 5. Knowledge grounding and organizational context

Agents operate on a blank slate. An architect with no awareness of approved platforms or existing services can propose a duplicate service, credentials in environment variables, or an unapproved data store. Two layers address this:

**Static knowledge (a standards hierarchy).** Extend the standards directory into layered docs the design-gate agents must read first and treat violations as an automatic `block` - not advisory:

```
agents/standards/
  enterprise.md        ← hard constraints (approved cloud & compute tiers, approved data stores, no long-lived cloud keys, private-by-default networking)
  service-catalog.md   ← what's deployed, connection patterns, ownership
  adrs/                ← past decisions with rationale
  security-baseline.md ← OWASP, credential handling, input validation
  tech-stack.md        ← approved frameworks, forbidden packages, version constraints
```

This is the 80% solution with no new infrastructure.

**Live state (pre-flight context).** For what's actually deployed right now, a host-side `context_collector` activity runs before the planner on medium/high-risk changes: it reads infrastructure-as-code state (Terraform or equivalent) and/or an internal service registry, fetches recent ADRs, and produces a read-only context document injected into the planner and architect. It runs on the host because it needs cloud read credentials - and it can only read, never act. This works identically across AWS, GCP, and Azure.

**Deployment safety net.** Regardless of what agents propose, they cannot deploy: no cloud SDKs in agent containers, `Bash` absent or scoped to test tooling, no push credentials mounted, and PR creation happens on the host - not inside an agent. Standards prevent proposing the wrong thing; the container model prevents deploying anything at all. Both are needed.

## 6. Red teaming

Security review reads code defensively, looking for known-bad patterns. Red teaming is offensive: a `red_team` agent (same read-only toolset, fundamentally different prompt) assumes the code is deployed and internet-reachable and tries to construct exploits - injection, privilege escalation, auth bypass, exfiltration, SSRF, prompt injection. It rates *exploitability*, not just severity, and blocks on any critical finding. It runs after the security reviewer (with that reviewer's findings as context) on `high` risk changes only - new external endpoints, auth changes, payment/PII handling, new service-to-service paths, or LLM prompt construction.

## 7. Execution graph and learning

Temporal's event history is the ground truth for a run, but it's opaque, transient (pruned after retention), not queryable across runs, and not a learning signal. A great run and one that took four retry cycles look identical from the outside.

**Design: a local execution-graph store.** At the end of each run, a `write_run_graph` activity (same fire-and-forget pattern as event publishing - short timeout, never fails the workflow) writes a structured record of the routing graph that *actually* occurred - nodes (each agent invocation with duration, verdict, findings) and edges (planned, triggers-review, block-retry, escalation) - to `runs/{workflow_id}.json`, plus a one-line summary in `runs/index.json`.

This enables:
- **Observability without the Temporal UI** - anyone can read `runs/`.
- **Pattern detection** - which agents block most, which goals need retries, which paths attract security findings.
- **Planner calibration** - if the planner says `low` but security blocks every time, the graph surfaces the miscalibration.
- **Routing history as context** - future runs on the same repo read prior graphs: "last time we touched `auth.py`, security blocked on missing validation - factor this in."
- **Cost accounting** - LLM calls, agent-seconds, and retry overhead per workflow.

The JSON is the adjacency-list form of a directed graph, so it loads unchanged into SQLite, Neo4j, or Memgraph when query needs outgrow `jq`.

## 8. Operational intelligence

The same substrate that writes and reviews code extends to **operational investigation**: reading live system state (logs, metrics, orchestration status, tickets), correlating it with code, and producing a diagnosis. The output is a ticket comment, an alert, or a fix PR - never a direct mutation of production infrastructure. The trigger is an event (an alert, a failed build, a ticket label change) rather than a human-typed goal.

A `TriageWorkflow` collects context in parallel (a log analyst, a cluster inspector, a code correlator - each with a narrowly-scoped, read-only credential set), a diagnoser correlates it into a structured result with a confidence score, and a decision phase either posts the diagnosis or pauses for HITL when confidence is low. The **read broadly, write narrowly** principle holds: only a single notifier agent can write externally, and only through a tightly-scoped allowlist.

### Why this needs Temporal, not an in-process agent framework

- **Durability.** An 8-minute investigation that hits an API timeout at minute 4 resumes at minute 4, not from scratch. Event-sourced execution replays from the last checkpoint; in-process frameworks lose state on crash.
- **HITL with real latency tolerance.** Pausing for a human reply for hours costs nothing - the workflow is idle in Temporal's state machine. An in-process wait loop holds a thread and connection slots the whole time.
- **Credential isolation.** Each agent container sees exactly one credential set. In a single-process framework, credentials are visible to every agent in the process. Docker enforces isolation at the OS level.
- **Per-agent tool restriction.** `--allowedTools` is enforced by the Claude Code CLI at invocation - a log agent can run its read command and nothing else. Code-level restrictions in a function-based framework can be bypassed by a bug or prompt injection.

The trade-off is real: Temporal adds operational overhead not worth it for a one-shot script. For a system that runs against production infrastructure, pauses for humans for hours, and must survive worker restarts, it is the right substrate.
