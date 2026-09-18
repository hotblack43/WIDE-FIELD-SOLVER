from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import os
from pathlib import Path
import sqlite3
from typing import Iterator

from .http import DownloadedFile
from .model import Candidate


UTC = timezone.utc


class OutputLockedError(RuntimeError):
    """Another downloader process holds the output lock."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def output_lock(output_root: Path) -> Iterator[None]:
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    lock_path = output_root / ".download.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise OutputLockedError(f"output is locked: {output_root}") from exc
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(f"pid={os.getpid()} acquired_utc={_utc_now()}\n")
        lock_file.flush()
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class Manifest:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS downloads (
              remote_url TEXT PRIMARY KEY,
              source_id TEXT NOT NULL,
              camera_id TEXT NOT NULL,
              observed_utc TEXT NOT NULL,
              observed_raw TEXT NOT NULL,
              remote_filename TEXT NOT NULL,
              local_path TEXT,
              advertised_bytes INTEGER,
              observed_bytes INTEGER,
              sha256 TEXT,
              download_status TEXT NOT NULL,
              validation_status TEXT NOT NULL,
              attempted_utc TEXT NOT NULL,
              error TEXT,
              inspector_kind TEXT,
              inspection_id TEXT
            )
            """
        )
        self.connection.commit()

    def __enter__(self) -> Manifest:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def record_attempt(self, candidate: Candidate) -> None:
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO downloads (
                    remote_url, source_id, camera_id, observed_utc, observed_raw,
                    remote_filename, advertised_bytes, download_status,
                    validation_status, attempted_utc, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'attempting', 'pending', ?, NULL)
                ON CONFLICT(remote_url) DO UPDATE SET
                    source_id=excluded.source_id,
                    camera_id=excluded.camera_id,
                    observed_utc=excluded.observed_utc,
                    observed_raw=excluded.observed_raw,
                    remote_filename=excluded.remote_filename,
                    advertised_bytes=excluded.advertised_bytes,
                    download_status='attempting',
                    validation_status='pending',
                    attempted_utc=excluded.attempted_utc,
                    error=NULL
                """,
                (
                    candidate.url,
                    candidate.source_id,
                    candidate.camera_id,
                    candidate.observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                    candidate.observed_raw,
                    candidate.filename,
                    candidate.size_bytes,
                    _utc_now(),
                ),
            )

    def record_success(
        self,
        candidate: Candidate,
        downloaded: DownloadedFile,
        output_root: Path,
    ) -> None:
        root = Path(output_root).resolve()
        relative = downloaded.path.resolve().relative_to(root)
        with self.connection:
            self.connection.execute(
                """
                UPDATE downloads SET local_path=?, observed_bytes=?, sha256=?,
                    download_status='downloaded', validation_status='verified',
                    attempted_utc=?, error=NULL
                WHERE remote_url=?
                """,
                (
                    relative.as_posix(),
                    downloaded.size_bytes,
                    downloaded.sha256,
                    _utc_now(),
                    candidate.url,
                ),
            )

    def record_failure(self, candidate: Candidate, error: str) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE downloads SET download_status='failed',
                    validation_status='failed', attempted_utc=?, error=?
                WHERE remote_url=?
                """,
                (_utc_now(), error, candidate.url),
            )

    def verified_download(
        self, candidate: Candidate, output_root: Path
    ) -> DownloadedFile | None:
        row = self.connection.execute(
            """
            SELECT local_path, observed_bytes, sha256, download_status,
                   validation_status
            FROM downloads WHERE remote_url=?
            """,
            (candidate.url,),
        ).fetchone()
        if row is None or row[3:] != ("downloaded", "verified"):
            return None
        local_path, expected_size, expected_hash = row[:3]
        path = Path(output_root) / local_path
        status = None
        validation = None
        if not path.is_file():
            status, validation = "missing_local", "missing"
        else:
            observed_size = path.stat().st_size
            if observed_size != expected_size:
                status, validation = "corrupt_local", "size_mismatch"
            elif _sha256(path) != expected_hash:
                status, validation = "corrupt_local", "checksum_mismatch"
            else:
                return DownloadedFile(path, expected_size, expected_hash)
        with self.connection:
            self.connection.execute(
                """
                UPDATE downloads SET download_status=?, validation_status=?,
                    attempted_utc=? WHERE remote_url=?
                """,
                (status, validation, _utc_now(), candidate.url),
            )
        return None

    def set_inspection_id(self, remote_url: str, kind: str, inspection_id: str) -> None:
        with self.connection:
            self.connection.execute(
                """
                UPDATE downloads SET inspector_kind=?, inspection_id=?
                WHERE remote_url=?
                """,
                (kind, inspection_id, remote_url),
            )
