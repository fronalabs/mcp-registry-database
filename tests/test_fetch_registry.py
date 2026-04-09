import json
from pathlib import Path

from scripts.fetch_registry import row_to_server

FIXTURE = Path(__file__).parent.parent / "fixtures" / "registry-sample.json"


def load_rows():
    return json.loads(FIXTURE.read_text())["servers"]


def test_flattens_stdio_package_entry():
    s = row_to_server(load_rows()[0])
    assert s.name == "io.github.taylorwilsdon/workspace-mcp"
    assert s.version == "1.11.1"
    assert s.status.value == "active"
    assert s.is_latest is True
    assert s.published_at is not None
    assert len(s.packages) == 1

    pkg = s.packages[0]
    assert pkg.registry_type == "pypi"
    assert pkg.identifier == "workspace-mcp"
    assert pkg.runtime_hint == "uvx"
    assert pkg.transport.kind == "stdio"
    assert len(pkg.environment_variables) == 1

    env = pkg.environment_variables[0]
    assert env.name == "GOOGLE_OAUTH_CLIENT_ID"
    assert env.is_required is True
    assert env.is_secret is True


def test_remote_server_flattens_without_packages():
    s = row_to_server(load_rows()[2])
    assert s.name == "ac.tandem/docs-mcp"
    assert s.packages == []
    assert len(s.remotes) == 1
    assert s.remotes[0].kind == "streamable-http"
    assert s.website_url == "https://tandem.ac/docs-mcp"


def test_enrichment_starts_none():
    for row in load_rows():
        assert row_to_server(row).enrichment is None


def test_missing_meta_envelope_yields_defaults():
    bare = {
        "server": {"name": "a/b", "description": "x", "version": "1"},
    }
    s = row_to_server(bare)
    assert s.status.value == "active"
    assert s.is_latest is False
    assert s.status_changed_at is None
