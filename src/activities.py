import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from temporalio import activity

from .models import AgentType, ProbeResult, TaskInput, TaskResult
from .providers import get_provider

_SLACK_WEBHOOK   = os.environ.get("SLACK_WEBHOOK_URL", "")
_EVENT_WEBHOOK   = os.environ.get("EVENT_WEBHOOK_URL", "")
_TEMPORAL_UI     = os.environ.get("TEMPORAL_UI_URL", "http://localhost:8233")

_SLACK_COLORS = {
    "workflow_started":   "#4A90E2",
    "task_completed":     "#36a64f",
    "phase_changed":      "#888888",
    "hitl_required":      "#E6A817",
    "workflow_completed": "#36a64f",
    "workflow_failed":    "#CC0000",
}
_SLACK_ICONS = {
    "workflow_started":   ":rocket:",
    "task_completed":     ":white_check_mark:",
    "phase_changed":      ":arrows_counterclockwise:",
    "hitl_required":      ":hand:",
    "workflow_completed": ":tada:",
    "workflow_failed":    ":x:",
}

CLAUDE_IMAGE    = os.environ.get("CLAUDE_IMAGE",    "daedalus:latest")
CLAUDE_QA_IMAGE = os.environ.get("CLAUDE_QA_IMAGE", "daedalus-qa:latest")

_AGENT_IMAGES: dict[str, str] = {
    AgentType.qa: CLAUDE_QA_IMAGE,
}

_ALLOWED_TOOLS: dict[str, str] = {
    AgentType.planner:     "Read",
    AgentType.implementer: "Read,Write,Edit,MultiEdit,Bash(git rm *)",
    AgentType.reviewer:    "Read",
    AgentType.security:    "Read",
    AgentType.architect:   "Read",
    AgentType.qa:          "Read,Write,Edit,MultiEdit,Bash(pytest *),Bash(python -m pytest *),Bash(uv run *),Bash(pip install *),Bash(pip3 install *),Bash(python -m flask *),Bash(flask *),Bash(curl *),Bash(python *.py *)",
    AgentType.changelog:   "Read,Write,Edit",
    AgentType.pr_author:   "Read,Write",
    AgentType.pr_reviewer:     "Read,Agent,Bash(gh pr diff:*),Bash(gh pr view:*),Bash(gh pr list:*),Bash(gh api:*),Bash(git log:*),Bash(git blame:*),Bash(git rev-parse:*),Bash(sl root:*),Bash(sl paths:*),TodoWrite",
    AgentType.pr_reviewer_ado: "Read,Agent,Bash(az repos pr show:*),Bash(az repos pr list:*),Bash(az rest:*),Bash(git fetch:*),Bash(git diff:*),Bash(git log:*),Bash(git blame:*),Bash(git rev-parse:*),Bash(sed *),TodoWrite",
}
_DEFAULT_TOOLS = "Read,Write,Edit,MultiEdit"

_USE_VERTEX        = os.environ.get("CLAUDE_CODE_USE_VERTEX", "") == "1"
_CLAUDE_MODEL      = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

# Vertex AI
_VERTEX_PROJECT    = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID", "")
_VERTEX_REGION     = os.environ.get("CLOUD_ML_REGION", "global")
_SA_KEY_HOST       = os.environ.get("VERTEX_SA_KEY_PATH",
                         str(Path.home() / ".config/gcloud/application_default_credentials.json"))
_SA_KEY_CONTAINER  = "/run/secrets/vertex-credentials.json"

# Anthropic API
_ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
# ADO PAT for pr_reviewer_ado - host var may be AZURE_DEVOPS_PAT; container expects AZURE_DEVOPS_EXT_PAT
_ADO_PAT = os.environ.get("AZURE_DEVOPS_EXT_PAT", "") or os.environ.get("AZURE_DEVOPS_PAT", "")

# Directory where per-task JSONL traces are written
_LOG_DIR = Path(os.environ.get("DAEDALUS_LOG_DIR", "/tmp/daedalus-logs"))

# Path to the agents/ directory (one level up from src/)
_AGENTS_DIR = Path(__file__).parent.parent / "agents"


