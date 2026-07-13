---
title: Deploy Daedalus to Kubernetes (Temporal Cloud + k8s workers)
state: To Do
repo: daedalus
type: feature
priority: P5
---

## Summary

Daedalus currently runs as a local process: Temporal server in docker-compose, worker and agent containers on a developer's laptop. This is fine for development but not viable for team use - workflows stall when the laptop closes, there is no HA, and there is no way for multiple team members to share a single deployment. This ticket tracks the full cloud deployment path: Temporal Cloud for the server, Kubernetes for the worker, and a decision on how agent containers run inside the cluster.

This consolidates three items from the ROADMAP (P5 - Temporal Cloud, Kubernetes workers, Agent containers in Kubernetes) into a single sequenced backlog ticket. The deployment is intentionally cloud-agnostic - the manifests should work against any conformant Kubernetes cluster (EKS, GKE, AKS, or self-hosted). Prerequisite: `container-registry-publishing.md` must be complete so images are available to the cluster.

## Acceptance Criteria

- Temporal server is replaced by a Temporal Cloud namespace. Worker connects via mTLS. No self-hosted Temporal server required for production runs.
- A Kubernetes deployment manifest (or Helm chart) exists for the Daedalus worker. The manifest includes resource limits, a liveness probe wired to the health endpoint (see ROADMAP P4), and scales worker replicas via HPA based on Temporal task queue depth.
- Agent containers run in a k8s-native way - see Plan below for the three options. The chosen approach is documented with reasoning.
- All credentials (`ANTHROPIC_API_KEY`, Git provider tokens, Temporal mTLS certs) are injected via Kubernetes Secrets - no provider-specific secret managers referenced in the manifests.
- The image pull source is configured via a variable (`REGISTRY`) so the same manifests work against any registry.
- A `README.md` section documents how to deploy, configure, and scale the worker on any Kubernetes cluster.
- Local docker-compose development path continues to work unchanged.

## Plan

### Sequence

1. **Temporal Cloud first** - switch the worker's connection config to point at a Temporal Cloud namespace. Worker code is unchanged; only connection config differs (`TEMPORAL_HOST`, `TEMPORAL_NAMESPACE`, mTLS certs). Validate locally before touching k8s.

2. **Container registry prerequisite** - ensure `container-registry-publishing.md` is complete so the worker image is pullable by the cluster.

3. **Worker Deployment manifest** - write a cloud-agnostic `k8s/worker-deployment.yaml`. Image pull uses `$REGISTRY/daedalus:latest`. Secrets mounted from a `daedalus-secrets` Secret object - operators populate this however their platform manages secrets (kubectl, external-secrets-operator, Vault, etc.).

4. **Agent execution model decision** - the critical architectural choice for k8s:

   | Option | How | Tradeoff |
   |---|---|---|
   | **Docker socket mount** | Mount host Docker socket into worker pod | Simple, works today, but grants root-equivalent access - security concern |
   | **Kubernetes Jobs** | Worker creates a k8s Job per agent task via the k8s API | Clean, native, no privileged access - requires `activities.py` changes to replace `docker run` with job creation |
   | **Direct Claude API** | Remove Docker layer; call Claude API directly from the worker | Simplest for basic use cases, but loses per-agent tool restriction and workspace isolation |

   Recommended starting point: Kubernetes Jobs. Each agent task becomes a Job spec using the `daedalus:latest` image, injected env vars, and a git volume mount. The worker submits the Job and polls for completion. This is the most idiomatic k8s approach and avoids the Docker socket security issue.

5. **HPA** - autoscale worker replicas based on Temporal task queue backlog depth. Requires a custom metrics adapter or Temporal Cloud's built-in metrics endpoint.

### Dependencies

- `container-registry-publishing.md` - images must be in a registry the cluster can pull from
- ROADMAP P4 worker health endpoint - needed for the liveness probe
- A Kubernetes cluster (provider is the operator's choice - EKS, GKE, AKS, or self-hosted)
- Temporal Cloud account and namespace (check pricing; free tier covers low-volume usage)
