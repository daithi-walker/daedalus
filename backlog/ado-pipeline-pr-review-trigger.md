---
title: ADO pipeline trigger for automatic PR review
state: To Do
repo: daedalus
type: feature
priority: P2
---

## Summary

Daedalus already has a `pr_reviewer_ado` agent that does a thorough 6-agent parallel review of any ADO pull request. Currently it can only be invoked manually from the CLI (`make review PR=42`). This item adds an ADO pipeline YAML so the review runs automatically on every PR and posts its findings back as a PR comment - closing the loop without human intervention.

Inspired by agentbox's GitHub Actions approach (`claude-code-review.yml`), which does the same pattern for GitHub repos. See local clone at `~/git/agentbox` for reference implementation. The ADO equivalent is straightforward because the review logic already exists - only the pipeline trigger and comment-posting step are missing.

## Acceptance Criteria

- An `azure-pipelines/pr-review.yml` pipeline YAML exists in the Daedalus repo.
- The pipeline triggers automatically on PR creation and every push to a PR branch targeting `main`.
- The pipeline runs the `pr_reviewer_ado` agent against the PR, passing `PR_ID`, `ORG_URL`, `PROJECT`, and `REPOSITORY` from pipeline variables.
- Agent stdout (the findings report) is posted back to the PR as a comment via `az repos pr comment create`.
- If the agent finds no issues above threshold, the "CLEAN" result is still posted as a comment.
- The pipeline requires two secret pipeline variables: `ANTHROPIC_API_KEY` and `AZURE_DEVOPS_EXT_PAT` (or uses `$(System.AccessToken)` for ADO auth).
- A second pipeline `azure-pipelines/pr-review-manual.yml` (or a separate stage) supports on-demand invocation via `/azp run` in a PR comment, for repos where auto-review on every push is too noisy.
- The Daedalus Docker image location (registry or direct install) is documented in `README.md` under a new "ADO Pipeline Integration" section.
- Existing CLI-based `make review` workflow is unaffected.

## Plan

Two implementation options - pick based on what's simpler to maintain:

**Option A: Docker image from a container registry**
- Push `daedalus:latest` to a container registry as part of the build (see `container-registry-publishing.md`).
- Pipeline pulls the image and runs `docker run ... daedalus:latest claude --dangerously-skip-permissions -p "..."`.
- Cleanest isolation; requires the registry publishing ticket to be complete first.

**Option B: Install Claude Code directly in pipeline**
- Pipeline agent (ubuntu-latest) installs Claude Code via `npm install -g @anthropic-ai/claude-code`.
- Copies `agents/pr_reviewer_ado.md` as `CLAUDE.md` into the workspace.
- Runs `claude --dangerously-skip-permissions -p "..." --yes` and captures output.
- No Docker required; simpler but less isolated.

Either way, the comment-posting step is the same:
```bash
az repos pr comment create \
  --id $PR_ID \
  --org "$ORG_URL" \
  --project "$PROJECT" \
  --repository "$REPOSITORY" \
  --text "$(cat review_output.txt)"
```

Use `$(System.AccessToken)` as `AZURE_DEVOPS_EXT_PAT` to avoid storing a PAT - the pipeline's built-in token has sufficient scope for posting PR comments.

For the `/azp run` on-demand trigger: ADO supports this natively with no additional config. Document the convention in the PR review pipeline YAML as a comment.

Note: a `@daedalus` mention-style trigger (watching PR comment text) would require a service hook wired to a webhook/function to queue a pipeline run via the ADO REST API. Out of scope for this ticket - the auto-trigger and `/azp run` patterns cover the main use cases.
