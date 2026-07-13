import subprocess
from urllib.parse import urlparse

from .base import GitProvider


class GitHubProvider(GitProvider):
    def __init__(self, remote_url: str) -> None:
        self.remote_url = remote_url
        self.repo = self._parse_repo(remote_url)

    @staticmethod
    def _parse_repo(remote_url: str) -> str:
        if remote_url.startswith("git@github.com:"):
            return remote_url.split(":")[-1].replace(".git", "")
        return urlparse(remote_url).path.lstrip("/").replace(".git", "")

    def create_pr(self, branch: str, base: str, title: str, body: str) -> str | None:
        result = subprocess.run(
            ["gh", "pr", "create",
             "--repo", self.repo,
             "--head", branch,
             "--base", base,
             "--title", title,
             "--body", body],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        print(f"gh pr create failed (exit {result.returncode}): {result.stderr.strip()}")
        return None

    def find_pr(self, branch: str, base: str) -> str | None:
        result = subprocess.run(
            ["gh", "pr", "view", branch,
             "--repo", self.repo,
             "--json", "url",
             "--jq", ".url"],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None
