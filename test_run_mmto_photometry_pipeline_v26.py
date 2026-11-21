"""V26 acquisition must continue the completed v23 queue."""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import date
from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from scripts import run_mmto_photometry_pipeline_v26 as PIPELINE

V23_PRODUCTION_CORE_FIGURES = frozenset(
    Path(name)
    for name in """\
acquisition_timeline.pdf
differential-photometry/model_comparison.pdf
differential-photometry/planet_relative_lightcurves.pdf
differential-photometry/residual_diagnostics.pdf
differential-photometry/signal_recovery.pdf
known-site-time-validation/mmto_planet_epoch_validation.png
known-site-time-validation/mmto_site_time_validation.png
nightly-extinction-v26/grey_transparency.png
nightly-extinction/extinction_by_band_and_night.pdf
nightly-extinction/extinction_diagnostics.pdf
planet-empirical-extinction/B/planet_only_airmass_before_after.pdf
planet-empirical-extinction/B/planet_only_extinction_distance_corrected_magnitude_vs_hours_past_local_noon.pdf
planet-empirical-extinction/G/planet_only_airmass_before_after.pdf
planet-empirical-extinction/G/planet_only_extinction_distance_corrected_magnitude_vs_hours_past_local_noon.pdf
planet-empirical-extinction/R/planet_only_airmass_before_after.pdf
planet-empirical-extinction/R/planet_only_extinction_distance_corrected_magnitude_vs_hours_past_local_noon.pdf
planet-photometry/B/planet_extinction_corrected_distance_magnitude_vs_airmass.pdf
planet-photometry/B/planet_extinction_corrected_distance_magnitude_vs_hours_past_local_noon.pdf
planet-photometry/B/planet_extinction_corrected_distance_magnitude_vs_time.pdf
planet-photometry/B/planet_raw_vs_extinction_corrected_magnitude_vs_airmass.pdf
planet-photometry/G/planet_extinction_corrected_distance_magnitude_vs_airmass.pdf
planet-photometry/G/planet_extinction_corrected_distance_magnitude_vs_hours_past_local_noon.pdf
planet-photometry/G/planet_extinction_corrected_distance_magnitude_vs_time.pdf
planet-photometry/G/planet_raw_vs_extinction_corrected_magnitude_vs_airmass.pdf
planet-photometry/R/planet_extinction_corrected_distance_magnitude_vs_airmass.pdf
planet-photometry/R/planet_extinction_corrected_distance_magnitude_vs_hours_past_local_noon.pdf
planet-photometry/R/planet_extinction_corrected_distance_magnitude_vs_time.pdf
planet-photometry/R/planet_raw_vs_extinction_corrected_magnitude_vs_airmass.pdf
planet-photometry/planet_brightness_matched_stellar_extinction.pdf
planet-photometry/planet_colour_colour.png
stellar-lightcurves/lightcurves.pdf
stellar-lightcurves/sd_vs_magnitude.pdf
variable-stars/variable_star_phase_curves.pdf
""".splitlines()
)


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