_PROBE_TIMEOUT = 110
_RE_PASSED = re.compile(r"(\d+) passed")
_RE_FAILED = re.compile(r"(\d+) failed")


@activity.defn(name="probe_tests")
async def probe_tests(repo_path: str) -> ProbeResult:
    """Run pytest read-only in the repo container and return pass/fail counts."""
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{repo_path}:/workspace",
        "--workdir", "/workspace",
        "--entrypoint", "python3",
        CLAUDE_QA_IMAGE,
        "-m", "pytest", "--tb=no", "-q",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        raw, _ = await asyncio.wait_for(proc.communicate(), timeout=_PROBE_TIMEOUT)
    except asyncio.TimeoutError:
        return ProbeResult(0, 0, [], timed_out=True)

    stdout = raw.decode(errors="replace")
    passed = int(m.group(1)) if (m := _RE_PASSED.search(stdout)) else 0
    failed = int(m.group(1)) if (m := _RE_FAILED.search(stdout)) else 0
    failing_tests = [
        line[len("FAILED "):].strip()
        for line in stdout.splitlines()
        if line.startswith("FAILED ")
    ]
    return ProbeResult(passed, failed, failing_tests)


@activity.defn
async def run_claude_task(input: TaskInput) -> TaskResult:
    logger = activity.logger
    logger.info(f"Starting {input.agent_type} task: {input.task_id}")

    if input.repo_path:
        return await _run_with_git(input, logger)
    else:
        return await _run_ephemeral(input, logger)


# ── git-based handoff ────────────────────────────────────────────────────────

async def _run_with_git(input: TaskInput, logger) -> TaskResult:
    import uuid
    repo     = Path(input.repo_path).resolve()
    _assert_git_root(repo)
    worktree = Path(tempfile.mkdtemp(prefix=f"agent-{input.task_id[:30]}-"))
    # Include a short UUID so retries and replays never collide on the same branch
    run_id   = uuid.uuid4().hex[:8]
    branch   = f"agent/{input.task_id[:50]}-{run_id}"
    base     = input.base_commit or "HEAD"

    try:
        _git(repo, ["worktree", "add", "-b", branch, str(worktree), base])
        _populate_workspace(worktree, input)
        _validate_provider()

        cmd = _build_docker_cmd(worktree, input.prompt, input.agent_type)

        activity.heartbeat(f"running {input.agent_type} for {input.task_id}")
        result = await _run_with_heartbeat(cmd, input.agent_type, input.task_id)

        if result.returncode != 0:
            raise RuntimeError(f"Claude exited {result.returncode}: {result.stderr[:400]}")

        commit_sha, files_changed = _git_commit(worktree, input.agent_type, input.prompt, input.ticket_id)

        pr_desc_path = worktree / "PR_DESCRIPTION.md"
        pr_description = pr_desc_path.read_text() if (input.agent_type == AgentType.pr_author and pr_desc_path.exists()) else ""

        logger.info(f"Task {input.task_id} committed {len(files_changed)} file(s): {commit_sha[:8] if commit_sha else 'no changes'}")
        return TaskResult(
            task_id=input.task_id,
            output=result.stdout.strip(),
            commit_sha=commit_sha,
            files_changed=files_changed,
            pr_description=pr_description,
            success=True,
        )

    except Exception as exc:
        logger.exception(f"Task {input.task_id} failed: {exc}")
        return TaskResult(task_id=input.task_id, output=f"FAILED: {exc}", success=False)

    finally:
        _git(repo, ["worktree", "remove", "--force", str(worktree)], check=False)
        _git(repo, ["branch", "-D", branch], check=False)   # clean up the per-run branch
        shutil.rmtree(worktree, ignore_errors=True)


