"""Pydantic models for the output shape.

All models deserialize from the upstream registry's camelCase wire format via
field aliases, and serialize back as snake_case. `model_dump(exclude_none=True)`
drops unset/null fields and is the standard way we write JSON.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        str_strip_whitespace=False,
    )

    def dump_pruned(self) -> dict[str, Any]:
        """Serialize dropping None values and empty collections, using aliases
        where defined so `kind` surfaces as `type` in the output.
        """
        return _prune(self.model_dump(exclude_none=True, by_alias=True))


def _prune(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            cleaned = _prune(v)
            if cleaned is None or cleaned == [] or cleaned == {}:
                continue
            out[k] = cleaned
        return out
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


class RegistryStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DELETED = "deleted"


class Repository(_Base):
    url: Optional[str] = None
    source: Optional[str] = None
    subfolder: Optional[str] = None


class RegistryTransport(_Base):
    # `type` is a Python builtin; use `kind` internally, alias on both sides.
    kind: str = Field(alias="type")
    url: Optional[str] = None


class RegistryArgument(_Base):
    kind: str = Field(alias="type")
    name: Optional[str] = None
    value_hint: Optional[str] = Field(default=None, validation_alias="valueHint")
    value: Optional[str] = None
    default: Optional[str] = None
    is_required: bool = Field(default=False, validation_alias="isRequired")
    is_repeated: bool = Field(default=False, validation_alias="isRepeated")


class RegistryEnvVar(_Base):
    name: str
    description: Optional[str] = None
    is_required: bool = Field(default=False, validation_alias="isRequired")
    is_secret: bool = Field(default=False, validation_alias="isSecret")
    format: Optional[str] = None
    # Provenance: None = upstream registry; "env-example" = inferred from a
    # .env.example-style file in the repo. Consumers can use this to render
    # inferred vars differently (e.g. "best-effort" badge).
    source: Optional[str] = None


class RegistryPackage(_Base):
    registry_type: str = Field(validation_alias="registryType")
    identifier: str
    version: Optional[str] = None
    runtime_hint: Optional[str] = Field(default=None, validation_alias="runtimeHint")
    transport: RegistryTransport
    package_arguments: list[RegistryArgument] = Field(
        default_factory=list, validation_alias="packageArguments"
    )
    runtime_arguments: list[RegistryArgument] = Field(
        default_factory=list, validation_alias="runtimeArguments"
    )
    environment_variables: list[RegistryEnvVar] = Field(
        default_factory=list, validation_alias="environmentVariables"
    )


class Enrichment(_Base):
    github_stars: Optional[int] = None
    github_forks: Optional[int] = None
    github_watchers: Optional[int] = None
    github_open_issues: Optional[int] = None
    github_open_pull_requests: Optional[int] = None
    github_created_at: Optional[datetime] = None
    github_pushed_at: Optional[datetime] = None
    github_is_fork: Optional[bool] = None
    github_is_disabled: Optional[bool] = None
    github_archived: Optional[bool] = None
    github_license: Optional[str] = None
    github_primary_language: Optional[str] = None
    github_topics: list[str] = []
    github_owner_avatar_url: Optional[str] = None
    enriched_at: datetime


__all__ = [
    "RegistryStatus",
    "Repository",
    "RegistryTransport",
    "RegistryArgument",
    "RegistryEnvVar",
    "RegistryPackage",
    "Enrichment",
    "RegistryServer",
]


class RegistryServer(_Base):
    name: str
    description: str
    version: str
    title: Optional[str] = None
    repository: Optional[Repository] = None
    website_url: Optional[str] = Field(default=None, validation_alias="websiteUrl")
    packages: list[RegistryPackage] = Field(default_factory=list)
    remotes: list[RegistryTransport] = Field(default_factory=list)

    status: RegistryStatus = RegistryStatus.ACTIVE
    is_latest: bool = False
    status_message: Optional[str] = None
    status_changed_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    enrichment: Optional[Enrichment] = None

    # Precomputed quality score (see scripts/ranking.py). Baked in at build time
    # so every consumer gets identical ranking without re-deriving per query.
    score: Optional[float] = None

    @classmethod
    def from_wire_row(cls, row: dict[str, Any]) -> "RegistryServer":
        """Construct from one upstream `{server, _meta}` row, flattening the
        `_meta.io.modelcontextprotocol.registry/official` envelope onto the
        server record.
        """
        wire_server = row.get("server") or {}
        meta = (row.get("_meta") or {}).get(
            "io.modelcontextprotocol.registry/official"
        ) or {}

        return cls.model_validate(
            {
                **wire_server,
                "status": meta.get("status") or "active",
                "is_latest": bool(meta.get("isLatest", False)),
                "status_message": meta.get("statusMessage"),
                "status_changed_at": meta.get("statusChangedAt"),
                "published_at": meta.get("publishedAt"),
                "updated_at": meta.get("updatedAt"),
            }
        )
