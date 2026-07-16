"""Tests for workflow utility functions: _parse_plan, _parse_review, _topo_sort, _build_context."""
import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from src.models import OrchestratorInput, ProbeResult, TaskResult
from src.workflows import (
    OrchestratorWorkflow,
    _build_context,
    _parse_plan,
    _parse_review,
    _planner_prompt,
    _topo_sort,
)


# ── _parse_plan ────────────────────────────────────────────────────────────────


class TestParsePlan:
    def _valid_plan(self, goal="add login", tasks=None):
        if tasks is None:
            tasks = [
                {
                    "id": "task-1",
                    "agent": "implementer",
                    "description": "add endpoint",
                    "depends_on": [],
                    "files": ["auth.py"],
                }
            ]
        return {"goal": goal, "tasks": tasks}

    def test_parses_valid_json(self):
        result = _parse_plan(json.dumps(self._valid_plan()))
        assert result["goal"] == "add login"
        assert len(result["tasks"]) == 1
        assert result["tasks"][0]["id"] == "task-1"

    def test_returns_all_task_fields(self):
        result = _parse_plan(json.dumps(self._valid_plan()))
        task = result["tasks"][0]
        assert task["agent"] == "implementer"
        assert task["description"] == "add endpoint"
        assert task["depends_on"] == []

    def test_strips_json_fenced_markdown(self):
        inner = json.dumps(self._valid_plan(goal="fenced goal"))
        output = f"```json\n{inner}\n```"
        result = _parse_plan(output)
        assert result["goal"] == "fenced goal"

    def test_strips_plain_fenced_markdown(self):
        inner = json.dumps(self._valid_plan(goal="plain fence"))
        output = f"```\n{inner}\n```"
        result = _parse_plan(output)
        assert result["goal"] == "plain fence"

    def test_raises_on_garbage_input(self):
        with pytest.raises(Exception):
            _parse_plan("this is not json at all!!")

    def test_raises_on_empty_string(self):
        with pytest.raises(Exception):
            _parse_plan("")

    def test_raises_on_partial_json(self):
        with pytest.raises(Exception):
            _parse_plan('{"goal": "incomplete"')


# ── _parse_review ──────────────────────────────────────────────────────────────


class TestParseReview:
    def _review_json(self, verdict, findings=None, summary=""):
        return json.dumps(
            {"verdict": verdict, "findings": findings or [], "summary": summary}
        )

    def test_pass_verdict(self):
        result = _parse_review(self._review_json("pass", summary="all good"))
        assert result.verdict == "pass"
        assert result.findings == []
        assert result.summary == "all good"

    def test_block_verdict(self):
        finding = {
            "file": "main.py",
            "line": 10,
            "severity": "error",
            "message": "SQL injection",
        }
        result = _parse_review(self._review_json("block", [finding], "critical issue"))
        assert result.verdict == "block"
        assert len(result.findings) == 1
        assert result.findings[0]["message"] == "SQL injection"

    def test_advisory_verdict(self):
        result = _parse_review(self._review_json("advisory", summary="minor notes"))
        assert result.verdict == "advisory"

    def test_invalid_json_treated_as_advisory(self):
        result = _parse_review("not json - just prose output from claude")
        assert result.verdict == "advisory"
        assert result.findings == []

    def test_invalid_json_summary_contains_raw_output(self):
        raw = "This is the raw prose output"
        result = _parse_review(raw)
        assert raw[:100] in result.summary

    def test_strips_json_fenced_markdown(self):
        inner = self._review_json("pass", summary="fenced")
        result = _parse_review(f"```json\n{inner}\n```")
        assert result.verdict == "pass"

    def test_strips_plain_fenced_markdown(self):
        inner = self._review_json("block", summary="blocked")
        result = _parse_review(f"```\n{inner}\n```")
        assert result.verdict == "block"

    def test_missing_verdict_key_defaults_to_advisory(self):
        data = json.dumps({"findings": [], "summary": "no verdict key"})
        result = _parse_review(data)
        assert result.verdict == "advisory"

    def test_raw_output_preserved_on_success(self):
        raw = self._review_json("pass", summary="s")
        result = _parse_review(raw)
        assert result.raw == raw

    def test_raw_output_preserved_on_parse_failure(self):
        raw = "unparseable prose"
        result = _parse_review(raw)
        assert result.raw == raw


# ── _topo_sort ────────────────────────────────────────────────────────────────


