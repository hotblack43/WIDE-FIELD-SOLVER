#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
from pathlib import Path
import sqlite3
import sys
from typing import Sequence

from allsky_download.processing import (
    OperationalFailure,
    ProcessingQueue,
    receipts_for_sha256,
    run_one,
)


REPO_ROOT = Path(__file__).resolve().parent
UTC = timezone.utc


class WorkerBusyError(OperationalFailure):
    """Another work or cleanup command owns the processing lock."""


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def _nonnegative_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer") from exc
    if value < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Process newly acquired all-sky images through a durable queue."
    )
    parser.add_argument(
        "--archive", type=Path, default=REPO_ROOT / "raw_allsky_samples"
    )
    parser.add_argument(
        "--results-dir", type=Path, default=REPO_ROOT / "results/mmto-automatic"
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--worker-lock",
        type=Path,
        default=Path("/tmp/wide-field-solver-mmto-processing.lock"),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    work = commands.add_parser("work", help="claim and process queued work")
    work.add_argument(
        "--once",
        action="store_true",
        required=True,
        help="process at most one pending job",
    )

    status = commands.add_parser("status", help="show queue state without writing")
    status.add_argument("--stale-after", type=_nonnegative_int, default=3600)
    status.add_argument("--recent", type=_nonnegative_int, default=10)

    cleanup = commands.add_parser(
        "cleanup", help="audit or explicitly recover overlooked work"
    )
    cleanup.add_argument("--job-id", type=_positive_int, action="append", default=[])
    cleanup.add_argument("--remote-url", action="append", default=[])
    cleanup.add_argument("--source")
    cleanup.add_argument("--night")
    cleanup.add_argument("--limit", type=_positive_int, default=100)
    cleanup.add_argument("--stale-after", type=_nonnegative_int, default=3600)
    cleanup.add_argument("--apply", action="store_true")
    return parser


@contextmanager
def _exclusive_worker_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WorkerBusyError(
                f"worker lock is already held: {path}"
            ) from exc
        # Close our descriptor on exit, but never explicitly unlock the shared
        # open-file description: a surviving solver may still own a copy.
        yield lock.fileno()


def _print_status(queue: ProcessingQueue, args: argparse.Namespace) -> int:
    status = queue.status(
        stale_after_seconds=args.stale_after,
        recent_limit=args.recent,
    )
    now = datetime.now(UTC)

    def age_seconds(value: str | None) -> str:
        if value is None:
            return "-"
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return str(max(0, int((now - observed).total_seconds())))

    print(
        "STATUS\t"
        + "\t".join(
            f"{state}={status.counts[state]}"
            for state in (
                "pending",
                "running",
                "succeeded",
                "solver_failed",
                "operational_failed",
                "interrupted",
            )
        )
        + f"\tstale_running={len(status.stale_running)}"
        + f"\toldest_pending={status.oldest_pending_utc or '-'}"
        + "\toldest_pending_age_seconds="
        + age_seconds(status.oldest_pending_utc)
    )
    for job in status.running:
        print(
            f"RUNNING\tjob={job.job_id}\tstarted={job.started_utc}"
            f"\tage_seconds={age_seconds(job.started_utc)}"
            f"\timage={job.local_path}"
        )
    for job in status.recent:
        print(
            f"RECENT\tjob={job.job_id}\tstate={job.state}"
            f"\timage={job.local_path}\trun={job.solver_run_id or '-'}"
        )
    return 0


def _cleanup(queue: ProcessingQueue, args: argparse.Namespace, results: Path) -> int:
    has_selector = bool(
        args.job_id or args.remote_url or args.source is not None or args.night is not None
    )
    if args.apply and not has_selector:
        print("cleanup --apply requires an explicit selector", file=sys.stderr)
        return 3
    if args.apply and args.job_id:
        placeholders = ",".join("?" * len(args.job_id))
        forbidden = queue.connection.execute(
            "SELECT job_id FROM processing_jobs WHERE state='solver_failed' "
            f"AND job_id IN ({placeholders}) ORDER BY job_id",
            tuple(args.job_id),
        ).fetchall()
        if forbidden:
            ids = ", ".join(str(row[0]) for row in forbidden)
            print(
                f"cleanup refuses solver_failed job(s): {ids}",
                file=sys.stderr,
            )
            return 3
    candidates = queue.audit_cleanup(
        source=args.source,
        night=args.night,
        job_ids=args.job_id,
        remote_urls=args.remote_url,
        limit=args.limit,
        stale_after_seconds=args.stale_after,
    )
    database = results / "stars.sqlite"
    receipt_sets = []
    for candidate in candidates:
        receipts = receipts_for_sha256(database, candidate.source_sha256)
        if len(receipts) > 1:
            run_ids = ", ".join(receipt.run_id for receipt in receipts)
            print(
                f"cleanup refuses ambiguous receipts for {candidate.remote_url}: {run_ids}",
                file=sys.stderr,
            )
            return 3
        receipt_sets.append(receipts)
    mode = "APPLY" if args.apply else "DRY-RUN"
    if not candidates:
        print(f"{mode}\tNO_CANDIDATES")
        return 0
    for candidate, receipts in zip(candidates, receipt_sets, strict=True):
        job_label = candidate.job_id if candidate.job_id is not None else "new"
        if not args.apply:
            action = "RECONCILE" if receipts else "REQUEUE"
            print(
                f"DRY-RUN\t{action}\tjob={job_label}\tkind={candidate.kind}"
                f"\timage={candidate.local_path}"
            )
            continue
        if receipts:
            job_id = queue.reconcile_cleanup(candidate, receipts[0])
            print(
                f"RECONCILED\tjob={job_id}\tstate="
                f"{'succeeded' if receipts[0].exit_code == 0 else 'solver_failed'}"
                f"\trun={receipts[0].run_id}"
            )
        else:
            changed = queue.apply_cleanup((candidate,))
            if changed:
                print(f"REQUEUED\tjob={changed[0]}\tkind={candidate.kind}")
            else:
                print(f"UNCHANGED\tjob={job_label}\tkind={candidate.kind}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = args.archive / "manifest.sqlite"
    try:
        if not manifest.is_file():
            raise OperationalFailure(f"acquisition manifest is missing: {manifest}")
        read_only = args.command == "status" or (
            args.command == "cleanup" and not args.apply
        )
        with ProcessingQueue(manifest, read_only=read_only) as queue:
            if args.command == "status":
                return _print_status(queue, args)
            if args.command == "cleanup":
                if args.apply:
                    try:
                        with _exclusive_worker_lock(args.worker_lock):
                            return _cleanup(queue, args, args.results_dir)
                    except WorkerBusyError as exc:
                        print(str(exc), file=sys.stderr)
                        return 3
                return _cleanup(queue, args, args.results_dir)
            try:
                with _exclusive_worker_lock(args.worker_lock) as worker_lock_fd:
                    result = run_one(
                        queue,
                        args.archive,
                        args.results_dir,
                        args.repo_root,
                        worker_lock_fd=worker_lock_fd,
                    )
            except WorkerBusyError:
                print("BUSY\tworker lock is held; no job claimed")
                return 0
        if result.state == "no_work":
            print("NO_WORK")
            return 0
        print(
            f"WORK\tjob={result.job_id}\tstate={result.state}"
            f"\trun={result.solver_run_id or '-'}"
            f"\tlog={result.processing_log or '-'}"
        )
        if result.state == "succeeded":
            return 0
        if result.state == "solver_failed":
            return 1
        return 2
    except (OSError, ValueError, sqlite3.Error, OperationalFailure) as exc:
        print(f"all-sky processing failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
