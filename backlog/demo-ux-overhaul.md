---
title: Improve homepage UX - add description, input guidance, and history auto-load
state: To Do
repo: agent-webapp-demo
type: feature
priority: P2
---

## Summary

The homepage gives no context about what the application does or what constitutes a valid input. A first-time visitor sees a blank form labelled "Value" with no explanation. The history panel is hidden behind a button click, so there is no immediate feedback that the app has been used before.

Improve the UX so the purpose of the app is immediately clear and the form is self-explanatory.

## Acceptance Criteria

- The page has a heading that names the application (e.g. "Positive Integer Validator")
- A short description below the heading explains what the app does in one or two sentences
- The input field has a placeholder and a visible hint explaining that the value must be a positive whole number greater than zero
- The history table loads automatically on page load rather than requiring a button click
- The "Load History" button is removed or replaced with a "Refresh" button alongside the table
- The Valid column in the history table displays "Valid" or "Invalid" instead of "true" or "false"
- All existing tests continue to pass
