"""Submit an OrchestratorWorkflow against a git repo and stream progress until it completes."""

import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from temporalio.client import Client

from src.workflows import OrchestratorWorkflow
from src.models import OrchestratorInput

TASK_QUEUE = "agent-tasks"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower())[:40].strip("-")


def _git(cwd: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd)] + args, capture_output=True, text=True, check=True)


def _init_repo(seed_dir: Path) -> tuple[Path, str]:
    """Create an isolated git repo in /tmp seeded with files from seed_dir."""
    repo = Path(tempfile.mkdtemp(prefix="agent-repo-"))
    _git(repo, ["init"])
    _git(repo, ["config", "user.email", "agent@daedalus"])
    _git(repo, ["config", "user.name", "Temporal Agent"])

    for src in seed_dir.rglob("*"):
        if src.is_file() and ".git" not in src.parts:
            dest = repo / src.relative_to(seed_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())

    _git(repo, ["add", "-A"])
    _git(repo, ["commit", "-m", "initial: seed files", "--author=Human <human@daedalus>"])
    seed_sha = _git(repo, ["rev-parse", "HEAD"]).stdout.strip()
    return repo, seed_sha


def _clone_repo(remote_url: str, agent_branch: str = "agent/improvements", base_branch: str = "main") -> tuple[Path, str]:
    """Shallow-clone a remote repo into /tmp, check out base_branch, and create agent_branch from it."""
    repo = Path(tempfile.mkdtemp(prefix="agent-repo-"))
    subprocess.run(["git", "clone", "--depth=1", "--branch", base_branch, remote_url, str(repo)], check=True)
    _git(repo, ["config", "user.email", "agent@daedalus"])
    _git(repo, ["config", "user.name", "Temporal Agent"])
    seed_sha = _git(repo, ["rev-parse", "HEAD"]).stdout.strip()
    _git(repo, ["checkout", "-b", agent_branch])
    return repo, seed_sha


def _show_diff(repo: Path, base_ref: str = "HEAD~1") -> str:
    r = subprocess.run(
        ["git", "-C", str(repo), "log", "--oneline", base_ref + "..HEAD"],
        capture_output=True, text=True,
    )
    commits = r.stdout.strip()

    r2 = subprocess.run(
        ["git", "-C", str(repo), "diff", base_ref, "HEAD"],
        capture_output=True, text=True,
    )
    return f"Commits:\n{commits}\n\nDiff:\n{r2.stdout}"


async def main(goal: str, repo_path: str = "", remote_url: str = "",
               base_branch: str = "", agent_branch: str = "",
               changelog: bool = True, ticket_id: str = "",
               git_exclude: list[str] | None = None) -> None:
    address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    client = await Client.connect(address)

    remote_url   = remote_url   or os.environ.get("TARGET_REPO_URL", "")
    base_branch  = base_branch  or os.environ.get("DAEDALUS_BASE_BRANCH", "main")
    agent_branch = agent_branch or os.environ.get("DAEDALUS_AGENT_BRANCH", "") or f"agent/run-{int(__import__('time').time())}"

    seed_sha = ""
    if not repo_path:
        if remote_url:
            print(f"Cloning {remote_url}")
            repo, seed_sha = _clone_repo(remote_url, agent_branch, base_branch)
            repo_path = str(repo)
            print(f"Repo: {repo_path}")
        else:
            seed_dir = Path(__file__).parent / "sandbox"
            if seed_dir.exists():
                print(f"Initializing isolated repo from {seed_dir}/")
                repo, seed_sha = _init_repo(seed_dir)
                repo_path = str(repo)
                print(f"Repo: {repo_path}")
            else:
                repo = None

    workflow_id = f"orchestrator-{_slug(goal)}-{int(time.time())}"

    # Pass directory path - activities resolve the files at execution time
    standards_dir = Path(__file__).parent / "agents" / "standards"

    handle = await client.start_workflow(
        OrchestratorWorkflow.run,
        OrchestratorInput(goal=goal, repo_path=repo_path,
                          standards_dir=str(standards_dir) if standards_dir.exists() else "",
                          changelog=changelog, ticket_id=ticket_id,
                          remote_url=remote_url, agent_branch=agent_branch,
                          base_branch=base_branch,
                          git_exclude=git_exclude or []),
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )

    ui_port = os.environ.get("TEMPORAL_UI_PORT", "8233")
    print(f"Started workflow: {handle.id}")
    print(f"UI:              http://localhost:{ui_port}/namespaces/default/workflows/{handle.id}")
    print("Waiting for result...\n")

    raw = await handle.result()

    try:
        result = json.loads(raw)
        summary = result.get("summary", raw)
        final_sha = result.get("final_commit", "")
    except (json.JSONDecodeError, TypeError):
        summary = raw
        final_sha = ""

    print("=" * 60)
    print(summary)
    print("=" * 60)

    if repo_path and final_sha:
        repo = Path(repo_path)
        subprocess.run(["git", "-C", str(repo), "merge", "--ff-only", final_sha],
                       capture_output=True)
        print(f"\nFinal commit: {final_sha[:12]}")
        diff_base = seed_sha or "HEAD~10"
        diff = _show_diff(repo, diff_base)
        print(diff[:4000])

        pr_url = result.get("pr_url", "")
        if pr_url:
            print(f"\nPR: {pr_url}")


if __name__ == "__main__":
    goal = " ".join(sys.argv[1:]).strip()
    if not goal:
        goal = "Improve sandbox/target.py: add type hints and docstrings to all functions"
    asyncio.run(main(goal))
