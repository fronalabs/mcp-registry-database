"""Orchestrator: paginate registry → enrich via GitHub → write output files."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import httpx
from httpx_retries import Retry, RetryTransport

from .build_output import apply_filter, attach_enrichment, write_outputs
from .enrich_github import enrich_all, extract_owner_repo
from .fetch_registry import paginate, row_to_server
from .models import Repository
from .ranking import rank
from .resolve_repo import resolve_repo_url


def _build_client() -> httpx.Client:
    # Retry transient failures with exponential backoff. Honors `Retry-After`
    # on 429 (the only header the registries we hit actually set).
    retry = Retry(
        total=5,
        backoff_factor=1.0,
        backoff_jitter=0.5,
        max_backoff_wait=30.0,
        status_forcelist=[408, 429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        respect_retry_after_header=True,
    )
    return httpx.Client(
        transport=RetryTransport(retry=retry),
        timeout=30.0,
        http2=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("."),
        help="Where to write servers.json and metadata.json.",
    )
    parser.add_argument(
        "--skip-enrichment",
        action="store_true",
        help="Skip the GitHub enrichment pass (useful for local dev).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("sync")

    with _build_client() as client:
        log.info("paginating registry…")
        rows = paginate(client)
        log.info("fetched %d rows", len(rows))

        servers = [row_to_server(r) for r in rows]
        before = len(servers)
        servers = apply_filter(servers)
        log.info(
            "kept %d / %d servers after npm/pypi stdio filter",
            len(servers),
            before,
        )

        # Recover missing repository URLs from the package registries (npm/pypi).
        # Drop any server that still has no repository URL afterwards.
        missing = [s for s in servers if not (s.repository and s.repository.url)]
        if missing:
            log.info(
                "resolving repository URL from package registries for %d server(s)…",
                len(missing),
            )
            recovered = 0
            for s in missing:
                for pkg in s.packages:
                    url = resolve_repo_url(client, pkg)
                    if url:
                        s.repository = Repository(url=url)
                        recovered += 1
                        break
            log.info("recovered %d / %d missing repo URLs", recovered, len(missing))

        before_drop = len(servers)
        servers = [s for s in servers if s.repository and s.repository.url]
        dropped = before_drop - len(servers)
        if dropped:
            log.info("dropped %d server(s) with no resolvable repository URL", dropped)

        if not args.skip_enrichment:
            token = os.environ.get("GITHUB_TOKEN")
            if not token:
                log.error("GITHUB_TOKEN not set; cannot enrich")
                return 2

            repos: list[tuple[str, str]] = []
            seen: set[tuple[str, str]] = set()
            for s in servers:
                repo_url = s.repository.url if s.repository else None
                owner_repo = extract_owner_repo(repo_url)
                if owner_repo and owner_repo not in seen:
                    seen.add(owner_repo)
                    repos.append(owner_repo)
            log.info("resolved %d unique GitHub repos", len(repos))

            enrichment = enrich_all(client, token, repos)
            log.info("enrichment returned %d entries", len(enrichment))
            attach_enrichment(servers, enrichment)

        rank(servers)
        log.info("ranked %d servers by quality score", len(servers))

        metadata = write_outputs(args.output_dir, servers)
        counts = metadata["counts"]
        log.info(
            "done. total=%d active=%d enriched=%d by_registry=%s",
            counts["total_servers"],
            counts["active"],
            counts["enriched_with_github"],
            counts["by_registry_type"],
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
