from dataclasses import dataclass, field
from enum import Enum


class AgentType(str, Enum):
    planner     = "planner"
    implementer = "implementer"
    reviewer    = "reviewer"
    security    = "security"
    architect   = "architect"
    qa          = "qa"
    changelog   = "changelog"
    pr_author   = "pr_author"
    pr_reviewer     = "pr_reviewer"
    pr_reviewer_ado = "pr_reviewer_ado"


@dataclass
class ProbeResult:
    passed: int
    failed: int
    failing_tests: list[str]
    timed_out: bool = False


@dataclass
class TaskInput:
    task_id: str
    prompt: str
    # str (not AgentType) so Temporal's JSON deserializer doesn't iterate the enum value as chars
    agent_type: str = AgentType.implementer
    repo_path: str = ""
    base_commit: str = ""
    parent_context: str = ""
    workspace_files: dict[str, str] = field(default_factory=dict)
    # Local path (or future GCS URI) to standards directory; resolved at execution time
    standards_dir: str = ""
    # Ticket reference appended to every commit message, e.g. "PROJ-123"
    ticket_id: str = ""
    # Extra patterns written to .git/info/exclude in the worktree before the agent runs
    git_exclude: list[str] = field(default_factory=list)


@dataclass
class TaskResult:
    task_id: str
    output: str
    commit_sha: str = ""
    files_changed: list[str] = field(default_factory=list)
    pr_description: str = ""
    success: bool = True


@dataclass
class ReviewResult:
    verdict: str              # "pass" | "advisory" | "block"
    findings: list[dict]
    summary: str
    raw: str = ""             # original output for debugging


@dataclass
class OrchestratorInput:
    goal: str
    repo_path: str = ""
    # Local path (or future GCS URI) to a directory of *.md standards files.
    # Activities read from this path at execution time - never embedded in history.
    standards_dir: str = ""
    # Fallback seed files when not using a git repo
    workspace_files: dict[str, str] = field(default_factory=dict)
    # Whether to run the changelog agent (set False for repos with no existing CHANGELOG.md)
    changelog: bool = True
    # Ticket reference appended to every commit message and PR title, e.g. "PROJ-123"
    ticket_id: str = ""
    remote_url: str = ""
    agent_branch: str = ""
    base_branch: str = "main"
    # Per-repo patterns written to .git/info/exclude in every agent worktree
    git_exclude: list[str] = field(default_factory=list)
    probe_tests: bool = True


@dataclass
class PRReviewInput:
    pr: str             # PR number or full URL
    repo: str = ""      # owner/repo slug for GitHub (optional; gh auto-detects from remote)
    remote_url: str = ""  # Full remote URL - used to detect provider and clone for ADO
    repo_path: str = ""   # Local clone path (populated by run_pr_review.py for ADO)
