# MCP Registry Database

Prebuilt, GitHub-stars-enriched snapshots of the [official MCP registry](https://registry.modelcontextprotocol.io)
published as gzipped JSON to this repo's [Releases](../../releases).

## Why

The upstream registry has no popularity signals and its built-in search only matches
on `name` — not `description` or `title`. Running your own paginated sync + GitHub
enrichment is ~3 minutes of API calls per refresh. Instead, we run that once per hour
here and publish the result as a single file anyone can `curl`.

## Scope

This dump is filtered to servers that publish at least one package where **both**:

- the package registry is **`npm`** or **`pypi`** (others — `oci`, `nuget`, `mcpb` — are dropped), and
- the transport is **`stdio`**, **`streamable-http`**, or **`sse`**.

Servers that only expose `remotes[]` (no `packages[]`) are dropped entirely. Kept
servers have their `packages[]` filtered in place to the surviving entries and their
`remotes[]` cleared. Servers with no resolvable `repository.url` (even after the
npm/pypi metadata fallback described below) are also dropped.

Transient upstream failures (408, 429, 5xx) are retried with exponential backoff +
jitter via `httpx-retries`, honoring `Retry-After`, so a flaky registry doesn't fail
a whole sync.

### Repository URL is required

Every kept entry must have a `repository.url`. If the upstream registry entry is
missing one, we fall back to the package registry (`registry.npmjs.org` or
`pypi.org/pypi/.../json`) and read the repo URL from the package's own metadata.
Servers that still have no repository URL after this fallback are **dropped**,
since without a repo we can't show provenance or enrich with popularity signals.

## Consuming

Two stable URLs that always resolve to the latest release:

```
https://github.com/fronalabs/mcp-registry-database/releases/latest/download/metadata.json
https://github.com/fronalabs/mcp-registry-database/releases/latest/download/servers.json.xz
```

Recommended flow for a client:

1. `GET metadata.json` (tiny, <1 KB) and read `content_sha256`
2. If different from the cached value, `GET servers.json.xz` and refresh your local index
3. Otherwise do nothing — the dump hasn't changed

Example:

```bash
curl -sSL https://github.com/fronalabs/mcp-registry-database/releases/latest/download/metadata.json | jq
curl -sSL https://github.com/fronalabs/mcp-registry-database/releases/latest/download/servers.json.xz | xz -d | jq '.[0]'
```

The payload is compressed with **xz** (LZMA, preset 9 + extreme). Decompression
is ~10 ms per refresh on a consumer — negligible for a background sync — and the
wire payload is ~30% smaller than gzip.

## Data shape

See [`schema/`](schema/) for the JSON Schema definitions.

- `servers.json.xz` — xz-compressed JSON array of [`RegistryServer`](schema/servers.v1.schema.json) objects.
  Each entry mirrors the upstream registry's `ServerJSON` with `_meta` flattened onto it,
  plus an optional `enrichment` block populated from the GitHub GraphQL API (stars,
  forks, watchers, open issues/PRs, license, primary language, topics, created/pushed
  timestamps, archived/fork/disabled flags, owner avatar).
- `metadata.json` — sibling file with `schema_version`, `generated_at`, `counts`, and
  `content_sha256` for change detection.

## Release cadence

- GitHub Action runs **hourly** and produces a new release **only when the content
  hash changes**. No-op runs don't churn the releases list.
- Releases older than 30 days are pruned nightly.
- Release tags are `sync-YYYYMMDDTHHMMSSZ` in UTC.

## Running locally

```bash
pip install -e .
export GITHUB_TOKEN=$(gh auth token)
python -m scripts.sync --output-dir ./out
```

`GITHUB_TOKEN` is required for GitHub enrichment. Any token with public read access
works — the GraphQL query only touches public repos.

## License

MIT
