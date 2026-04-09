from datetime import datetime, timezone

from scripts.enrich_github import _node_to_enrichment, build_query, extract_owner_repo


def test_extract_owner_repo_plain():
    assert extract_owner_repo("https://github.com/foo/bar") == ("foo", "bar")


def test_extract_owner_repo_git_suffix():
    assert extract_owner_repo("https://github.com/foo/bar.git") == ("foo", "bar")


def test_extract_owner_repo_trailing_path():
    assert extract_owner_repo("https://github.com/foo/bar/tree/main") == ("foo", "bar")


def test_extract_owner_repo_rejects_non_github():
    assert extract_owner_repo("https://gitlab.com/foo/bar") is None
    assert extract_owner_repo(None) is None
    assert extract_owner_repo("") is None


def test_extract_owner_repo_case_insensitive_host():
    assert extract_owner_repo("https://GitHub.com/FOO/BAR") == ("FOO", "BAR")


def test_build_query_uses_aliases():
    q = build_query([("a", "b"), ("c", "d")])
    assert "r0: repository(" in q
    assert "r1: repository(" in q
    assert 'owner: "a"' in q
    assert 'name: "b"' in q


def test_build_query_requests_all_enrichment_fields():
    q = build_query([("a", "b")])
    expected = [
        "stargazerCount",
        "forkCount",
        "createdAt",
        "pushedAt",
        "isArchived",
        "isDisabled",
        "isFork",
        "watchers",
        "issues(states: OPEN)",
        "pullRequests(states: OPEN)",
        "licenseInfo",
        "spdxId",
        "primaryLanguage",
        "repositoryTopics",
        "owner",
        "avatarUrl",
    ]
    for field in expected:
        assert field in q, f"missing {field} in query"


def test_node_to_enrichment_parses_full_response():
    node = {
        "stargazerCount": 2060,
        "forkCount": 150,
        "createdAt": "2024-08-15T10:22:00Z",
        "pushedAt": "2026-03-28T21:15:32Z",
        "isArchived": False,
        "isDisabled": False,
        "isFork": False,
        "watchers": {"totalCount": 42},
        "issues": {"totalCount": 7},
        "pullRequests": {"totalCount": 3},
        "licenseInfo": {"spdxId": "MIT"},
        "primaryLanguage": {"name": "Python"},
        "repositoryTopics": {
            "nodes": [
                {"topic": {"name": "mcp"}},
                {"topic": {"name": "google-workspace"}},
            ]
        },
        "owner": {"avatarUrl": "https://avatars.githubusercontent.com/u/1234"},
    }
    now = datetime(2026, 4, 9, tzinfo=timezone.utc)
    e = _node_to_enrichment(node, now)
    assert e.github_stars == 2060
    assert e.github_forks == 150
    assert e.github_watchers == 42
    assert e.github_open_issues == 7
    assert e.github_open_pull_requests == 3
    assert e.github_is_fork is False
    assert e.github_is_disabled is False
    assert e.github_archived is False
    assert e.github_license == "MIT"
    assert e.github_primary_language == "Python"
    assert e.github_topics == ["mcp", "google-workspace"]
    assert e.github_owner_avatar_url.startswith("https://avatars.")
    assert e.enriched_at == now


def test_node_to_enrichment_tolerates_missing_nested_fields():
    # Repos with no license, no language, no topics, no watchers, etc.
    node = {
        "stargazerCount": 3,
        "forkCount": 0,
        "createdAt": "2025-01-01T00:00:00Z",
        "pushedAt": "2025-01-01T00:00:00Z",
        "isArchived": False,
        "isDisabled": False,
        "isFork": False,
        "watchers": None,
        "issues": None,
        "pullRequests": None,
        "licenseInfo": None,
        "primaryLanguage": None,
        "repositoryTopics": None,
        "owner": None,
    }
    now = datetime(2026, 4, 9, tzinfo=timezone.utc)
    e = _node_to_enrichment(node, now)
    assert e.github_stars == 3
    assert e.github_watchers is None
    assert e.github_open_issues is None
    assert e.github_open_pull_requests is None
    assert e.github_license is None
    assert e.github_primary_language is None
    assert e.github_topics == []
    assert e.github_owner_avatar_url is None
