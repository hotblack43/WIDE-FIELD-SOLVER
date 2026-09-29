#!/usr/bin/env python3
"""Run the independent goBIG solves across this host and Monster2.

The frozen v11 runtime is invoked unchanged.  Monster2 writes its own SQLite
database; completed run directories are copied home and indexed locally.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
import threading


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_STATE = REPO_ROOT / "results" / "distributed-gobig" / "state.sqlite"
REMOTE_REPO = Path("/home/pth/WORKSHOP/WIDE-FIELD-SOLVER")
FINAL_STATUSES = {"succeeded", "solver_failed", "operational_failed"}


@dataclass(frozen=True)
class Job:
    line_no: int
    relative_image: Path


def load_jobs(manifest: Path, repo_root: Path = REPO_ROOT) -> list[Job]:
    """Parse the deliberately narrow ``./go11.sh IMAGE`` goBIG format."""
    root = repo_root.resolve()
    jobs: list[Job] = []
    seen: set[Path] = set()
    for line_no, raw in enumerate(Path(manifest).read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            words = shlex.split(raw)
        except ValueError as exc:
            raise ValueError(f"goBIG line {line_no} is not valid shell syntax") from exc
        if len(words) != 2 or words[0] != "./go11.sh":
            raise ValueError(f"goBIG line {line_no} must be exactly './go11.sh IMAGE'")
        try:
            image = (root / words[1]).resolve(strict=True)
            relative = image.relative_to(root)
        except (FileNotFoundError, ValueError) as exc:
            raise ValueError(f"goBIG line {line_no} is missing or outside the repository") from exc
        if relative in seen:
            raise ValueError(f"goBIG line {line_no} repeats {relative}")
        seen.add(relative)
        jobs.append(Job(line_no, relative))
    if not jobs:
        raise ValueError("goBIG contains no jobs")
    return jobs


def _job_signature(jobs: list[Job]) -> str:
    payload = [[job.line_no, job.relative_image.as_posix()] for job in jobs]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def _connect(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database, timeout=60)
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize_state(database: Path, jobs: list[Job], start_line: int) -> None:
    """Create an immutable manifest and alternating local/remote queue."""
    if start_line <= 0:
        raise ValueError("start_line must be positive")
    selected = [job for job in jobs if job.line_no >= start_line]
    if not selected:
        raise ValueError("start_line is beyond the final goBIG job")
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    signature = _job_signature(jobs)
    with _connect(database) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                line_no INTEGER PRIMARY KEY,
                relative_image TEXT NOT NULL UNIQUE,
                assigned TEXT NOT NULL CHECK (assigned IN ('local','remote')),
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                exit_code INTEGER,
                run_dir TEXT,
                error TEXT,
                updated_at TEXT NOT NULL
            )"""
        )
        existing = dict(connection.execute("SELECT key, value FROM meta"))
        expected = {"signature": signature, "start_line": str(start_line)}
        if existing:
            if any(existing.get(key) != value for key, value in expected.items()):
                raise ValueError("Existing distributed state belongs to another manifest or start line")
            return
        now = datetime.now(timezone.utc).isoformat()
        connection.executemany("INSERT INTO meta VALUES (?,?)", expected.items())
        connection.executemany(
            "INSERT INTO jobs(line_no,relative_image,assigned,status,updated_at) VALUES (?,?,?,?,?)",
            [
                (
                    job.line_no,
                    job.relative_image.as_posix(),
                    "local" if index % 2 == 0 else "remote",
                    "pending",
                    now,
                )
                for index, job in enumerate(selected)
            ],
        )


def claim_job(database: Path, assigned: str) -> Job | None:
    if assigned not in {"local", "remote"}:
        raise ValueError("assigned must be local or remote")
    with _connect(database) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT line_no, relative_image FROM jobs "
            "WHERE assigned=? AND status='pending' ORDER BY line_no LIMIT 1",
            (assigned,),
        ).fetchone()
        if row is None:
            return None
        connection.execute(
            "UPDATE jobs SET status='running', attempts=attempts+1, updated_at=? WHERE line_no=?",
            (datetime.now(timezone.utc).isoformat(), row[0]),
        )
        return Job(row[0], Path(row[1]))


def finish_job(
    database: Path,
    line_no: int,
    status: str,
    exit_code: int | None,
    run_dir: str | None,
    error: str | None = None,
) -> None:
    if status not in FINAL_STATUSES:
        raise ValueError(f"Invalid final status: {status}")
    with _connect(database) as connection:
        changed = connection.execute(
            "UPDATE jobs SET status=?, exit_code=?, run_dir=?, error=?, updated_at=? "
            "WHERE line_no=? AND status='running'",
            (status, exit_code, run_dir, error, datetime.now(timezone.utc).isoformat(), line_no),
        ).rowcount
        if changed != 1:
            raise ValueError(f"Job {line_no} is not running")


