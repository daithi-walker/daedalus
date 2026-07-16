"""Submit a PRReviewWorkflow and stream progress until it completes."""

import asyncio
import os
import subprocess
import tempfile
import time
from pathlib import Path

from temporalio.client import Client

from src.workflows import PRReviewWorkflow
from src.models import PRReviewInput
from src.providers import _detect as detect_provider

TASK_QUEUE = "agent-tasks"


def _clone_for_review(remote_url: str) -> Path:
    """Shallow-clone the default branch into /tmp for ADO pr_reviewer context."""
    repo = Path(tempfile.mkdtemp(prefix="pr-review-"))
    subprocess.run(["git", "clone", "--depth=5", remote_url, str(repo)], check=True,
                   capture_output=True)
    return repo


async def main(pr: str, repo: str = "", remote_url: str = "") -> None:
    address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    client = await Client.connect(address)

    remote_url = remote_url or os.environ.get("TARGET_REPO_URL", "")
    provider = detect_provider(remote_url) if remote_url else "github"

    repo_path = ""
    if provider == "ado" and remote_url:
        print("ADO repo detected - cloning for git context...")
        repo_path = str(_clone_for_review(remote_url))
        print(f"Cloned to: {repo_path}")

    pr_slug = pr.replace("/", "-").replace(":", "-")
    workflow_id = f"pr-review-{pr_slug}-{int(time.time())}"

    handle = await client.start_workflow(
        PRReviewWorkflow.run,
        PRReviewInput(pr=pr, repo=repo, remote_url=remote_url, repo_path=repo_path),
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )

    ui_port = os.environ.get("TEMPORAL_UI_PORT", "8233")
    print(f"Started: {handle.id}")
    print(f"UI:      http://localhost:{ui_port}/namespaces/default/workflows/{handle.id}")
    print("Waiting for result...\n")

    output = await handle.result()
    print(output)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run a PR review workflow.")
    parser.add_argument("pr", help="PR number")
    parser.add_argument("repo", nargs="?", default="", help="owner/repo (GitHub only)")
    parser.add_argument("--repo-url", default="", dest="remote_url",
                        help="Full remote URL (required for ADO; overrides TARGET_REPO_URL)")
    args = parser.parse_args()
    asyncio.run(main(args.pr, args.repo, args.remote_url))
