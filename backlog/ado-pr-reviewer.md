---
title: ADO pr_reviewer agent
state: To Do
repo: daedalus
priority: P3
---

## Summary

The `pr_reviewer` agent is GitHub-only. It uses `gh pr diff`, `gh pr view`, and `gh api`. Teams using Azure DevOps have no equivalent entry point. The `ADOProvider` exists in the codebase but the pr_reviewer agent and workflow have no ADO variant.

Add an ADO-compatible pr_reviewer agent type (`pr_reviewer_ado`) with equivalent instructions using `az repos pr show` and `az repos pr list`. The Docker image already includes the Azure CLI.

## Acceptance Criteria

- A new agent type `AgentType.pr_reviewer_ado` exists in `src/models.py`.
- `agents/pr_reviewer_ado.md` contains the full 9-step parallel review skill adapted for ADO (using `az repos pr` commands instead of `gh pr` commands).
- `_ALLOWED_TOOLS[AgentType.pr_reviewer_ado]` covers the `az repos` and `git` commands needed.
- `PRReviewWorkflow` accepts a `provider: str = "github"` field on `PRReviewInput`; when `"ado"`, it uses `pr_reviewer_ado`.
- `run_pr_review.py` accepts a `--provider ado` flag.
- `make review` accepts `PROVIDER=ado`.
- The Dockerfile includes the Azure CLI and `az devops` extension (already present - verify it builds cleanly).
- README documents the ADO review workflow.

## Plan

- Add `pr_reviewer_ado = "pr_reviewer_ado"` to `AgentType` enum.
- Copy `agents/pr_reviewer.md` to `agents/pr_reviewer_ado.md` and replace all `gh pr *` commands with `az repos pr *` equivalents.
- Add `AgentType.pr_reviewer_ado` to `_ALLOWED_TOOLS` with the ADO tool set.
- Update `PRReviewInput` to include `provider: str = "github"`.
- Update `PRReviewWorkflow.run` to select agent type based on provider.
- Update `run_pr_review.py` and `Makefile`.
- Verify Docker image builds with `az` available.
