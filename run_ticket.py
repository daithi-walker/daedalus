"""Load a ticket and submit it as a Daedalus workflow goal.

Usage:
    python run_ticket.py 1500                          # ADO ticket by ID
    python run_ticket.py backlog/self-repair-loop.md  # direct backlog path
    python run_ticket.py 1500 --base-branch main --agent-branch agent/1500-refactor
    python run_ticket.py 1500 --repo-url https://...  # one-off URL override

Branch resolution order (highest to lowest priority):
    CLI --base-branch / --agent-branch
    repos.yaml entry for the ticket's `repo:` alias
    DAEDALUS_BASE_BRANCH / DAEDALUS_AGENT_BRANCH env vars
    Built-in defaults (develop / agent/<ticket-id>-<timestamp>)

Ticket files: direct .md path, DAEDALUS_TICKETS_DIR env var, or --tickets-dir argument.
Repo lookup:  repos.yaml (gitignored) in this directory.
"""

import asyncio
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

from src.ticket import find_ticket, load_ticket, check_quality, build_goal

_REPOS_FILE = Path(__file__).parent / "repos.yaml"

_DEFAULT_BASE_BRANCH  = "develop"
_DEFAULT_AGENT_BRANCH = ""


@dataclass
class RepoConfig:
    url: str
    base_branch: str
    agent_branch: str
    changelog: bool = True
    git_exclude: list[str] = field(default_factory=list)


def _load_repos() -> dict:
    if _HAS_YAML and _REPOS_FILE.exists():
        with _REPOS_FILE.open() as f:
            return _yaml.safe_load(f) or {}
    return {}


def _resolve_repo(
    ticket_repo: str,
    cli_url: str,
    cli_base: str,
    cli_agent: str,
) -> RepoConfig:
    """Resolve repo URL and branch config.

    Priority per field:
      url:          cli_url > repos.yaml[ticket_repo].url > ticket_repo (as raw URL) > TARGET_REPO_URL env
      base_branch:  cli_base > repos.yaml[ticket_repo].base_branch > DAEDALUS_BASE_BRANCH env > 'develop'
      agent_branch: cli_agent > repos.yaml[ticket_repo].agent_branch > DAEDALUS_AGENT_BRANCH env > 'agent/<ticket-id>-<timestamp>'
    """
    repos = _load_repos()
    entry = repos.get(ticket_repo, {}) if ticket_repo else {}

    # Plain string entries are treated as URL-only
    if isinstance(entry, str):
        entry = {"url": entry}

    url = (
        cli_url
        or entry.get("url", "")
        or (ticket_repo if ticket_repo and "://" in ticket_repo else "")
        or os.environ.get("TARGET_REPO_URL", "")
    )
    base_branch = (
        cli_base
        or entry.get("base_branch", "")
        or os.environ.get("DAEDALUS_BASE_BRANCH", "")
        or _DEFAULT_BASE_BRANCH
    )
    agent_branch = (
        cli_agent
        or entry.get("agent_branch", "")
        or os.environ.get("DAEDALUS_AGENT_BRANCH", "")
        or _DEFAULT_AGENT_BRANCH
    )
    # repos.yaml: changelog: false disables the changelog agent for this repo
    changelog = entry.get("changelog", True)
    git_exclude = entry.get("git_exclude", [])

    return RepoConfig(url=url, base_branch=base_branch, agent_branch=agent_branch,
                      changelog=changelog, git_exclude=git_exclude)


# Import run_task main so we don't duplicate the workflow submission logic
from run_task import main as _run_workflow  # noqa: E402  (intentional deferred import)


def _tickets_dir_or_none() -> Path | None:
    d = os.environ.get("DAEDALUS_TICKETS_DIR", "")
    if not d:
        return None
    p = Path(d).expanduser()
    if not p.is_dir():
        raise SystemExit(f"DAEDALUS_TICKETS_DIR={d!r} does not exist or is not a directory.")
    return p


def _parse_args():
    import argparse

    parser = argparse.ArgumentParser(description="Run a Daedalus workflow from a ticket file.")
    parser.add_argument("ticket_id", help="ADO ticket ID (e.g. 1500) or direct path to a .md file (e.g. backlog/self-repair-loop.md)")
    parser.add_argument(
        "--repo-url",
        default="",
        help="Remote git URL (overrides repos.yaml and TARGET_REPO_URL)",
    )
    parser.add_argument(
        "--base-branch",
        default="",
        help="PR target branch (overrides repos.yaml and DAEDALUS_BASE_BRANCH)",
    )
    parser.add_argument(
        "--agent-branch",
        default="",
        help="Agent working branch name (overrides repos.yaml and DAEDALUS_AGENT_BRANCH)",
    )
    parser.add_argument(
        "--tickets-dir",
        default="",
        help="Directory containing ticket markdown files (defaults to DAEDALUS_TICKETS_DIR env var)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip quality gate and run even if ticket has errors",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    # Direct .md path bypasses DAEDALUS_TICKETS_DIR entirely
    is_direct_path = args.ticket_id.endswith(".md") or Path(args.ticket_id).exists()
    if args.tickets_dir:
        tickets_dir: Path | None = Path(args.tickets_dir).expanduser()
    elif is_direct_path:
        tickets_dir = None
    else:
        tickets_dir = _tickets_dir_or_none()
        if tickets_dir is None:
            raise SystemExit(
                "DAEDALUS_TICKETS_DIR is not set - either set it, use --tickets-dir, "
                "or pass a direct path to a .md file (e.g. backlog/self-repair-loop.md)."
            )

    try:
        ticket_path = find_ticket(tickets_dir, args.ticket_id)
    except FileNotFoundError as e:
        raise SystemExit(str(e))

    ticket = load_ticket(ticket_path)
    quality = check_quality(ticket)

    ref = f" (ADO #{ticket.ado_id})" if ticket.ado_id else ""
    print(f"Ticket: {ticket.title}{ref}")
    print(f"State:  {ticket.state}")
    print(f"File:   {ticket_path.name}")
    print()

    if quality.errors or quality.warnings:
        print(quality.report())
        print()

    if not quality.passed:
        if args.force:
            print("Quality gate failed - running anyway (--force).")
        else:
            print("Quality gate failed - fix the issues above or use --force to override.")
            sys.exit(1)

    goal = build_goal(ticket)
    print("Goal:")
    print("-" * 60)
    print(goal)
    print("-" * 60)
    print()

    repo = _resolve_repo(ticket.repo, args.repo_url, args.base_branch, args.agent_branch)

    if not repo.agent_branch:
        import time
        ticket_slug = ticket.ado_id or ticket_path.stem
        repo.agent_branch = f"agent/{ticket_slug}-{int(time.time())}"

    if repo.url:
        print(f"Repo:         {ticket.repo or repo.url[:60]}")
    else:
        print("Repo:         (none - sandbox mode)")
    print(f"Base branch:  {repo.base_branch}")
    print(f"Agent branch: {repo.agent_branch}")
    print(f"Changelog:    {'enabled' if repo.changelog else 'disabled'}")
    print()

    ticket_ref = f"AB#{ticket.ado_id}" if ticket.ado_id else ticket.path.stem
    asyncio.run(_run_workflow(
        goal=goal,
        remote_url=repo.url,
        base_branch=repo.base_branch,
        agent_branch=repo.agent_branch,
        changelog=repo.changelog,
        ticket_id=ticket_ref,
        git_exclude=repo.git_exclude,
    ))


if __name__ == "__main__":
    main()
