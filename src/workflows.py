import json
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from .activities import probe_tests, publish_event, push_and_create_pr, run_claude_task

from .models import AgentType, OrchestratorInput, PRReviewInput, ProbeResult, ReviewResult, TaskInput, TaskResult

_TASK_TIMEOUT     = timedelta(minutes=25)
_ANALYSIS_TIMEOUT = timedelta(minutes=10)
_HITL_TIMEOUT     = timedelta(hours=24)
# Higher attempt count so transient worker restarts don't exhaust the budget.
# 2 was too low: a single bad restart consumed both attempts before a healthy
# worker came up. Terminal phases (changelog, pr_author) retry for up to 1h.
_RETRY            = RetryPolicy(maximum_attempts=5, backoff_coefficient=2.0,
                                initial_interval=timedelta(seconds=10),
                                maximum_interval=timedelta(minutes=2))
_TERMINAL_RETRY   = RetryPolicy(maximum_attempts=10, backoff_coefficient=2.0,
                                initial_interval=timedelta(seconds=10),
                                maximum_interval=timedelta(minutes=5))

_REVIEW_AGENTS = {AgentType.reviewer, AgentType.security, AgentType.architect, AgentType.qa}
_MAX_REVIEW_CYCLES = 2


@workflow.defn
class TaskWorkflow:
    """Single Claude task - thin wrapper kept for backward compatibility."""

    @workflow.run
    async def run(self, input: TaskInput) -> TaskResult:
        return await workflow.execute_activity(
            run_claude_task, input,
            start_to_close_timeout=_TASK_TIMEOUT,
            retry_policy=_RETRY,
        )


@workflow.defn
class PRReviewWorkflow:
    """Run the pr_reviewer agent against a GitHub or ADO PR and return a markdown findings report."""

    @workflow.run
    async def run(self, input: PRReviewInput) -> str:
        from .providers import _detect as detect_provider
        from .providers.ado import ADOProvider

        provider = detect_provider(input.remote_url) if input.remote_url else "github"

        if provider == "ado":
            ado = ADOProvider(input.remote_url)
            prompt = (
                f"Review pull request #{input.pr}.\n\n"
                f"PR_ID={input.pr}\n"
                f"ORG_URL={ado.org_url}\n"
                f"PROJECT={ado.project}\n"
                f"REPOSITORY={ado.repo}\n\n"
                "Follow all steps in your CLAUDE.md instructions precisely. "
                "Output the structured markdown findings report to stdout when done."
            )
            task_input = TaskInput(
                task_id=f"pr-review-{input.pr}",
                agent_type=AgentType.pr_reviewer_ado,
                prompt=prompt,
                repo_path=input.repo_path,
            )
        else:
            repo_clause = f" in {input.repo}" if input.repo else ""
            prompt = (
                f"Review pull request #{input.pr}{repo_clause}.\n\n"
                "Follow all steps in your CLAUDE.md instructions precisely. "
                "Output the structured markdown findings report to stdout when done."
            )
            task_input = TaskInput(
                task_id=f"pr-review-{input.pr}",
                agent_type=AgentType.pr_reviewer,
                prompt=prompt,
            )

        result = await workflow.execute_activity(
            run_claude_task,
            task_input,
            start_to_close_timeout=timedelta(minutes=25),
            retry_policy=RetryPolicy(maximum_attempts=2, backoff_coefficient=2.0,
                                     initial_interval=timedelta(seconds=15)),
        )
        return result.output