class TestTopoSort:
    def _task(self, tid, depends_on=None):
        return {"id": tid, "depends_on": depends_on or []}

    def test_empty_list_returns_empty(self):
        assert _topo_sort([]) == []

    def test_single_task_returned(self):
        tasks = [self._task("only")]
        assert [t["id"] for t in _topo_sort(tasks)] == ["only"]

    def test_independent_tasks_all_present(self):
        tasks = [self._task("a"), self._task("b")]
        result = _topo_sort(tasks)
        assert {t["id"] for t in result} == {"a", "b"}

    def test_dependency_comes_before_dependent(self):
        tasks = [self._task("task-2", ["task-1"]), self._task("task-1")]
        ids = [t["id"] for t in _topo_sort(tasks)]
        assert ids.index("task-1") < ids.index("task-2")

    def test_three_task_chain_ordered_correctly(self):
        tasks = [
            self._task("c", ["b"]),
            self._task("a"),
            self._task("b", ["a"]),
        ]
        ids = [t["id"] for t in _topo_sort(tasks)]
        assert ids == ["a", "b", "c"]

    def test_cycle_does_not_hang(self):
        tasks = [self._task("x", ["y"]), self._task("y", ["x"])]
        result = _topo_sort(tasks)
        assert len(result) == 2

    def test_cycle_includes_all_tasks(self):
        tasks = [self._task("x", ["y"]), self._task("y", ["x"])]
        result = _topo_sort(tasks)
        assert {t["id"] for t in result} == {"x", "y"}

    def test_diamond_dependency(self):
        # a → b, a → c, b+c → d
        tasks = [
            self._task("d", ["b", "c"]),
            self._task("b", ["a"]),
            self._task("c", ["a"]),
            self._task("a"),
        ]
        ids = [t["id"] for t in _topo_sort(tasks)]
        assert ids.index("a") < ids.index("b")
        assert ids.index("a") < ids.index("c")
        assert ids.index("b") < ids.index("d")
        assert ids.index("c") < ids.index("d")


# ── _build_context ────────────────────────────────────────────────────────────


class TestBuildContext:
    def _completed(self, tid, output="done", files=None):
        return TaskResult(
            task_id=tid,
            output=output,
            files_changed=files or [],
        )

    def test_includes_goal(self):
        task = {"id": "t1", "description": "do something", "depends_on": []}
        ctx = _build_context("add authentication", task, {})
        assert "add authentication" in ctx

    def test_includes_task_description(self):
        task = {"id": "t1", "description": "implement login endpoint", "depends_on": []}
        ctx = _build_context("goal", task, {})
        assert "implement login endpoint" in ctx

    def test_includes_dependency_output_when_present(self):
        completed = {"task-1": self._completed("task-1", "wrote auth.py with JWT")}
        task = {"id": "task-2", "description": "write tests", "depends_on": ["task-1"]}
        ctx = _build_context("goal", task, completed)
        assert "wrote auth.py with JWT" in ctx

    def test_includes_files_changed_from_dep(self):
        completed = {
            "dep-1": self._completed("dep-1", "done", ["models.py", "views.py"])
        }
        task = {"id": "t2", "description": "review", "depends_on": ["dep-1"]}
        ctx = _build_context("goal", task, completed)
        assert "models.py" in ctx

    def test_omits_missing_dep_silently(self):
        task = {"id": "t2", "description": "desc", "depends_on": ["ghost-task"]}
        ctx = _build_context("goal", task, {})
        assert "goal" in ctx
        assert "desc" in ctx
        assert "### ghost-task" not in ctx

    def test_no_exception_on_missing_dep(self):
        task = {"id": "t2", "description": "desc", "depends_on": ["missing"]}
        _build_context("goal", task, {})  # must not raise

    def test_no_prior_results_section_without_deps(self):
        task = {"id": "t1", "description": "first task", "depends_on": []}
        ctx = _build_context("goal", task, {})
        assert "Prior task results" not in ctx

    def test_partial_deps_includes_only_completed(self):
        completed = {"present": self._completed("present", "present output")}
        task = {
            "id": "t3",
            "description": "use both",
            "depends_on": ["present", "absent"],
        }
        ctx = _build_context("goal", task, completed)
        assert "present output" in ctx
        assert "### absent" not in ctx


# ── OrchestratorWorkflow: probe_tests skip ───────────────────────────────────


def test_orchestrator_probe_skipped_when_false():
    from src.activities import probe_tests as probe_tests_fn
    from src.activities import publish_event, push_and_create_pr, run_claude_task

    probe_called = False

    async def mock_execute_activity(activity_fn, *args, **kwargs):
        nonlocal probe_called
        if activity_fn is probe_tests_fn:
            probe_called = True
            return ProbeResult(0, 0, [])
        if activity_fn is publish_event:
            return None
        if activity_fn is run_claude_task:
            return TaskResult(
                task_id="mock",
                output=json.dumps({"goal": "g", "tasks": []}),
                success=True,
            )
        if activity_fn is push_and_create_pr:
            return ""
        return None

    mock_wf = MagicMock()
    mock_wf.execute_activity = mock_execute_activity
    mock_wf.info.return_value = MagicMock(workflow_id="test-wf-id")
    mock_wf.logger = MagicMock()

    with patch("src.workflows.workflow", mock_wf):
        orc = OrchestratorWorkflow()
        asyncio.run(
            orc.run(
                OrchestratorInput(
                    goal="test goal",
                    probe_tests=False,
                    repo_path="/fake/repo",
                    changelog=False,
                    remote_url="",
                )
            )
        )

    assert not probe_called


# ── _planner_prompt ───────────────────────────────────────────────────────────


def test_planner_prompt_includes_baseline():
    probe = ProbeResult(passed=3, failed=1, failing_tests=["tests/test_x.py::test_y"])
    prompt = _planner_prompt("my goal", probe)
    assert "## Test baseline" in prompt
    assert "tests/test_x.py::test_y" in prompt


def test_planner_prompt_timeout():
    probe = ProbeResult(passed=0, failed=0, failing_tests=[], timed_out=True)
    prompt = _planner_prompt("my goal", probe)
    assert "baseline unknown" in prompt
