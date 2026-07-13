---
title: Add doc-update agent to pipeline
state: To Do
repo: daedalus
type: feature
priority: P2
---

## Summary

When Daedalus modifies code it doesn't update adjacent documentation - README files, module docstrings, and docs directories drift silently. A dedicated doc-update agent, running after the implementer and before the PR author, reads `_context.md` to understand what changed and updates any code-level docs in the affected paths. The resulting PR contains code and doc changes together as a coherent unit.

## Acceptance Criteria

- `agents/doc_update.md` exists and instructs the agent to read `_context.md` and the list of modified files, then scan for and update adjacent documentation (README.md files, inline docstrings, any `docs/` directory within a modified path).
- The agent must only update docs that are directly tied to modified code - it must not touch architectural docs, ADRs, or process documentation.
- If no relevant docs exist, the agent exits cleanly with a no-op note in `_context.md`.
- The agent is inserted into the workflow between the implementer and the PR author.
- Updated doc files are committed alongside code changes in the same PR branch.
- Existing pipeline tests continue to pass.

## Plan

- Add `AgentType.doc_update` to the agent type enum and `_ALLOWED_TOOLS`.
- Write `agents/doc_update.md`: read `_context.md` → identify modified file paths → for each path walk up to find README.md and any `docs/` directory → diff existing doc content against what the code now does → write updates.
- Insert the `doc_update` step into `workflows.py` after the last implementer task and before `changelog`.
- Scope strictly to code-level docs - the agent prompt must explicitly exclude ADRs, architecture docs, and anything outside the modified file tree.
