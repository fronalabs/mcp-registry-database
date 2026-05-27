"""Filter, enrich, and serialize `RegistryServer` models to the output files."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .enrich_github import extract_owner_repo
from .fetch_registry import API_VERSION, REGISTRY_BASE_URL
from .models import Enrichment, RegistryEnvVar, RegistryServer, RegistryStatus

SCHEMA_VERSION = "1.0.0"

# Scope: npm/pypi packages only, with either stdio or HTTP transport. Servers
# with no `packages[]` at all (remote-only entries) are dropped; other package
# registry types (oci/nuget/mcpb) are dropped from kept servers' package lists.
SUPPORTED_REGISTRY_TYPES = frozenset({"npm", "pypi"})
SUPPORTED_TRANSPORTS = frozenset({"stdio", "streamable-http", "sse"})

logger = logging.getLogger(__name__)


def keep_server(server: RegistryServer) -> bool:
    """Filter a server in-place; return True if at least one package survives."""
    kept = [
        p
        for p in server.packages
        if p.registry_type in SUPPORTED_REGISTRY_TYPES
        and p.transport.kind in SUPPORTED_TRANSPORTS
    ]
    if not kept:
        return False
    server.packages = kept
    server.remotes = []
    return True


def apply_filter(servers: list[RegistryServer]) -> list[RegistryServer]:
    return [s for s in servers if keep_server(s)]


def attach_enrichment(
    servers: list[RegistryServer],
    enrichment: dict[tuple[str, str], Enrichment],
) -> None:
    for server in servers:
        repo_url = server.repository.url if server.repository else None
        owner_repo = extract_owner_repo(repo_url)
        if owner_repo and owner_repo in enrichment:
            server.enrichment = enrichment[owner_repo]


def attach_inferred_env_vars(
    servers: list[RegistryServer],
    inferred: dict[tuple[str, str], list[tuple[str, bool]]],
) -> None:
    """Populate `environment_variables` on each package of a server whose
    registry entry didn't declare any, using the (name, is_secret) pairs we
    parsed from a `.env.example` file. Entries are tagged with
    `source="env-example"` so consumers can tell them apart from upstream data.
    """
    for server in servers:
        if any(p.environment_variables for p in server.packages):
            continue
        repo_url = server.repository.url if server.repository else None
        owner_repo = extract_owner_repo(repo_url)
        if not owner_repo or owner_repo not in inferred:
            continue
        synthesized = [
            RegistryEnvVar(name=name, is_secret=is_secret, source="env-example")
            for name, is_secret in inferred[owner_repo]
        ]
        if not synthesized:
            continue
        for pkg in server.packages:
            pkg.environment_variables = list(synthesized)


def compute_counts(servers: list[RegistryServer]) -> dict[str, Any]:
    active = 0
    deprecated = 0
    with_repo = 0
    enriched = 0
    with_env_vars = 0
    with_inferred_env_vars = 0
    by_registry: dict[str, int] = {}

    for s in servers:
        if s.status == RegistryStatus.ACTIVE:
            active += 1
        elif s.status in (RegistryStatus.DEPRECATED, RegistryStatus.DELETED):
            deprecated += 1

        if s.repository and s.repository.url:
            with_repo += 1
        if s.enrichment:
            enriched += 1

        any_env = any(p.environment_variables for p in s.packages)
        if any_env:
            with_env_vars += 1
        any_inferred = any(
            ev.source == "env-example"
            for p in s.packages
            for ev in p.environment_variables
        )
        if any_inferred:
            with_inferred_env_vars += 1

        seen = {p.registry_type for p in s.packages}
        for r in seen:
            by_registry[r] = by_registry.get(r, 0) + 1

    return {
        "total_servers": len(servers),
        "active": active,
        "deprecated": deprecated,
        "with_github_repo": with_repo,
        "enriched_with_github": enriched,
        "with_env_vars": with_env_vars,
        "with_inferred_env_vars": with_inferred_env_vars,
        "by_registry_type": by_registry,
    }


def write_outputs(
    output_dir: Path,
    servers: list[RegistryServer],
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    servers_path = output_dir / "servers.json"
    metadata_path = output_dir / "metadata.json"

    dumped = [s.dump_pruned() for s in servers]
    payload = json.dumps(
        dumped, separators=(",", ":"), ensure_ascii=False, default=_json_default
    ).encode("utf-8")
    servers_path.write_bytes(payload)

    content_sha256 = hashlib.sha256(payload).hexdigest()

    metadata = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "source": {
            "registry_base_url": REGISTRY_BASE_URL,
            "registry_api_version": API_VERSION,
        },
        "counts": compute_counts(servers),
        "content_sha256": content_sha256,
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )

    logger.info(
        "wrote %s (%d bytes) and %s",
        servers_path,
        len(payload),
        metadata_path,
    )
    return metadata


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat().replace("+00:00", "Z")
    raise TypeError(f"{type(obj).__name__} is not JSON serializable")