def _git_commit(worktree: Path, agent_type: str, prompt: str, ticket_id: str = "") -> tuple[str, list[str]]:
    _git(worktree, ["add", "-A"])
    # Exclude Daedalus workspace scaffolding - not part of the target repo's code.
    # For files already tracked in HEAD (e.g. CLAUDE.md in the daedalus repo itself),
    # git rm --cached would stage a *deletion*. Use restore --staged to simply unstage
    # the change; fall back to rm --cached only for new untracked files.
    for excl in ["CLAUDE.md", "_context.md", "PR_DESCRIPTION.md",
                 "standards", "__pycache__", ".pytest_cache"]:
        r = _git(worktree, ["restore", "--staged", "--", excl], check=False)
        if r.returncode != 0:
            _git(worktree, ["rm", "-r", "--cached", "--ignore-unmatch", "--", excl], check=False)
    status = subprocess.run(
        ["git", "-C", str(worktree), "diff", "--cached", "--name-only"],
        capture_output=True, text=True,
    )
    files_changed = [f for f in status.stdout.strip().splitlines() if f]
    if not files_changed:
        return "", []

    # Subject: "agent-type: first sentence of prompt (ticket_id)"
    # Trailers: Authored-By-Agent and Intent-Ref for audit trail (SDLC §8)
    first_line = prompt.split("\n")[0].strip().rstrip(".")
    inline_ref = f" ({ticket_id})" if ticket_id else ""
    subject = f"{agent_type}: {first_line}"[:72 - len(inline_ref)] + inline_ref
    trailers = [f"Authored-By-Agent: daedalus/{agent_type}"]
    if ticket_id:
        trailers.append(f"Intent-Ref: {ticket_id}")
    msg = subject + "\n\n" + "\n".join(trailers)
    r = _git(worktree, ["commit", "-m", msg, "--author=Claude Agent <agent@daedalus>"], check=False)
    if r.returncode != 0:
        return "", []

    sha = _git(worktree, ["rev-parse", "HEAD"]).stdout.strip()
    return sha, files_changed


# ── ephemeral fallback ───────────────────────────────────────────────────────

async def _run_ephemeral(input: TaskInput, logger) -> TaskResult:
    workspace = Path(tempfile.mkdtemp(prefix=f"agent-{input.task_id[:40]}-"))
    try:
        _populate_workspace(workspace, input)
        _validate_provider()

        cmd = _build_docker_cmd(workspace, input.prompt, input.agent_type)

        activity.heartbeat(f"running {input.agent_type} for {input.task_id}")
        result = await _run_with_heartbeat(cmd, input.agent_type, input.task_id)

        if result.returncode != 0:
            raise RuntimeError(f"Claude exited {result.returncode}: {result.stderr[:400]}")

        known = set(input.workspace_files.keys()) | {"CLAUDE.md", "_context.md"}
        files_changed = [
            str(p.relative_to(workspace))
            for p in workspace.rglob("*")
            if p.is_file() and str(p.relative_to(workspace)) not in known
        ]

        return TaskResult(
            task_id=input.task_id,
            output=result.stdout.strip(),
            files_changed=files_changed,
            success=True,
        )

    except Exception as exc:
        logger.exception(f"Task {input.task_id} failed: {exc}")
        return TaskResult(task_id=input.task_id, output=f"FAILED: {exc}", success=False)

    finally:
        shutil.rmtree(workspace, ignore_errors=True)


# ── helpers ───────────────────────────────────────────────────────────────────

# Always excluded - daedalus internal scaffolding that must never land in target repos
_ALWAYS_EXCLUDE = ["_context.md", "PR_DESCRIPTION.md"]


def _write_git_exclude(workspace: Path, extra: list[str]) -> None:
    """Append daedalus exclusions to the worktree's local .git/info/exclude."""
    git_marker = workspace / ".git"
    if git_marker.is_file():
        gitdir = Path(git_marker.read_text().split("gitdir:", 1)[1].strip())
    elif git_marker.is_dir():
        gitdir = git_marker
    else:
        return
    exclude = gitdir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text() if exclude.exists() else ""
    patterns = _ALWAYS_EXCLUDE + [p for p in extra if p not in _ALWAYS_EXCLUDE]
    block = "\n# daedalus\n" + "\n".join(patterns) + "\n"
    if "# daedalus" not in existing:
        exclude.write_text(existing + block)


