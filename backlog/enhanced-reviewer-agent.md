---
title: Enhanced reviewer agent (parallel sub-agents)
state: To Do
repo: daedalus
priority: P2
---

## Summary

The `reviewer` agent in the orchestrator loop does a single-pass review. Its `block` verdicts lack the confidence and depth of the `pr_reviewer` skill's 6-agent parallel approach. Shallow reviews mean the implementer gets blocked on weak signal, or worse, real issues slip through.

Rewrite the `reviewer` agent instructions to use the same parallel sub-agent pattern as `pr_reviewer`: convention compliance, deep contextual review, surface scan, historical context, previous PR feedback, and code comment compliance. Each sub-agent produces structured findings with a confidence score. The aggregated, deduplicated, and tiered output drives the `approve` / `block` decision.

## Acceptance Criteria

- `agents/reviewer.md` instructs the agent to spawn parallel sub-agents, adapted for in-loop use (`git diff HEAD~1` instead of `gh pr diff`).
- Sub-agents are **technology-typed**: the reviewer first classifies what types of changes are present (Python/Temporal, Docker/containerised, Node/npm, React/frontend, database/migrations) and spawns only the sub-agents relevant to the diff. A pure Python change does not run the Docker sub-agent.
- Each sub-agent returns a structured JSON findings list with `file`, `line`, `severity`, `confidence`, and `description`.
- One dedicated **infrastructure/deployment sub-agent** handles cross-file consistency checks for the detected stack:
  - Python/Temporal: activity registration in worker, dataclass field defaults, call-site updates for new parameters
  - Docker: ENTRYPOINT traps when running shell commands, `:ro` mount write-access constraints, missing ENV vars
  - Node: lockfile consistency, `.env.example` coverage
  - React: router registration, API shape alignment
  - Database: NOT NULL columns without backfill, missing `CONCURRENTLY` on large-table indexes
- The reviewer aggregates, deduplicates (same file+line within 3 lines = same finding), and tiers findings: critical (≥90), high (≥70), advisory (<70).
- `block` is issued only when at least one critical or high-confidence finding exists.
- The block reason is a concise summary of the critical/high findings (not the raw sub-agent output).
- `approve` output includes the advisory findings as a non-blocking note for the changelog/pr_author.
- The `reviewer` entry in `_ALLOWED_TOOLS` is updated to include `Agent` so it can spawn sub-agents.
- Existing reviewer tests are updated to match the new output format.

## Plan

- Add a stack-classification step to `agents/reviewer.md`: read the diff, emit a JSON `{"stacks": ["temporal", "docker"]}` object, then spawn only the sub-agents for those stacks.
- Copy the parallel sub-agent prompts from `agents/pr_reviewer.md` into `agents/reviewer.md`, adapted for in-loop use.
- Add the infrastructure/deployment sub-agent (see above) as a new prompt not present in `pr_reviewer.md`.
- Update `_ALLOWED_TOOLS[AgentType.reviewer]` to `"Read,Agent"`.
- Define the expected JSON output format for sub-agents and the aggregation algorithm in the agent instructions.
- Update `src/workflows.py` to parse the new reviewer output format and extract the block reason from the findings summary.
- Update tests to reflect the new output format.
