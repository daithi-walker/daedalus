import os

from .base import GitProvider
from .github import GitHubProvider
from .ado import ADOProvider


def get_provider(remote_url: str) -> GitProvider | None:
    """Return the appropriate GitProvider for a remote URL.

    Auto-detects from the URL. Override with DAEDALUS_PR_PROVIDER=github|ado|none.
    Returns None if the provider is unknown or explicitly disabled.
    """
    override = os.environ.get("DAEDALUS_PR_PROVIDER", "").lower()
    provider = override or _detect(remote_url)

    if provider == "github":
        return GitHubProvider(remote_url)
    if provider == "ado":
        return ADOProvider(remote_url)
    if provider == "none":
        return None
    print(f"Unknown provider for {remote_url!r} - skipping PR creation.")
    print("Set DAEDALUS_PR_PROVIDER=github|ado|none to override.")
    return None


def _detect(remote_url: str) -> str:
    url = remote_url.lower()
    if "github.com" in url:
        return "github"
    if "dev.azure.com" in url or "visualstudio.com" in url or "ssh.dev.azure.com" in url:
        return "ado"
    return "unknown"


__all__ = ["GitProvider", "GitHubProvider", "ADOProvider", "get_provider"]
