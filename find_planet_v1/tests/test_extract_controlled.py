from __future__ import annotations

from dataclasses import asdict, fields
import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT / "find_planet_v1"))

from find_planet.extract_controlled import (
    ControlledExtractionError,
    load_exact_receipts,
    select_answer_key_rows,
    write_answer_key_audit,
)
from find_planet.types import SelectedCentroid


def fixture_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript((FIXTURES / "runs.sql").read_text(encoding="utf-8"))
    connection.commit()
    connection.close()


class ControlledSelectionTests(unittest.TestCase):
    def test_exact_audit_hash_is_required(self):
        audit = FIXTURES / "controlled_audit.csv"
        with self.assertRaisesRegex(ControlledExtractionError, "SHA-256"):
            select_answer_key_rows(audit, "0" * 64)

    def test_mars_only_selection_preserves_audit_and_order(self):
        audit = FIXTURES / "controlled_audit.csv"
        selected, audit_rows = select_answer_key_rows(audit, fixture_hash(audit))

        self.assertEqual([row.source_sha256 for row in selected], ["sha-a", "sha-c"])
        self.assertEqual(len(audit_rows), 5)
        by_run = {row["run_id"]: row for row in audit_rows}
        self.assertEqual(by_run["run-a"]["answer_key_selection_status"], "selected")
        self.assertEqual(by_run["run-s"]["answer_key_selection_reason"], "different_answer_key_object")
        self.assertEqual(by_run["run-a-copy"]["answer_key_selection_reason"], "duplicate_source_sha256")
        self.assertEqual(by_run["run-b"]["answer_key_selection_reason"], "metadata_association_unavailable")

    def test_selected_centroid_is_identity_free(self):
        audit = FIXTURES / "controlled_audit.csv"
        selected, _ = select_answer_key_rows(audit, fixture_hash(audit))

        banned = ("planet", "predicted", "distance", "mars", "horizons")
        field_names = " ".join(field.name.lower() for field in fields(SelectedCentroid))
        serialised = json.dumps([asdict(row) for row in selected]).lower()
        for word in banned:
            self.assertNotIn(word, field_names)
            self.assertNotIn(word, serialised)

    def test_answer_key_writer_preserves_every_original_row(self):
        audit = FIXTURES / "controlled_audit.csv"
        _, audit_rows = select_answer_key_rows(audit, fixture_hash(audit))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "answer_key_selection.csv"
            write_answer_key_audit(output, audit_rows)
            with output.open(newline="", encoding="utf-8") as handle:
                written = list(csv.DictReader(handle))

        self.assertEqual(len(written), 5)
        self.assertEqual([row["run_id"] for row in written], [row["run_id"] for row in audit_rows])
        self.assertIn("answer_key_selection_reason", written[0])


class ExactReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "stars.sqlite"
        fixture_database(self.database)
        audit = FIXTURES / "controlled_audit.csv"
        self.selected, _ = select_answer_key_rows(audit, fixture_hash(audit))

    def tearDown(self):
        self.temporary.cleanup()

    def test_exact_successful_receipts_are_loaded(self):
        receipts = load_exact_receipts(self.database, self.selected)

        self.assertEqual(set(receipts), {"run-a", "run-c"})
        self.assertEqual(receipts["run-a"].source_sha256, "sha-a")
        self.assertEqual(receipts["run-c"].solver_version, "0.21.0")
        self.assertEqual(receipts["run-a"].camera["model"], "Barghini_2019_equations_5_6_11")

    def test_missing_receipt_never_falls_back_to_same_source(self):
        missing = SelectedCentroid(
            run_id="run-missing",
            source_sha256="sha-a",
            source_path="/archive/image-a.fits",
            night="2026-09-01",
            observation_time_utc="2026-09-02T03:00:00Z",
            detection_id="10",
            x_px=101.5,
            y_px=201.5,
            stellar_fit_rms_arcmin=2.0,
            source_class="compact",
            saturated=False,
        )
        with self.assertRaisesRegex(ControlledExtractionError, "run-missing.*exactly one"):
            load_exact_receipts(self.database, [missing])

    def test_failed_mismatched_duplicate_and_malformed_receipts_are_rejected(self):
        connection = sqlite3.connect(self.database)
        base = (
            "/archive/image-a.fits",
            "sha-a",
            "0.23.0",
            json.dumps({"camera": {"model": "Barghini_2019_equations_5_6_11"}}),
        )
        connection.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)", ("run-failed", base[0], base[1], 1, base[2], base[3]))
        connection.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)", ("run-mismatch", base[0], "other-sha", 0, base[2], base[3]))
        connection.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)", ("run-duplicate", base[0], base[1], 0, base[2], base[3]))
        connection.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)", ("run-duplicate", base[0], base[1], 0, base[2], base[3]))
        connection.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)", ("run-malformed", base[0], base[1], 0, base[2], "{}"))
        connection.commit()
        connection.close()

        def row(run_id: str) -> SelectedCentroid:
            return SelectedCentroid(
                run_id=run_id,
                source_sha256="sha-a",
                source_path=base[0],
                night="2026-09-01",
                observation_time_utc="2026-09-02T03:00:00Z",
                detection_id="10",
                x_px=101.5,
                y_px=201.5,
                stellar_fit_rms_arcmin=2.0,
                source_class="compact",
                saturated=False,
            )

        cases = {
            "run-failed": "failed",
            "run-mismatch": "source SHA",
            "run-duplicate": "exactly one",
            "run-malformed": "camera",
        }
        for run_id, message in cases.items():
            with self.subTest(run_id=run_id):
                with self.assertRaisesRegex(ControlledExtractionError, message):
                    load_exact_receipts(self.database, [row(run_id)])


if __name__ == "__main__":
    unittest.main()
