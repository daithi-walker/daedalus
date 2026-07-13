.PHONY: build build-qa server worker run run-ticket backlog review clean logs status steer resume abandon

GOAL ?= "Improve sandbox/target.py: add type hints and docstrings to all functions"

build:
	docker build -t daedalus:latest .

build-qa:
	docker build -f Dockerfile.qa -t daedalus-qa:latest .

server:
	docker compose up -d
	@echo "Temporal UI: http://localhost:8080"
	@echo "Temporal gRPC: localhost:7233"

worker:
	@test -f .env || (echo "Copy .env.example to .env and fill in values" && exit 1)
	@export $$(grep -v '^\s*#' .env | grep -v '^\s*$$' | xargs) && .venv/bin/python3 -m src.worker

run:
	@test -f .env || (echo "Copy .env.example to .env and fill in values" && exit 1)
	@export $$(grep -v '^\s*#' .env | grep -v '^\s*$$' | xargs) && .venv/bin/python3 run_task.py $(GOAL)

# Run a workflow from an ADO ticket file
# Usage: make run-ticket TICKET=123 [REPO_URL=...] [BASE_BRANCH=develop] [AGENT_BRANCH=agent/...] [FORCE=1]
run-ticket:
	@test -f .env || (echo "Copy .env.example to .env and fill in values" && exit 1)
	@test -n "$(TICKET)" || (echo "Usage: make run-ticket TICKET=<id> [REPO_URL=<url>] [BASE_BRANCH=<branch>] [AGENT_BRANCH=<branch>] [FORCE=1]" && exit 1)
	@export $$(grep -v '^\s*#' .env | grep -v '^\s*$$' | xargs) && \
		.venv/bin/python3 run_ticket.py $(TICKET) \
		$$([ -n "$(REPO_URL)" ] && echo "--repo-url $(REPO_URL)") \
		$$([ -n "$(BASE_BRANCH)" ] && echo "--base-branch $(BASE_BRANCH)") \
		$$([ -n "$(AGENT_BRANCH)" ] && echo "--agent-branch $(AGENT_BRANCH)") \
		$$([ -n "$(FORCE)" ] && echo "--force")

# Query the live status of a running workflow
# Usage: make status WF_ID=orchestrator-my-workflow
status:
	@test -n "$(WF_ID)" || (echo "Usage: make status WF_ID=<workflow-id>" && exit 1)
	@export $$(grep -v '^\s*#' .env | grep -v '^\s*$$' | xargs) && .venv/bin/python3 -c "\
import asyncio, json, os; \
from temporalio.client import Client; \
async def q(): \
    c = await Client.connect(os.environ.get('TEMPORAL_ADDRESS','localhost:7233')); \
    s = await c.get_workflow_handle('$(WF_ID)').query('status'); \
    print(json.dumps(s, indent=2)); \
asyncio.run(q())"

# Inject steering guidance into the next agent turn (mid-flight)
# Usage: make steer WF_ID=<id> TEXT="Focus on error handling"
steer:
	@test -n "$(WF_ID)" || (echo "Usage: make steer WF_ID=<id> TEXT='...' " && exit 1)
	@test -n "$(TEXT)"  || (echo "Usage: make steer WF_ID=<id> TEXT='...' " && exit 1)
	@export $$(grep -v '^\s*#' .env | grep -v '^\s*$$' | xargs) && .venv/bin/python3 -c "\
import asyncio, os; \
from temporalio.client import Client; \
async def s(): \
    c = await Client.connect(os.environ.get('TEMPORAL_ADDRESS','localhost:7233')); \
    await c.get_workflow_handle('$(WF_ID)').signal('steer', '$(TEXT)'); \
    print('Steering injected.'); \
asyncio.run(s())"

# Resume a HITL-paused workflow
# Usage: make resume WF_ID=<id>
resume:
	@test -n "$(WF_ID)" || (echo "Usage: make resume WF_ID=<id>" && exit 1)
	@export $$(grep -v '^\s*#' .env | grep -v '^\s*$$' | xargs) && .venv/bin/python3 -c "\
import asyncio, os; \
from temporalio.client import Client; \
async def s(): \
    c = await Client.connect(os.environ.get('TEMPORAL_ADDRESS','localhost:7233')); \
    await c.get_workflow_handle('$(WF_ID)').signal('resume', 'resume'); \
    print('Workflow resumed.'); \
asyncio.run(s())"

# Abandon a HITL-paused workflow
# Usage: make abandon WF_ID=<id>
abandon:
	@test -n "$(WF_ID)" || (echo "Usage: make abandon WF_ID=<id>" && exit 1)
	@export $$(grep -v '^\s*#' .env | grep -v '^\s*$$' | xargs) && .venv/bin/python3 -c "\
import asyncio, os; \
from temporalio.client import Client; \
async def s(): \
    c = await Client.connect(os.environ.get('TEMPORAL_ADDRESS','localhost:7233')); \
    await c.get_workflow_handle('$(WF_ID)').signal('resume', 'abandon'); \
    print('Workflow abandoned.'); \
asyncio.run(s())"

# Run a backlog ticket directly from the backlog/ directory
# Usage: make backlog ITEM=self-repair-loop [REPO_URL=...] [BASE_BRANCH=develop] [FORCE=1]
backlog:
	@test -f .env || (echo "Copy .env.example to .env and fill in values" && exit 1)
	@test -n "$(ITEM)" || (echo "Usage: make backlog ITEM=<slug>  (e.g. self-repair-loop)" && exit 1)
	@test -f backlog/$(ITEM).md || (echo "No backlog/$(ITEM).md found. Available:" && ls backlog/*.md | xargs -n1 basename | sed 's/\.md//' && exit 1)
	@export $$(grep -v '^\s*#' .env | grep -v '^\s*$$' | xargs) && \
		.venv/bin/python3 run_ticket.py backlog/$(ITEM).md \
		$$([ -n "$(REPO_URL)" ] && echo "--repo-url $(REPO_URL)") \
		$$([ -n "$(BASE_BRANCH)" ] && echo "--base-branch $(BASE_BRANCH)") \
		$$([ -n "$(AGENT_BRANCH)" ] && echo "--agent-branch $(AGENT_BRANCH)") \
		$$([ -n "$(FORCE)" ] && echo "--force")

# Review a GitHub PR using the pr_reviewer agent
# Usage: make review PR=42 [REPO=owner/repo]
review:
	@test -f .env || (echo "Copy .env.example to .env and fill in values" && exit 1)
	@test -n "$(PR)" || (echo "Usage: make review PR=<number or URL> [REPO=owner/repo]" && exit 1)
	@export $$(grep -v '^\s*#' .env | grep -v '^\s*$$' | xargs) && \
		.venv/bin/python3 run_pr_review.py $(PR) $(REPO)

logs:
	docker compose logs -f temporal

clean:
	docker compose down -v
	find /tmp -maxdepth 1 -name "agent-*" -type d -exec rm -rf {} + 2>/dev/null || true