class V26ProgressInheritanceTests(unittest.TestCase):
    def test_host_selected_results_state_selects_the_matching_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            config_root = root / "config"
            config_dir = config_root / "wide-field-solver"
            config_dir.mkdir(parents=True)

            for hostname in ("home-host", "work-host"):
                with self.subTest(hostname=hostname):
                    results = root / f"{hostname}-results"
                    archive = root / f"{hostname}-archive"
                    results.mkdir()
                    archive.mkdir()
                    (config_dir / f"results-dir.{hostname}").write_text(
                        str(results) + "\n", encoding="utf-8"
                    )
                    state_path = results / "mmto-v26-backfill-state.json"
                    write_state(
                        state_path,
                        archive,
                        next_night="2026-06-29",
                        latest_current_night="2026-11-17",
                    )

                    with (
                        mock.patch.dict(
                            os.environ,
                            {"XDG_CONFIG_HOME": str(config_root)},
                            clear=True,
                        ),
                        mock.patch.object(
                            PIPELINE.os,
                            "uname",
                            return_value=SimpleNamespace(nodename=hostname),
                        ),
                    ):
                        selected_results = PIPELINE._default_results_dir(repo)

                    self.assertEqual(selected_results, results)
                    self.assertEqual(
                        PIPELINE._default_archive_dir(repo, state_path), archive
                    )

    def test_v26_launcher_does_not_override_host_selected_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            capture = root / "uv-arguments.txt"
            uv = bin_dir / "uv"
            uv.write_text(
                "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$WFS_CAPTURE\"\n",
                encoding="utf-8",
            )
            uv.chmod(0o755)
            env = dict(os.environ)
            env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
            env["WFS_CAPTURE"] = str(capture)

            completed = subprocess.run(
                [str(PIPELINE.REPO_ROOT / "go_mmto_photometry_v26.sh"), "--max-images", "234"],
                cwd=root,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout)
            arguments = capture.read_text(encoding="utf-8").splitlines()
            self.assertNotIn("--results-dir", arguments)

    def test_v23_figure_contract_matches_latest_complete_v23_output(self):
        # Normalized fixed-figure inventory from v23-20261110T191148Z.
        self.assertEqual(len(V23_PRODUCTION_CORE_FIGURES), 33)
        self.assertEqual(
            PIPELINE.V23_CORE_FIGURE_CONTRACT,
            V23_PRODUCTION_CORE_FIGURES,
        )

    def test_v26_cannot_complete_with_a_missing_v23_core_figure(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for relative in PIPELINE.V23_CORE_FIGURE_CONTRACT:
                path = output / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"figure")
            missing = (
                output
                / "planet-photometry"
                / "R"
                / "planet_extinction_corrected_distance_magnitude_vs_time.pdf"
            )
            missing.unlink()

            with self.assertRaisesRegex(
                PIPELINE.OperationalFailure,
                "planet_extinction_corrected_distance_magnitude_vs_time.pdf",
            ):
                PIPELINE._require_v23_core_figures(output)

            missing.write_bytes(b"figure")
            PIPELINE._require_v23_core_figures(output)

    def test_v26_rejects_an_empty_v23_core_figure(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for relative in V23_PRODUCTION_CORE_FIGURES:
                path = output / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"figure")
            empty = output / "planet-photometry" / "planet_colour_colour.png"
            empty.write_bytes(b"")

            with self.assertRaisesRegex(
                PIPELINE.OperationalFailure,
                "planet_colour_colour.png",
            ):
                PIPELINE._require_v23_core_figures(output)

    def test_success_is_recorded_only_after_v23_figure_parity_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for relative in V23_PRODUCTION_CORE_FIGURES:
                path = output / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"figure")
            missing = output / "planet-photometry" / "R" / (
                "planet_extinction_corrected_distance_magnitude_vs_time.pdf"
            )
            missing.unlink()
            summary: dict[str, object] = {"status": "running"}
            log = StringIO()

            with self.assertRaises(PIPELINE.OperationalFailure):
                PIPELINE._finalize_success(output, summary, log)

            self.assertEqual(summary, {"status": "running"})
            self.assertFalse((output / "pipeline_summary.json").exists())

            missing.write_bytes(b"figure")
            PIPELINE._finalize_success(output, summary, log)

            self.assertEqual(summary["status"], "complete")
            saved = json.loads((output / "pipeline_summary.json").read_text())
            self.assertEqual(saved["status"], "complete")

    def test_every_configured_v26_derived_stage_program_can_start(self):
        stages = PIPELINE._stage_commands(
            PIPELINE.REPO_ROOT,
            Path("/database.sqlite"),
            Path("/manifest.sqlite"),
            Path("/output"),
        )

        for name, command in stages:
            completed = subprocess.run(
                [*command, "--help"],
                cwd=PIPELINE.REPO_ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, f"{name}: {completed.stdout}")

    def test_generated_python_stages_pin_the_v26_project(self):
        stages = dict(PIPELINE._stage_commands(
            PIPELINE.REPO_ROOT,
            Path("/database.sqlite"),
            Path("/manifest.sqlite"),
            Path("/output"),
        ))
        expected_prefix = [
            "uv", "run", "--project", str(PIPELINE.REPO_ROOT / "v26"), "--frozen",
        ]
        for name in ("same_sidereal_transmission", "known_site_time_validation"):
            with self.subTest(stage=name):
                self.assertEqual(stages[name][:5], expected_prefix)

    def test_receipt_verification_waits_until_all_solver_workers_finish(self):
        active = 0
        lock = threading.Lock()
        both_started = threading.Event()

        def solve(item: int) -> str:
            nonlocal active
            with lock:
                active += 1
                if active == 2:
                    both_started.set()
            self.assertTrue(both_started.wait(timeout=1.0))
            if item == 2:
                time.sleep(0.1)
            with lock:
                active -= 1
            return f"solved-{item}"

        def verify(_item: int, result: str) -> str:
            with lock:
                self.assertEqual(active, 0)
            return result

        results = PIPELINE._run_solver_jobs_then_verify(
            (1, 2), 2, solve, verify
        )

        self.assertEqual(results, ("solved-1", "solved-2"))

    def test_solver_transcript_is_retained_without_streaming_to_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            terminal = StringIO()
            command = [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "print('Traceback: expected per-image solver failure'); "
                    "sys.exit(1)"
                ),
            ]

            with redirect_stdout(terminal):
                return_code, transcript = PIPELINE._run_logged_solver(
                    command,
                    run_dir,
                    cwd=Path(__file__).resolve().parent,
                    prefix="PROCESS test-image.fits\n",
                )

            saved = (run_dir / "run.log").read_text(encoding="utf-8")

        self.assertEqual(return_code, 1)
        self.assertEqual(
            terminal.getvalue(),
            f"SOLVER EXIT 1; details: {run_dir / 'run.log'}\n",
        )
        self.assertIn("PROCESS test-image.fits", saved)
        self.assertIn("Traceback: expected per-image solver failure", saved)
        self.assertEqual(transcript, saved)

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
                / "v26"
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

    def test_mmto_assignment_resolves_through_bundled_generic_registry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assignments = root / "assignments.jsonl"
            digest = "a" * 64
            resolved = {
                "source_id": "mmto",
                "camera_id": "mmto-skycam",
                "installation_id": "mmto-skycam-2026a",
                "mask_id": "mmto-visible-sky-2026a-v1",
                "manifest_path": str(
                    root / "v26/data/sky_masks/mmto_installation_2026a.json"
                ),
            }
            with mock.patch.object(
                PIPELINE, "resolve_source_calibration", return_value=resolved
            ) as resolve:
                self.assertEqual(
                    PIPELINE._resolve_mmto_calibration(root, assignments, digest),
                    resolved,
                )
            resolve.assert_called_once_with(
                (root / PIPELINE.MMTO_CALIBRATION_REGISTRY,),
                assignments,
                digest,
            )

    def test_batch_solver_refuses_a_non_mmto_mask_assignment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / PIPELINE.MMTO_VISIBLE_SKY_MASK_MANIFEST
            manifest.parent.mkdir(parents=True)
            manifest.write_text("{}\n")
            assignment = {
                "installation_id": PIPELINE.MMTO_CAMERA_INSTALLATION_ID,
                "manifest_path": str(manifest),
                "mask_id": "another-mask",
            }
            with self.assertRaisesRegex(ValueError, "approved installation mask"):
                PIPELINE._prepare_solver_run(
                    root, root / "image.fits", root / "results", assignment
                )

    def test_batch_solver_refuses_unassigned_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "unassigned"):
                PIPELINE._prepare_solver_run(
                    root, root/"image.fits", root/"results", None)

    def test_predecessor_receipts_and_successful_masked_v26_receipts_are_completed(self):
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
                        ("v24-direct", "0.24.0", "{}", 1, None),
                        ("v24-manifest", "", '{"version":"0.24.0"}', 1, None),
                        (
                            "v26-masked",
                            "0.26.0",
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
                            "v26-failed-before-mask",
                            "",
                            '{"version":"0.26.0"}',
                            1,
                            None,
                        ),
                        (
                            "v26-unmasked",
                            "0.26.0",
                            "{}",
                            0,
                            json.dumps({
                                "input_image": {
                                    "visible_sky_mask": {"status": "not_configured"}
                                }
                            }),
                        ),
                        (
                            "v26-other-approved-mask",
                            "0.26.0",
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
            {
                "v23-direct", "v23-manifest", "v24-direct", "v24-manifest",
                "v26-masked",
            },
        )

    def test_processing_gate_retries_failed_and_unmasked_v26_receipts(self):
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
                        ("failed", "", '{"version":"0.26.0"}', 1, None),
                        ("unmasked", "0.26.0", "{}", 0, unmasked),
                        ("masked", "0.26.0", "{}", 0, approved),
                    ),
                )

            self.assertIsNone(
                PIPELINE._latest_completed_masked_v26_receipt(
                    database_path, "failed"
                )
            )
            self.assertIsNone(
                PIPELINE._latest_completed_masked_v26_receipt(
                    database_path, "unmasked"
                )
            )
            self.assertEqual(
                PIPELINE._latest_completed_masked_v26_receipt(
                    database_path, "masked"
                ),
                0,
            )

    def test_missing_v26_state_inherits_v24_cursor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            write_state(
                root / "mmto-v24-backfill-state.json",
                archive,
                next_night="2026-08-31",
                latest_current_night="2026-11-10",
                pending_recent_nights=["2026-11-09"],
            )

            state = PIPELINE.load_backfill_state(
                root / "mmto-v26-backfill-state.json",
                archive,
                date(2026, 11, 10),
            )

        self.assertEqual(state.next_night, date(2026, 8, 31))
        self.assertEqual(state.latest_current_night, date(2026, 11, 10))
        self.assertEqual(state.pending_recent_nights, (date(2026, 11, 9),))

    def test_existing_v26_state_remains_authoritative(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            write_state(
                root / "mmto-v24-backfill-state.json",
                archive,
                next_night="2026-08-31",
                latest_current_night="2026-11-10",
            )
            write_state(
                root / "mmto-v26-backfill-state.json",
                archive,
                next_night="2026-08-20",
                latest_current_night="2026-11-11",
            )

            state = PIPELINE.load_backfill_state(
                root / "mmto-v26-backfill-state.json",
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
                root / "mmto-v26-backfill-state.json",
                archive,
                date(2026, 11, 10),
            )

        self.assertEqual(state.next_night, date(2026, 11, 10))
        self.assertEqual(state.latest_current_night, date(2026, 11, 10))

    def test_invalid_v24_state_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            other_archive = root / "other-archive"
            archive.mkdir()
            other_archive.mkdir()
            write_state(
                root / "mmto-v24-backfill-state.json",
                other_archive,
                next_night="2026-08-31",
                latest_current_night="2026-11-10",
            )

            with self.assertRaisesRegex(ValueError, "different archive"):
                PIPELINE.load_backfill_state(
                    root / "mmto-v26-backfill-state.json",
                    archive,
                    date(2026, 11, 10),
                )

    def test_v24_state_directory_is_not_treated_as_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            (root / "mmto-v24-backfill-state.json").mkdir()

            with self.assertRaisesRegex(ValueError, "not a regular file"):
                PIPELINE.load_backfill_state(
                    root / "mmto-v26-backfill-state.json",
                    archive,
                    date(2026, 11, 10),
                )

    def test_v26_state_directory_does_not_fall_back_to_v24(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            (root / "mmto-v26-backfill-state.json").mkdir()
            write_state(
                root / "mmto-v24-backfill-state.json",
                archive,
                next_night="2026-08-31",
                latest_current_night="2026-11-10",
            )

            with self.assertRaisesRegex(ValueError, "not a regular file"):
                PIPELINE.load_backfill_state(
                    root / "mmto-v26-backfill-state.json",
                    archive,
                    date(2026, 11, 10),
                )


if __name__ == "__main__":
    unittest.main()