def _populate_workspace(workspace: Path, input: TaskInput) -> None:
    _write_git_exclude(workspace, input.git_exclude)
    # Agent-specific CLAUDE.md takes priority over the generic one
    agent_md = _AGENTS_DIR / f"{input.agent_type}.md"
    fallback_md = _AGENTS_DIR / "default.md"
    md_source = agent_md if agent_md.exists() else fallback_md
    if md_source.exists():
        (workspace / "CLAUDE.md").write_text(md_source.read_text())

    # Resolve standards from directory reference (late-binding - not embedded in history)
    standards_dir = Path(input.standards_dir) if input.standards_dir else _AGENTS_DIR / "standards"
    if standards_dir.exists():
        dest = workspace / "standards"
        dest.mkdir(exist_ok=True)
        for f in standards_dir.glob("*.md"):
            (dest / f.name).write_text(f.read_text())

    # Any extra inline seed files (rarely used now that standards_dir handles standards)
    for filename, content in input.workspace_files.items():
        path = workspace / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    if input.parent_context:
        (workspace / "_context.md").write_text(input.parent_context)


def _validate_provider() -> None:
    if _USE_VERTEX:
        sa_key = Path(_SA_KEY_HOST)
        if not sa_key.exists():
            raise FileNotFoundError(f"Vertex credentials not found at {_SA_KEY_HOST}")
        if not _VERTEX_PROJECT:
            raise ValueError("ANTHROPIC_VERTEX_PROJECT_ID is required for Vertex AI")
    else:
        if not _ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is required when not using Vertex AI")


def _build_docker_cmd(workspace: Path, prompt: str, agent_type: str) -> list[str]:
    tools = _ALLOWED_TOOLS.get(agent_type, _DEFAULT_TOOLS)
    image = _AGENT_IMAGES.get(agent_type, CLAUDE_IMAGE)

    base = [
        "docker", "run", "--rm",
        "--network", "bridge",
    ]

    if _USE_VERTEX:
        sa_key = Path(_SA_KEY_HOST).resolve()
        base += [
            "-v", f"{sa_key}:{_SA_KEY_CONTAINER}:ro",
            "-e", f"GOOGLE_APPLICATION_CREDENTIALS={_SA_KEY_CONTAINER}",
            "-e", "CLAUDE_CODE_USE_VERTEX=1",
            "-e", f"ANTHROPIC_VERTEX_PROJECT_ID={_VERTEX_PROJECT}",
            "-e", f"CLOUD_ML_REGION={_VERTEX_REGION}",
        ]
    else:
        base += [
            "-e", f"ANTHROPIC_API_KEY={_ANTHROPIC_API_KEY}",
        ]

    if agent_type == AgentType.pr_reviewer and _GITHUB_TOKEN:
        base += ["-e", f"GITHUB_TOKEN={_GITHUB_TOKEN}"]
    if agent_type == AgentType.pr_reviewer_ado and _ADO_PAT:
        base += ["-e", f"AZURE_DEVOPS_EXT_PAT={_ADO_PAT}"]

    return base + [
        "-v", f"{workspace}:/workspace",
        "--workdir", "/workspace",
        "--memory", "512m",
        "--cpus", "1.0",
        image,
        "--model", _CLAUDE_MODEL,
        "--allowedTools", tools,
        "-p", prompt,
        "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions",
    ]


def _kill_container(cid_path: Path) -> None:
    """Kill the Docker container named in cid_path, then remove the file.

    Called from the finally block of _run_with_heartbeat so that a Temporal
    cancellation or timeout never leaves an orphaned container running.
    Safe to call when the container has already exited (docker kill is a no-op).
    """
    try:
        cid = cid_path.read_text().strip()
        if cid:
            subprocess.run(["docker", "kill", cid], capture_output=True)
    except (FileNotFoundError, OSError):
        pass
    finally:
        cid_path.unlink(missing_ok=True)


