"""Integration tests for git operations using real git repos in tempdir.

These tests complement the mocked unit tests in test_activities.py by exercising
actual git behaviour that mocks cannot verify:

  1. _git_commit must not stage deletion of tracked files (CLAUDE.md bug)
  2. push_and_create_pr must recreate the agent branch from final_sha before pushing
  3. base_branch must flow through to provider.ensure_pr
"""
import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import src.activities as activities
from src.activities import _git, _git_commit
from src.models import TaskInput


# ── git helpers ───────────────────────────────────────────────────────────────

def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "T"], capture_output=True)


def _stage_and_commit(path: Path, message: str = "commit") -> str:
    subprocess.run(["git", "-C", str(path), "add", "-A"], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", message, "--author=T <t@t.com>"],
        capture_output=True, check=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _write_and_commit(path: Path, name: str, content: str, message: str = "") -> str:
    (path / name).parent.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(content)
    return _stage_and_commit(path, message or f"add {name}")


def _head_sha(path: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _show_file_at_head(path: Path, filename: str) -> str:
    return subprocess.run(
        ["git", "-C", str(path), "show", f"HEAD:{filename}"],
        capture_output=True, text=True, check=True,
    ).stdout


def _make_clone_pair(tmp_path: Path) -> tuple[Path, Path]:
    """Create a bare remote and a local clone with one commit. Returns (local, remote)."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    subprocess.run(["git", "init", "--bare", str(remote)], capture_output=True, check=True)

    local = tmp_path / "local"
    subprocess.run(["git", "clone", str(remote), str(local)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(local), "config", "user.email", "t@t.com"], capture_output=True)
    subprocess.run(["git", "-C", str(local), "config", "user.name", "T"], capture_output=True)
    _write_and_commit(local, "README.md", "# project")
    subprocess.run(
        ["git", "-C", str(local), "push", "origin", "HEAD"],
        capture_output=True, check=True,
    )
    return local, remote


# ── _git_commit: exclusions prevent scaffold files from landing in target repos ─


class TestGitCommitExclusions:
    """_git_commit must exclude workspace scaffolding regardless of tracking state."""

    def _repo_with_tracked_claude_md(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)
        _write_and_commit(repo, "CLAUDE.md", "# Original CLAUDE.md")
        _write_and_commit(repo, "app.py", "print('hello')")
        return repo

    def test_tracked_claude_md_not_in_commit(self, tmp_path):
        """CLAUDE.md already in HEAD must not appear in files_changed after agent runs."""
        repo = self._repo_with_tracked_claude_md(tmp_path)
        (repo / "CLAUDE.md").write_text("# Agent instructions - must not be committed")
        (repo / "feature.py").write_text("def feature(): pass\n")

        sha, files_changed = _git_commit(repo, "implementer", "add feature", "TICK-1")

        assert sha, "expected a commit"
        assert "CLAUDE.md" not in files_changed, \
            f"CLAUDE.md must be excluded but appeared in {files_changed}"
        assert "feature.py" in files_changed

    def test_tracked_claude_md_content_preserved_in_head(self, tmp_path):
        """After the commit, HEAD:CLAUDE.md must still hold the original content."""
        repo = self._repo_with_tracked_claude_md(tmp_path)
        (repo / "CLAUDE.md").write_text("# Agent instructions - must not overwrite HEAD")
        (repo / "feature.py").write_text("def feature(): pass\n")

        _git_commit(repo, "implementer", "add feature", "")

        content = _show_file_at_head(repo, "CLAUDE.md")
        assert "Original CLAUDE.md" in content, \
            f"HEAD CLAUDE.md should be original, got: {content!r}"
        assert "Agent instructions" not in content

    def test_untracked_claude_md_excluded(self, tmp_path):
        """CLAUDE.md that has never been committed (untracked) must also be excluded."""
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_repo(repo)
        _write_and_commit(repo, "app.py", "print('hello')")
        (repo / "CLAUDE.md").write_text("# Agent instructions")
        (repo / "feature.py").write_text("def feature(): pass\n")

        sha, files_changed = _git_commit(repo, "implementer", "add feature", "")

        assert "CLAUDE.md" not in files_changed, \
            f"CLAUDE.md must be excluded but appeared in {files_changed}"

    def test_context_md_excluded(self, tmp_path):
        """_context.md written by _populate_workspace must never land in a commit."""
        repo = self._repo_with_tracked_claude_md(tmp_path)
        (repo / "_context.md").write_text("## Goal\ndo the thing")
        (repo / "impl.py").write_text("x = 1\n")

        sha, files_changed = _git_commit(repo, "implementer", "add impl", "")

        assert "_context.md" not in files_changed
        assert "impl.py" in files_changed

    def test_pr_description_md_excluded(self, tmp_path):
        """PR_DESCRIPTION.md written by the pr_author agent must not be committed."""
        repo = self._repo_with_tracked_claude_md(tmp_path)
        (repo / "PR_DESCRIPTION.md").write_text("## Summary\nThis PR does stuff.")
        (repo / "impl.py").write_text("x = 1\n")

        sha, files_changed = _git_commit(repo, "pr_author", "write PR body", "")

        assert "PR_DESCRIPTION.md" not in files_changed
        assert "impl.py" in files_changed

    def test_standards_dir_excluded(self, tmp_path):
        """standards/ copied by _populate_workspace must not appear in commits."""
        repo = self._repo_with_tracked_claude_md(tmp_path)
        (repo / "standards").mkdir()
        (repo / "standards" / "coding.md").write_text("# Coding standards")
        (repo / "impl.py").write_text("x = 1\n")

        sha, files_changed = _git_commit(repo, "implementer", "add impl", "")

        assert not any("standards" in f for f in files_changed), \
            f"standards/ must be excluded but found: {[f for f in files_changed if 'standards' in f]}"

    def test_no_commit_when_only_excluded_files_changed(self, tmp_path):
        """When only scaffold files changed, _git_commit returns empty sha and no files."""
        repo = self._repo_with_tracked_claude_md(tmp_path)
        (repo / "CLAUDE.md").write_text("# Agent instructions")
        (repo / "_context.md").write_text("## context")

        sha, files_changed = _git_commit(repo, "implementer", "nothing real", "")

        assert sha == "", "no commit should be made"
        assert files_changed == []

    def test_commit_message_includes_agent_type_and_ticket(self, tmp_path):
        """Commit subject line must embed agent type and ticket ID for audit trail."""
        repo = self._repo_with_tracked_claude_md(tmp_path)
        (repo / "login.py").write_text("def login(): pass\n")

        sha, _ = _git_commit(repo, "implementer", "add the login feature", "PROJ-99")

        log = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%B"],
            capture_output=True, text=True, check=True,
        ).stdout
        assert "implementer" in log
        assert "PROJ-99" in log
        assert "Authored-By-Agent: daedalus/implementer" in log
        assert "Intent-Ref: PROJ-99" in log


# ── _run_with_git: PR_DESCRIPTION.md captured in TaskResult ──────────────────


class TestPrDescriptionCapture:
    """_run_with_git must read PR_DESCRIPTION.md into TaskResult.pr_description."""

    def setup_method(self, method):
        self._tmpdir = Path(tempfile.mkdtemp())
        self.repo = self._tmpdir / "repo"
        self.repo.mkdir()
        _init_repo(self.repo)
        _write_and_commit(self.repo, "README.md", "# project")

        self.worktree = self._tmpdir / "worktree"
        self.worktree.mkdir()
        (self.worktree / "PR_DESCRIPTION.md").write_text("# Fix login bug\n\nDetails.")

    def teardown_method(self, method):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_run_with_git_captures_pr_description(self):
        task_input = TaskInput(
            task_id="pr-desc-test",
            prompt="Write PR description",
            agent_type="pr_author",
            repo_path=str(self.repo),
            ticket_id="PROJ-1",
        )

        with patch("tempfile.mkdtemp", return_value=str(self.worktree)), \
             patch("src.activities._run_with_heartbeat",
                   new_callable=AsyncMock,
                   return_value=subprocess.CompletedProcess([], 0, "done", "")), \
             patch("src.activities._git_commit", return_value=("abc123", ["impl.py"])), \
             patch("src.activities._validate_provider"), \
             patch("src.activities._populate_workspace"), \
             patch("src.activities._git",
                   return_value=MagicMock(returncode=0, stdout="", stderr="")), \
             patch("src.activities.activity.heartbeat"):
            result = asyncio.run(activities._run_with_git(task_input, MagicMock()))

        assert result.pr_description == "# Fix login bug\n\nDetails."


# ── push_and_create_pr: final_sha branch recovery ────────────────────────────


class TestPushWithFinalSha:
    """push_and_create_pr must recover orphaned agent commits via final_sha."""

    def test_orphaned_sha_is_pushed_to_remote(self, tmp_path):
        """Commits on a deleted branch are orphans; final_sha must resurrect them."""
        local, remote = _make_clone_pair(tmp_path)

        # Simulate an agent activity: commit on a temp branch, then delete the branch
        _git(local, ["checkout", "-b", "agent/test-task-abc"])
        _write_and_commit(local, "feature.py", "x = 1\n")
        final_sha = _head_sha(local)

        # Delete the branch - final_sha is now an orphan (simulates finally block)
        _git(local, ["checkout", "HEAD~0"])  # detach HEAD first
        _git(local, ["branch", "-D", "agent/test-task-abc"])

        with patch("src.activities.get_provider", return_value=None):
            asyncio.run(activities.push_and_create_pr(
                str(local),
                "https://github.com/org/repo.git",  # used only for provider detection
                "agent/test-task-abc",
                "main",
                "TICK-1",
                final_sha=final_sha,
            ))

        remote_result = subprocess.run(
            ["git", "-C", str(remote), "rev-parse", "refs/heads/agent/test-task-abc"],
            capture_output=True, text=True,
        )
        assert remote_result.returncode == 0, \
            "agent branch must exist in remote after push"
        assert remote_result.stdout.strip() == final_sha, \
            f"remote branch should point to {final_sha[:8]}, got {remote_result.stdout.strip()[:8]}"

    def test_without_final_sha_pushes_branch_tip(self, tmp_path):
        """When final_sha is absent, the existing branch tip is pushed directly."""
        local, remote = _make_clone_pair(tmp_path)

        _git(local, ["checkout", "-b", "agent/test-task-xyz"])
        _write_and_commit(local, "feature.py", "y = 2\n")
        tip_sha = _head_sha(local)

        with patch("src.activities.get_provider", return_value=None):
            asyncio.run(activities.push_and_create_pr(
                str(local),
                "https://github.com/org/repo.git",
                "agent/test-task-xyz",
                "main",
                "TICK-2",
                final_sha="",
            ))

        remote_result = subprocess.run(
            ["git", "-C", str(remote), "rev-parse", "refs/heads/agent/test-task-xyz"],
            capture_output=True, text=True,
        )
        assert remote_result.returncode == 0
        assert remote_result.stdout.strip() == tip_sha

    def test_multiple_agent_commits_all_reach_remote(self, tmp_path):
        """All commits made across multiple agent activities must be reachable from remote."""
        local, remote = _make_clone_pair(tmp_path)

        # Simulate two sequential agent activities, each on its own temp branch
        _git(local, ["checkout", "-b", "agent/task-run1"])
        _write_and_commit(local, "step1.py", "a = 1\n")
        sha1 = _head_sha(local)
        _git(local, ["checkout", "HEAD~0"])
        _git(local, ["branch", "-D", "agent/task-run1"])

        _git(local, ["checkout", "-b", "agent/task-run2", sha1])
        _write_and_commit(local, "step2.py", "b = 2\n")
        sha2 = _head_sha(local)
        _git(local, ["checkout", "HEAD~0"])
        _git(local, ["branch", "-D", "agent/task-run2"])

        # sha2 is the final_sha that the workflow tracks
        with patch("src.activities.get_provider", return_value=None):
            asyncio.run(activities.push_and_create_pr(
                str(local),
                "https://github.com/org/repo.git",
                "agent/final-branch",
                "main",
                "TICK-3",
                final_sha=sha2,
            ))

        remote_result = subprocess.run(
            ["git", "-C", str(remote), "rev-parse", "refs/heads/agent/final-branch"],
            capture_output=True, text=True,
        )
        assert remote_result.returncode == 0
        assert remote_result.stdout.strip() == sha2

        # Both step files must be reachable from the pushed tip
        ls = subprocess.run(
            ["git", "-C", str(remote), "ls-tree", "-r", "--name-only", "agent/final-branch"],
            capture_output=True, text=True, check=True,
        ).stdout
        assert "step1.py" in ls
        assert "step2.py" in ls


# ── push_and_create_pr: base_branch flows to provider ─────────────────────────


class TestBasebranchFlowthrough:
    """base_branch must reach provider.ensure_pr regardless of its value."""

    def _push_ok(self) -> MagicMock:
        m = MagicMock()
        m.returncode = 0
        m.stdout = ""
        m.stderr = ""
        return m

    def test_develop_base_branch_reaches_provider(self):
        mock_provider = MagicMock()
        mock_provider.ensure_pr.return_value = "https://github.com/org/repo/pull/1"

        with patch("subprocess.run", return_value=self._push_ok()), \
             patch("src.activities.get_provider", return_value=mock_provider):
            asyncio.run(activities.push_and_create_pr(
                "/tmp/repo",
                "https://github.com/org/repo.git",
                "agent/task-abc",
                "develop",
                "TICK-99",
                pr_body="## Summary\nDoes something.\n",
            ))

        base_arg = mock_provider.ensure_pr.call_args.args[1]
        assert base_arg == "develop", f"expected 'develop', got {base_arg!r}"

    def test_main_base_branch_reaches_provider(self):
        mock_provider = MagicMock()
        mock_provider.ensure_pr.return_value = ""

        with patch("subprocess.run", return_value=self._push_ok()), \
             patch("src.activities.get_provider", return_value=mock_provider):
            asyncio.run(activities.push_and_create_pr(
                "/tmp/repo",
                "https://github.com/org/repo.git",
                "agent/task-xyz",
                "main",
                "TICK-1",
            ))

        base_arg = mock_provider.ensure_pr.call_args.args[1]
        assert base_arg == "main", f"expected 'main', got {base_arg!r}"

    def test_release_branch_as_base_reaches_provider(self):
        mock_provider = MagicMock()
        mock_provider.ensure_pr.return_value = ""

        with patch("subprocess.run", return_value=self._push_ok()), \
             patch("src.activities.get_provider", return_value=mock_provider):
            asyncio.run(activities.push_and_create_pr(
                "/tmp/repo",
                "https://github.com/org/repo.git",
                "agent/task",
                "release/v2",
                "TICK-1",
            ))

        base_arg = mock_provider.ensure_pr.call_args.args[1]
        assert base_arg == "release/v2", f"expected 'release/v2', got {base_arg!r}"

    def test_push_and_create_pr_title_extracted_from_heading(self):
        """Title passed to ensure_pr is the text of the first markdown heading."""
        mock_provider = MagicMock()
        mock_provider.ensure_pr.return_value = "https://github.com/org/repo/pull/7"

        with patch("subprocess.run", return_value=self._push_ok()), \
             patch("src.activities.get_provider", return_value=mock_provider):
            asyncio.run(activities.push_and_create_pr(
                "/tmp/repo",
                "https://github.com/org/repo.git",
                "agent/task-login",
                "main",
                "PROJ-42",
                pr_body="# Fix login bug\n\nDetails here.",
            ))

        title_arg = mock_provider.ensure_pr.call_args.args[2]
        assert title_arg == "Fix login bug", f"expected 'Fix login bug', got {title_arg!r}"

    def test_push_and_create_pr_title_fallback_when_pr_body_empty(self):
        """When pr_body is empty, ticket_id is used as the PR title."""
        mock_provider = MagicMock()
        mock_provider.ensure_pr.return_value = ""

        with patch("subprocess.run", return_value=self._push_ok()), \
             patch("src.activities.get_provider", return_value=mock_provider):
            asyncio.run(activities.push_and_create_pr(
                "/tmp/repo",
                "https://github.com/org/repo.git",
                "agent/task-proj42",
                "main",
                "PROJ-42",
                pr_body="",
            ))

        title_arg = mock_provider.ensure_pr.call_args.args[2]
        assert title_arg == "PROJ-42", f"expected 'PROJ-42', got {title_arg!r}"

    def test_push_and_create_pr_title_fallback_no_heading(self):
        """When pr_body has no markdown heading, ticket_id is used as the PR title."""
        mock_provider = MagicMock()
        mock_provider.ensure_pr.return_value = ""

        with patch("subprocess.run", return_value=self._push_ok()), \
             patch("src.activities.get_provider", return_value=mock_provider):
            asyncio.run(activities.push_and_create_pr(
                "/tmp/repo",
                "https://github.com/org/repo.git",
                "agent/task-proj42",
                "main",
                "PROJ-42",
                pr_body="Summary paragraph.\n\nDetails without any heading.",
            ))

        title_arg = mock_provider.ensure_pr.call_args.args[2]
        assert title_arg == "PROJ-42", f"expected 'PROJ-42', got {title_arg!r}"

    def test_push_and_create_pr_title_from_non_first_line_heading(self):
        """A markdown heading not on the first line is still extracted as the PR title."""
        mock_provider = MagicMock()
        mock_provider.ensure_pr.return_value = ""

        with patch("subprocess.run", return_value=self._push_ok()), \
             patch("src.activities.get_provider", return_value=mock_provider):
            asyncio.run(activities.push_and_create_pr(
                "/tmp/repo",
                "https://github.com/org/repo.git",
                "agent/task-proj42",
                "main",
                "PROJ-42",
                pr_body="Summary paragraph.\n\n# Fix login bug\n\nDetails here.",
            ))

        title_arg = mock_provider.ensure_pr.call_args.args[2]
        assert title_arg == "Fix login bug", f"expected 'Fix login bug', got {title_arg!r}"

    def test_push_and_create_pr_title_empty_heading_falls_back_to_ticket_id(self):
        """A heading line that strips to '' (e.g. bare '#') falls back to ticket_id."""
        mock_provider = MagicMock()
        mock_provider.ensure_pr.return_value = ""

        with patch("subprocess.run", return_value=self._push_ok()), \
             patch("src.activities.get_provider", return_value=mock_provider):
            asyncio.run(activities.push_and_create_pr(
                "/tmp/repo",
                "https://github.com/org/repo.git",
                "agent/task-proj42",
                "main",
                "PROJ-42",
                pr_body="#\n\nContent here.",
            ))

        title_arg = mock_provider.ensure_pr.call_args.args[2]
        assert title_arg == "PROJ-42", f"expected 'PROJ-42', got {title_arg!r}"

    def test_push_and_create_pr_title_shebang_not_treated_as_heading(self):
        """Lines starting with '#!' or '#word' (no space) are not ATX headings."""
        mock_provider = MagicMock()
        mock_provider.ensure_pr.return_value = ""

        with patch("subprocess.run", return_value=self._push_ok()), \
             patch("src.activities.get_provider", return_value=mock_provider):
            asyncio.run(activities.push_and_create_pr(
                "/tmp/repo",
                "https://github.com/org/repo.git",
                "agent/task-proj42",
                "main",
                "PROJ-42",
                pr_body="#!/usr/bin/env python\n\nNo real heading here.",
            ))

        title_arg = mock_provider.ensure_pr.call_args.args[2]
        assert title_arg == "PROJ-42", f"expected 'PROJ-42', got {title_arg!r}"
