---
title: Add security scanning pipeline phase (discover → verify → patch)
state: To Do
repo: daedalus
type: feature
priority: P2
---

## Summary

The `security_scanner` agent (see `security-scanner-agent.md`) handles discovery, but discovery alone is not enough. Anthropic's research shows the real bottleneck is verification, triage, and patching - and that verification must be a separate agent pass to preserve recall. This item wires the full loop into Daedalus: threat model via `architect`, discovery via `security_scanner`, independent verification, triage into the PR description, and patching via the existing implementer/QA cycle.

## Acceptance Criteria

- The planner can produce a task graph that includes a security scanning phase: threat model task (`architect`) → discovery task (`security_scanner`, depends on threat model) → verification task (separate `security` agent re-reading findings, not the same pass, depends on discovery).
- Verification task outputs a filtered findings list (exploitable = true/false per finding); non-exploitable findings are dropped before the implementer sees them.
- Confirmed findings are passed to the implementer as context in `_context.md`; the implementer generates targeted fix tasks.
- `pr_author` includes a security findings summary section in the PR description, grouping findings by severity with CWE references.
- The planner only invokes this phase when the goal explicitly requests a security scan or when a task touches auth, permissions, credential handling, or external I/O - not on every run.
- Existing single-phase (no security scan) workflows are unaffected and existing tests continue to pass.

## Plan

- Depends on `security-scanner-agent.md` being complete first.
- No changes to `OrchestratorWorkflow` are needed if the planner produces the right dependency-ordered task graph - the existing topological executor handles sequencing.
- Update `agents/planner.md` to document the three-task security phase pattern and when to emit it.
- Update `agents/security.md` (existing verifier role): reframe it as the verification pass that reads `security_scanner` findings from `_context.md` and confirms exploitability rather than doing its own discovery.
- Update `agents/pr_author.md` to include a security findings section when the context contains scanner output.
- Consider a `threat_model` field in `_context.md` schema so the scanner receives it as structured input rather than raw text.
- Validation: run a test workflow against a repo with a known injection vulnerability (e.g. a demo Flask app with an unsanitised query param) and confirm the pipeline finds, verifies, and patches it end to end.
