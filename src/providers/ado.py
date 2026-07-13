import json
import os
import subprocess
from urllib.parse import urlparse, unquote

from .base import GitProvider


class ADOProvider(GitProvider):
    def __init__(self, remote_url: str) -> None:
        self.remote_url = remote_url
        self.org_url, self.project, self.repo = self._parse_url(remote_url)

    @staticmethod
    def _parse_url(remote_url: str) -> tuple[str, str, str]:
        """Parse ADO remote URL into (org_url, project, repo).

        Handles:
          HTTPS: https://dev.azure.com/{org}/{project}/_git/{repo}
          SSH:   git@ssh.dev.azure.com:v3/{org}/{project}/{repo}
        """
        if "dev.azure.com" in remote_url and not remote_url.startswith("git@"):
            path = urlparse(remote_url).path.lstrip("/")
            parts = path.split("/")
            org = parts[0]
            project = unquote(parts[1])
            repo = unquote(parts[3]).replace(".git", "") if len(parts) > 3 else parts[2].replace(".git", "")
            return f"https://dev.azure.com/{org}", project, repo

        if "ssh.dev.azure.com" in remote_url:
            path = remote_url.split(":v3/", 1)[-1]
            parts = path.split("/")
            org, project, repo = parts[0], parts[1], parts[2].replace(".git", "")
            return f"https://dev.azure.com/{org}", project, repo

        raise ValueError(f"Cannot parse ADO URL: {remote_url!r}")

    def _env(self) -> dict:
        env = os.environ.copy()
        pat = os.environ.get("AZURE_DEVOPS_PAT", "")
        if pat:
            env["AZURE_DEVOPS_EXT_PAT"] = pat
        return env

    def _pr_url(self, pr_id: int) -> str:
        return f"{self.org_url}/{self.project}/_git/{self.repo}/pullrequest/{pr_id}"

    def create_pr(self, branch: str, base: str, title: str, body: str) -> str | None:
        result = subprocess.run(
            ["az", "repos", "pr", "create",
             "--org", self.org_url,
             "--project", self.project,
             "--repository", self.repo,
             "--source-branch", branch,
             "--target-branch", base,
             "--title", title,
             "--description", body,
             "--output", "json"],
            capture_output=True, text=True, env=self._env(),
        )
        if result.returncode == 0:
            try:
                pr_id = json.loads(result.stdout)["pullRequestId"]
                return self._pr_url(pr_id)
            except (json.JSONDecodeError, KeyError):
                return result.stdout.strip()
        return None

    def find_pr(self, branch: str, base: str) -> str | None:
        result = subprocess.run(
            ["az", "repos", "pr", "list",
             "--org", self.org_url,
             "--project", self.project,
             "--repository", self.repo,
             "--source-branch", branch,
             "--target-branch", base,
             "--output", "json"],
            capture_output=True, text=True, env=self._env(),
        )
        if result.returncode == 0:
            try:
                prs = json.loads(result.stdout)
                if prs:
                    return self._pr_url(prs[0]["pullRequestId"])
            except (json.JSONDecodeError, KeyError, IndexError):
                pass
        return None
