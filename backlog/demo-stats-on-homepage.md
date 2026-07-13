---
title: Display live validation stats on the homepage
state: To Do
repo: agent-webapp-demo
type: feature
priority: P2
---

## Summary

The `/stats` endpoint exists but its data is not surfaced in the UI. Add a small stats panel to the homepage that shows total, valid, and invalid counts, and updates automatically after each validation attempt.

## Acceptance Criteria

- The homepage displays a stats panel showing Total, Valid, and Invalid counts fetched from `GET /stats`
- The panel updates immediately after each successful or failed `/validate` call without a full page reload
- The panel shows a neutral state (e.g. "No validations yet") when all counts are zero
- The stats panel is positioned logically relative to the form - below the result message and above the history table
- All existing tests continue to pass
- No new backend changes are required - this is a frontend-only change consuming the existing `/stats` endpoint
