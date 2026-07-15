"""Docker Hub search + registry API calls.

No authentication is required for any of this — the registry token endpoint
issues anonymous pull-scoped tokens for public images.
"""

from __future__ import annotations

import requests

SEARCH_URL = "https://hub.docker.com/v2/search/repositories/"
NAMESPACE_REPOS_URL = "https://hub.docker.com/v2/repositories/{namespace}/"
AUTH_URL = "https://auth.docker.io/token"
REGISTRY_URL = "https://registry-1.docker.io"

# Boosted in the image picker so your own low-traffic images surface even for a
# short prefix — Docker Hub's search API tokenizes on hyphens (each segment must
# match a whole word), which makes it unreliable for hyphenated names like
# "pto-tracker" while still mid-typing. Listing the namespace directly sidesteps
# that entirely since it doesn't go through the search/query tokenizer.
PERSONAL_NAMESPACE = "solublespork"

MANIFEST_ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)

TIMEOUT = 10


class DockerHubError(Exception):
    """Raised when a Docker Hub / registry call fails."""


def _registry_repo(repo: str) -> str:
    """Official images (e.g. 'nginx') live under 'library/' in the registry API."""
    return repo if "/" in repo else f"library/{repo}"


def search_repositories(query: str, page_size: int = 10) -> list[dict]:
    """Live-search Docker Hub. Returns raw results, no re-ranking."""
    if not query.strip():
        return []
    try:
        resp = requests.get(
            SEARCH_URL,
            params={"query": query, "page_size": page_size},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise DockerHubError(f"Docker Hub search failed: {exc}") from exc
    return resp.json().get("results", [])


def list_namespace_repos(namespace: str = PERSONAL_NAMESPACE, page_size: int = 100) -> list[dict]:
    """List all repos under a namespace directly — not a search query, so it's
    immune to the hyphen-tokenization issue in search_repositories()."""
    try:
        resp = requests.get(
            NAMESPACE_REPOS_URL.format(namespace=namespace),
            params={"page_size": page_size},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise DockerHubError(f"Failed to list repos for namespace {namespace}: {exc}") from exc
    return resp.json().get("results", [])


def get_anon_token(repo: str) -> str:
    registry_repo = _registry_repo(repo)
    try:
        resp = requests.get(
            AUTH_URL,
            params={
                "service": "registry.docker.io",
                "scope": f"repository:{registry_repo}:pull",
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise DockerHubError(f"Failed to get registry token for {repo}: {exc}") from exc
    return resp.json()["token"]


def list_tags(repo: str, token: str, limit: int = 100) -> list[str]:
    registry_repo = _registry_repo(repo)
    try:
        resp = requests.get(
            f"{REGISTRY_URL}/v2/{registry_repo}/tags/list",
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise DockerHubError(f"Failed to list tags for {repo}: {exc}") from exc
    tags = resp.json().get("tags") or []
    return sorted(tags)[:limit]


def _get_manifest(registry_repo: str, reference: str, token: str) -> dict:
    resp = requests.get(
        f"{REGISTRY_URL}/v2/{registry_repo}/manifests/{reference}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": MANIFEST_ACCEPT,
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def get_declared_volumes(repo: str, tag: str) -> list[str]:
    """Return the container-side paths declared via VOLUME in the image's Dockerfile.

    Resolves multi-arch manifest lists to linux/amd64 before reading the config blob.
    Returns an empty list if the image declares no volumes.
    """
    registry_repo = _registry_repo(repo)
    token = get_anon_token(repo)

    try:
        manifest = _get_manifest(registry_repo, tag, token)

        if manifest.get("manifests"):
            # Manifest list / OCI index — resolve to linux/amd64.
            candidates = manifest["manifests"]
            match = next(
                (
                    m
                    for m in candidates
                    if m.get("platform", {}).get("architecture") == "amd64"
                    and m.get("platform", {}).get("os") == "linux"
                ),
                candidates[0] if candidates else None,
            )
            if match is None:
                return []
            manifest = _get_manifest(registry_repo, match["digest"], token)

        config_digest = manifest.get("config", {}).get("digest")
        if not config_digest:
            return []

        resp = requests.get(
            f"{REGISTRY_URL}/v2/{registry_repo}/blobs/{config_digest}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        config = resp.json()
    except requests.RequestException as exc:
        raise DockerHubError(f"Failed to inspect image config for {repo}:{tag}: {exc}") from exc

    volumes = config.get("config", {}).get("Volumes") or {}
    return sorted(volumes.keys())
