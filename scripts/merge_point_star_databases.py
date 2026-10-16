#!/usr/bin/env python3
"""Losslessly merge a point-star receipt database into one canonical database."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
import sqlite3
import sys


APPLICATION_ID = 0x57465336
SCHEMA_VERSION = 1
RUN_COLUMNS = (
    "run_id", "recorded_at_utc", "source_path", "source_sha256",
    "analysis_path", "exit_code", "error", "solver_version",
    "catalogue_sha256", "solver_status", "result_json", "recorder_sha256",
    "source_manifest_json",
)
RUN_SELECT = ",".join(RUN_COLUMNS)


@dataclass(frozen=True)
class DatabaseLayout:
    path: Path
    storage: str
    runs: int
    products: int
    measurements: int


@dataclass(frozen=True)
class MergeReport:
    source_runs: int
    source_products: int
    source_measurements: int
    absent_runs: int = 0
    imported_runs: int = 0
    existing_runs: int = 0
    verified_runs: int = 0
    missing_content_bytes: int = 0
    required_free_bytes: int = 0
    free_bytes: int = 0


def _readonly_uri(path: Path) -> str:
    return path.resolve(strict=True).as_uri() + "?mode=ro&immutable=1"


def _connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(_readonly_uri(path), uri=True)


def inspect_database(path: Path) -> DatabaseLayout:
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f"database must not be a symlink: {path}")
    with _connect_readonly(path) as db:
        app_id = db.execute("PRAGMA application_id").fetchone()[0]
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if (app_id, version) != (APPLICATION_ID, SCHEMA_VERSION):
            raise ValueError(f"unrecognized point-star database: {path}")
        objects = dict(db.execute(
            "SELECT name,type FROM sqlite_master WHERE name IN "
            "('runs','products','measurements','storage_format')"
        ))
        if objects.get("runs") != "table":
            raise ValueError(f"unrecognized point-star database: {path}")
        if objects.get("storage_format") == "table":
            if objects.get("products") != "view" or objects.get("measurements") != "view":
                raise ValueError(f"invalid compact point-star database: {path}")
            if db.execute("SELECT version FROM storage_format").fetchall() != [(1,)]:
                raise ValueError(f"unsupported compact storage format: {path}")
            storage = "compact"
        elif objects.get("products") == "table" and objects.get("measurements") == "table":
            storage = "legacy"
        else:
            raise ValueError(f"unrecognized point-star database layout: {path}")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError(f"foreign-key failure in {path}")
        invalid_json = db.execute(
            "SELECT count(*) FROM measurements WHERE NOT json_valid(values_json)"
        ).fetchone()[0]
        if invalid_json:
            raise ValueError(f"{invalid_json} malformed measurement JSON rows in {path}")
        counts = [db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                  for table in ("runs", "products", "measurements")]
    return DatabaseLayout(path.resolve(), storage, *counts)


def _validate_product_hashes(path: Path) -> None:
    with _connect_readonly(path) as db:
        for recorded, content in db.execute("SELECT sha256,content FROM products"):
            actual = hashlib.sha256(content).hexdigest()
            if actual != recorded:
                raise ValueError(f"product SHA-256 mismatch: recorded {recorded}, actual {actual}")


def _attached(destination: Path, source: Path) -> sqlite3.Connection:
    db = sqlite3.connect(destination, timeout=60, isolation_level=None, uri=True)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("ATTACH DATABASE ? AS src", (_readonly_uri(source),))
    return db


def _base_report(db: sqlite3.Connection, destination: Path) -> MergeReport:
    counts = [db.execute(f"SELECT count(*) FROM src.{table}").fetchone()[0]
              for table in ("runs", "products", "measurements")]
    absent = db.execute(
        "SELECT count(*) FROM src.runs s LEFT JOIN main.runs d USING(run_id) "
        "WHERE d.run_id IS NULL"
    ).fetchone()[0]
    missing_content = db.execute(
        "SELECT coalesce(sum(n),0) FROM ("
        " SELECT max(length(p.content)) AS n FROM src.products p "
        " JOIN src.runs r USING(run_id) LEFT JOIN main.runs d USING(run_id) "
        " WHERE d.run_id IS NULL AND NOT EXISTS "
        " (SELECT 1 FROM main.product_content c WHERE c.sha256=p.sha256) "
        " GROUP BY p.sha256)"
    ).fetchone()[0]
    missing_measurements = db.execute(
        "SELECT count(*) FROM src.measurements m JOIN src.runs r USING(run_id) "
        "LEFT JOIN main.runs d USING(run_id) WHERE d.run_id IS NULL"
    ).fetchone()[0]
    missing_products = db.execute(
        "SELECT count(*) FROM src.products p JOIN src.runs r USING(run_id) "
        "LEFT JOIN main.runs d USING(run_id) WHERE d.run_id IS NULL"
    ).fetchone()[0]
    required = 64 * 1024 * 1024 + 2 * (
        int(missing_content) + int(missing_measurements) * 160 + int(missing_products) * 160
    )
    free = shutil.disk_usage(destination.parent).free
    return MergeReport(*counts, absent_runs=absent,
                       missing_content_bytes=missing_content,
                       required_free_bytes=required, free_bytes=free)


def estimate_merge(destination: Path, source: Path) -> MergeReport:
    destination, source = Path(destination), Path(source)
    if destination.is_symlink() or source.is_symlink():
        raise ValueError("database paths must not be symlinks")
    if destination.resolve(strict=True) == source.resolve(strict=True):
        raise ValueError("source and destination are the same database")
    dst_layout = inspect_database(destination)
    inspect_database(source)
    if dst_layout.storage != "compact":
        raise ValueError("destination must use compact point-star storage")
    _validate_product_hashes(source)
    with _attached(destination, source) as db:
        report = _base_report(db, destination)
        conflicts = db.execute(
            "SELECT count(*) FROM src.product_content s JOIN main.product_content d USING(sha256) "
            "WHERE s.content != d.content" if _source_is_compact(db) else
            "SELECT count(*) FROM src.products s JOIN main.product_content d USING(sha256) "
            "WHERE s.content != d.content"
        ).fetchone()[0]
        if conflicts:
            raise ValueError("conflicting product bytes for an existing SHA-256")
    if report.required_free_bytes > report.free_bytes:
        raise OSError(
            f"insufficient free space: require {report.required_free_bytes}, "
            f"have {report.free_bytes}"
        )
    return report


def _source_is_compact(db: sqlite3.Connection) -> bool:
    return db.execute(
        "SELECT count(*) FROM src.sqlite_master WHERE type='table' AND name='storage_format'"
    ).fetchone()[0] == 1


def _assert_run_equal(db: sqlite3.Connection, run_id: str) -> None:
    source_run = db.execute(
        f"SELECT {RUN_SELECT} FROM src.runs WHERE run_id=?", (run_id,)
    ).fetchone()
    destination_run = db.execute(
        f"SELECT {RUN_SELECT} FROM main.runs WHERE run_id=?", (run_id,)
    ).fetchone()
    if source_run != destination_run:
        raise ValueError(f"conflicting run UUID: {run_id}")
    source_products = db.execute(
        "SELECT count(*) FROM src.products WHERE run_id=?", (run_id,)
    ).fetchone()[0]
    destination_products = db.execute(
        "SELECT count(*) FROM main.product_refs WHERE run_id=?", (run_id,)
    ).fetchone()[0]
    product_mismatch = db.execute(
        "SELECT 1 FROM src.products s "
        "LEFT JOIN main.product_refs p ON p.run_id=s.run_id AND p.product=s.product "
        "LEFT JOIN main.product_content c ON c.sha256=p.sha256 "
        "WHERE s.run_id=? AND (p.sha256 IS NULL OR p.sha256!=s.sha256 "
        "OR c.content IS NOT s.content) LIMIT 1", (run_id,),
    ).fetchone()
    source_measurements = db.execute(
        "SELECT count(*) FROM src.measurements WHERE run_id=?", (run_id,)
    ).fetchone()[0]
    destination_measurements = db.execute(
        "SELECT count(*) FROM main.measurement_refs WHERE run_id=?", (run_id,)
    ).fetchone()[0]
    measurement_mismatch = db.execute(
        "SELECT 1 FROM src.measurements s "
        "LEFT JOIN main.measurement_refs m ON m.run_id=s.run_id "
        "AND m.product=s.product AND m.row_number=s.row_number "
        "LEFT JOIN main.product_refs p ON p.run_id=m.run_id AND p.product=m.product "
        "LEFT JOIN main.measurement_content c ON c.sha256=p.sha256 "
        "AND c.row_number=m.row_number "
        "WHERE s.run_id=? AND (m.run_id IS NULL OR m.star_id IS NOT s.star_id "
        "OR m.detection_id IS NOT s.detection_id "
        "OR c.values_json IS NOT json(s.values_json)) LIMIT 1", (run_id,),
    ).fetchone()
    product_difference = source_products != destination_products or product_mismatch
    measurement_difference = (
        source_measurements != destination_measurements or measurement_mismatch
    )
    if product_difference or measurement_difference:
        raise ValueError(f"conflicting run UUID: {run_id}")


def merge_databases(destination: Path, source: Path) -> MergeReport:
    destination, source = Path(destination), Path(source)
    estimate = estimate_merge(destination, source)
    imported = existing = 0
    with _attached(destination, source) as db:
        run_ids = [row[0] for row in db.execute(
            "SELECT run_id FROM src.runs ORDER BY recorded_at_utc,run_id"
        )]
        for number, run_id in enumerate(run_ids, 1):
            if db.execute("SELECT 1 FROM main.runs WHERE run_id=?", (run_id,)).fetchone():
                _assert_run_equal(db, run_id)
                existing += 1
                continue
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    f"INSERT INTO main.runs ({RUN_SELECT}) "
                    f"SELECT {RUN_SELECT} FROM src.runs WHERE run_id=?", (run_id,)
                )
                conflict = db.execute(
                    "SELECT 1 FROM src.products s JOIN main.product_content d USING(sha256) "
                    "WHERE s.run_id=? AND s.content!=d.content LIMIT 1", (run_id,)
                ).fetchone()
                if conflict:
                    raise ValueError(f"conflicting product bytes in run {run_id}")
                db.execute(
                    "INSERT OR IGNORE INTO main.product_content(sha256,content) "
                    "SELECT sha256,content FROM src.products WHERE run_id=?", (run_id,)
                )
                db.execute(
                    "INSERT INTO main.product_refs(run_id,product,sha256) "
                    "SELECT run_id,product,sha256 FROM src.products WHERE run_id=?", (run_id,)
                )
                conflict = db.execute(
                    "SELECT 1 FROM src.measurements m JOIN src.products p USING(run_id,product) "
                    "JOIN main.measurement_content c ON c.sha256=p.sha256 AND c.row_number=m.row_number "
                    "WHERE m.run_id=? AND c.values_json!=json(m.values_json) LIMIT 1", (run_id,)
                ).fetchone()
                if conflict:
                    raise ValueError(f"conflicting measurement content in run {run_id}")
                db.execute(
                    "INSERT OR IGNORE INTO main.measurement_content(sha256,row_number,values_json) "
                    "SELECT p.sha256,m.row_number,json(m.values_json) "
                    "FROM src.measurements m JOIN src.products p USING(run_id,product) "
                    "WHERE m.run_id=?", (run_id,)
                )
                db.execute(
                    "INSERT INTO main.measurement_refs(run_id,product,row_number,star_id,detection_id) "
                    "SELECT run_id,product,row_number,star_id,detection_id "
                    "FROM src.measurements WHERE run_id=?", (run_id,)
                )
                broken_product = db.execute(
                    "SELECT 1 FROM main.product_refs p "
                    "LEFT JOIN main.product_content c USING(sha256) "
                    "WHERE p.run_id=? AND c.sha256 IS NULL LIMIT 1", (run_id,)
                ).fetchone()
                broken_measurement = db.execute(
                    "SELECT 1 FROM main.measurement_refs m "
                    "LEFT JOIN main.product_refs p USING(run_id,product) "
                    "LEFT JOIN main.measurement_content c "
                    "ON c.sha256=p.sha256 AND c.row_number=m.row_number "
                    "WHERE m.run_id=? AND (p.sha256 IS NULL OR c.sha256 IS NULL) LIMIT 1",
                    (run_id,),
                ).fetchone()
                if broken_product or broken_measurement:
                    raise ValueError(f"foreign-key/content failure after run {run_id}")
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
            imported += 1
            print(f"MERGED {number}/{len(run_ids)} {run_id}", flush=True)
    return MergeReport(
        estimate.source_runs, estimate.source_products, estimate.source_measurements,
        estimate.absent_runs, imported, existing,
        missing_content_bytes=estimate.missing_content_bytes,
        required_free_bytes=estimate.required_free_bytes, free_bytes=estimate.free_bytes,
    )


def verify_databases(destination: Path, source: Path) -> MergeReport:
    destination, source = Path(destination), Path(source)
    inspect_database(destination)
    source_layout = inspect_database(source)
    _validate_product_hashes(source)
    with _attached(destination, source) as db:
        verified = 0
        for (run_id,) in db.execute("SELECT run_id FROM src.runs ORDER BY run_id"):
            if not db.execute("SELECT 1 FROM main.runs WHERE run_id=?", (run_id,)).fetchone():
                raise ValueError(f"source run absent from destination: {run_id}")
            _assert_run_equal(db, run_id)
            verified += 1
        if db.execute("PRAGMA main.foreign_key_check").fetchone() is not None:
            raise ValueError("destination foreign-key check failed")
    return MergeReport(source_layout.runs, source_layout.products,
                       source_layout.measurements, verified_runs=verified)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify-only", action="store_true")
    mode.add_argument("--estimate-only", action="store_true")
    args = parser.parse_args(argv)
    if args.verify_only:
        report = verify_databases(args.destination, args.source)
    elif args.estimate_only:
        report = estimate_merge(args.destination, args.source)
    else:
        report = merge_databases(args.destination, args.source)
    print("MERGE_REPORT " + " ".join(
        f"{name}={getattr(report, name)}" for name in report.__dataclass_fields__
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