@workflow.defn
class OrchestratorWorkflow:
    """
    Multi-agent pipeline:
      Plan → Execute task graph (with review/retry loops) → PR Author → done

    HITL: if review retries are exhausted the workflow pauses and waits for a
    `resume` or `abandon` Signal before continuing.
    """

    def __init__(self) -> None:
        self._phase: str = "starting"
        self._current_task: str = ""
        self._blocked_reason: str = ""
        self._hitl_decision: Optional[str] = None   # set by Signal
        self._current_sha: str = ""
        self._pending_feedback: list[str] = []

    # ── Signals & Queries ────────────────────────────────────────────────────

    @workflow.signal
    def resume(self, decision: str) -> None:
        """Human sends 'resume' or 'abandon' after a HITL pause."""
        self._hitl_decision = decision

    @workflow.signal
    def steer(self, text: str) -> None:
        """Inject guidance; added to the next agent's context."""
        self._pending_feedback.append(text)

    @workflow.query
    def status(self) -> dict:
        return {
            "phase": self._phase,
            "current_task": self._current_task,
            "blocked_reason": self._blocked_reason,
            "current_sha": self._current_sha,
            "pending_feedback": len(self._pending_feedback),
        }

    # ── Main run ─────────────────────────────────────────────────────────────

    @workflow.run
    async def run(self, input: OrchestratorInput) -> str:
        wf_id = workflow.info().workflow_id

        # standards_dir is resolved by activities at execution time - nothing embedded here
        standards_files: dict[str, str] = {}

        await self._emit({"type": "workflow_started", "workflow_id": wf_id,
                          "goal": input.goal})

        try:
            # Probe before Phase 1
            if input.probe_tests and input.repo_path:
                probe = await workflow.execute_activity(
                    probe_tests, input.repo_path,
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            else:
                probe = None

            # Phase 1: Plan
            self._phase = "planning"
            await self._emit({"type": "phase_changed", "workflow_id": wf_id,
                              "phase": "planning"})
            plan = await self._plan(wf_id, input, standards_files, probe=probe)
            tasks = plan.get("tasks", [])
            workflow.logger.info(f"Plan has {len(tasks)} tasks")
            await self._emit({
                "type": "task_completed",
                "workflow_id": wf_id,
                "task_id": "plan",
                "phase": "planning",
                "baseline_tests_passed": probe.passed if probe and not probe.timed_out else 0,
                "baseline_tests_failed": probe.failed if probe and not probe.timed_out else 0,
            })

            # Phase 2: Execute task graph (topological order, review/retry loops)
            self._phase = "executing"
            await self._emit({"type": "phase_changed", "workflow_id": wf_id,
                              "phase": "executing", "task_count": len(tasks)})
            completed: dict[str, TaskResult] = {}

            for task in _topo_sort(tasks):
                self._current_task = task["id"]
                result = await self._execute_task(task, completed, wf_id, input)
                completed[task["id"]] = result
                await self._emit({"type": "task_completed", "workflow_id": wf_id,
                                  "task_id": task["id"],
                                  "files_changed": result.files_changed,
                                  "success": result.success})

            # Phase 3: Changelog + version bump (skipped when input.changelog is False)
            cl_result = None
            if input.changelog:
                self._phase = "changelog"
                self._current_task = "changelog"
                await self._emit({"type": "phase_changed", "workflow_id": wf_id,
                                  "phase": "changelog"})
                cl_result = await self._run_terminal_activity(self._with_feedback(self._task(
                    input, f"{wf_id}--changelog",
                    agent_type=AgentType.changelog,
                    prompt=_changelog_prompt(input.goal, completed),
                )), wf_id, "changelog")
                if cl_result and cl_result.commit_sha:
                    self._current_sha = cl_result.commit_sha

            # Phase 4: PR Author
            self._phase = "authoring"
            self._current_task = "pr_author"
            await self._emit({"type": "phase_changed", "workflow_id": wf_id,
                              "phase": "authoring"})
            pr_result = await self._run_terminal_activity(self._with_feedback(self._task(
                input, f"{wf_id}--pr-author",
                agent_type=AgentType.pr_author,
                prompt=_pr_author_prompt(input.goal, completed, cl_result),
            )), wf_id, "pr_author")

            if pr_result.commit_sha:
                self._current_sha = pr_result.commit_sha

            # Phase 5: Push and create PR
            self._phase = "pushing"
            self._current_task = "push_pr"
            await self._emit({"type": "phase_changed", "workflow_id": wf_id,
                              "phase": "pushing"})
            pr_url = await workflow.execute_activity(
                push_and_create_pr,
                args=[input.repo_path, input.remote_url, input.agent_branch, input.base_branch, input.ticket_id, self._current_sha, pr_result.pr_description],
                start_to_close_timeout=_ANALYSIS_TIMEOUT,
                retry_policy=_TERMINAL_RETRY,
            )

            self._phase = "done"
            result_payload = {
                "summary": pr_result.output,
                "final_commit": self._current_sha,
                "tasks_completed": len(completed),
                "pr_url": pr_url,
            }
            await self._emit({"type": "workflow_completed", "workflow_id": wf_id,
                              "summary": pr_result.output,
                              "final_commit": self._current_sha,
                              "tasks_completed": len(completed)})
            return json.dumps(result_payload)

        except Exception as exc:
            await self._emit({"type": "workflow_failed", "workflow_id": wf_id,
                              "error": str(exc)[:300]})
            raise

    # ── Task execution with review/retry loop ────────────────────────────────

    async def _execute_task(
        self,
        task: dict,
        completed: dict[str, TaskResult],
        wf_id: str,
        input: OrchestratorInput,
    ) -> TaskResult:
        try:
            agent_type = AgentType(task.get("agent", "implementer"))
        except ValueError:
            agent_type = AgentType.implementer
        context = _build_context(input.goal, task, completed)

        # Non-review tasks: run once
        if agent_type not in _REVIEW_AGENTS:
            result = await self._run_activity(self._with_feedback(self._task(
                input, f"{wf_id}--{task['id']}",
                agent_type=agent_type,
                prompt=task["description"],
                parent_context=context,
            )))
            if result.commit_sha:
                self._current_sha = result.commit_sha
            return result

        # Review task: parse verdict, retry implementer if blocked
        # Find the implementer task this review covers (first dependency)
        depends_on   = task.get("depends_on") or []
        impl_task_id = depends_on[0] if depends_on else None
        impl_task    = next((t for t in _topo_sort([task]) if t["id"] == impl_task_id), None)  # noqa: F841  (WIP: reserved for review-retry targeting)

        review_context = context
        for cycle in range(_MAX_REVIEW_CYCLES + 1):
            result = await self._run_activity(self._task(
                input, f"{wf_id}--{task['id']}--review-{cycle}",
                agent_type=agent_type,
                prompt=task["description"],
                parent_context=review_context,
            ))

            review = _parse_review(result.output)
            workflow.logger.info(
                f"Review {task['id']} cycle {cycle}: verdict={review.verdict} "
                f"findings={len(review.findings)}"
            )

            if result.commit_sha:
                self._current_sha = result.commit_sha
            if review.verdict != "block":
                return result

            # Block: re-run the implementer (if we know which one)
            if cycle < _MAX_REVIEW_CYCLES and impl_task_id and impl_task_id in completed:
                workflow.logger.info(
                    f"Block on {task['id']}, re-running implementer {impl_task_id} "
                    f"(cycle {cycle + 1}/{_MAX_REVIEW_CYCLES})"
                )
                findings_text = _format_findings(review.findings)
                re_impl = await self._run_activity(self._task(
                    input, f"{wf_id}--{impl_task_id}--fix-{cycle}",
                    agent_type=AgentType.implementer,
                    prompt=completed[impl_task_id].output or task["description"],
                    parent_context=(
                        f"{context}\n\n## Review findings (must fix before proceeding)\n"
                        f"{findings_text}"
                    ),
                ))
                if re_impl.commit_sha:
                    self._current_sha = re_impl.commit_sha
                completed[impl_task_id] = re_impl
                review_context = (
                    f"{context}\n\n## Prior review findings\n{findings_text}"
                )
                continue

            # Retries exhausted - HITL
            self._phase = "awaiting_hitl"
            self._blocked_reason = (
                f"{task['id']} blocked after {cycle} retries: {review.summary}"
            )
            workflow.logger.warning(f"HITL required: {self._blocked_reason}")
            await self._emit({"type": "hitl_required",
                              "workflow_id": workflow.info().workflow_id,
                              "blocked_reason": self._blocked_reason})

            await workflow.wait_condition(
                lambda: self._hitl_decision is not None,
                timeout=_HITL_TIMEOUT,
            )

            decision = self._hitl_decision
            self._hitl_decision = None
            self._phase = "executing"
            self._blocked_reason = ""

            if decision == "abandon":
                return TaskResult(
                    task_id=task["id"],
                    output=f"ABANDONED after HITL: {review.summary}",
                    success=False,
                )
            # resume: accept the block as advisory and move on
            return result

        return result  # unreachable but satisfies type checker

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _task(self, input: OrchestratorInput, task_id: str, **kwargs) -> TaskInput:
        """Build a TaskInput pre-filled with orchestrator-level config fields."""
        return TaskInput(
            task_id=task_id,
            repo_path=input.repo_path,
            base_commit=self._current_sha,
            standards_dir=input.standards_dir,
            ticket_id=input.ticket_id,
            git_exclude=input.git_exclude,
            **kwargs,
        )

    async def _plan(self, wf_id: str, input: OrchestratorInput, standards_files: dict,
                    probe: Optional[ProbeResult] = None) -> dict:
        result = await self._run_activity(self._task(
            input, f"{wf_id}--plan",
            agent_type=AgentType.planner,
            prompt=_planner_prompt(input.goal, probe),
            workspace_files=input.workspace_files,
        ), timeout=_ANALYSIS_TIMEOUT)

        if result.commit_sha:
            self._current_sha = result.commit_sha

        try:
            return _parse_plan(result.output)
        except Exception as exc:
            workflow.logger.error(f"Plan parse failed: {exc}\nRaw: {result.output[:500]}")
            # Fall back to a single implementer task
            return {"tasks": [{"id": "task-1", "agent": "implementer",
                                "description": input.goal, "depends_on": []}]}

    async def _run_activity(self, task_input: TaskInput,
                            timeout: timedelta = _TASK_TIMEOUT) -> TaskResult:
        return await workflow.execute_activity(
            run_claude_task, task_input,
            start_to_close_timeout=timeout,
            retry_policy=_RETRY,
        )

    async def _run_terminal_activity(
        self, task_input: TaskInput, wf_id: str, phase: str
    ) -> TaskResult:
        """Run a terminal phase (changelog/pr_author) with HITL fallback.

        These phases don't produce code - they only write docs. If they
        repeatedly fail (worker churn, timeout) the workflow pauses and waits
        for a human `resume` signal rather than killing itself outright.
        """
        try:
            return await workflow.execute_activity(
                run_claude_task, task_input,
                start_to_close_timeout=_ANALYSIS_TIMEOUT,
                retry_policy=_TERMINAL_RETRY,
            )
        except ActivityError as exc:
            blocked = f"{phase} failed after retries: {exc}"
            workflow.logger.warning(f"HITL required for terminal phase: {blocked}")
            self._phase = "awaiting_hitl"
            self._blocked_reason = blocked
            await self._emit({"type": "hitl_required", "workflow_id": wf_id,
                              "blocked_reason": blocked,
                              "phase": phase})
            await workflow.wait_condition(
                lambda: self._hitl_decision is not None,
                timeout=_HITL_TIMEOUT,
            )
            decision = self._hitl_decision
            self._hitl_decision = None
            self._phase = "executing"
            self._blocked_reason = ""
            if decision == "abandon":
                return TaskResult(task_id=task_input.task_id,
                                  output=f"ABANDONED at {phase}", success=False)
            # resume: retry once more with a fresh attempt
            return await workflow.execute_activity(
                run_claude_task, task_input,
                start_to_close_timeout=_ANALYSIS_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

    def _with_feedback(self, task_input: TaskInput) -> TaskInput:
        """Consume any pending steer() feedback and inject it into context."""
        if not self._pending_feedback:
            return task_input
        block = "\n\n## Human steering instructions (incorporate these)\n" + \
                "\n".join(f"- {f}" for f in self._pending_feedback)
        self._pending_feedback.clear()
        from dataclasses import replace
        return replace(task_input,
                       parent_context=(task_input.parent_context or "") + block)

    async def _emit(self, event: dict) -> None:
        """Fire a lifecycle event. Never fails the workflow."""
        try:
            await workflow.execute_activity(
                publish_event, event,
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except ActivityError:
            pass


# ── Prompt builders ───────────────────────────────────────────────────────────

def _planner_prompt(goal: str, probe: Optional[ProbeResult] = None) -> str:
    if probe is None:
        baseline = "Baseline unknown (probe skipped or timed out)."
    elif probe.timed_out:
        baseline = "Probe timed out - baseline unknown."
    else:
        baseline = f"Passed: {probe.passed}, Failed: {probe.failed}"
        if probe.failed > 0:
            baseline += "\nFailing tests:\n" + "\n".join(f"- {t}" for t in probe.failing_tests)

    return f"""You are a task planner. Read all files in /workspace to understand the codebase.
Read /workspace/standards/ if present. Then produce an ordered task plan for this goal.

Goal: {goal}

## Test baseline
{baseline}

Return ONLY valid JSON - no markdown fences, no explanation:
{{
  "goal": "restate concisely",
  "tasks": [
    {{
      "id": "task-1",
      "agent": "implementer",
      "description": "Exactly what to do - specific files, functions, changes",
      "depends_on": [],
      "files": ["list of files this task touches"]
    }}
  ]
}}

Agent types: implementer, reviewer, security, architect, qa, pr_author
Review/qa tasks must list the implementer task(s) they cover in depends_on.
Keep to 3-5 tasks. Return ONLY valid JSON."""


def _changelog_prompt(goal: str, results: dict[str, TaskResult]) -> str:
    body = "\n\n".join(
        f"### {tid}\nFiles: {', '.join(r.files_changed) or 'none'}\n{r.output[:300]}"
        for tid, r in results.items()
    )
    return f"""Update CHANGELOG.md and bump the project version based on the changes below.

Goal: {goal}

What changed:
{body}

Follow the instructions in /workspace/CLAUDE.md exactly."""


def _pr_author_prompt(goal: str, results: dict[str, TaskResult], changelog_result: "TaskResult | None" = None) -> str:
    body = "\n\n".join(
        f"### {tid}\nFiles: {', '.join(r.files_changed) or 'none'}\n{r.output[:300]}"
        for tid, r in results.items()
    )
    cl_note = ""
    if changelog_result and changelog_result.output:
        cl_note = f"\n\nChangelog update:\n{changelog_result.output[:200]}"
    return f"""Read all files in /workspace. Write a pull request description to /workspace/PR_DESCRIPTION.md.

Original goal: {goal}

Agent results:
{body}{cl_note}

Format the PR description with sections: What changed, Why, Review notes, Test coverage, Files changed.
Include the version bump from the changelog agent if present.
Be direct and honest - include any advisory findings."""


# ── Utilities ─────────────────────────────────────────────────────────────────

def _parse_plan(output: str) -> dict:
    text = output.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        end = -1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])
    # Planner sometimes wraps JSON in prose or a code fence with trailing text.
    # Find the first { then use raw_decode so trailing non-JSON is ignored.
    brace = text.find("{")
    if brace > 0:
        text = text[brace:]
    plan, _ = json.JSONDecoder().raw_decode(text)
    # Normalise depends_on: flatten nested lists the planner occasionally emits
    # e.g. [["task-0"]] → ["task-0"]. Non-string values are dropped.
    for task in plan.get("tasks", []):
        raw = task.get("depends_on", [])
        flat: list[str] = []
        for item in raw:
            if isinstance(item, str):
                flat.append(item)
            elif isinstance(item, list):
                flat.extend(s for s in item if isinstance(s, str))
        task["depends_on"] = flat
    return plan


def _parse_review(output: str) -> ReviewResult:
    text = output.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        end = -1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[1:end])
    try:
        data = json.loads(text)
        return ReviewResult(
            verdict=data.get("verdict", "advisory"),
            findings=data.get("findings", []),
            summary=data.get("summary", ""),
            raw=output,
        )
    except (json.JSONDecodeError, KeyError):
        # If the agent didn't return valid JSON, treat as advisory
        return ReviewResult(verdict="advisory", findings=[], summary=output[:200], raw=output)


