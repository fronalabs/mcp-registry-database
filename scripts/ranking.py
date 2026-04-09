"""Compute a single quality score per server from the enrichment signals.

The score is baked into each entry at build time so every consumer of the dump
gets the same ranking without re-deriving it per query. Design rules:

- Log-scale popularity (stars/forks follow a power law — the 10k-star repo
  should beat the 100-star one, but not by 100x).
- Exponential decay on recency so a server stale for a year falls below a
  server pushed last week, regardless of star count.
- Hard floor at 0.0 for `deleted` / disabled repos so they can be dropped from
  listings without a separate predicate.
- Soft multiplicative penalties for deprecated, archived, and fork — they stay
  visible but rank below healthy peers.
- Missing enrichment scores a small fixed fallback so these entries don't
  disappear entirely from un-ranked listings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from .models import RegistryServer, RegistryStatus


@dataclass(frozen=True)
class ScoreWeights:
    stars: float = 10.0
    forks: float = 3.0
    recency: float = 15.0
    license: float = 2.0
    topics: float = 1.0
    recency_half_life_days: float = 180.0
    archived_penalty: float = 0.2
    fork_penalty: float = 0.5
    deprecated_penalty: float = 0.3
    missing_enrichment_score: float = 1.0


DEFAULT_WEIGHTS = ScoreWeights()


def compute_score(
    server: RegistryServer,
    *,
    now: datetime | None = None,
    weights: ScoreWeights = DEFAULT_WEIGHTS,
) -> float:
    """Quality score for a server. Higher is better. Always >= 0."""
    if server.status == RegistryStatus.DELETED:
        return 0.0

    enrichment = server.enrichment
    if enrichment is None:
        return weights.missing_enrichment_score

    if enrichment.github_is_disabled is True:
        return 0.0

    score = 0.0
    score += _log1p_weighted(enrichment.github_stars, weights.stars)
    score += _log1p_weighted(enrichment.github_forks, weights.forks)
    score += (
        _recency_score(
            enrichment.github_pushed_at,
            now or datetime.now(timezone.utc),
            weights.recency_half_life_days,
        )
        * weights.recency
    )

    if enrichment.github_license:
        score += weights.license
    if enrichment.github_topics:
        score += weights.topics

    if enrichment.github_archived is True:
        score *= weights.archived_penalty
    if enrichment.github_is_fork is True:
        score *= weights.fork_penalty
    if server.status == RegistryStatus.DEPRECATED:
        score *= weights.deprecated_penalty

    return max(score, 0.0)


def rank(
    servers: list[RegistryServer],
    *,
    now: datetime | None = None,
    weights: ScoreWeights = DEFAULT_WEIGHTS,
) -> None:
    """Sort `servers` in place, descending by score, and attach the computed
    score to each entry's `score` field."""
    frozen_now = now or datetime.now(timezone.utc)
    for s in servers:
        s.score = compute_score(s, now=frozen_now, weights=weights)
    servers.sort(key=lambda s: s.score or 0.0, reverse=True)


def _log1p_weighted(value: int | None, weight: float) -> float:
    return math.log10((value or 0) + 1) * weight


def _recency_score(
    pushed_at: datetime | None,
    now: datetime,
    half_life_days: float,
) -> float:
    if pushed_at is None:
        return 0.0
    if pushed_at.tzinfo is None:
        pushed_at = pushed_at.replace(tzinfo=timezone.utc)
    days = max((now - pushed_at).days, 0)
    return math.exp(-days / half_life_days)
