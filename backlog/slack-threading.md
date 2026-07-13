---
title: Slack threading
state: To Do
repo: daedalus
priority: P3
---

## Summary

Each workflow lifecycle event (started, task completed, phase changed, HITL, done) posts a separate top-level Slack message. A single workflow run with 6 tasks and a HITL pause produces 10+ top-level messages, flooding the channel.

Replace the incoming webhook with a bot token so the first event per workflow creates a thread and all subsequent events for the same workflow are replies. Thread timestamps are stored in workflow state and passed through to each `publish_event` call.

## Acceptance Criteria

- When `SLACK_BOT_TOKEN` is set, events use `chat.postMessage` instead of the incoming webhook.
- The `workflow_started` event creates a new message and returns its `ts` (thread timestamp).
- All subsequent events for the same workflow are posted as replies to that `ts` using `thread_ts`.
- When `SLACK_WEBHOOK_URL` is still set (and no bot token), the existing behaviour is unchanged.
- The `ts` is stored in `OrchestratorWorkflow` state and passed to every `publish_event` activity call.
- `publish_event` accepts an optional `thread_ts` parameter in the event dict.
- `.env.example` documents `SLACK_BOT_TOKEN` with a note about required OAuth scopes (`chat:write`).
- If `chat.postMessage` fails (e.g. invalid token), the error is logged as a warning and the workflow continues - events must never block business logic.

## Plan

- Add `SLACK_BOT_TOKEN` env var to `activities.py`.
- Add `_post_slack_threaded(event_type, event, thread_ts)` that calls `chat.postMessage` with `thread_ts` when provided.
- In `publish_event`, detect which mode to use (bot token vs webhook) and call the appropriate function.
- Update the `publish_event` activity signature to accept `thread_ts: str = ""` in the event dict.
- In `OrchestratorWorkflow`, capture the `ts` returned by the `workflow_started` event and pass it to all subsequent event publishes.
- Update `.env.example`.
