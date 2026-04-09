# MCP Registry Database

Prebuilt, GitHub-stars-enriched, quality-ranked snapshots of the [official MCP registry](https://registry.modelcontextprotocol.io),
published hourly as xz-compressed JSON to this repo's [Releases](../../releases).

## Why

The upstream registry has no popularity signals and its built-in search only matches
on `name`, not `description` or `title`. A paginated sync plus GitHub enrichment is
roughly 3 minutes of API calls per refresh. We run that once per hour here so any
consumer can `curl` a single file instead.

## Scope

Kept servers must publish at least one package where **both**:

- the package registry is `npm` or `pypi` (`oci`, `nuget`, `mcpb` are dropped), and
- the transport is `stdio`, `streamable-http`, or `sse`.

Surviving servers have their `packages[]` filtered in place and `remotes[]` cleared.
Remote-only servers (no `packages[]`) are dropped entirely.

Every kept server must have a `repository.url`. When the upstream entry is missing
one, we fall back to the package registry (`registry.npmjs.org` or `pypi.org`) and
read it from the package's own metadata. Servers still missing a repo URL after
that fallback are dropped, since without a repo we can't show provenance or enrich
with popularity signals.

Transient upstream failures (408, 429, 5xx) are retried with exponential backoff
plus jitter via `httpx-retries`, honoring `Retry-After`.

## Ranking

Every entry has a precomputed `score` field. The array in `servers.json.xz` is
already sorted by `score` descending, so streaming the file in order yields the
top-N for free (no client-side ranking pass needed).

The score folds together stars, forks, last-push recency, license presence,
topics, and the registry's own `status`, with hard zeros for `deleted` or
disabled repos and soft penalties for archived, fork, or deprecated entries.
See [`scripts/ranking.py`](scripts/ranking.py) for the exact weights.

## Consuming

Two stable URLs that always resolve to the latest release:

```
https://github.com/fronalabs/mcp-registry-database/releases/latest/download/metadata.json
https://github.com/fronalabs/mcp-registry-database/releases/latest/download/servers.json.xz
```

Recommended client flow:

1. `GET metadata.json` and read `content_sha256`
2. If it differs from the cached value, `GET servers.json.xz` and refresh your index
3. Otherwise do nothing; the dump hasn't changed

```bash
curl -sSL https://github.com/fronalabs/mcp-registry-database/releases/latest/download/metadata.json | jq
curl -sSL https://github.com/fronalabs/mcp-registry-database/releases/latest/download/servers.json.xz | xz -d | jq '.[0]'
```

The payload is compressed with xz (LZMA, preset 9 + extreme): roughly 30%
smaller on the wire than gzip, with negligible decompression cost.

## Data shape

See [`schema/`](schema/) for the JSON Schema definitions.

- `servers.json.xz`: JSON array of [`RegistryServer`](schema/servers.v1.schema.json)
  objects sorted by `score` descending. Each entry mirrors the upstream
  `ServerJSON` with `_meta` flattened onto it, plus an optional `enrichment`
  block populated from the GitHub GraphQL API (stars, forks, watchers, open
  issues and PRs, license, primary language, topics, created and pushed
  timestamps, archived/fork/disabled flags, owner avatar) and a `score` field.
- `metadata.json`: sibling file with `schema_version`, `generated_at`, `counts`,
  and `content_sha256` for change detection.

## Release cadence

- GitHub Action runs hourly and creates a new release only when `content_sha256`
  changes, so no-op runs don't churn the releases list.
- Releases older than 30 days are pruned nightly.
- Release tags are `sync-YYYYMMDDTHHMMSSZ` in UTC.

## Running locally

```bash
pip install -e .
export GITHUB_TOKEN=$(gh auth token)
python -m scripts.sync --output-dir ./out
```

Any token with public read access works; the GraphQL query only touches public
repos.

## License

MIT
