from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import re
import sqlite3
import subprocess
from typing import Iterable
import uuid


UTC = timezone.utc
PROCESSING_STATES = (
    "pending",
    "running",
    "succeeded",
    "solver_failed",
    "operational_failed",
    "interrupted",
)


class ClaimLostError(RuntimeError):
    """A queue claim was changed or does not belong to this worker."""


class OperationalFailure(RuntimeError):
    """The orchestration boundary failed independently of solver science."""


@dataclass(frozen=True, slots=True)
class ProcessingJob:
    job_id: int
    remote_url: str
    source_sha256: str
    solver_target: str
    state: str
    enqueued_utc: str
    started_utc: str | None
    finished_utc: str | None
    attempt_count: int
    worker_token: str | None
    solver_run_id: str | None
    analysis_path: str | None
    solver_exit_code: int | None
    failure_kind: str | None
    error: str | None
    processing_log: str | None
    launcher_sha256: str | None
    source_manifest_sha256: str | None
    source_id: str
    camera_id: str
    observed_utc: str
    local_path: str | None
    observed_bytes: int | None
    download_status: str
    validation_status: str


@dataclass(frozen=True, slots=True)
class QueueStatus:
    counts: dict[str, int]
    running: tuple[ProcessingJob, ...]
    stale_running: tuple[ProcessingJob, ...]
    oldest_pending_utc: str | None
    recent: tuple[ProcessingJob, ...]


@dataclass(frozen=True, slots=True)
class CleanupCandidate:
    kind: str
    job_id: int | None
    remote_url: str
    source_sha256: str
    state: str | None
    local_path: str | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SolverReceipt:
    run_id: str
    source_sha256: str
    analysis_path: str
    exit_code: int
    error: str | None


@dataclass(frozen=True, slots=True)
class WorkResult:
    job_id: int | None
    state: str
    solver_run_id: str | None
    processing_log: str | None
    message: str


