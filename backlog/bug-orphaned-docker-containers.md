---
title: Kill Docker container when Temporal activity times out
state: Done
repo: daedalus
type: bug
priority: P1
---

## Summary

When Temporal fires a `StartToClose` timeout on a `run_claude_task` activity, it cancels the activity from Temporal's perspective and schedules a retry. The Python activity worker receives the cancellation, but the Docker subprocess (`docker run ...`) is not killed. The container keeps running - consuming CPU and memory - while a new activity attempt starts a fresh container. Over multiple timeouts (e.g. repeated laptop sleep cycles) orphaned containers accumulate indefinitely.

Observed: container `c8df78d7358a` ran for 6+ hours after its activity was timed out and retried.

## Acceptance Criteria

- When a `run_claude_task` activity is cancelled (via Temporal timeout or explicit cancellation), the Docker container started by that activity is killed before the activity exits.
- If the container has already exited, the kill is a no-op (no error).
- The fix does not interfere with `asyncio.shield` in `_run_with_heartbeat` - the shield must remain to prevent heartbeat pipe corruption on 30s ticks.
- After the fix, running `docker ps` shows no `daedalus:latest` containers that outlive their parent activity.

## Plan

- In `_run_with_heartbeat` in `src/activities.py`, capture the container ID from the `docker run` output (use `--cidfile` or parse from `docker run --rm` with `docker ps`).
- Wrap the subprocess wait in a `try/finally` that runs `docker kill <container-id>` if the process is still running when the coroutine is cancelled.
- Alternatively, replace `asyncio.create_subprocess_exec` with a context manager that guarantees `docker kill` on exit regardless of cancellation reason.