async def _run_with_heartbeat(
    cmd: list[str], agent_type: str, task_id: str
) -> subprocess.CompletedProcess:
    """Run a Claude agent container, stream its output, and heartbeat Temporal every 30 s.

    Uses --output-format stream-json so every tool call, assistant message, and
    result event is written to a per-task JSONL trace file in _LOG_DIR. Tool calls
    are also logged to the worker log in real time so you can tail the worker
    terminal to follow what the agent is doing.

    The final `result` event contains the text output that becomes TaskResult.output,
    plus token counts and cost which are logged at completion.
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    # Sanitise task_id for use as a filename
    safe_id = task_id.replace("/", "-").replace(":", "-")[:120]
    log_path = _LOG_DIR / f"{safe_id}.jsonl"

    # --cidfile writes the container ID as soon as the container is created,
    # giving us a handle to kill it in the finally block on cancellation.
    # Docker requires the file to not exist before the run starts.
    cid_path = Path(tempfile.gettempdir()) / f"daedalus-{safe_id}.cid"
    cid_path.unlink(missing_ok=True)
    docker_cmd = cmd[:2] + ["--cidfile", str(cid_path)] + cmd[2:]

    proc = await asyncio.create_subprocess_exec(
        *docker_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=1 * 1024 * 1024,  # 1 MB: default 64 KB is too small for large result events
    )

    lines: list[str] = []
    stderr_chunks: list[str] = []

    async def _read_stdout() -> None:
        with log_path.open("w") as lf:
            async for raw in proc.stdout:  # type: ignore[union-attr]
                line = raw.decode().rstrip()
                if not line:
                    continue
                lf.write(line + "\n")
                lf.flush()
                lines.append(line)
                _log_stream_event(line, agent_type)

    async def _read_stderr() -> None:
        async for chunk in proc.stderr:  # type: ignore[union-attr]
            stderr_chunks.append(chunk.decode())

    async def _heartbeat_loop() -> None:
        elapsed = 0
        while True:
            await asyncio.sleep(30)
            elapsed += 30
            activity.heartbeat(f"{agent_type} still running ({elapsed}s) for {task_id}")

    heartbeat = asyncio.ensure_future(_heartbeat_loop())
    try:
        await asyncio.gather(_read_stdout(), _read_stderr())
        await proc.wait()
    finally:
        heartbeat.cancel()
        _kill_container(cid_path)

    output_text, is_error = _extract_stream_result(lines)
    rc = proc.returncode or 0
    if is_error and rc == 0:
        rc = 1
    activity.logger.info(f"Trace written to {log_path}")
    return subprocess.CompletedProcess(cmd, rc, output_text, "".join(stderr_chunks))


def _log_stream_event(line: str, agent_type: str) -> None:
    """Log tool calls and completion stats from a stream-json event line."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return
    etype = event.get("type")
    if etype == "assistant":
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_use":
                tool = block.get("name", "")
                inp = block.get("input", {})
                detail = (
                    inp.get("file_path")
                    or inp.get("command", "")[:80]
                    or inp.get("description", "")[:80]
                    or ""
                )
                activity.logger.info(f"[{agent_type}] {tool}: {detail}")
    elif etype == "result":
        cost = event.get("total_cost_usd", event.get("cost_usd", 0)) or 0
        usage = event.get("usage", {})
        activity.logger.info(
            f"[{agent_type}] done - cost=${cost:.4f} "
            f"in={usage.get('input_tokens', 0)} "
            f"out={usage.get('output_tokens', 0)} "
            f"cache_hit={usage.get('cache_read_input_tokens', 0)}"
        )


def _extract_stream_result(lines: list[str]) -> tuple[str, bool]:
    """Find the final result event and return (text_output, is_error)."""
    for line in reversed(lines):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            return event.get("result", ""), bool(event.get("is_error", False))
    # Fallback: return last non-empty line as plain text
    for line in reversed(lines):
        if line.strip():
            return line.strip(), False
    return "", False


def _assert_git_root(repo: Path) -> None:
    """Fail fast if repo_path is a subdirectory of a larger git repo.

    Pointing Daedalus at a monorepo subdirectory causes git to resolve the parent
    repo, so agent worktrees span the entire monorepo and can overwrite
    unrelated root-level files (e.g. CLAUDE.md).
    """
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"repo_path is not a git repository: {repo}")
    toplevel = Path(result.stdout.strip()).resolve()
    if toplevel != repo:
        raise ValueError(
            f"repo_path must be the git root, not a subdirectory.\n"
            f"  Given:    {repo}\n"
            f"  Git root: {toplevel}\n"
            f"Pass the git root directly, or use repo_subdir for subdirectory isolation."
        )