_JOB_SELECT = """
    SELECT j.job_id, j.remote_url, j.source_sha256, j.solver_target,
           j.state, j.enqueued_utc, j.started_utc, j.finished_utc,
           j.attempt_count, j.worker_token, j.solver_run_id,
           j.analysis_path, j.solver_exit_code, j.failure_kind, j.error,
           j.processing_log, j.launcher_sha256, j.source_manifest_sha256,
           d.source_id, d.camera_id, d.observed_utc, d.local_path,
           d.observed_bytes, d.download_status, d.validation_status
    FROM processing_jobs AS j
    JOIN downloads AS d ON d.remote_url = j.remote_url
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def ensure_processing_schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS processing_jobs (
          job_id INTEGER PRIMARY KEY,
          remote_url TEXT NOT NULL UNIQUE REFERENCES downloads(remote_url),
          source_sha256 TEXT NOT NULL UNIQUE,
          solver_target TEXT NOT NULL CHECK (solver_target = 'go10'),
          state TEXT NOT NULL CHECK (
            state IN (
              'pending', 'running', 'succeeded', 'solver_failed',
              'operational_failed', 'interrupted'
            )
          ),
          enqueued_utc TEXT NOT NULL,
          started_utc TEXT,
          finished_utc TEXT,
          attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
          worker_token TEXT,
          solver_run_id TEXT,
          analysis_path TEXT,
          solver_exit_code INTEGER,
          failure_kind TEXT CHECK (
            failure_kind IS NULL OR
            failure_kind IN ('solver', 'operational', 'interrupted')
          ),
          error TEXT,
          processing_log TEXT,
          launcher_sha256 TEXT,
          source_manifest_sha256 TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS processing_events (
          event_id INTEGER PRIMARY KEY,
          job_id INTEGER NOT NULL REFERENCES processing_jobs(job_id),
          event_utc TEXT NOT NULL,
          previous_state TEXT,
          new_state TEXT NOT NULL CHECK (
            new_state IN (
              'pending', 'running', 'succeeded', 'solver_failed',
              'operational_failed', 'interrupted'
            )
          ),
          worker_token TEXT,
          reason TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS processing_jobs_state_fifo "
        "ON processing_jobs(state, enqueued_utc, job_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS processing_events_job "
        "ON processing_events(job_id, event_id)"
    )


def enqueue_job(
    connection: sqlite3.Connection,
    remote_url: str,
    source_sha256: str,
    solver_target: str = "go10",
) -> int | None:
    now = utc_now()
    inserted = connection.execute(
        """
        INSERT OR IGNORE INTO processing_jobs (
            remote_url, source_sha256, solver_target, state, enqueued_utc
        ) VALUES (?, ?, ?, 'pending', ?)
        """,
        (remote_url, source_sha256, solver_target, now),
    )
    if inserted.rowcount != 1:
        return None
    job_id = int(inserted.lastrowid)
    connection.execute(
        """
        INSERT INTO processing_events (
            job_id, event_utc, previous_state, new_state, worker_token, reason
        ) VALUES (?, ?, NULL, 'pending', NULL, 'new verified download')
        """,
        (job_id, now),
    )
    return job_id


def _job_from_row(row: sqlite3.Row) -> ProcessingJob:
    return ProcessingJob(**{field: row[field] for field in ProcessingJob.__dataclass_fields__})


class ProcessingQueue:
    def __init__(self, manifest_path: Path, *, read_only: bool = False) -> None:
        self.path = Path(manifest_path)
        if read_only:
            self.connection = sqlite3.connect(
                self.path.resolve().as_uri() + "?mode=ro",
                uri=True,
                timeout=30,
            )
        else:
            self.connection = sqlite3.connect(self.path, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        required = {"downloads", "processing_jobs", "processing_events"}
        tables = {
            row[0]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = sorted(required - tables)
        if missing:
            self.connection.close()
            raise ValueError(
                "manifest lacks processing schema: " + ", ".join(missing)
            )

    def __enter__(self) -> ProcessingQueue:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _event(
        self,
        job_id: int,
        previous_state: str | None,
        new_state: str,
        worker_token: str | None,
        reason: str,
        *,
        event_utc: str | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO processing_events (
                job_id, event_utc, previous_state, new_state,
                worker_token, reason
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                event_utc or utc_now(),
                previous_state,
                new_state,
                worker_token,
                reason,
            ),
        )

    def get_job(self, job_id: int) -> ProcessingJob:
        row = self.connection.execute(
            _JOB_SELECT + " WHERE j.job_id=?", (job_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown processing job: {job_id}")
        return _job_from_row(row)

    def claim_next(self) -> ProcessingJob | None:
        token = str(uuid.uuid4())
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                "SELECT job_id FROM processing_jobs WHERE state='pending' "
                "ORDER BY enqueued_utc, job_id LIMIT 1"
            ).fetchone()
            if row is None:
                self.connection.commit()
                return None
            now = utc_now()
            changed = self.connection.execute(
                """
                UPDATE processing_jobs
                SET state='running', started_utc=?, finished_utc=NULL,
                    attempt_count=attempt_count+1, worker_token=?
                WHERE job_id=? AND state='pending'
                """,
                (now, token, row["job_id"]),
            ).rowcount
            if changed != 1:
                raise ClaimLostError("pending claim changed concurrently")
            self._event(
                row["job_id"],
                "pending",
                "running",
                token,
                "worker claim",
                event_utc=now,
            )
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
        return self.get_job(row["job_id"])

    def finish(
        self,
        job_id: int,
        worker_token: str | None,
        *,
        state: str,
        solver_exit_code: int | None = None,
        failure_kind: str | None = None,
        error: str | None = None,
        solver_run_id: str | None = None,
        analysis_path: str | None = None,
        processing_log: str | None = None,
        launcher_sha256: str | None = None,
        source_manifest_sha256: str | None = None,
    ) -> None:
        if state not in {"succeeded", "solver_failed", "operational_failed"}:
            raise ValueError(f"invalid terminal processing state: {state}")
        if state == "succeeded" and solver_exit_code != 0:
            raise ValueError("successful processing requires solver exit code zero")
        now = utc_now()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            changed = self.connection.execute(
                """
                UPDATE processing_jobs
                SET state=?, finished_utc=?, solver_run_id=?, analysis_path=?,
                    solver_exit_code=?, failure_kind=?, error=?,
                    processing_log=COALESCE(?, processing_log),
                    launcher_sha256=COALESCE(?, launcher_sha256),
                    source_manifest_sha256=COALESCE(?, source_manifest_sha256)
                WHERE job_id=? AND state='running' AND worker_token=?
                """,
                (
                    state,
                    now,
                    solver_run_id,
                    analysis_path,
                    solver_exit_code,
                    failure_kind,
                    error,
                    processing_log,
                    launcher_sha256,
                    source_manifest_sha256,
                    job_id,
                    worker_token,
                ),
            ).rowcount
            if changed != 1:
                raise ClaimLostError(
                    f"job {job_id} is not running under worker token {worker_token}"
                )
            self._event(
                job_id,
                "running",
                state,
                worker_token,
                error or f"worker completed as {state}",
                event_utc=now,
            )
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def record_attempt_context(
        self,
        job_id: int,
        worker_token: str | None,
        *,
        processing_log: str | None = None,
        launcher_sha256: str | None = None,
        source_manifest_sha256: str | None = None,
    ) -> None:
        with self.connection:
            changed = self.connection.execute(
                """
                UPDATE processing_jobs
                SET processing_log=COALESCE(?, processing_log),
                    launcher_sha256=COALESCE(?, launcher_sha256),
                    source_manifest_sha256=COALESCE(?, source_manifest_sha256)
                WHERE job_id=? AND state='running' AND worker_token=?
                """,
                (
                    processing_log,
                    launcher_sha256,
                    source_manifest_sha256,
                    job_id,
                    worker_token,
                ),
            ).rowcount
            if changed != 1:
                raise ClaimLostError(
                    f"job {job_id} is not running under worker token {worker_token}"
                )

    def status(
        self, *, stale_after_seconds: int = 3600, recent_limit: int = 10
    ) -> QueueStatus:
        if stale_after_seconds < 0 or recent_limit < 0:
            raise ValueError("status limits must be nonnegative")
        counts = {state: 0 for state in PROCESSING_STATES}
        counts.update(
            {
                row["state"]: row["count"]
                for row in self.connection.execute(
                    "SELECT state, count(*) AS count FROM processing_jobs GROUP BY state"
                )
            }
        )
        running = tuple(
            _job_from_row(row)
            for row in self.connection.execute(
                _JOB_SELECT + " WHERE j.state='running' ORDER BY j.started_utc, j.job_id"
            )
        )
        cutoff = (
            datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
        ).isoformat(timespec="seconds").replace("+00:00", "Z")
        stale = tuple(
            job
            for job in running
            if job.started_utc is not None and job.started_utc <= cutoff
        )
        oldest = self.connection.execute(
            "SELECT min(enqueued_utc) FROM processing_jobs WHERE state='pending'"
        ).fetchone()[0]
        recent = tuple(
            _job_from_row(row)
            for row in self.connection.execute(
                _JOB_SELECT + " ORDER BY j.job_id DESC LIMIT ?", (recent_limit,)
            )
        )
        return QueueStatus(counts, running, stale, oldest, recent)

    def audit_cleanup(
        self,
        *,
        source: str | None = None,
        night: str | None = None,
        job_ids: Iterable[int] = (),
        remote_urls: Iterable[str] = (),
        limit: int = 100,
        stale_after_seconds: int = 3600,
    ) -> tuple[CleanupCandidate, ...]:
        if limit <= 0 or stale_after_seconds < 0:
            raise ValueError("cleanup limits must be positive/nonnegative")
        selected_ids = tuple(dict.fromkeys(int(value) for value in job_ids))
        selected_urls = tuple(dict.fromkeys(str(value) for value in remote_urls))
        cutoff = (
            datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
        ).isoformat(timespec="seconds").replace("+00:00", "Z")
        clauses = [
            "(j.state='operational_failed' OR "
            "(j.state='running' AND j.started_utc IS NOT NULL AND j.started_utc<=?))"
        ]
        parameters: list[object] = [cutoff]
        if source is not None:
            clauses.append("d.source_id=?")
            parameters.append(source)
        if night is not None:
            clauses.append("d.local_path LIKE ?")
            parameters.append(f"%/{night}/%")
        if selected_ids:
            clauses.append("j.job_id IN (" + ",".join("?" * len(selected_ids)) + ")")
            parameters.extend(selected_ids)
        if selected_urls:
            clauses.append("j.remote_url IN (" + ",".join("?" * len(selected_urls)) + ")")
            parameters.extend(selected_urls)
        rows = self.connection.execute(
            """
            SELECT j.job_id, j.remote_url, j.source_sha256, j.state,
                   d.local_path, j.error
            FROM processing_jobs AS j
            JOIN downloads AS d ON d.remote_url=j.remote_url
            WHERE """
            + " AND ".join(clauses)
            + " ORDER BY j.job_id LIMIT ?",
            (*parameters, limit),
        ).fetchall()
        candidates = [
            CleanupCandidate(
                "stale_running" if row["state"] == "running" else row["state"],
                row["job_id"],
                row["remote_url"],
                row["source_sha256"],
                row["state"],
                row["local_path"],
                row["error"],
            )
            for row in rows
        ]
        remaining = limit - len(candidates)
        if remaining > 0 and not selected_ids:
            missing_clauses = [
                "j.job_id IS NULL",
                "d.download_status='downloaded'",
                "d.validation_status='verified'",
                "d.sha256 IS NOT NULL",
            ]
            missing_parameters: list[object] = []
            if source is not None:
                missing_clauses.append("d.source_id=?")
                missing_parameters.append(source)
            if night is not None:
                missing_clauses.append("d.local_path LIKE ?")
                missing_parameters.append(f"%/{night}/%")
            if selected_urls:
                missing_clauses.append(
                    "d.remote_url IN (" + ",".join("?" * len(selected_urls)) + ")"
                )
                missing_parameters.extend(selected_urls)
            missing = self.connection.execute(
                """
                SELECT d.remote_url, d.sha256, d.local_path
                FROM downloads AS d
                LEFT JOIN processing_jobs AS j ON j.remote_url=d.remote_url
                WHERE """
                + " AND ".join(missing_clauses)
                + " ORDER BY d.attempted_utc, d.remote_url LIMIT ?",
                (*missing_parameters, remaining),
            ).fetchall()
            candidates.extend(
                CleanupCandidate(
                    "missing_job",
                    None,
                    row["remote_url"],
                    row["sha256"],
                    None,
                    row["local_path"],
                )
                for row in missing
            )
        return tuple(candidates)

    def apply_cleanup(
        self,
        candidates: Iterable[CleanupCandidate],
        *,
        reason: str = "explicit cleanup",
    ) -> tuple[int, ...]:
        changed_ids: list[int] = []
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            for candidate in candidates:
                if candidate.kind == "missing_job":
                    job_id = enqueue_job(
                        self.connection,
                        candidate.remote_url,
                        candidate.source_sha256,
                    )
                    if job_id is not None:
                        changed_ids.append(job_id)
                    continue
                if candidate.job_id is None:
                    raise ValueError("cleanup queue transition requires a job ID")
                row = self.connection.execute(
                    "SELECT state, worker_token, error FROM processing_jobs "
                    "WHERE job_id=?",
                    (candidate.job_id,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown processing job: {candidate.job_id}")
                if row["state"] == "solver_failed":
                    raise ValueError("cleanup never requeues solver_failed jobs")
                now = utc_now()
                if candidate.kind == "stale_running" and row["state"] == "running":
                    detail = f"{reason}; interrupted stale worker"
                    self.connection.execute(
                        """
                        UPDATE processing_jobs
                        SET state='interrupted', finished_utc=?,
                            failure_kind='interrupted', error=?
                        WHERE job_id=? AND state='running'
                        """,
                        (now, detail, candidate.job_id),
                    )
                    self._event(
                        candidate.job_id,
                        "running",
                        "interrupted",
                        row["worker_token"],
                        detail,
                        event_utc=now,
                    )
                    previous = "interrupted"
                elif (
                    candidate.kind == "operational_failed"
                    and row["state"] == "operational_failed"
                ):
                    previous = "operational_failed"
                else:
                    raise ClaimLostError(
                        f"job {candidate.job_id} no longer matches cleanup audit"
                    )
                detail = f"{reason}; requeued from {previous}"
                self.connection.execute(
                    """
                    UPDATE processing_jobs
                    SET state='pending', started_utc=NULL, finished_utc=NULL,
                        worker_token=NULL, solver_run_id=NULL, analysis_path=NULL,
                        solver_exit_code=NULL, failure_kind=NULL, error=NULL
                    WHERE job_id=? AND state=?
                    """,
                    (candidate.job_id, previous),
                )
                self._event(
                    candidate.job_id,
                    previous,
                    "pending",
                    None,
                    detail + (f"; prior error: {row['error']}" if row["error"] else ""),
                    event_utc=now,
                )
                changed_ids.append(candidate.job_id)
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
        return tuple(changed_ids)

    def reconcile_cleanup(
        self,
        candidate: CleanupCandidate,
        receipt: SolverReceipt,
        *,
        reason: str = "explicit cleanup found existing solver receipt",
    ) -> int:
        terminal_state = "succeeded" if receipt.exit_code == 0 else "solver_failed"
        failure_kind = None if receipt.exit_code == 0 else "solver"
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            job_id = candidate.job_id
            if job_id is None:
                job_id = enqueue_job(
                    self.connection,
                    candidate.remote_url,
                    candidate.source_sha256,
                )
                if job_id is None:
                    row = self.connection.execute(
                        "SELECT job_id FROM processing_jobs WHERE source_sha256=?",
                        (candidate.source_sha256,),
                    ).fetchone()
                    if row is None:
                        raise ClaimLostError("duplicate cleanup enqueue has no queue row")
                    job_id = int(row["job_id"])
            row = self.connection.execute(
                "SELECT state, worker_token, solver_run_id FROM processing_jobs "
                "WHERE job_id=?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown processing job: {job_id}")
            if row["state"] in {"succeeded", "solver_failed"}:
                if row["solver_run_id"] == receipt.run_id:
                    self.connection.commit()
                    return job_id
                raise ClaimLostError(f"job {job_id} is already terminal")
            if row["state"] not in {
                "pending",
                "running",
                "operational_failed",
                "interrupted",
            }:
                raise ClaimLostError(
                    f"job {job_id} cannot reconcile from state {row['state']}"
                )
            now = utc_now()
            self.connection.execute(
                """
                UPDATE processing_jobs
                SET state=?, finished_utc=?, worker_token=NULL,
                    solver_run_id=?, analysis_path=?, solver_exit_code=?,
                    failure_kind=?, error=?
                WHERE job_id=? AND state=?
                """,
                (
                    terminal_state,
                    now,
                    receipt.run_id,
                    receipt.analysis_path,
                    receipt.exit_code,
                    failure_kind,
                    receipt.error,
                    job_id,
                    row["state"],
                ),
            )
            self._event(
                job_id,
                row["state"],
                terminal_state,
                row["worker_token"],
                reason,
                event_utc=now,
            )
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
        return job_id


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validated_input(
    root: Path,
    local_path: str | None,
    expected_size: int | None,
    expected_sha256: str,
) -> Path:
    try:
        resolved_root = Path(root).resolve(strict=True)
    except OSError as exc:
        raise OperationalFailure(f"acquisition root is unavailable: {exc}") from exc
    if not local_path:
        raise OperationalFailure("verified download has no local path")
    relative = Path(local_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise OperationalFailure("input path escapes acquisition root")
    current = resolved_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise OperationalFailure("input path contains a symlink")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise OperationalFailure(f"input file is unavailable beneath archive: {exc}") from exc
    if not resolved.is_file():
        raise OperationalFailure("input path is not a regular file")
    if expected_size is None or resolved.stat().st_size != expected_size:
        raise OperationalFailure("input size no longer matches manifest")
    if sha256_file(resolved) != expected_sha256:
        raise OperationalFailure("input checksum no longer matches manifest")
    return resolved


def reconcile_receipt(
    results_database: Path,
    run_id: str,
    expected_sha256: str,
) -> SolverReceipt:
    try:
        normalized_run_id = str(uuid.UUID(run_id))
    except ValueError as exc:
        raise OperationalFailure(f"solver receipt has invalid run UUID: {run_id}") from exc
    if normalized_run_id != run_id.lower():
        raise OperationalFailure(f"solver receipt has noncanonical run UUID: {run_id}")
    database = Path(results_database)
    if database.is_symlink():
        raise OperationalFailure(f"solver receipt database is a symlink: {database}")
    if not database.is_file():
        raise OperationalFailure(f"solver receipt database is missing: {database}")
    try:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            row = connection.execute(
                """
                SELECT run_id, source_sha256, analysis_path, exit_code, error
                FROM runs WHERE run_id=?
                """,
                (run_id,),
            ).fetchone()
    except sqlite3.Error as exc:
        raise OperationalFailure(f"cannot read solver receipt database: {exc}") from exc
    if row is None:
        raise OperationalFailure(f"solver receipt {run_id} is absent from stars.sqlite")
    receipt = SolverReceipt(str(row[0]), str(row[1]), str(row[2]), int(row[3]), row[4])
    if receipt.source_sha256 != expected_sha256:
        raise OperationalFailure("solver receipt source checksum does not match input")
    analysis = Path(receipt.analysis_path)
    try:
        analysis.resolve(strict=True).relative_to(database.parent.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise OperationalFailure(
            "solver receipt analysis path is missing or outside results root"
        ) from exc
    if not analysis.is_dir():
        raise OperationalFailure("solver receipt analysis path is not a directory")
    return receipt


def receipts_for_sha256(
    results_database: Path, expected_sha256: str
) -> tuple[SolverReceipt, ...]:
    database = Path(results_database)
    if database.is_symlink():
        raise OperationalFailure(f"solver receipt database is a symlink: {database}")
    if not database.is_file():
        return ()
    try:
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
            run_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT run_id FROM runs WHERE source_sha256=? ORDER BY run_id",
                    (expected_sha256,),
                )
            ]
    except sqlite3.Error as exc:
        raise OperationalFailure(f"cannot search solver receipt database: {exc}") from exc
    return tuple(
        reconcile_receipt(database, run_id, expected_sha256) for run_id in run_ids
    )


_RECEIPT_PATTERN = re.compile(
    r"^Database:\s+(.+?)\s+\(run\s+([0-9A-Fa-f-]{36})\)\s*$",
    re.MULTILINE,
)


def _receipt_from_output(
    output: str, results_database: Path, expected_sha256: str
) -> SolverReceipt:
    matches = _RECEIPT_PATTERN.findall(output)
    if len(matches) != 1:
        raise OperationalFailure(
            f"expected one solver receipt in launcher output, found {len(matches)}"
        )
    printed_database, run_id = matches[0]
    expected_path = Path(results_database)
    if expected_path.is_symlink():
        raise OperationalFailure(
            f"solver receipt database is a symlink: {expected_path}"
        )
    try:
        printed = Path(printed_database).resolve(strict=True)
        expected = expected_path.resolve(strict=True)
    except OSError as exc:
        raise OperationalFailure(f"solver receipt database is unavailable: {exc}") from exc
    if printed != expected:
        raise OperationalFailure(
            f"solver receipt named unexpected database: {printed_database}"
        )
    return reconcile_receipt(expected_path, run_id, expected_sha256)


def run_one(
    queue: ProcessingQueue,
    acquisition_root: Path,
    results_root: Path,
    repo_root: Path,
    *,
    run_process=subprocess.run,
    worker_lock_fd: int | None = None,
) -> WorkResult:
    job = queue.claim_next()
    if job is None:
        return WorkResult(None, "no_work", None, None, "no pending processing job")
    log_relative = Path("processing-logs") / (
        f"job-{job.job_id}-attempt-{job.attempt_count}.log"
    )
    log_path = Path(acquisition_root) / log_relative
    launcher_hash = None
    manifest_hash = None
    process_exit_code = None
    output = ""
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.touch(exist_ok=True)
        queue.record_attempt_context(
            job.job_id,
            job.worker_token,
            processing_log=log_relative.as_posix(),
        )
        if job.solver_target != "go10":
            raise OperationalFailure(
                f"unsupported processing solver target: {job.solver_target}"
            )
        if job.download_status != "downloaded" or job.validation_status != "verified":
            raise OperationalFailure("download row is no longer verified")
        image = validated_input(
            acquisition_root,
            job.local_path,
            job.observed_bytes,
            job.source_sha256,
        )
        repo = Path(repo_root).resolve(strict=True)
        launcher = repo / "go10.sh"
        source_manifest = repo / "v10" / "SOURCE_MANIFEST.json"
        if launcher.is_symlink() or source_manifest.is_symlink():
            raise OperationalFailure("frozen launcher provenance path is a symlink")
        launcher_hash = sha256_file(launcher)
        manifest_hash = sha256_file(source_manifest)
        queue.record_attempt_context(
            job.job_id,
            job.worker_token,
            launcher_sha256=launcher_hash,
            source_manifest_sha256=manifest_hash,
        )
        results = Path(results_root).resolve()
        results.mkdir(parents=True, exist_ok=True)
        # The launcher inherits the lock and writes directly to its durable log.
        # A killed wrapper therefore neither permits a second solver nor loses
        # the first solver's output while that process is still running.
        with log_path.open('w', encoding='utf-8') as log:
            completed = run_process(
                [str(launcher), str(image), "--results-dir", str(results)],
                cwd=repo,
                text=True,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
                pass_fds=() if worker_lock_fd is None else (worker_lock_fd,),
            )
        process_exit_code = completed.returncode
        output = log_path.read_text(encoding="utf-8")
        receipt = _receipt_from_output(
            output, results / "stars.sqlite", job.source_sha256
        )
        if completed.returncode == 0 and receipt.exit_code == 0:
            state = "succeeded"
            failure_kind = None
            error = None
        elif completed.returncode != 0 and receipt.exit_code != 0:
            state = "solver_failed"
            failure_kind = "solver"
            error = receipt.error or f"solver exited {completed.returncode}"
        else:
            raise OperationalFailure(
                "launcher exit code and solver database receipt disagree"
            )
        queue.finish(
            job.job_id,
            job.worker_token,
            state=state,
            solver_exit_code=completed.returncode,
            failure_kind=failure_kind,
            error=error,
            solver_run_id=receipt.run_id,
            analysis_path=receipt.analysis_path,
            processing_log=log_relative.as_posix(),
            launcher_sha256=launcher_hash,
            source_manifest_sha256=manifest_hash,
        )
        return WorkResult(
            job.job_id,
            state,
            receipt.run_id,
            log_relative.as_posix(),
            error or "solver receipt verified",
        )
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as stream:
                if output and not output.endswith("\n"):
                    stream.write("\n")
                stream.write(f"WORKER ERROR: {detail}\n")
        except OSError:
            pass
        queue.finish(
            job.job_id,
            job.worker_token,
            state="operational_failed",
            solver_exit_code=process_exit_code,
            failure_kind="operational",
            error=detail,
            processing_log=log_relative.as_posix(),
            launcher_sha256=launcher_hash,
            source_manifest_sha256=manifest_hash,
        )
        return WorkResult(
            job.job_id,
            "operational_failed",
            None,
            log_relative.as_posix(),
            detail,
        )
