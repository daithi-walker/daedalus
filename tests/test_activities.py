"""Tests for src/activities utility functions."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.activities as activities
from src.activities import (
    CLAUDE_IMAGE,
    CLAUDE_QA_IMAGE,
    _ALLOWED_TOOLS,
    _assert_git_root,
    _build_docker_cmd,
    _populate_workspace,
    probe_tests,
    push_and_create_pr,
)
from src.models import ProbeResult, TaskInput


# ── _ALLOWED_TOOLS routing ────────────────────────────────────────────────────


class TestAllowedToolsRouting:
    def test_planner_is_read_only(self):
        assert _ALLOWED_TOOLS["planner"] == "Read"

    def test_reviewer_is_read_only(self):
        assert _ALLOWED_TOOLS["reviewer"] == "Read"

    def test_security_is_read_only(self):
        assert _ALLOWED_TOOLS["security"] == "Read"

    def test_architect_is_read_only(self):
        assert _ALLOWED_TOOLS["architect"] == "Read"

    def test_implementer_includes_write(self):
        assert "Write" in _ALLOWED_TOOLS["implementer"]

    def test_implementer_includes_edit(self):
        assert "Edit" in _ALLOWED_TOOLS["implementer"]

    def test_implementer_includes_multiedit(self):
        assert "MultiEdit" in _ALLOWED_TOOLS["implementer"]

    def test_qa_includes_pytest(self):
        assert "pytest" in _ALLOWED_TOOLS["qa"]

    def test_qa_includes_pip_install(self):
        # pip install enables installing packages like flask
        assert "pip install" in _ALLOWED_TOOLS["qa"]

    def test_qa_includes_write_tools(self):
        tools = _ALLOWED_TOOLS["qa"]
        assert "Write" in tools
        assert "Edit" in tools

    def test_all_named_agents_have_entry(self):
        expected = {
            "planner",
            "implementer",
            "reviewer",
            "security",
            "architect",
            "qa",
            "changelog",
            "pr_author",
        }
        for agent in expected:
            assert agent in _ALLOWED_TOOLS, f"missing entry for agent: {agent}"


# ── _build_docker_cmd ─────────────────────────────────────────────────────────


class TestBuildDockerCmd:
    _WORKSPACE = Path("/tmp/test-workspace-xyz")

    def _cmd(self, agent_type="implementer", prompt="test prompt", workspace=None):
        ws = workspace or self._WORKSPACE
        return _build_docker_cmd(ws, prompt, agent_type)

    def _volume_mounts(self, cmd):
        return [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-v"]

    def _env_values(self, cmd):
        return [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-e"]

    def test_mounts_workspace_volume(self):
        cmd = self._cmd()
        mounts = self._volume_mounts(cmd)
        assert any(":/workspace" in m for m in mounts)

    def test_workspace_volume_maps_correct_host_path(self):
        ws = Path("/tmp/my-specific-workspace")
        cmd = self._cmd(workspace=ws)
        mounts = self._volume_mounts(cmd)
        assert any(m.startswith(str(ws) + ":/workspace") for m in mounts)

    def test_anthropic_mode_passes_api_key(self):
        with patch.object(activities, "_USE_VERTEX", False), \
             patch.object(activities, "_ANTHROPIC_API_KEY", "sk-ant-test"):
            cmd = self._cmd()
        env_vals = self._env_values(cmd)
        assert any("ANTHROPIC_API_KEY=sk-ant-test" in v for v in env_vals)

    def test_anthropic_mode_does_not_mount_sa_key(self):
        with patch.object(activities, "_USE_VERTEX", False):
            cmd = self._cmd()
        mounts = self._volume_mounts(cmd)
        assert not any(":ro" in m for m in mounts)

    def test_vertex_mode_mounts_sa_key_read_only(self):
        sa_key = Path("/fake/sa-key.json")
        with patch.object(activities, "_USE_VERTEX", True), \
             patch.object(activities, "_SA_KEY_HOST", str(sa_key)), \
             patch.object(activities, "_VERTEX_PROJECT", "my-project"):
            cmd = self._cmd()
        mounts = self._volume_mounts(cmd)
        assert any(":ro" in m and "sa-key.json" in m for m in mounts)

    def test_vertex_mode_passes_vertex_env_vars(self):
        sa_key = Path("/fake/sa-key.json")
        with patch.object(activities, "_USE_VERTEX", True), \
             patch.object(activities, "_SA_KEY_HOST", str(sa_key)), \
             patch.object(activities, "_VERTEX_PROJECT", "my-project"), \
             patch.object(activities, "_VERTEX_REGION", "us-east5"):
            cmd = self._cmd()
        env_vals = self._env_values(cmd)
        assert any("CLAUDE_CODE_USE_VERTEX=1" in v for v in env_vals)
        assert any("ANTHROPIC_VERTEX_PROJECT_ID=my-project" in v for v in env_vals)

    def test_passes_prompt_with_p_flag(self):
        prompt = "implement the login feature now"
        cmd = self._cmd(prompt=prompt)
        assert "-p" in cmd
        p_idx = cmd.index("-p")
        assert cmd[p_idx + 1] == prompt

    def test_memory_limit_is_512m(self):
        cmd = self._cmd()
        assert "--memory" in cmd
        idx = cmd.index("--memory")
        assert cmd[idx + 1] == "512m"

    def test_cpu_limit_is_1_0(self):
        cmd = self._cmd()
        assert "--cpus" in cmd
        idx = cmd.index("--cpus")
        assert cmd[idx + 1] == "1.0"

    def test_uses_qa_image_for_qa_agent(self):
        cmd = self._cmd(agent_type="qa")
        assert CLAUDE_QA_IMAGE in cmd

    def test_uses_default_image_for_implementer(self):
        cmd = self._cmd(agent_type="implementer")
        assert CLAUDE_IMAGE in cmd

    def test_qa_and_implementer_use_different_images(self):
        qa_cmd = self._cmd(agent_type="qa")
        impl_cmd = self._cmd(agent_type="implementer")
        assert CLAUDE_QA_IMAGE in qa_cmd
        assert CLAUDE_QA_IMAGE not in impl_cmd

    def test_command_starts_with_docker_run(self):
        cmd = self._cmd()
        assert cmd[0] == "docker"
        assert cmd[1] == "run"


# ── _populate_workspace ───────────────────────────────────────────────────────


class TestPopulateWorkspace:
    def _input(self, **kwargs):
        defaults = {"task_id": "test-task", "prompt": "test prompt"}
        defaults.update(kwargs)
        return TaskInput(**defaults)

    def test_writes_workspace_files(self, tmp_path):
        task_input = self._input(workspace_files={"app/main.py": "print('hello')"})
        _populate_workspace(tmp_path, task_input)
        out = tmp_path / "app" / "main.py"
        assert out.exists()
        assert out.read_text() == "print('hello')"

    def test_writes_multiple_workspace_files(self, tmp_path):
        files = {"a.py": "# a", "b/c.py": "# b-c"}
        task_input = self._input(workspace_files=files)
        _populate_workspace(tmp_path, task_input)
        assert (tmp_path / "a.py").read_text() == "# a"
        assert (tmp_path / "b" / "c.py").read_text() == "# b-c"

    def test_writes_deeply_nested_workspace_files(self, tmp_path):
        task_input = self._input(
            workspace_files={"deep/nested/dir/file.txt": "content"}
        )
        _populate_workspace(tmp_path, task_input)
        assert (
            tmp_path / "deep" / "nested" / "dir" / "file.txt"
        ).read_text() == "content"

    def test_writes_context_md_when_parent_context_present(self, tmp_path):
        task_input = self._input(parent_context="## Goal\ndo the thing")
        _populate_workspace(tmp_path, task_input)
        ctx = tmp_path / "_context.md"
        assert ctx.exists()
        assert ctx.read_text() == "## Goal\ndo the thing"

    def test_omits_context_md_when_parent_context_empty(self, tmp_path):
        task_input = self._input(parent_context="")
        _populate_workspace(tmp_path, task_input)
        assert not (tmp_path / "_context.md").exists()

    def test_omits_context_md_when_parent_context_not_set(self, tmp_path):
        task_input = self._input()  # parent_context defaults to ""
        _populate_workspace(tmp_path, task_input)
        assert not (tmp_path / "_context.md").exists()

    def test_copies_md_files_from_standards_dir(self, tmp_path):
        standards_src = tmp_path / "stds"
        standards_src.mkdir()
        (standards_src / "coding.md").write_text("# coding standards")
        (standards_src / "testing.md").write_text("# testing standards")

        workspace = tmp_path / "ws"
        workspace.mkdir()
        task_input = self._input(standards_dir=str(standards_src))
        _populate_workspace(workspace, task_input)

        assert (workspace / "standards" / "coding.md").read_text() == "# coding standards"
        assert (workspace / "standards" / "testing.md").read_text() == "# testing standards"

    def test_standards_dir_ignores_non_md_files(self, tmp_path):
        standards_src = tmp_path / "stds"
        standards_src.mkdir()
        (standards_src / "coding.md").write_text("# coding")
        (standards_src / "ignored.txt").write_text("not markdown")

        workspace = tmp_path / "ws"
        workspace.mkdir()
        task_input = self._input(standards_dir=str(standards_src))
        _populate_workspace(workspace, task_input)

        assert not (workspace / "standards" / "ignored.txt").exists()
        assert (workspace / "standards" / "coding.md").exists()

    def test_writes_claude_md_from_agent_file(self, tmp_path, monkeypatch):
        import src.activities as act

        fake_agents = tmp_path / "agents"
        fake_agents.mkdir()
        (fake_agents / "implementer.md").write_text("# Implementer role")
        monkeypatch.setattr(act, "_AGENTS_DIR", fake_agents)

        workspace = tmp_path / "ws"
        workspace.mkdir()
        task_input = self._input(agent_type="implementer")
        act._populate_workspace(workspace, task_input)

        claude_md = workspace / "CLAUDE.md"
        assert claude_md.exists()
        assert "Implementer role" in claude_md.read_text()

    def test_claude_md_agent_file_takes_priority_over_fallback(self, tmp_path, monkeypatch):
        import src.activities as act

        fake_agents = tmp_path / "agents"
        fake_agents.mkdir()
        (fake_agents / "planner.md").write_text("# Planner-specific instructions")
        monkeypatch.setattr(act, "_AGENTS_DIR", fake_agents)

        workspace = tmp_path / "ws"
        workspace.mkdir()
        task_input = self._input(agent_type="planner")
        act._populate_workspace(workspace, task_input)

        assert "Planner-specific instructions" in (workspace / "CLAUDE.md").read_text()


# ── _assert_git_root ──────────────────────────────────────────────────────────


class TestAssertGitRoot:
    def test_passes_for_actual_git_root(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"], capture_output=True)
        subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "T"], capture_output=True)
        _assert_git_root(tmp_path)  # must not raise

    def test_raises_for_subdirectory_of_git_root(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        subdir = tmp_path / "src"
        subdir.mkdir()
        with pytest.raises(ValueError, match="git root"):
            _assert_git_root(subdir)

    def test_raises_for_non_git_directory(self, tmp_path):
        with pytest.raises(ValueError, match="not a git repository"):
            _assert_git_root(tmp_path)

    def test_error_message_shows_given_path(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        subdir = tmp_path / "nested"
        subdir.mkdir()
        with pytest.raises(ValueError) as exc:
            _assert_git_root(subdir)
        assert str(subdir) in str(exc.value)

    def test_error_message_shows_git_root(self, tmp_path):
        import subprocess
        subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
        subdir = tmp_path / "nested"
        subdir.mkdir()
        with pytest.raises(ValueError) as exc:
            _assert_git_root(subdir)
        assert str(tmp_path) in str(exc.value)


# ── push_and_create_pr ────────────────────────────────────────────────────────
#
# Both src.activities and the provider modules reference the same subprocess
# singleton, so a single patch("subprocess.run") with side_effect covers all
# calls without one patch overwriting the other.


class TestPushAndCreatePR:
    _REPO   = "/tmp/test-repo"
    _BRANCH = "feature/test-branch"
    _TICKET = "TICKET-42"
    _BODY   = "## Summary\n\nThis PR does a thing."

    def test_empty_remote_url_returns_empty_string_without_subprocess(self):
        import asyncio
        with patch("subprocess.run") as mock_run:
            result = asyncio.run(push_and_create_pr(self._REPO, "", self._BRANCH, "main", self._TICKET, ""))
        assert result == ""
        mock_run.assert_not_called()

    def test_github_remote_calls_git_push_force_and_gh_pr_create(self):
        import asyncio
        push_ok = MagicMock(returncode=0)
        gh_ok   = MagicMock(returncode=0, stdout="https://github.com/org/repo/pull/42\n")

        with patch("subprocess.run", side_effect=[push_ok, gh_ok]) as mock_run, \
             patch.dict("os.environ", {"DAEDALUS_PR_PROVIDER": ""}):
            result = asyncio.run(push_and_create_pr(
                self._REPO,
                "https://github.com/org/repo.git",
                self._BRANCH,
                "main",
                self._TICKET,
                "",
                self._BODY,
            ))

        assert mock_run.call_count == 2
        git_call, gh_call = mock_run.call_args_list
        assert git_call.args[0] == [
            "git", "-C", self._REPO, "push", "origin", self._BRANCH, "--force"
        ]
        assert git_call.kwargs.get("check") is True
        assert gh_call.args[0] == [
            "gh", "pr", "create",
            "--repo", "org/repo",
            "--head", self._BRANCH,
            "--base", "main",
            "--title", "Summary",
            "--body", self._BODY,
        ]
        assert result == "https://github.com/org/repo/pull/42"

    def test_ado_remote_calls_git_push_and_az_repos_pr_create(self):
        import asyncio
        push_ok = MagicMock(returncode=0)
        az_ok   = MagicMock(returncode=0, stdout=json.dumps({"pullRequestId": 99}))

        with patch("subprocess.run", side_effect=[push_ok, az_ok]) as mock_run, \
             patch.dict("os.environ", {"DAEDALUS_PR_PROVIDER": ""}):
            result = asyncio.run(push_and_create_pr(
                self._REPO,
                "https://dev.azure.com/org/proj/_git/repo",
                self._BRANCH,
                "main",
                self._TICKET,
                "",
                self._BODY,
            ))

        assert mock_run.call_count == 2
        git_call, az_call = mock_run.call_args_list
        assert git_call.args[0] == [
            "git", "-C", self._REPO, "push", "origin", self._BRANCH, "--force"
        ]
        assert git_call.kwargs.get("check") is True
        assert az_call.args[0] == [
            "az", "repos", "pr", "create",
            "--org", "https://dev.azure.com/org",
            "--project", "proj",
            "--repository", "repo",
            "--source-branch", self._BRANCH,
            "--target-branch", "main",
            "--title", "Summary",
            "--description", self._BODY,
            "--output", "json",
        ]
        assert az_call.kwargs.get("capture_output") is True
        assert az_call.kwargs.get("text") is True
        assert result == "https://dev.azure.com/org/proj/_git/repo/pullrequest/99"


# ── probe_tests ───────────────────────────────────────────────────────────────


class TestProbeTests:
    def test_probe_tests_pass(self):
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"2 passed in 0.1s\n", None))

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
            result = asyncio.run(probe_tests("/fake/repo"))

        assert result == ProbeResult(passed=2, failed=0, failing_tests=[], timed_out=False)

    def test_probe_tests_fail(self):
        stdout = b"FAILED tests/test_foo.py::test_bar\n1 failed, 1 passed in 0.2s\n"
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(stdout, None))

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
            result = asyncio.run(probe_tests("/fake/repo"))

        assert result.passed == 1
        assert result.failed == 1
        assert result.failing_tests == ["tests/test_foo.py::test_bar"]

    def test_probe_tests_timeout(self):
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock()

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)), \
             patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            result = asyncio.run(probe_tests("/fake/repo"))

        assert result.timed_out is True
        assert result.passed == 0
        assert result.failed == 0
        assert result.failing_tests == []
