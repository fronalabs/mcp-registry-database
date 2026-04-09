"""Resolve GitHub repos from server entries and enrich with star/fork/activity data."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx

from .models import Enrichment

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
GRAPHQL_BATCH_SIZE = 50

logger = logging.getLogger(__name__)

_GITHUB_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s#?]+)",
    re.IGNORECASE,
)


def extract_owner_repo(url: str | None) -> tuple[str, str] | None:
    if not url:
        return None
    match = _GITHUB_URL_RE.match(url.strip())
    if not match:
        return None
    owner = match.group("owner")
    repo = match.group("repo").removesuffix(".git")
    if not owner or not repo:
        return None
    return owner, repo


_REPO_FIELDS = """
  stargazerCount
  forkCount
  createdAt
  pushedAt
  isArchived
  isDisabled
  isFork
  watchers { totalCount }
  issues(states: OPEN) { totalCount }
  pullRequests(states: OPEN) { totalCount }
  licenseInfo { spdxId }
  primaryLanguage { name }
  repositoryTopics(first: 10) { nodes { topic { name } } }
  owner { avatarUrl }
"""


def build_query(repos: list[tuple[str, str]]) -> str:
    fragments = []
    for i, (owner, repo) in enumerate(repos):
        owner_esc = owner.replace('"', '\\"')
        repo_esc = repo.replace('"', '\\"')
        fragments.append(
            f'r{i}: repository(owner: "{owner_esc}", name: "{repo_esc}") {{'
            f"{_REPO_FIELDS}}}"
        )
    return "query BatchRepoLookup { " + " ".join(fragments) + " }"


def enrich_batch(
    client: httpx.Client,
    token: str,
    repos: list[tuple[str, str]],
) -> dict[tuple[str, str], Enrichment]:
    if not repos:
        return {}
    query = build_query(repos)
    response = client.post(
        GITHUB_GRAPHQL_URL,
        json={"query": query},
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "mcp-registry-database",
        },
    )
    response.raise_for_status()
    payload = response.json()

    data = payload.get("data") or {}
    now = datetime.now(timezone.utc)
    results: dict[tuple[str, str], Enrichment] = {}
    for i, (owner, repo) in enumerate(repos):
        node = data.get(f"r{i}")
        if not node:
            # Repo deleted / private / moved — GraphQL returns null for the alias.
            continue
        results[(owner, repo)] = _node_to_enrichment(node, now)
    return results


def _node_to_enrichment(node: dict[str, Any], enriched_at: datetime) -> Enrichment:
    license_info = node.get("licenseInfo") or {}
    primary_language = node.get("primaryLanguage") or {}
    owner = node.get("owner") or {}
    topics_wrapper = node.get("repositoryTopics") or {}
    topic_nodes = topics_wrapper.get("nodes") or []
    topics = [
        t["topic"]["name"]
        for t in topic_nodes
        if isinstance(t, dict) and t.get("topic", {}).get("name")
    ]
    return Enrichment(
        github_stars=node.get("stargazerCount"),
        github_forks=node.get("forkCount"),
        github_watchers=(node.get("watchers") or {}).get("totalCount"),
        github_open_issues=(node.get("issues") or {}).get("totalCount"),
        github_open_pull_requests=(node.get("pullRequests") or {}).get("totalCount"),
        github_created_at=node.get("createdAt"),
        github_pushed_at=node.get("pushedAt"),
        github_is_fork=node.get("isFork"),
        github_is_disabled=node.get("isDisabled"),
        github_archived=node.get("isArchived"),
        github_license=license_info.get("spdxId"),
        github_primary_language=primary_language.get("name"),
        github_topics=topics,
        github_owner_avatar_url=owner.get("avatarUrl"),
        enriched_at=enriched_at,
    )


def enrich_all(
    client: httpx.Client,
    token: str,
    repos: Iterable[tuple[str, str]],
    batch_size: int = GRAPHQL_BATCH_SIZE,
) -> dict[tuple[str, str], Enrichment]:
    unique = list(dict.fromkeys(repos))
    out: dict[tuple[str, str], Enrichment] = {}
    for i in range(0, len(unique), batch_size):
        chunk = unique[i : i + batch_size]
        logger.info("enriching batch %d..%d / %d", i, i + len(chunk), len(unique))
        try:
            out.update(enrich_batch(client, token, chunk))
        except httpx.HTTPError as e:
            logger.warning("batch failed (%s); skipping", e)
    return out
