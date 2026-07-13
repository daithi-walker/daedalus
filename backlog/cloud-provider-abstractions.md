---
title: Extend provider abstraction to cover all cloud-touching axes
state: To Do
repo: daedalus
type: feature
priority: P3
---

## Summary

Daedalus already abstracts Git hosting behind a `GitProvider` ABC (`src/providers/`) with `GitHubProvider` and `ADOProvider` as concrete implementations. The same pattern should cover every other axis where a cloud-specific implementation would otherwise be baked in: agent execution (currently `docker run` hardcoded in `activities.py`), container registry, secrets, and notifications. Without these abstractions the cloud deployment and CI pipeline tickets will produce Azure-specific or Docker-specific code that is hard to generalise later.

## Acceptance Criteria

- Four new ABC classes exist in `src/providers/`, each following the same pattern as `GitProvider`:
  - `ClusterProvider` - runs an agent task and returns its stdout. Local implementation wraps `docker run`; k8s implementation creates a Job and polls for completion.
  - `ContainerRegistry` - pushes and returns the pull URL for a tagged image. Implementations: local Docker daemon, any OCI-compatible registry (configured via `REGISTRY` env var).
  - `SecretProvider` - reads a named secret. Implementations: environment variables (default/dev), Kubernetes Secrets, and stubs for cloud-managed stores (AWS SM, GCP SM, Azure KV, HashiCorp Vault).
  - `NotificationProvider` - sends a lifecycle event. Implementations: Slack webhook (existing behaviour), Teams webhook, generic HTTP webhook, no-op.
- `activities.py` uses `ClusterProvider` instead of calling `docker run` directly. The local Docker implementation preserves all existing behaviour - no regression.
- The active provider for each axis is resolved from `platform.yaml` (see ROADMAP P4.5) or environment variables. Concrete classes are not imported directly by workflow or activity code.
- Each provider axis has at least two implementations (local + one cloud-native) with unit tests covering both.
- Existing tests continue to pass with the local/Docker implementation as default.

## Plan

**`ClusterProvider`** is the most important and the right place to start - it's the axis that directly blocks the k8s deployment ticket.

```python
class ClusterProvider(ABC):
    @abstractmethod
    def run_agent(self, task: TaskInput, image: str, workspace: str, env: dict) -> str:
        """Run an agent task and return its stdout."""
```

Local implementation: extract the existing `docker run` logic from `_run_with_heartbeat` in `activities.py` into `DockerClusterProvider`. k8s implementation: `KubernetesClusterProvider` submits a Job via the k8s Python client, polls for completion, retrieves logs from the pod.

**`ContainerRegistry`**:

```python
class ContainerRegistry(ABC):
    @abstractmethod
    def push(self, image: str, tag: str) -> None: ...
    @abstractmethod
    def pull_url(self, image: str, tag: str) -> str: ...
```

Default implementation uses `docker push` with `REGISTRY` env var. No cloud-SDK dependency in the base; authentication is handled by `docker login` before the push (the CI step owns that).

**`SecretProvider`**:

```python
class SecretProvider(ABC):
    @abstractmethod
    def get(self, key: str) -> str: ...
```

`EnvSecretProvider` (default): reads from `os.environ`. `KubernetesSecretProvider`: reads from a mounted Secret volume. Cloud-specific providers (AWS SM, GCP SM, etc.) can be added as thin wrappers without touching core code.

**`NotificationProvider`**: extract the existing Slack webhook call from `activities.py` into `SlackNotificationProvider`. Add `TeamsNotificationProvider` and `WebhookNotificationProvider` (generic HTTP POST). `NullNotificationProvider` for deployments that don't want notifications.

**Platform config** (ROADMAP P4.5): introduce `platform.yaml` or equivalent env var block:

```yaml
cluster:   docker       # docker | kubernetes
registry:  local        # local | oci (uses $REGISTRY)
secrets:   env          # env | kubernetes | vault | aws-sm | gcp-sm | azure-kv
notify:    slack        # slack | teams | webhook | none
git:       github       # github | ado  (already works, just formalise)
```

Provider instances are constructed once at worker startup by a `ProviderFactory` and injected into activities. No `if provider == "azure"` conditionals in workflow or activity logic.

**Do this before** implementing `cloud-deployment-k8s.md` - the k8s Job execution model belongs in `KubernetesClusterProvider`, not scattered through `activities.py`.
