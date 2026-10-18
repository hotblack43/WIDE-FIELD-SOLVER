"""Transactional v21 MMTO FITS-header observation sidecar storage."""
from __future__ import annotations

from datetime import datetime, timezone
import re
import sqlite3

from .mmto_time import MMTOObservation


UTC = timezone.utc
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observation datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("stored observation datetime is not timezone-aware")
    return parsed.astimezone(UTC)


def ensure_observation_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS mmto_v21_observations (
            source_sha256 TEXT PRIMARY KEY,
            remote_url TEXT NOT NULL UNIQUE,
            discovery_utc TEXT NOT NULL,
            header_start_utc TEXT NOT NULL,
            header_midpoint_utc TEXT NOT NULL,
            exposure_seconds REAL NOT NULL,
            header_schema TEXT NOT NULL,
            provenance TEXT NOT NULL,
            instrument TEXT NOT NULL,
            recorded_utc TEXT NOT NULL
        )
        """
    )


def record_observation(
    connection: sqlite3.Connection,
    source_sha256: str,
    remote_url: str,
    discovery_utc: str,
    observation: MMTOObservation,
) -> None:
    """Record an immutable header interpretation without changing downloads."""

    if _SHA256.fullmatch(source_sha256) is None:
        raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
    if not remote_url:
        raise ValueError("remote_url must be present")
    _parse_utc(discovery_utc)
    values = (
        source_sha256,
        remote_url,
        discovery_utc,
        _utc_text(observation.start_utc),
        _utc_text(observation.midpoint_utc),
        float(observation.exposure_seconds),
        observation.schema,
        observation.provenance,
        observation.instrument,
    )
    with connection:
        ensure_observation_schema(connection)
        download = connection.execute(
            "SELECT sha256 FROM downloads WHERE remote_url=?", (remote_url,)
        ).fetchone()
        if download is None or str(download[0] or "") != source_sha256:
            raise ValueError("MMTO observation does not match a manifest download")
        previous = connection.execute(
            """
            SELECT source_sha256, remote_url, discovery_utc, header_start_utc,
                   header_midpoint_utc, exposure_seconds, header_schema,
                   provenance, instrument
            FROM mmto_v21_observations WHERE source_sha256=? OR remote_url=?
            """,
            (source_sha256, remote_url),
        ).fetchone()
        if previous is not None:
            if tuple(previous) != values:
                raise ValueError("conflicting authoritative MMTO observation record")
            return
        connection.execute(
            """
            INSERT INTO mmto_v21_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (*values, datetime.now(UTC).isoformat(timespec="seconds")),
        )


def observation_for_sha256(
    connection: sqlite3.Connection, source_sha256: str
) -> MMTOObservation | None:
    ensure_observation_schema(connection)
    row = connection.execute(
        """
        SELECT header_start_utc, header_midpoint_utc, exposure_seconds,
               header_schema, provenance, instrument
        FROM mmto_v21_observations WHERE source_sha256=?
        """,
        (source_sha256,),
    ).fetchone()
    if row is None:
        return None
    return MMTOObservation(
        start_utc=_parse_utc(str(row[0])),
        midpoint_utc=_parse_utc(str(row[1])),
        exposure_seconds=float(row[2]),
        schema=str(row[3]),
        provenance=str(row[4]),
        instrument=str(row[5]),
    )