def _git(cwd: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd)] + args,
        capture_output=True, text=True, check=check,
    )


# ── PR push & creation ────────────────────────────────────────────────────────

@activity.defn
async def push_and_create_pr(repo_path: str, remote_url: str, agent_branch: str, base_branch: str, ticket_id: str, final_sha: str = "", pr_body: str = "") -> str:
    if not remote_url:
        return ""

    # Push the final SHA directly as a refspec so we never need to move a local
    # branch pointer. git branch -f fails when the branch is checked out in the
    # main worktree (exit 128), so we avoid it entirely.
    push_ref = f"{final_sha}:refs/heads/{agent_branch}" if final_sha else agent_branch
    subprocess.run(
        ["git", "-C", repo_path, "push", "origin", push_ref, "--force"],
        capture_output=True, text=True, check=True,
    )

    provider = get_provider(remote_url)
    if provider is None:
        return ""

    heading = next(
        (ln for ln in pr_body.splitlines() if re.match(r'\s{0,3}#{1,6}(?:\s|$)', ln)),
        None,
    )
    title = (re.sub(r'^\s*#+\s*', '', heading).strip() if heading else "") or ticket_id

    url = provider.ensure_pr(agent_branch, base_branch, title, pr_body)
    return url or ""


# ── Event publishing ──────────────────────────────────────────────────────────

@activity.defn
async def publish_event(event: dict) -> None:
    """Post a lifecycle event to Slack and/or a generic webhook. Never raises."""
    event_type = event.get("type", "unknown")

    if _SLACK_WEBHOOK:
        _post_slack(event_type, event)

    if _EVENT_WEBHOOK:
        _post_json(_EVENT_WEBHOOK, event)


def _post_slack(event_type: str, event: dict) -> None:
    color = _SLACK_COLORS.get(event_type, "#888888")
    icon  = _SLACK_ICONS.get(event_type, ":speech_balloon:")
    wf_id = event.get("workflow_id", "")
    title = f"{icon}  {event_type.replace('_', ' ').title()}"

    fields = []
    if event.get("goal"):
        fields.append({"type": "mrkdwn", "text": f"*Goal*\n{event['goal'][:120]}"})
    if event.get("phase"):
        fields.append({"type": "mrkdwn", "text": f"*Phase*\n{event['phase']}"})
    if event.get("task_id"):
        fields.append({"type": "mrkdwn", "text": f"*Task*\n{event['task_id']}"})
    if event.get("files_changed"):
        fields.append({"type": "mrkdwn", "text": f"*Files*\n{', '.join(event['files_changed'][:5])}"})
    if event.get("blocked_reason"):
        fields.append({"type": "mrkdwn", "text": f"*Blocked*\n{event['blocked_reason']}"})
    if event.get("summary"):
        fields.append({"type": "mrkdwn", "text": f"*Summary*\n{str(event['summary'])[:300]}"})
    if wf_id:
        ui_url = f"{_TEMPORAL_UI}/namespaces/default/workflows/{wf_id}"
        fields.append({"type": "mrkdwn", "text": f"*Workflow*\n<{ui_url}|{wf_id[:40]}>"})

    blocks: list[dict] = [{"type": "header", "text": {"type": "plain_text", "text": title, "emoji": True}}]
    if fields:
        blocks.append({"type": "section", "fields": fields[:10]})
    if event.get("pr_url"):
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"<{event['pr_url']}|View Pull Request>"},
        })
    if event_type == "hitl_required":
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn",
                     "text": f"Signal the workflow to proceed:\n```make resume WF_ID={wf_id}```\nor\n```make abandon WF_ID={wf_id}```"},
        })

    payload = {"attachments": [{"color": color, "blocks": blocks}]}
    _post_json(_SLACK_WEBHOOK, payload)


def _post_json(url: str, payload: dict) -> None:
    try:
        body = json.dumps(payload).encode()
        req  = urllib.request.Request(url, data=body,
                                      headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:
        activity.logger.warning(f"Event publish failed ({url[:40]}): {exc}")
