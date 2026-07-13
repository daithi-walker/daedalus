---
title: Add security_scanner agent for SAST-based vulnerability discovery
state: To Do
repo: daedalus
type: feature
priority: P2
---

## Summary

Daedalus has a `security` agent but it only does post-implementation code review. A dedicated `security_scanner` agent would run SAST tools (semgrep, bandit) against the repo before or after implementation and emit structured JSON findings. This separates discovery from verification - combining them in one pass degrades recall, per Anthropic's published research on LLM-based security scanning.

## Acceptance Criteria

- A new `security_scanner` agent type exists in `src/models.py` (`AgentType` enum).
- `agents/security_scanner.md` instructs the agent to run semgrep and bandit and output a JSON findings list with fields: `file`, `line`, `cwe`, `severity` (`critical` / `high` / `medium` / `low`), `description`, `confidence`.
- `_ALLOWED_TOOLS` in `src/activities.py` grants `security_scanner` access to `Read` and `Bash(semgrep *)` and `Bash(bandit *)`.
- The agent is listed in `agents/planner.md` with documented trigger conditions (e.g. any task touching auth, external I/O, or data parsing).
- `agents/standards/security.md` is injected into the scanner workspace alongside coding and testing standards.
- Existing tests continue to pass; a new unit test covers the `security_scanner` tool allowlist entry.

## Plan

- `src/models.py`: add `security_scanner = "security_scanner"` to `AgentType`.
- `src/activities.py`: add entry to `_ALLOWED_TOOLS` - `AgentType.security_scanner: "Read,Bash(semgrep *),Bash(bandit *)"`.
- `agents/security_scanner.md`: new file. Role: read code and threat model from `_context.md`, run SAST tools, return structured JSON findings. Output schema matches the `ReviewResult` findings format so it slots into the existing review verdict pipeline.
- `agents/planner.md`: add `security_scanner` to the agent type table with trigger conditions.
- semgrep and bandit must be present in the `daedalus` Docker image - check `Dockerfile` and add if missing.
