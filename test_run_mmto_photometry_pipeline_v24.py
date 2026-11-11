"""V24 acquisition must continue the completed v23 queue."""
from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

from scripts import run_mmto_photometry_pipeline_v24 as PIPELINE


def write_state(
    path: Path,
    archive: Path,
    *,
    next_night: str,
    latest_current_night: str,
    pending_recent_nights: list[str] | None = None,
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "archive": str(archive.resolve()),
                "next_night": next_night,
                "latest_current_night": latest_current_night,
                "pending_recent_nights": pending_recent_nights or [],
            }
        )
        + "\n",
        encoding="utf-8",
    )


class V24ProgressInheritanceTests(unittest.TestCase):
    def test_variable_star_stage_launcher_is_executable(self):
        stages = dict(PIPELINE._stage_commands(
            PIPELINE.REPO_ROOT,
            Path("/database.sqlite"),
            Path("/manifest.sqlite"),
            Path("/output"),
        ))

        launcher = Path(stages["variable_star_phase_curves"][0])

        self.assertTrue(launcher.is_file(), launcher)
        self.assertTrue(os.access(launcher, os.X_OK), launcher)

    def test_batch_solver_requires_approved_mmto_visible_sky_mask(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "image.fits.bz2"
            source.write_bytes(b"fixture")
            manifest = (
                root
                / "v24"
                / "data"
                / "sky_masks"
                / "mmto_installation_2026a.json"
            )
            manifest.parent.mkdir(parents=True)
            manifest.write_text("{}\n", encoding="utf-8")
            assignment = {
                "installation_id": "mmto-skycam-2026a",
                "manifest_path": str(manifest.resolve()),
                "mask_id": "mmto-visible-sky-2026a-v1",
            }

            _run_dir, command = PIPELINE._prepare_solver_run(
                root,
                source,
                root / "results",
                assignment,
            )

        self.assertEqual(command[3], sys.executable)
        self.assertIn("--visible-sky-mask-manifest", command)
        self.assertIn("--camera-installation-id", command)
        self.assertEqual(
            command[command.index("--visible-sky-mask-manifest") + 1],
            str(manifest),
        )
        self.assertEqual(
            command[command.index("--camera-installation-id") + 1],
            "mmto-skycam-2026a",
        )

    def test_batch_solver_refuses_unassigned_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "unassigned"):
                PIPELINE._prepare_solver_run(
                    root, root/"image.fits", root/"results", None)

    def test_v23_receipts_and_successful_masked_v24_receipts_are_completed(self):
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "stars.sqlite"
            with sqlite3.connect(database_path) as database:
                database.execute(
                    "CREATE TABLE runs ("
                    "source_sha256 TEXT, solver_version TEXT, "
                    "source_manifest_json TEXT, exit_code INTEGER, "
                    "result_json TEXT)"
                )
                database.executemany(
                    "INSERT INTO runs VALUES (?, ?, ?, ?, ?)",
                    (
                        ("v23-direct", "0.23.0", "{}", 1, None),
                        ("v23-manifest", "", '{"version":"0.23.0"}', 1, None),
                        (
                            "v24-masked",
                            "0.24.0",
                            "{}",
                            0,
                            json.dumps({
                                "input_image": {
                                    "visible_sky_mask": {
                                        "status": "approved",
                                        "mask_id": "mmto-visible-sky-2026a-v1",
                                        "installation_id": "mmto-skycam-2026a",
                                    }
                                }
                            }),
                        ),
                        (
                            "v24-failed-before-mask",
                            "",
                            '{"version":"0.24.0"}',
                            1,
                            None,
                        ),
                        (
                            "v24-unmasked",
                            "0.24.0",
                            "{}",
                            0,
                            json.dumps({
                                "input_image": {
                                    "visible_sky_mask": {"status": "not_configured"}
                                }
                            }),
                        ),
                        (
                            "v24-other-approved-mask",
                            "0.24.0",
                            "{}",
                            0,
                            json.dumps({
                                "input_image": {
                                    "visible_sky_mask": {
                                        "status": "approved",
                                        "mask_id": "another-mask",
                                        "installation_id": "another-installation",
                                    }
                                }
                            }),
                        ),
                        ("v22-old", "0.22.0", '{"version":"0.22.0"}', 0, None),
                    ),
                )

            completed = PIPELINE._processed_source_digests(database_path)

        self.assertEqual(
            completed,
            {"v23-direct", "v23-manifest", "v24-masked"},
        )

    def test_processing_gate_retries_failed_and_unmasked_v24_receipts(self):
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "stars.sqlite"
            approved = json.dumps({
                "input_image": {
                    "visible_sky_mask": {
                        "status": "approved",
                        "mask_id": "mmto-visible-sky-2026a-v1",
                        "installation_id": "mmto-skycam-2026a",
                    }
                }
            })
            unmasked = json.dumps({
                "input_image": {
                    "visible_sky_mask": {"status": "not_configured"}
                }
            })
            with sqlite3.connect(database_path) as database:
                database.execute(
                    "CREATE TABLE runs ("
                    "source_sha256 TEXT, solver_version TEXT, "
                    "source_manifest_json TEXT, exit_code INTEGER, "
                    "result_json TEXT)"
                )
                database.executemany(
                    "INSERT INTO runs VALUES (?, ?, ?, ?, ?)",
                    (
                        ("failed", "", '{"version":"0.24.0"}', 1, None),
                        ("unmasked", "0.24.0", "{}", 0, unmasked),
                        ("masked", "0.24.0", "{}", 0, approved),
                    ),
                )

            self.assertIsNone(
                PIPELINE._latest_completed_masked_v24_receipt(
                    database_path, "failed"
                )
            )
            self.assertIsNone(
                PIPELINE._latest_completed_masked_v24_receipt(
                    database_path, "unmasked"
                )
            )
            self.assertEqual(
                PIPELINE._latest_completed_masked_v24_receipt(
                    database_path, "masked"
                ),
                0,
            )

    def test_missing_v24_state_inherits_v23_cursor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            write_state(
                root / "mmto-v23-backfill-state.json",
                archive,
                next_night="2026-08-31",
                latest_current_night="2026-11-10",
                pending_recent_nights=["2026-11-09"],
            )

            state = PIPELINE.load_backfill_state(
                root / "mmto-v24-backfill-state.json",
                archive,
                date(2026, 11, 10),
            )

        self.assertEqual(state.next_night, date(2026, 8, 31))
        self.assertEqual(state.latest_current_night, date(2026, 11, 10))
        self.assertEqual(state.pending_recent_nights, (date(2026, 11, 9),))

    def test_existing_v24_state_remains_authoritative(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            write_state(
                root / "mmto-v23-backfill-state.json",
                archive,
                next_night="2026-08-31",
                latest_current_night="2026-11-10",
            )
            write_state(
                root / "mmto-v24-backfill-state.json",
                archive,
                next_night="2026-08-20",
                latest_current_night="2026-11-11",
            )

            state = PIPELINE.load_backfill_state(
                root / "mmto-v24-backfill-state.json",
                archive,
                date(2026, 11, 11),
            )

        self.assertEqual(state.next_night, date(2026, 8, 20))
        self.assertEqual(state.latest_current_night, date(2026, 11, 11))

    def test_missing_predecessor_state_keeps_new_queue_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()

            state = PIPELINE.load_backfill_state(
                root / "mmto-v24-backfill-state.json",
                archive,
                date(2026, 11, 10),
            )

        self.assertEqual(state.next_night, date(2026, 11, 10))
        self.assertEqual(state.latest_current_night, date(2026, 11, 10))

    def test_invalid_v23_state_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            other_archive = root / "other-archive"
            archive.mkdir()
            other_archive.mkdir()
            write_state(
                root / "mmto-v23-backfill-state.json",
                other_archive,
                next_night="2026-08-31",
                latest_current_night="2026-11-10",
            )

            with self.assertRaisesRegex(ValueError, "different archive"):
                PIPELINE.load_backfill_state(
                    root / "mmto-v24-backfill-state.json",
                    archive,
                    date(2026, 11, 10),
                )

    def test_v23_state_directory_is_not_treated_as_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            (root / "mmto-v23-backfill-state.json").mkdir()

            with self.assertRaisesRegex(ValueError, "not a regular file"):
                PIPELINE.load_backfill_state(
                    root / "mmto-v24-backfill-state.json",
                    archive,
                    date(2026, 11, 10),
                )

    def test_v24_state_directory_does_not_fall_back_to_v23(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            (root / "mmto-v24-backfill-state.json").mkdir()
            write_state(
                root / "mmto-v23-backfill-state.json",
                archive,
                next_night="2026-08-31",
                latest_current_night="2026-11-10",
            )

            with self.assertRaisesRegex(ValueError, "not a regular file"):
                PIPELINE.load_backfill_state(
                    root / "mmto-v24-backfill-state.json",
                    archive,
                    date(2026, 11, 10),
                )


if __name__ == "__main__":
    unittest.main()
