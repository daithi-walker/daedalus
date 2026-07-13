---
title: Validated-By commit trailer
state: To Do
repo: daedalus
priority: P2
---

## Summary

Commits carry `Authored-By-Agent` and `Intent-Ref` trailers but not `Validated-By`. The audit trail requires knowing which agents validated a change and their conclusion, not just who authored it. Without this, the intent → authoring → validation → outcome chain is incomplete and cannot be parsed programmatically for compliance reporting.

## Acceptance Criteria

- After the reviewer agent runs with an `approve` verdict, a `Validated-By: daedalus/reviewer@approve` trailer is appended to the implementer's most recent commit via `git notes` or an additional empty commit.
- When the reviewer issues a `block`, no `Validated-By` trailer is appended (the commit is still in progress).
- When `pr_reviewer` runs post-merge, it appends `Validated-By: daedalus/pr_reviewer@<verdict>` to the merge commit (or the PR's head commit via a git note).
- The trailer format is parseable: `daedalus/<agent-type>@<verdict>`.
- A `scripts/audit_trail.py` script reads a git range and produces a CSV of `commit_sha, authored_by, intent_ref, validated_by, verdict` for compliance reporting.
- Existing commit message tests are updated to include the new trailer.

## Plan

- In `_git_commit`, accept an optional `validated_by` argument. If set, add it as a git trailer to the commit message.
- In `OrchestratorWorkflow`, pass `validated_by=f"daedalus/reviewer@approve"` to the final implementer commit after approval.
- Add `scripts/audit_trail.py` that uses `git log --format='%H %s %b'` and parses `Authored-By-Agent`, `Intent-Ref`, and `Validated-By` trailers into a CSV.
- Document the trailer format in `docs/architecture.md`.
