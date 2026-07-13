from abc import ABC, abstractmethod


class GitProvider(ABC):
    """Abstract interface for a remote git hosting provider."""

    @abstractmethod
    def create_pr(self, branch: str, base: str, title: str, body: str) -> str | None:
        """Create a PR and return its URL, or None on failure."""

    @abstractmethod
    def find_pr(self, branch: str, base: str) -> str | None:
        """Return the URL of an existing open PR for this branch, or None."""

    def ensure_pr(self, branch: str, base: str, title: str, body: str) -> str | None:
        """Create a PR, or return an existing one if it already exists."""
        url = self.create_pr(branch, base, title, body)
        if url:
            return url
        return self.find_pr(branch, base)
