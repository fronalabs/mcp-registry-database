import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.build_output import (
    apply_filter,
    attach_enrichment,
    compute_counts,
    keep_server,
    write_outputs,
)
from scripts.fetch_registry import row_to_server
from scripts.models import (
    Enrichment,
    RegistryArgument,
    RegistryEnvVar,
    RegistryPackage,
    RegistryServer,
    RegistryTransport,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "registry-sample.json"


def load_servers() -> list[RegistryServer]:
    rows = json.loads(FIXTURE.read_text())["servers"]
    return [row_to_server(r) for r in rows]


def _pkg(registry_type: str, identifier: str, transport: str = "stdio") -> RegistryPackage:
    return RegistryPackage(
        registry_type=registry_type,
        identifier=identifier,
        transport=RegistryTransport(kind=transport),
    )


def test_attach_enrichment_matches_by_repo_url():
    servers = apply_filter(load_servers())
    enrichment = {
        ("taylorwilsdon", "google_workspace_mcp"): Enrichment(
            github_stars=2060,
            github_forks=150,
            github_archived=False,
            enriched_at=datetime(2026, 4, 9, tzinfo=timezone.utc),
        )
    }
    attach_enrichment(servers, enrichment)
    hit = next(s for s in servers if "taylorwilsdon" in s.name)
    assert hit.enrichment is not None
    assert hit.enrichment.github_stars == 2060
    others = [s for s in servers if "taylorwilsdon" not in s.name]
    assert all(s.enrichment is None for s in others)


def test_apply_filter_drops_remote_only_server():
    servers = load_servers()
    assert len(servers) == 3
    filtered = apply_filter(servers)
    assert len(filtered) == 2
    names = {s.name for s in filtered}
    assert "ac.tandem/docs-mcp" not in names
    assert "io.github.taylorwilsdon/workspace-mcp" in names
    assert "io.github.domdomegg/gmail-mcp" in names


def test_keep_server_drops_non_npm_pypi_packages():
    server = RegistryServer(
        name="x/y",
        description="d",
        version="1",
        packages=[
            _pkg("npm", "keep-me"),
            _pkg("oci", "drop-me"),
            _pkg("nuget", "drop-me-2"),
        ],
    )
    assert keep_server(server) is True
    assert len(server.packages) == 1
    assert server.packages[0].identifier == "keep-me"


def test_keep_server_accepts_http_transport():
    server = RegistryServer(
        name="x/y",
        description="d",
        version="1",
        packages=[_pkg("pypi", "http-server", transport="streamable-http")],
    )
    assert keep_server(server) is True
    assert len(server.packages) == 1


def test_keep_server_drops_unsupported_transport():
    server = RegistryServer(
        name="x/y",
        description="d",
        version="1",
        packages=[_pkg("npm", "weird-transport", transport="websocket")],
    )
    assert keep_server(server) is False


def test_keep_server_clears_remotes():
    server = RegistryServer(
        name="x/y",
        description="d",
        version="1",
        packages=[_pkg("npm", "x")],
        remotes=[RegistryTransport(kind="streamable-http", url="https://x")],
    )
    assert keep_server(server) is True
    assert server.remotes == []


def test_compute_counts_reports_by_registry_type():
    servers = apply_filter(load_servers())
    counts = compute_counts(servers)
    assert counts["total_servers"] == 2
    assert counts["active"] == 2
    assert counts["deprecated"] == 0
    assert counts["with_github_repo"] == 2
    assert counts["enriched_with_github"] == 0
    assert counts["by_registry_type"] == {"npm": 1, "pypi": 1}


def test_dump_pruned_drops_nulls_and_empty_collections():
    server = RegistryServer(
        name="x/y",
        description="d",
        version="1",
        title=None,
        repository=None,
        website_url=None,
        packages=[_pkg("npm", "x")],
        remotes=[],
        status_message=None,
    )
    dumped = server.dump_pruned()
    # Nulls gone
    assert "title" not in dumped
    assert "repository" not in dumped
    assert "website_url" not in dumped
    assert "status_message" not in dumped
    # Empty collections gone
    assert "remotes" not in dumped
    # Non-null kept
    assert dumped["name"] == "x/y"
    assert dumped["description"] == "d"
    assert len(dumped["packages"]) == 1
    # False/booleans preserved
    assert dumped["is_latest"] is False


def test_write_outputs_produces_servers_and_metadata(tmp_path: Path):
    servers = apply_filter(load_servers())
    meta = write_outputs(tmp_path, servers)

    assert (tmp_path / "servers.json").exists()
    assert (tmp_path / "metadata.json").exists()

    assert meta["schema_version"] == "1.0.0"
    assert len(meta["content_sha256"]) == 64
    assert meta["counts"]["total_servers"] == 2

    on_disk = json.loads((tmp_path / "metadata.json").read_text())
    assert on_disk["content_sha256"] == meta["content_sha256"]

    loaded = json.loads((tmp_path / "servers.json").read_text())
    assert len(loaded) == 2

    for s in loaded:
        # Nulls and empties must not survive to the output.
        assert "enrichment" not in s
        for k, v in s.items():
            assert v is not None, f"null survived in {k}"
            if isinstance(v, (list, dict)):
                assert v, f"empty {type(v).__name__} survived in {k}"
