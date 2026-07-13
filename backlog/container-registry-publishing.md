---
title: Publish Daedalus Docker images to a container registry
state: To Do
repo: daedalus
type: feature
priority: P3
---

## Summary

Daedalus images are currently built and run only on a developer's local machine. Publishing `daedalus:latest` (and `daedalus-qa:latest`) to a container registry makes them available to CI pipeline agents and Kubernetes workers - unblocking both the CI pipeline PR review trigger (see `ado-pipeline-pr-review-trigger.md`) and the cloud deployment path (see `cloud-deployment-k8s.md`).

## Acceptance Criteria

- A CI pipeline (ADO or GitHub Actions) builds and pushes `daedalus:latest` and `daedalus-qa:latest` to a nominated OCI-compatible container registry on every merge to `main`.
- Images are tagged with both `latest` and the short git SHA (`daedalus:<sha>`).
- The registry hostname and image pull path are documented in `README.md`.
- The pipeline authenticates to the registry using short-lived credentials or workload identity - no long-lived secrets stored in plaintext.
- A `make push-images` target exists for manual pushes during development.
- Pull access for the images is documented so the CI pipeline and k8s deployment tickets can reference it.

## Plan

- The registry choice is deployment-specific (ECR on AWS, GCR/Artifact Registry on GCP, ACR on Azure, GHCR for open source). The Makefile and CI YAML should take `REGISTRY` as a variable rather than hardcoding a provider.
- CI step: `docker build`, `docker tag daedalus:latest $REGISTRY/daedalus:latest`, `docker push`. Standard `docker/login-action` works against any OCI registry.
- Tag strategy: `daedalus:latest` and `daedalus:<short-sha>`.
- Update `README.md` with the registry variable pattern and pull instructions.
- This is a prerequisite for `ado-pipeline-pr-review-trigger.md` (Option A) and `cloud-deployment-k8s.md`.
