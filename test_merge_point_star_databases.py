from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.merge_point_star_databases import merge_databases, verify_databases
from v20.point_star_database import APPLICATION_ID, SCHEMA, SCHEMA_VERSION, _initialize


RUN_COLUMNS = 13


def make_legacy(path: Path) -> None:
    with sqlite3.connect(path) as db:
        for statement in SCHEMA:
            db.execute(statement)
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        content = b"star_id,flux\n1,42\n"
        digest = hashlib.sha256(content).hexdigest()
        for number, exit_code in ((1, 0), (2, 1)):
            run_id = f"run-{number}"
            db.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, f"2026-10-0{number}T00:00:00+00:00", "/same.fits",
                 "same-source-digest", f"/analysis/{number}", exit_code,
                 None if not exit_code else "failed", "0.16.0", "catalogue",
                 "ok" if not exit_code else "failed", None, "recorder", None),
            )
            db.execute("INSERT INTO products VALUES (?,?,?,?)",
                       (run_id, "stellar_photometry.csv", digest, content))
            db.execute("INSERT INTO measurements VALUES (?,?,?,?,?,?)",
                       (run_id, "stellar_photometry.csv", 1, "1", "d1",
                        '{ "flux": "42", "star_id": "1" }'))


def make_compact(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.execute("BEGIN IMMEDIATE")
        _initialize(db)
        db.commit()


class MergePointStarDatabasesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.source = root / "legacy.sqlite"
        self.destination = root / "canonical.sqlite"
        make_legacy(self.source)
        make_compact(self.destination)

    def tearDown(self):
        self.temp.cleanup()

    def test_merge_preserves_repeated_digest_failed_run_and_exact_rows(self):
        source_before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        report = merge_databases(self.destination, self.source)
        self.assertEqual((report.source_runs, report.imported_runs), (2, 2))
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), source_before)
        with sqlite3.connect(self.destination) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM runs").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT exit_code FROM runs ORDER BY run_id").fetchall(), [(0,), (1,)])
            self.assertEqual(db.execute("SELECT count(*) FROM products").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT count(*) FROM product_content").fetchone()[0], 1)
            values = db.execute("SELECT values_json FROM measurements ORDER BY run_id").fetchall()
            self.assertEqual(values, [(json.dumps({"flux": "42", "star_id": "1"}, separators=(",", ":")),)] * 2)
        verified = verify_databases(self.destination, self.source)
        self.assertEqual(verified.verified_runs, 2)

    def test_merge_is_idempotent(self):
        merge_databases(self.destination, self.source)
        report = merge_databases(self.destination, self.source)
        self.assertEqual((report.imported_runs, report.existing_runs), (0, 2))

    def test_conflicting_existing_uuid_fails_closed(self):
        merge_databases(self.destination, self.source)
        with sqlite3.connect(self.source) as db:
            db.execute("UPDATE runs SET source_path='/different.fits' WHERE run_id='run-1'")
        with self.assertRaisesRegex(ValueError, "conflicting run UUID"):
            merge_databases(self.destination, self.source)

    def test_verifier_detects_a_missing_destination_measurement(self):
        merge_databases(self.destination, self.source)
        with sqlite3.connect(self.destination) as db:
            db.execute("DELETE FROM measurement_refs WHERE run_id='run-1'")
        with self.assertRaisesRegex(ValueError, "conflicting run UUID"):
            verify_databases(self.destination, self.source)


if __name__ == "__main__":
    unittest.main()
