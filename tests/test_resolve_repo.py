import httpx

from scripts.models import RegistryPackage, RegistryTransport
from scripts.resolve_repo import _clean_git_url, resolve_repo_url


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _npm_pkg(identifier: str) -> RegistryPackage:
    return RegistryPackage(
        registryType="npm",
        identifier=identifier,
        transport=RegistryTransport(type="stdio"),
    )


def _pypi_pkg(identifier: str) -> RegistryPackage:
    return RegistryPackage(
        registryType="pypi",
        identifier=identifier,
        transport=RegistryTransport(type="stdio"),
    )


def test_clean_git_url_strips_git_plus_and_suffix():
    assert (
        _clean_git_url("git+https://github.com/foo/bar.git")
        == "https://github.com/foo/bar"
    )


def test_clean_git_url_handles_ssh_style():
    assert _clean_git_url("git@github.com:foo/bar.git") == "https://github.com/foo/bar"


def test_clean_git_url_normalizes_git_protocol():
    assert _clean_git_url("git://github.com/foo/bar") == "https://github.com/foo/bar"


def test_npm_repo_from_object():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "repository": {
                    "type": "git",
                    "url": "git+https://github.com/example/pkg.git",
                }
            },
        )

    url = resolve_repo_url(_client(handler), _npm_pkg("@example/pkg"))
    assert url == "https://github.com/example/pkg"


def test_npm_repo_from_string_form():
    def handler(request):
        return httpx.Response(
            200,
            json={"repository": "https://github.com/example/pkg"},
        )

    url = resolve_repo_url(_client(handler), _npm_pkg("pkg"))
    assert url == "https://github.com/example/pkg"


def test_npm_falls_back_to_homepage():
    def handler(request):
        return httpx.Response(
            200,
            json={"homepage": "https://example.com/pkg"},
        )

    url = resolve_repo_url(_client(handler), _npm_pkg("pkg"))
    assert url == "https://example.com/pkg"


def test_npm_404_returns_none():
    def handler(request):
        return httpx.Response(404)

    url = resolve_repo_url(_client(handler), _npm_pkg("missing"))
    assert url is None


def test_pypi_prefers_repository_project_url():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "info": {
                    "project_urls": {
                        "Homepage": "https://example.com",
                        "Repository": "https://github.com/foo/bar",
                        "Documentation": "https://docs.example.com",
                    }
                }
            },
        )

    url = resolve_repo_url(_client(handler), _pypi_pkg("bar"))
    assert url == "https://github.com/foo/bar"


def test_pypi_falls_back_to_homepage_when_github():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "info": {
                    "project_urls": {
                        "Homepage": "https://github.com/foo/bar",
                    }
                }
            },
        )

    url = resolve_repo_url(_client(handler), _pypi_pkg("bar"))
    assert url == "https://github.com/foo/bar"


def test_pypi_accepts_non_github_homepage_as_last_resort():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "info": {
                    "project_urls": {
                        "Homepage": "https://gitlab.com/foo/bar",
                    }
                }
            },
        )

    url = resolve_repo_url(_client(handler), _pypi_pkg("bar"))
    assert url == "https://gitlab.com/foo/bar"


def test_pypi_uses_info_home_page_when_project_urls_empty():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "info": {
                    "project_urls": {},
                    "home_page": "https://example.com/bar",
                }
            },
        )

    url = resolve_repo_url(_client(handler), _pypi_pkg("bar"))
    assert url == "https://example.com/bar"


def test_pypi_no_urls_returns_none():
    def handler(request):
        return httpx.Response(200, json={"info": {}})

    url = resolve_repo_url(_client(handler), _pypi_pkg("bar"))
    assert url is None


def test_unknown_registry_type_returns_none():
    pkg = RegistryPackage(
        registryType="oci",
        identifier="foo/bar",
        transport=RegistryTransport(type="stdio"),
    )

    def handler(request):
        raise AssertionError("should not make any HTTP call")

    url = resolve_repo_url(_client(handler), pkg)
    assert url is None
