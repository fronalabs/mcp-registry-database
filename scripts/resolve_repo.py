"""Fallback repository-URL resolver for servers whose registry entry has no repo.

Called only for entries missing `repository.url` — we look up the package in
its native registry (npm or PyPI) and extract a URL from the package metadata.
Servers that still have no URL after this pass are dropped by the caller.
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import Optional

import httpx

from .models import RegistryPackage

logger = logging.getLogger(__name__)

NPM_REGISTRY_URL = "https://registry.npmjs.org"
PYPI_JSON_URL = "https://pypi.org/pypi"

# PyPI project_urls keys to probe in priority order.
_PYPI_REPO_KEYS = ("Repository", "Source", "Source Code", "Code")
_PYPI_FALLBACK_KEYS = ("Homepage", "Documentation", "Issues")


def resolve_repo_url(
    client: httpx.Client, package: RegistryPackage
) -> Optional[str]:
    if package.registry_type == "npm":
        return _fetch_npm_repo(client, package.identifier)
    if package.registry_type == "pypi":
        return _fetch_pypi_repo(client, package.identifier)
    return None


def _fetch_npm_repo(client: httpx.Client, identifier: str) -> Optional[str]:
    url = f"{NPM_REGISTRY_URL}/{urllib.parse.quote(identifier, safe='@/')}"
    data = _get_json(client, url)
    if not data:
        return None

    repo = data.get("repository")
    if isinstance(repo, dict):
        candidate = repo.get("url")
    elif isinstance(repo, str):
        candidate = repo
    else:
        candidate = None

    if candidate:
        return _clean_git_url(candidate)

    homepage = data.get("homepage")
    if isinstance(homepage, str) and homepage:
        return homepage

    return None


def _fetch_pypi_repo(client: httpx.Client, identifier: str) -> Optional[str]:
    url = f"{PYPI_JSON_URL}/{urllib.parse.quote(identifier, safe='')}/json"
    data = _get_json(client, url)
    if not data:
        return None

    info = data.get("info") or {}
    project_urls = info.get("project_urls") or {}

    for key in _PYPI_REPO_KEYS:
        value = project_urls.get(key)
        if value:
            return value

    for key in _PYPI_FALLBACK_KEYS:
        value = project_urls.get(key)
        if value and "github.com" in value:
            return value

    for key in _PYPI_FALLBACK_KEYS:
        value = project_urls.get(key)
        if value:
            return value

    home = info.get("home_page")
    if isinstance(home, str) and home:
        return home

    return None


def _get_json(client: httpx.Client, url: str) -> Optional[dict]:
    try:
        response = client.get(url, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.debug("package lookup failed for %s: %s", url, e)
        return None


def _clean_git_url(url: str) -> str:
    """Normalize npm's `git+https://...git` to a plain HTTPS URL."""
    url = url.strip()
    url = url.removeprefix("git+")
    if url.startswith("git://"):
        url = "https://" + url[len("git://") :]
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url[len("git@github.com:") :]
    url = url.removesuffix(".git")
    return url
