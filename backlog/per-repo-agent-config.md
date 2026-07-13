---
title: Per-repo agent configuration
state: To Do
repo: daedalus
priority: P2
---

## Summary

Agent instructions (`agents/<type>.md`) and standards files are global - every repo gets the same prompts. There is no way to give one repo a stricter reviewer, add a domain-specific agent (e.g. a migration-safety checker), or include project-specific standards (e.g. PHI data policy, RBAC rules) without touching the framework itself.

Extend `repos.yaml` to support per-repo agent overrides and additional standards. `_populate_workspace` reads these at activity execution time - no changes to workflow logic.

## Acceptance Criteria

- `repos.yaml` supports an `agents` map and a `standards` list per repo entry.
- An `agents` entry with a path replaces the default `agents/<type>.md` for that repo and agent type.
- A `standards` list entry appends the referenced file into `standards/` in the agent workspace.
- An `agents.extra` list adds additional agent types the planner can invoke (documented in planner instructions).
- If a referenced file does not exist, `_populate_workspace` raises a clear error at activity start (not silently skips).
- The global defaults remain unchanged for repos that do not specify overrides.
- Documentation in README and `repos.example.yml` shows the full per-repo config schema.

## Plan

- Update `repos.example.yml` to show the full schema including `agents` and `standards` fields.
- Parse `agents` and `standards` from the repo entry in `_resolve_repo` (or pass the raw entry to `_populate_workspace`).
- In `_populate_workspace`, after loading the global agent markdown, check for a repo-specific override and use it if present.
- Append extra standards files into `workspace/standards/` before the agent runs.
- Add validation in `_load_repos` to check referenced paths exist.
- Add tests for: override replaces default, standards appended, missing file raises error.
