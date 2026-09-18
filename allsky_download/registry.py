from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .model import Site
from .sources.common import SourceAdapter
from .sources.mmto import MmtoAdapter
from .sources.rubin import RubinPublicSamplesAdapter
from .sources.trex_rgb import TrexRgbAdapter


class SourceUnavailableError(ValueError):
    """A known source has no verified public raw adapter."""


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    source_id: str
    aliases: tuple[str, ...]
    name: str
    status: str
    adapter: str | None
    archive_roots: tuple[str, ...]
    documentation: tuple[str, ...]
    licensing: str
    sites: tuple[Site, ...]


class SourceRegistry:
    def __init__(self, definitions: tuple[SourceDefinition, ...]) -> None:
        self._definitions = {item.source_id: item for item in definitions}
        self._aliases: dict[str, str] = {}
        for item in definitions:
            for name in (item.source_id, *item.aliases):
                key = name.strip().lower()
                if not key or key in self._aliases:
                    raise ValueError(f"duplicate or empty source name: {name!r}")
                self._aliases[key] = item.source_id

    @classmethod
    def from_json(cls, path: Path) -> SourceRegistry:
        payload: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1:
            raise ValueError("sources.json schema_version must be 1")
        definitions: list[SourceDefinition] = []
        for raw in payload.get("sources", []):
            source_id = str(raw["id"])
            sites = tuple(
                Site(
                    source_id,
                    str(camera["id"]),
                    str(camera["name"]),
                    str(camera["timezone"]),
                    camera.get("latitude_deg"),
                    camera.get("longitude_deg"),
                    camera.get("elevation_m"),
                )
                for camera in raw.get("cameras", [])
            )
            definitions.append(
                SourceDefinition(
                    source_id,
                    tuple(raw.get("aliases", [])),
                    str(raw["name"]),
                    str(raw["status"]),
                    raw.get("adapter"),
                    tuple(raw.get("archive_roots", [])),
                    tuple(raw.get("documentation", [])),
                    str(raw.get("licensing", "unknown")),
                    sites,
                )
            )
        return cls(tuple(definitions))

    def resolve_source_id(self, name_or_alias: str) -> str:
        try:
            return self._aliases[name_or_alias.strip().lower()]
        except KeyError as exc:
            raise ValueError(f"unknown source: {name_or_alias}") from exc

    def listed_sources(self) -> tuple[SourceDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))

    def get_adapter(self, source_id: str) -> SourceAdapter:
        canonical = self.resolve_source_id(source_id)
        definition = self._definitions[canonical]
        if definition.adapter is None:
            raise SourceUnavailableError(
                f"{canonical} has no verified public raw download adapter"
            )
        if not definition.archive_roots:
            raise ValueError(f"{canonical} adapter has no archive root")
        if definition.adapter == "mmto":
            return MmtoAdapter(definition.archive_roots[0], definition.sites)
        if definition.adapter == "trex_rgb":
            return TrexRgbAdapter(definition.archive_roots[0], definition.sites)
        if definition.adapter == "rubin_public_samples":
            return RubinPublicSamplesAdapter(definition.archive_roots[0], definition.sites)
        raise ValueError(f"unsupported adapter kind: {definition.adapter}")
