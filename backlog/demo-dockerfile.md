---
title: Add Dockerfile and docker-compose.yml for local development
state: To Do
repo: agent-webapp-demo
type: feature
priority: P3
---

## Summary

The application has no container configuration. Running it locally requires a manual Python environment setup. Add a `Dockerfile` and `docker-compose.yml` so the app can be started with a single command, and update the README with instructions.

## Acceptance Criteria

- A `Dockerfile` is added that builds a production-ready image using `python:3.11-slim` as the base
- The image installs only the packages in `requirements.txt` and runs the Flask app on port 5000
- A `docker-compose.yml` is added that builds and starts the app, mapping host port 5000 to container port 5000
- `docker compose up` starts the application with no additional configuration
- The README is updated with a "Running with Docker" section showing the `docker compose up` command
- The `.dockerignore` excludes `__pycache__`, `*.pyc`, and any virtual environment directories
- All existing tests continue to pass