def reset_interrupted_jobs(database: Path) -> int:
    with _connect(database) as connection:
        return connection.execute(
            "UPDATE jobs SET status='pending', error='dispatcher interrupted', updated_at=? "
            "WHERE status='running'",
            (datetime.now(timezone.utc).isoformat(),),
        ).rowcount


def extract_run_directory(output: str, expected_runs_root: Path) -> Path:
    expected = Path(expected_runs_root)
    matches = [Path(line.removeprefix("Run folder: ").strip())
               for line in output.splitlines() if line.startswith("Run folder: ")]
    if len(matches) != 1 or not matches[0].is_absolute() or matches[0].parent != expected:
        raise ValueError("Solver output did not identify one run below the expected results root")
    return matches[0]


def _run(command: list[str], *, cwd: Path | None = None,
         env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def _write_log(path: Path, command: list[str], output: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Command: " + shlex.join(command) + "\n\n" + output, encoding="utf-8")


def _run_local_job(job: Job, database: Path, repo: Path, results: Path,
                   log_dir: Path, planet_workers: int) -> None:
    command = [str(repo / "go11.sh"), str(repo / job.relative_image),
               "--results-dir", str(results)]
    environment = os.environ.copy()
    environment["WFS_PLANET_WORKERS"] = str(planet_workers)
    completed = _run(command, cwd=repo, env=environment)
    _write_log(log_dir / f"line-{job.line_no:04d}-local.log", command, completed.stdout)
    try:
        run_dir = extract_run_directory(completed.stdout, results / "runs")
        report = run_dir / "analysis" / "report.pdf"
        status = "succeeded" if completed.returncode == 0 and report.is_file() else "solver_failed"
        finish_job(database, job.line_no, status, completed.returncode, str(run_dir))
    except Exception as exc:
        finish_job(database, job.line_no, "operational_failed", completed.returncode, None, str(exc))


def _append_remote_run(repo: Path, results: Path, run_dir: Path, image: Path,
                       exit_code: int) -> None:
    sys.path.insert(0, str(repo / "v11"))
    try:
        from point_star_database import append_run
        append_run(results / "stars.sqlite", run_dir / "analysis", image,
                   exit_code=exit_code,
                   error=None if exit_code == 0 else f"Monster2 go11 exit {exit_code}")
    finally:
        sys.path.pop(0)


def _run_remote_job(job: Job, database: Path, repo: Path, results: Path,
                    log_dir: Path, host: str, remote_repo: Path,
                    remote_results: Path, planet_workers: int,
                    import_lock: threading.Lock) -> None:
    remote_image = remote_repo / job.relative_image
    remote_command = ["env", f"WFS_PLANET_WORKERS={planet_workers}",
                      str(remote_repo / "go11.sh"), str(remote_image),
                      "--results-dir", str(remote_results)]
    command = ["ssh", "-o", "BatchMode=yes", host, shlex.join(remote_command)]
    completed = _run(command, cwd=repo)
    _write_log(log_dir / f"line-{job.line_no:04d}-remote.log", command, completed.stdout)
    local_run: Path | None = None
    try:
        remote_run = extract_run_directory(completed.stdout, remote_results / "runs")
        local_run = results / "runs" / remote_run.name
        if local_run.exists():
            raise FileExistsError(f"Refusing to overwrite {local_run}")
        local_run.parent.mkdir(parents=True, exist_ok=True)
        copied = _run(["rsync", "-a", f"{host}:{remote_run}/", f"{local_run}/"])
        if copied.returncode != 0:
            raise RuntimeError(f"rsync failed: {copied.stdout.strip()}")
        with import_lock:
            _append_remote_run(repo, results, local_run, repo / job.relative_image,
                               completed.returncode)
        report = local_run / "analysis" / "report.pdf"
        status = "succeeded" if completed.returncode == 0 and report.is_file() else "solver_failed"
        finish_job(database, job.line_no, status, completed.returncode, str(local_run))
    except Exception as exc:
        finish_job(database, job.line_no, "operational_failed", completed.returncode,
                   str(local_run) if local_run else None, str(exc))


def _worker_loop(assigned: str, database: Path, action) -> None:
    while True:
        job = claim_job(database, assigned)
        if job is None:
            return
        try:
            action(job)
        except Exception as exc:
            finish_job(database, job.line_no, "operational_failed", None, None, str(exc))


def prepare_remote(database: Path, repo: Path, host: str,
                   remote_repo: Path, remote_results: Path) -> None:
    """Synchronize only v11 and the images assigned to Monster2."""
    with _connect(database) as connection:
        images = [row[0] for row in connection.execute(
            "SELECT relative_image FROM jobs WHERE assigned='remote' ORDER BY line_no"
        )]
    mkdir = _run(["ssh", "-o", "BatchMode=yes", host,
                  shlex.join(["mkdir", "-p", str(remote_repo), str(remote_results / "runs")])])
    if mkdir.returncode != 0:
        raise RuntimeError(mkdir.stdout.strip())
    for source, destination, extra in (
        (str(repo / "go11.sh"), f"{host}:{remote_repo}/go11.sh", []),
        (str(repo / "v11") + "/", f"{host}:{remote_repo}/v11/", ["--exclude=.venv/"]),
    ):
        copied = _run(["rsync", "-a", *extra, source, destination])
        if copied.returncode != 0:
            raise RuntimeError(copied.stdout.strip())
    inputs = subprocess.run(
        ["rsync", "-aR", "--files-from=-", str(repo) + "/", f"{host}:{remote_repo}/"],
        input="\n".join(images) + "\n", text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    if inputs.returncode != 0:
        raise RuntimeError(inputs.stdout.strip())
    sync = _run(["ssh", "-o", "BatchMode=yes", host,
                 shlex.join(["uv", "sync", "--project", str(remote_repo / "v11"), "--frozen"])])
    if sync.returncode != 0:
        raise RuntimeError(sync.stdout.strip())
    version = _run(["ssh", "-o", "BatchMode=yes", host,
                    shlex.join([str(remote_repo / "go11.sh"), "--version"])])
    if version.returncode != 0 or "0.11.0" not in version.stdout:
        raise RuntimeError(f"Remote v11 verification failed: {version.stdout.strip()}")


def run_queue(args: argparse.Namespace) -> int:
    state = args.state.resolve()
    lock_path = state.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another distributed goBIG dispatcher is running")
        reset_interrupted_jobs(state)
        prepare_remote(state, args.repo, args.host, args.remote_repo, args.remote_results)
        import_lock = threading.Lock()
        log_dir = state.parent / "logs"
        local_action = lambda job: _run_local_job(
            job, state, args.repo, args.results, log_dir, args.planet_workers)
        remote_action = lambda job: _run_remote_job(
            job, state, args.repo, args.results, log_dir, args.host,
            args.remote_repo, args.remote_results, args.planet_workers, import_lock)
        with ThreadPoolExecutor(max_workers=args.local_workers + args.remote_workers) as pool:
            futures = [
                *(pool.submit(_worker_loop, "local", state, local_action)
                  for _ in range(args.local_workers)),
                *(pool.submit(_worker_loop, "remote", state, remote_action)
                  for _ in range(args.remote_workers)),
            ]
            for future in futures:
                future.result()
    return print_status(state)


def print_status(database: Path) -> int:
    with _connect(database) as connection:
        rows = connection.execute(
            "SELECT assigned, status, count(*) FROM jobs GROUP BY assigned, status "
            "ORDER BY assigned, status"
        ).fetchall()
    for assigned, status, count in rows:
        print(f"{assigned}\t{status}\t{count}")
    return 1 if any(status in {"pending", "running", "operational_failed"}
                    for _, status, _ in rows) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)
    initialize = subparsers.add_parser("init")
    initialize.add_argument("--manifest", type=Path, default=REPO_ROOT / "goBIG")
    initialize.add_argument("--start-line", type=int, required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--host", default="Monster2")
    run.add_argument("--results", type=Path, default=REPO_ROOT / "results")
    run.add_argument("--remote-repo", type=Path, default=REMOTE_REPO)
    run.add_argument("--remote-results", type=Path,
                     default=REMOTE_REPO / "results-distributed-gobig")
    run.add_argument("--local-workers", type=int, default=2)
    run.add_argument("--remote-workers", type=int, default=2)
    run.add_argument("--planet-workers", type=int, default=4)
    subparsers.add_parser("status")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init":
        initialize_state(args.state, load_jobs(args.manifest, args.repo), args.start_line)
        print_status(args.state)
        return 0
    if args.command == "status":
        return print_status(args.state)
    if min(args.local_workers, args.remote_workers, args.planet_workers) <= 0:
        raise SystemExit("worker counts must be positive")
    return run_queue(args)


if __name__ == "__main__":
    raise SystemExit(main())
