"""Assignment-aware manifest layered over the frozen downloader manifest."""
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone

from allsky_download.manifest import (
    Manifest as FrozenManifest,
    OutputLockedError,
    output_lock,
)
from allsky_download.processing import enqueue_job


class Manifest(FrozenManifest):
    """V25 manifest schema with nullable installation-assignment evidence."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        columns = {
            row[1]
            for row in self.connection.execute("PRAGMA table_info(downloads)")
        }
        for name, declaration in (
            ("installation_assignment_status", "TEXT"),
            ("installation_id", "TEXT"),
            ("installation_assignment_error", "TEXT"),
        ):
            if name not in columns:
                self.connection.execute(
                    f"ALTER TABLE downloads ADD COLUMN {name} {declaration}"
                )
        self.connection.commit()

    def record_assignment_success(
        self, remote_url: str, installation_id: str
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE downloads SET installation_assignment_status='assigned',
                    installation_id=?, installation_assignment_error=NULL
                WHERE remote_url=?
                """,
                (installation_id, remote_url),
            )

    def record_configured_success(
        self, candidate, downloaded, output_root: Path
    ) -> None:
        """Atomically record verified bytes as explicitly awaiting assignment."""
        root = Path(output_root).resolve()
        relative = downloaded.path.resolve().relative_to(root)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
        with self.connection:
            self.connection.execute(
                """
                UPDATE downloads SET local_path=?, observed_bytes=?, sha256=?,
                    download_status='downloaded', validation_status='verified',
                    attempted_utc=?, error=NULL,
                    installation_assignment_status='unassigned',
                    installation_id=NULL,
                    installation_assignment_error='assignment_pending'
                WHERE remote_url=?
                """,
                (
                    relative.as_posix(), downloaded.size_bytes, downloaded.sha256,
                    now, candidate.url,
                ),
            )

    def record_assignment_success_and_enqueue(
        self, remote_url: str, installation_id: str,
        source_sha256: str, *, enqueue_processing: bool
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE downloads SET installation_assignment_status='assigned',
                    installation_id=?, installation_assignment_error=NULL
                WHERE remote_url=?
                """,
                (installation_id, remote_url),
            )
            if enqueue_processing:
                enqueue_job(self.connection, remote_url, source_sha256)

    def record_assignment_failure(
        self, remote_url: str, installation_id: str | None, error: str
    ) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE downloads SET installation_assignment_status='unassigned',
                    installation_id=?, installation_assignment_error=?
                WHERE remote_url=?
                """,
                (installation_id, error, remote_url),
            )

    def enqueue_processing(self, remote_url: str, source_sha256: str) -> None:
        with self.connection:
            enqueue_job(self.connection, remote_url, source_sha256)

    def assignment_candidates(
        self, source_id: str, camera_id: str, limit: int
    ) -> tuple[dict[str, object], ...]:
        rows = self.connection.execute(
            """
            SELECT remote_url, local_path, sha256, observed_bytes, observed_utc
            FROM downloads
            WHERE source_id=? AND camera_id=?
              AND download_status='downloaded'
              AND validation_status='verified'
              AND (
                installation_assignment_status IS NULL OR
                installation_assignment_status != 'assigned'
              )
            ORDER BY observed_utc, remote_url
            LIMIT ?
            """,
            (source_id, camera_id, limit),
        ).fetchall()
        return tuple(
            {
                "remote_url": row[0],
                "local_path": row[1],
                "sha256": row[2],
                "observed_bytes": row[3],
                "observed_utc": row[4],
            }
            for row in rows
        )
