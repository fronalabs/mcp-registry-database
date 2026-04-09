"""Paginate the official MCP registry with ?version=latest into typed models."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .models import RegistryServer

REGISTRY_BASE_URL = "https://registry.modelcontextprotocol.io"
API_VERSION = "v0"

logger = logging.getLogger(__name__)


def paginate(
    client: httpx.Client,
    base_url: str = REGISTRY_BASE_URL,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    """Return the raw wire rows. Callers convert via `RegistryServer.from_wire_row`."""
    url = f"{base_url.rstrip('/')}/{API_VERSION}/servers"
    params: dict[str, Any] = {"limit": page_size, "version": "latest"}
    rows: list[dict[str, Any]] = []
    page = 0
    while True:
        response = client.get(url, params=params)
        response.raise_for_status()
        body = response.json()
        batch = body.get("servers", [])
        rows.extend(batch)
        page += 1
        logger.info("fetched page %d (%d rows, %d total)", page, len(batch), len(rows))
        cursor = (body.get("metadata") or {}).get("nextCursor")
        if not cursor:
            break
        params["cursor"] = cursor
    return rows


def row_to_server(row: dict[str, Any]) -> RegistryServer:
    return RegistryServer.from_wire_row(row)
