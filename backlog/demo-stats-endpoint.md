---
title: Add /stats endpoint returning total, valid, and invalid validation counts
state: To Do
repo: agent-webapp-demo
type: feature
priority: P2
---

## Summary

There is no way to see aggregate validation counts at a glance. The `/history` endpoint returns raw records but requires the caller to count them manually. Add a `/stats` endpoint that returns a summary of all validations since the server started.

## Acceptance Criteria

- `GET /stats` returns a JSON object with three integer fields: `total`, `valid`, and `invalid`
- `total` equals `valid + invalid`
- Counts reflect all `/validate` calls made since the server started (uses the existing in-memory `_history` deque)
- The endpoint is covered by at least three tests: empty state, after valid submissions, after mixed valid and invalid submissions
- All existing tests continue to pass