def _topo_sort(tasks: list[dict]) -> list[dict]:
    """Kahn's algorithm - returns tasks in dependency order."""
    by_id   = {t["id"]: t for t in tasks}  # noqa: F841  (kept for readability of Kahn's algorithm)
    in_deg  = {t["id"]: 0 for t in tasks}
    for t in tasks:
        for dep in t.get("depends_on", []):
            if not isinstance(dep, str):
                continue  # guard: planner may emit nested lists; skip non-string deps
            if dep in in_deg:
                in_deg[t["id"]] += 1

    queue  = [t for t in tasks if in_deg[t["id"]] == 0]
    result = []
    while queue:
        node = queue.pop(0)
        result.append(node)
        for t in tasks:
            deps = [d for d in t.get("depends_on", []) if isinstance(d, str)]
            if node["id"] in deps:
                in_deg[t["id"]] -= 1
                if in_deg[t["id"]] == 0:
                    queue.append(t)
    # append any remaining (cycles / unknown deps) at the end
    seen = {t["id"] for t in result}
    result += [t for t in tasks if t["id"] not in seen]
    return result


def _build_context(goal: str, task: dict, completed: dict[str, TaskResult]) -> str:
    parts = [f"## Goal\n{goal}", f"## This task\n{task['description']}"]
    deps = task.get("depends_on", [])
    if deps:
        parts.append("## Prior task results")
        for dep in deps:
            if dep in completed:
                r = completed[dep]
                parts.append(f"### {dep}\nFiles: {', '.join(r.files_changed) or 'none'}\n{r.output[:400]}")
    return "\n\n".join(parts)


def _format_findings(findings: list[dict]) -> str:
    if not findings:
        return "No specific findings."
    lines = []
    for f in findings:
        loc = f.get("file", "")
        if f.get("line"):
            loc += f":{f['line']}"
        lines.append(f"- [{f.get('severity','?')}] {loc}: {f.get('message','')}")
    return "\n".join(lines)
