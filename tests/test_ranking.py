from datetime import datetime, timedelta, timezone

from scripts.models import (
    Enrichment,
    RegistryPackage,
    RegistryServer,
    RegistryStatus,
    RegistryTransport,
)
from scripts.ranking import DEFAULT_WEIGHTS, ScoreWeights, compute_score, rank


NOW = datetime(2026, 4, 1, tzinfo=timezone.utc)


def _base(name: str = "x/y") -> RegistryServer:
    return RegistryServer(
        name=name,
        description="d",
        version="1.0.0",
        packages=[
            RegistryPackage(
                registryType="npm",
                identifier=name,
                version="1.0.0",
                transport=RegistryTransport(type="stdio"),
            )
        ],
        status=RegistryStatus.ACTIVE,
    )


def _enrichment(**kwargs) -> Enrichment:
    defaults = {
        "enriched_at": NOW,
        "github_topics": [],
    }
    defaults.update(kwargs)
    return Enrichment(**defaults)


def test_deleted_status_scores_zero():
    s = _base()
    s.status = RegistryStatus.DELETED
    assert compute_score(s, now=NOW) == 0.0


def test_disabled_repo_scores_zero_even_with_stars():
    s = _base()
    s.enrichment = _enrichment(github_stars=10_000, github_is_disabled=True)
    assert compute_score(s, now=NOW) == 0.0


def test_missing_enrichment_scores_small_positive():
    s = _base()
    score = compute_score(s, now=NOW)
    assert 0.0 < score < 5.0


def test_stars_rank_logarithmically():
    def score_for(stars: int) -> float:
        s = _base()
        s.enrichment = _enrichment(github_stars=stars, github_pushed_at=NOW)
        return compute_score(s, now=NOW)

    s100 = score_for(100)
    s1k = score_for(1_000)
    s10k = score_for(10_000)
    assert s100 < s1k < s10k
    # Each decade adds roughly the same increment (log-scale property).
    assert abs((s1k - s100) - (s10k - s1k)) < 0.5


def test_recency_decays():
    def score_for(days_stale: int) -> float:
        s = _base()
        s.enrichment = _enrichment(
            github_stars=1_000,
            github_pushed_at=NOW - timedelta(days=days_stale),
        )
        return compute_score(s, now=NOW)

    assert score_for(0) > score_for(180) > score_for(720)


def test_archived_fork_deprecated_penalties():
    def baseline() -> RegistryServer:
        s = _base()
        s.enrichment = _enrichment(github_stars=1_000, github_pushed_at=NOW)
        return s

    base_score = compute_score(baseline(), now=NOW)

    archived = baseline()
    archived.enrichment.github_archived = True
    assert compute_score(archived, now=NOW) < base_score * 0.5

    forked = baseline()
    forked.enrichment.github_is_fork = True
    assert compute_score(forked, now=NOW) < base_score * 0.75

    deprecated = baseline()
    deprecated.status = RegistryStatus.DEPRECATED
    assert compute_score(deprecated, now=NOW) < base_score * 0.5


def test_rank_sorts_descending_and_attaches_score_field():
    popular_fresh = _base("a/popular")
    popular_fresh.enrichment = _enrichment(github_stars=5_000, github_pushed_at=NOW)

    tiny_fresh = _base("b/tiny")
    tiny_fresh.enrichment = _enrichment(github_stars=5, github_pushed_at=NOW)

    popular_stale = _base("c/stale")
    popular_stale.enrichment = _enrichment(
        github_stars=5_000,
        github_pushed_at=NOW - timedelta(days=1000),
    )

    no_enrichment = _base("d/unknown")

    servers = [no_enrichment, tiny_fresh, popular_stale, popular_fresh]
    rank(servers, now=NOW)

    assert servers[0].name == "a/popular"
    assert servers[-1].name == "d/unknown"
    assert all(s.score is not None for s in servers)
    assert servers[0].score > servers[1].score


def test_custom_weights_override_defaults():
    s = _base()
    s.enrichment = _enrichment(github_stars=1_000, github_pushed_at=NOW)

    default_score = compute_score(s, now=NOW)
    double_stars = compute_score(
        s,
        now=NOW,
        weights=ScoreWeights(
            stars=DEFAULT_WEIGHTS.stars * 2,
            forks=DEFAULT_WEIGHTS.forks,
            recency=DEFAULT_WEIGHTS.recency,
            license=DEFAULT_WEIGHTS.license,
            topics=DEFAULT_WEIGHTS.topics,
            recency_half_life_days=DEFAULT_WEIGHTS.recency_half_life_days,
            archived_penalty=DEFAULT_WEIGHTS.archived_penalty,
            fork_penalty=DEFAULT_WEIGHTS.fork_penalty,
            deprecated_penalty=DEFAULT_WEIGHTS.deprecated_penalty,
            missing_enrichment_score=DEFAULT_WEIGHTS.missing_enrichment_score,
        ),
    )
    assert double_stars > default_score
