"""Bounded backward MMTO acquisition and v21 orchestration behavior."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from contextlib import redirect_stdout
import bz2
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

import numpy as np
from astropy.io import fits

from allsky_download.http import DownloadedFile
from allsky_download.manifest import Manifest
from allsky_download.model import Candidate
from allsky_download.registry import SourceRegistry
from scripts import run_mmto_photometry_pipeline_v21 as PIPELINE
from scripts.run_mmto_photometry_pipeline_v19 import _stage_commands as v19_stage_commands


ROOT = Path(__file__).resolve().parent
ARIZONA = ZoneInfo("America/Phoenix")
SITE = SourceRegistry.from_json(ROOT / "sources.json").get_adapter("mmto").sites(
    "mmto-skycam"
)[0]


def candidate(night: date, minute: int, name: str) -> Candidate:
    observed = datetime(
        night.year, night.month, night.day, 22, minute, tzinfo=ARIZONA
    )
    return Candidate(
        "mmto",
        "mmto-skycam",
        observed,
        observed.isoformat(),
        f"https://mmto/{night.isoformat()}/{name}",
        f"{name}.fits.bz2",
        None,
        {"archive_bucket": night.isoformat(), "compression": "bzip2"},
    )


class Listing:
    def __init__(self, by_night: dict[date, tuple[Candidate, ...]]):
        self.by_night = by_night
        self.calls = []

    def list_candidates(self, _client, _site, date_range):
        self.calls.append(date_range)
        night = date_range.start_utc.astimezone(ARIZONA).date()
        return self.by_night.get(night, ())


def record_verified(archive: Path, item: Candidate, payload: bytes) -> tuple[Path, str]:
    destination = (
        archive / "mmto" / "mmto-skycam" / item.metadata["archive_bucket"]
        / item.filename
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    with Manifest(archive / "manifest.sqlite") as manifest:
        manifest.record_attempt(item)
        manifest.record_success(
            item,
            DownloadedFile(destination, len(payload), digest),
            archive,
        )
    return destination, digest


def results_database(path: Path, receipts: list[tuple[str, str, int]]) -> None:
    with sqlite3.connect(path) as database:
        database.execute(
            "CREATE TABLE IF NOT EXISTS runs (source_sha256 TEXT, solver_version TEXT, "
            "exit_code INTEGER, source_manifest_json TEXT)"
        )
        database.executemany(
            "INSERT INTO runs VALUES (?,?,?,?)",
            [
                (digest, version, exit_code, json.dumps({"version": version}))
                for digest, version, exit_code in receipts
            ],
        )


def mmto_fits_payload(item: Candidate, exposure: float = 20.0) -> bytes:
    local = item.observed_at.astimezone(ARIZONA).replace(tzinfo=None)
    start = item.observed_at.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    end = start + timedelta(seconds=exposure)
    header = fits.Header(
        {
            "INSTRUME": "ZWO ASI294MC Pro",
            "SITELAT": "+31:41:12:00",
            "SITELONG": "-110:53:03:00",
            "STACKNB": 1,
            "DATE-OBS": local.isoformat(timespec="microseconds"),
            "DATE-BEG": start.isoformat(timespec="microseconds"),
            "DATE-END": end.isoformat(timespec="microseconds"),
            "EXPOSURE": exposure,
        }
    )
    stream = io.BytesIO()
    fits.PrimaryHDU(np.zeros((4, 4), dtype=np.uint16), header).writeto(stream)
    return bz2.compress(stream.getvalue())


class V21SelectionTests(unittest.TestCase):
    def test_cli_defaults_to_forty_and_rejects_nonpositive_caps(self):
        parser = PIPELINE._build_parser()
        self.assertEqual(parser.parse_args([]).max_images, 40)
        self.assertEqual(parser.parse_args([]).oldest_night, date(2026, 6, 30))
        with self.assertRaises(SystemExit):
            parser.parse_args(["--max-images", "0"])

    def test_lists_only_single_nights_and_stops_as_soon_as_cap_is_full(self):
        current = date(2026, 10, 15)
        previous = current - timedelta(days=1)
        listing = Listing(
            {
                current: (candidate(current, 0, "current"),),
                previous: (candidate(previous, 0, "previous"),),
                previous - timedelta(days=1): (
                    candidate(previous - timedelta(days=1), 0, "too-old"),
                ),
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = PIPELINE.build_acquisition_plan(
                root / "archive",
                root / "stars.sqlite",
                state_path=root / "state.json",
                current_night=current,
                oldest_night=previous - timedelta(days=1),
                max_images=2,
                adapter=listing,
                client=object(),
                site=SITE,
            )

        self.assertEqual([item.candidate.filename for item in plan.selected], [
            "current.fits.bz2", "previous.fits.bz2"
        ])
        self.assertEqual(len(listing.calls), 2)
        for requested in listing.calls:
            self.assertEqual(requested.end_utc - requested.start_utc, timedelta(days=1))

    def test_old_receipts_do_not_suppress_v21_reprocessing(self):
        night = date(2026, 10, 15)
        first = candidate(night, 0, "v16-failed")
        second = candidate(night, 20, "other-version")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            _, first_digest = record_verified(archive, first, b"first")
            _, second_digest = record_verified(archive, second, b"second")
            database = root / "stars.sqlite"
            results_database(
                database,
                [(first_digest, "0.16.0", 1), (second_digest, "0.12.0", 0)],
            )
            plan = PIPELINE.build_acquisition_plan(
                archive,
                database,
                state_path=root / "state.json",
                current_night=night,
                oldest_night=night,
                max_images=40,
                adapter=Listing({night: (first, second)}),
                client=object(),
                site=SITE,
            )

        self.assertEqual(plan.processed_receipts_skipped, 0)
        self.assertEqual(
            {item.source_sha256 for item in plan.selected},
            {first_digest, second_digest},
        )

    def test_any_v21_receipt_including_failure_marks_digest_processed(self):
        night = date(2026, 10, 15)
        first = candidate(night, 0, "v21-failed")
        second = candidate(night, 20, "v21-success")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            _, first_digest = record_verified(archive, first, b"first")
            _, second_digest = record_verified(archive, second, b"second")
            database = root / "stars.sqlite"
            results_database(
                database,
                [(first_digest, "0.21.0", 1), (second_digest, "0.21.0", 0)],
            )
            plan = PIPELINE.build_acquisition_plan(
                archive,
                database,
                state_path=root / "state.json",
                current_night=night,
                oldest_night=night,
                max_images=40,
                adapter=Listing({night: (first, second)}),
                client=object(),
                site=SITE,
            )

        self.assertEqual(plan.processed_receipts_skipped, 2)
        self.assertEqual(plan.selected, ())

    def test_completed_twenty_minute_slot_rejects_one_minute_neighbor(self):
        night = date(2026, 10, 15)
        early = candidate(night, 19, "one-minute-early")
        nominal = candidate(night, 20, "nominal")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            record_verified(archive, early, b"early-neighbor")
            _, nominal_digest = record_verified(archive, nominal, b"nominal-frame")
            database = root / "stars.sqlite"
            results_database(database, [(nominal_digest, "0.21.0", 0)])
            plan = PIPELINE.build_acquisition_plan(
                archive,
                database,
                state_path=root / "state.json",
                current_night=night,
                oldest_night=night,
                max_images=40,
                adapter=Listing({night: (early, nominal)}),
                client=object(),
                site=SITE,
            )

        self.assertEqual(plan.selected, ())

    def test_completed_floor_slot_rejects_late_dawn_frame(self):
        night = date(2026, 10, 15)
        def dawn(minute: int, name: str) -> Candidate:
            observed = datetime(2026, 10, 16, 5, minute, tzinfo=ARIZONA)
            return Candidate(
                "mmto", "mmto-skycam", observed, observed.isoformat(),
                f"https://mmto/{night.isoformat()}/{name}", f"{name}.fits.bz2",
                None, {"archive_bucket": night.isoformat(), "compression": "bzip2"},
            )
        completed = dawn(20, "completed-0520")
        late = dawn(34, "late-dawn-same-slot")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            _, digest = record_verified(archive, completed, b"completed")
            database = root / "stars.sqlite"
            results_database(database, [(digest, "0.21.0", 0)])
            plan = PIPELINE.build_acquisition_plan(
                archive, database, state_path=root / "state.json",
                current_night=night, oldest_night=night, max_images=40,
                adapter=Listing({night: (completed, late)}), client=object(), site=SITE,
            )

        self.assertEqual(plan.selected, ())

    def test_downloaded_unreceipted_image_is_reused_after_current_listing(self):
        night = date(2026, 10, 15)
        item = candidate(night, 0, "local")
        listing = Listing({})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            path, digest = record_verified(archive, item, b"local-image")
            plan = PIPELINE.build_acquisition_plan(
                archive,
                root / "stars.sqlite",
                state_path=root / "state.json",
                current_night=night,
                oldest_night=night,
                max_images=1,
                adapter=listing,
                client=object(),
                site=SITE,
            )

        self.assertEqual(len(listing.calls), 1)
        self.assertEqual(plan.selected[0].source_sha256, digest)
        self.assertEqual(plan.selected[0].local_path, path.relative_to(archive))
        self.assertTrue(plan.selected[0].downloaded)

    def test_current_night_has_priority_without_advancing_older_cursor(self):
        current = date(2026, 10, 15)
        cursor = date(2026, 9, 1)
        listing = Listing(
            {
                current: (candidate(current, 0, "new"),),
                cursor: (candidate(cursor, 0, "old"),),
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            PIPELINE.write_backfill_state_atomic(root / "state.json", archive, cursor)
            plan = PIPELINE.build_acquisition_plan(
                archive,
                root / "stars.sqlite",
                state_path=root / "state.json",
                current_night=current,
                oldest_night=date(2026, 6, 30),
                max_images=1,
                adapter=listing,
                client=object(),
                site=SITE,
            )

        self.assertEqual(plan.selected[0].candidate.filename, "new.fits.bz2")
        self.assertEqual(plan.cursor_before, cursor)
        self.assertEqual(plan.cursor_after, cursor)
        self.assertEqual(len(listing.calls), 1)

    def test_current_remote_night_precedes_full_local_backlog(self):
        current = date(2026, 10, 15)
        older = current - timedelta(days=1)
        newest = candidate(current, 0, "current-remote")
        backlog = candidate(older, 0, "older-local")
        listing = Listing({current: (newest,)})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            record_verified(archive, backlog, b"older-local-image")
            plan = PIPELINE.build_acquisition_plan(
                archive,
                root / "stars.sqlite",
                state_path=root / "state.json",
                current_night=current,
                oldest_night=older,
                max_images=1,
                adapter=listing,
                client=object(),
                site=SITE,
            )

        self.assertEqual(
            [item.candidate.filename for item in plan.selected],
            ["current-remote.fits.bz2"],
        )
        self.assertEqual(plan.nights_listed, (current,))
        self.assertEqual(plan.files_listed, 1)

    def test_partial_cursor_night_retains_night_for_next_run(self):
        night = date(2026, 10, 15)
        listing = Listing(
            {
                night: tuple(
                    candidate(night, minute, name)
                    for minute, name in ((0, "a"), (20, "b"), (40, "c"))
                )
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = PIPELINE.build_acquisition_plan(
                root / "archive",
                root / "stars.sqlite",
                state_path=root / "state.json",
                current_night=night,
                oldest_night=night,
                max_images=2,
                adapter=listing,
                client=object(),
                site=SITE,
            )

        self.assertEqual(plan.cursor_after, night)
        self.assertEqual(
            [item.candidate.filename for item in plan.selected],
            ["c.fits.bz2", "b.fits.bz2"],
        )

    def test_fully_scanned_cursor_night_advances_to_preceding_night(self):
        night = date(2026, 10, 15)
        listing = Listing({night: (candidate(night, 0, "only"),)})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = PIPELINE.build_acquisition_plan(
                root / "archive",
                root / "stars.sqlite",
                state_path=root / "state.json",
                current_night=night,
                oldest_night=night,
                max_images=2,
                adapter=listing,
                client=object(),
                site=SITE,
            )

        self.assertEqual(plan.cursor_after, night - timedelta(days=1))
        self.assertEqual(plan.nights_listed, (night,))

    def test_state_for_different_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state.json"
            PIPELINE.write_backfill_state_atomic(
                state, root / "first-archive", date(2026, 10, 15)
            )
            with self.assertRaisesRegex(ValueError, "different archive"):
                PIPELINE.load_backfill_state(
                    state, root / "second-archive", date(2026, 10, 16)
                )


class DownloadClient:
    def __init__(self, payloads: dict[str, bytes]):
        self.payloads = payloads
        self.calls: list[str] = []

    def download_atomic(self, item: Candidate, destination: Path) -> DownloadedFile:
        self.calls.append(item.url)
        payload = self.payloads[item.url]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return DownloadedFile(
            destination,
            len(payload),
            hashlib.sha256(payload).hexdigest(),
        )


class FailingDownloadClient:
    def download_atomic(self, _item: Candidate, _destination: Path) -> DownloadedFile:
        raise OSError("simulated MMTO transfer failure")


def executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def fake_product_stages(root: Path) -> None:
    for name in (
        "plot_mmto_lightcurves.sh",
        "calibrate_mmto_extinction.sh",
        "calibrate_mmto_extinction_v21.sh",
        "plot_mmto_variable_stars_v21.sh",
        "plot_ALL_planets.sh",
        "plot_planet_empirical_extinction.sh",
    ):
        executable(root / name, "#!/usr/bin/env bash\nexit 0\n")
    (root / "scripts").mkdir()
    executable(
        root / "scripts" / "validate_mmto_site_time_v21.py",
        "#!/usr/bin/env python3\nraise SystemExit(0)\n",
    )
    executable(
        root / "scripts" / "map_mmto_sidereal_transmission_v21.py",
        "#!/usr/bin/env python3\nraise SystemExit(0)\n",
    )


class V21OrchestrationTests(unittest.TestCase):
    def test_missing_file_selected_from_manifest_is_redownloaded_to_recorded_path(self):
        night = date(2026, 10, 15)
        item = candidate(night, 0, "missing")
        replacement = mmto_fits_payload(item)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            missing_path, _ = record_verified(archive, item, b"original-payload")
            missing_path.unlink()
            plan = PIPELINE.build_acquisition_plan(
                archive,
                root / "stars.sqlite",
                state_path=root / "state.json",
                current_night=night,
                oldest_night=night,
                max_images=1,
                adapter=Listing({}),
                client=object(),
                site=SITE,
            )
            ready, reused, downloaded = PIPELINE.acquire_selected_images(
                archive,
                plan.selected,
                client=DownloadClient({item.url: replacement}),
                site=SITE,
            )

            self.assertEqual(ready[0].path, missing_path)
            self.assertEqual(missing_path.read_bytes(), replacement)

        self.assertEqual((reused, downloaded), (0, 1))

    def test_acquisition_reuses_verified_file_and_redownloads_missing_file(self):
        night = date(2026, 10, 15)
        present = candidate(night, 0, "present")
        missing = candidate(night, 20, "missing")
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "archive"
            archive.mkdir()
            present_payload = mmto_fits_payload(present)
            missing_payload = mmto_fits_payload(missing)
            present_path, present_digest = record_verified(
                archive, present, present_payload
            )
            missing_path, missing_digest = record_verified(
                archive, missing, missing_payload
            )
            missing_path.unlink()
            selected = (
                PIPELINE.SelectedImage(
                    present,
                    present_digest,
                    present_path.relative_to(archive),
                    present_path.stat().st_size,
                    True,
                ),
                PIPELINE.SelectedImage(
                    missing,
                    missing_digest,
                    missing_path.relative_to(archive),
                    len(missing_payload),
                    True,
                ),
            )
            client = DownloadClient({missing.url: missing_payload})
            ready, reused, downloaded = PIPELINE.acquire_selected_images(
                archive, selected, client=client, site=SITE
            )

            with sqlite3.connect(archive / "manifest.sqlite") as database:
                sidecar_count = database.execute(
                    "SELECT count(*) FROM mmto_v21_observations"
                ).fetchone()[0]

        self.assertEqual(client.calls, [missing.url])
        self.assertEqual((reused, downloaded), (1, 1))
        self.assertEqual([item.source_sha256 for item in ready], [
            present_digest, missing_digest
        ])
        self.assertEqual(sidecar_count, 2)

    def test_stage_commands_retain_v19_products_and_use_v21_variable_launcher(self):
        root = Path("/repo")
        database = Path("/results/stars.sqlite")
        manifest = Path("/archive/manifest.sqlite")
        output = Path("/output")
        actual = PIPELINE._stage_commands(root, database, manifest, output)
        inherited = v19_stage_commands(root, database, manifest, output)
        self.assertEqual(
            [name for name, _ in actual[:len(inherited)]],
            [name for name, _ in inherited],
        )
        self.assertEqual(
            [name for name, _ in actual[len(inherited):]],
            ["v21_grey_extinction", "same_sidereal_transmission", "known_site_time_validation"],
        )
        for (name, command), (_, old_command) in zip(actual[:len(inherited)], inherited, strict=True):
            if name == "variable_star_time_series":
                self.assertEqual(command[1:], old_command[1:])
                self.assertEqual(command[0], "/repo/plot_mmto_variable_stars_v21.sh")
            else:
                self.assertEqual(command, old_command)

    def test_dry_run_does_not_create_output_or_advance_cursor(self):
        night = date(2026, 10, 15)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            results = root / "results"
            state = root / "state.json"
            output = root / "output"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = PIPELINE.main(
                    [
                        "--repo-root", str(root),
                        "--archive", str(archive),
                        "--results-dir", str(results),
                        "--output", str(output),
                        "--state-file", str(state),
                        "--oldest-night", night.isoformat(),
                        "--dry-run",
                    ],
                    adapter=Listing({}),
                    client=object(),
                    site=SITE,
                    now=datetime(2026, 10, 16, 5, tzinfo=ZoneInfo("UTC")),
                )

        self.assertEqual(code, 0)
        self.assertFalse(state.exists())
        self.assertFalse(output.exists())
        self.assertIn("selected=0", stdout.getvalue())

    def test_real_run_downloads_solves_advances_cursor_and_runs_all_stages(self):
        night = date(2026, 10, 15)
        item = candidate(night, 0, "new")
        payload = mmto_fits_payload(item)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            results = root / "results"
            output = root / "output"
            state = root / "state.json"
            fake_product_stages(root)
            executable(
                root / "go21.sh",
                "#!/usr/bin/env python3\n"
                "import hashlib, json, sqlite3, sys\n"
                "from pathlib import Path\n"
                "source = Path(sys.argv[1])\n"
                "assert '--blind-planets' in sys.argv\n"
                "assert '--observation-time' not in sys.argv\n"
                "assert '--latitude' not in sys.argv\n"
                "assert '--longitude' not in sys.argv\n"
                "results = Path(sys.argv[sys.argv.index('--results-dir') + 1])\n"
                "digest = hashlib.sha256(source.read_bytes()).hexdigest()\n"
                "with sqlite3.connect(results / 'stars.sqlite') as database:\n"
                "    database.execute('CREATE TABLE IF NOT EXISTS runs "
                "(source_sha256 TEXT, solver_version TEXT, exit_code INTEGER, "
                "source_manifest_json TEXT)')\n"
                "    database.execute('INSERT INTO runs VALUES (?,?,?,?)', "
                "(digest, '0.21.0', 0, json.dumps({'version':'0.21.0'})))\n",
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = PIPELINE.main(
                    [
                        "--repo-root", str(root),
                        "--archive", str(archive),
                        "--results-dir", str(results),
                        "--output", str(output),
                        "--state-file", str(state),
                        "--lock-file", str(root / "pipeline.lock"),
                        "--oldest-night", night.isoformat(),
                        "--max-images", "1",
                    ],
                    adapter=Listing({night: (item,)}),
                    client=DownloadClient({item.url: payload}),
                    site=SITE,
                    now=datetime(2026, 10, 16, 5, tzinfo=ZoneInfo("UTC")),
                )

            summary = json.loads((output / "pipeline_summary.json").read_text())
            saved_state = json.loads(state.read_text())

        self.assertEqual(code, 0)
        self.assertEqual(summary["status"], "complete")
        self.assertEqual(summary["selection"]["selected"], 1)
        self.assertEqual(summary["acquisition"]["downloaded"], 1)
        self.assertEqual(summary["processing"]["succeeded"], 1)
        self.assertEqual(
            [stage["name"] for stage in summary["stages"]],
            [
                "stellar_lightcurves",
                "nightly_extinction",
                "variable_star_time_series",
                "planet_photometry",
                "planet_empirical_extinction",
                "v21_grey_extinction",
                "same_sidereal_transmission",
                "known_site_time_validation",
            ],
        )
        self.assertEqual(saved_state["next_night"], "2026-10-14")
        self.assertIn("FIGURES (0)", stdout.getvalue())

    def test_post_download_digest_with_v21_receipt_skips_go21(self):
        night = date(2026, 10, 15)
        item = candidate(night, 0, "duplicate")
        payload = mmto_fits_payload(item)
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            results = root / "results"
            results.mkdir()
            output = root / "output"
            state = root / "state.json"
            results_database(results / "stars.sqlite", [(digest, "0.21.0", 1)])
            fake_product_stages(root)
            executable(root / "go21.sh", "#!/usr/bin/env bash\nexit 99\n")
            code = PIPELINE.main(
                [
                    "--repo-root", str(root),
                    "--archive", str(archive),
                    "--results-dir", str(results),
                    "--output", str(output),
                    "--state-file", str(state),
                    "--lock-file", str(root / "pipeline.lock"),
                    "--oldest-night", night.isoformat(),
                    "--max-images", "1",
                ],
                adapter=Listing({night: (item,)}),
                client=DownloadClient({item.url: payload}),
                site=SITE,
                now=datetime(2026, 10, 16, 5, tzinfo=ZoneInfo("UTC")),
            )
            summary = json.loads((output / "pipeline_summary.json").read_text())
            saved_state = json.loads(state.read_text())

        self.assertEqual(code, 0)
        self.assertEqual(summary["processing"]["receipt_skipped"], 1)
        self.assertEqual(summary["processing"]["attempted"], 0)
        self.assertEqual(saved_state["next_night"], "2026-10-14")

    def test_missing_v21_receipt_fails_without_advancing_cursor(self):
        night = date(2026, 10, 15)
        item = candidate(night, 0, "no-receipt")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            state = root / "state.json"
            executable(root / "go21.sh", "#!/usr/bin/env bash\nexit 0\n")
            fake_product_stages(root)
            code = PIPELINE.main(
                [
                    "--repo-root", str(root),
                    "--archive", str(root / "archive"),
                    "--results-dir", str(root / "results"),
                    "--output", str(output),
                    "--state-file", str(state),
                    "--lock-file", str(root / "pipeline.lock"),
                    "--oldest-night", night.isoformat(),
                    "--max-images", "1",
                ],
                adapter=Listing({night: (item,)}),
                client=DownloadClient({item.url: mmto_fits_payload(item)}),
                site=SITE,
                now=datetime(2026, 10, 16, 5, tzinfo=ZoneInfo("UTC")),
            )
            summary = json.loads((output / "pipeline_summary.json").read_text())

        self.assertEqual(code, 2)
        self.assertEqual(summary["status"], "operational_failed")
        self.assertFalse(state.exists())

    def test_download_failure_does_not_advance_cursor(self):
        night = date(2026, 10, 15)
        item = candidate(night, 0, "transfer-failure")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            state = root / "state.json"
            code = PIPELINE.main(
                [
                    "--repo-root", str(root),
                    "--archive", str(root / "archive"),
                    "--results-dir", str(root / "results"),
                    "--output", str(output),
                    "--state-file", str(state),
                    "--lock-file", str(root / "pipeline.lock"),
                    "--oldest-night", night.isoformat(),
                    "--max-images", "1",
                ],
                adapter=Listing({night: (item,)}),
                client=FailingDownloadClient(),
                site=SITE,
                now=datetime(2026, 10, 16, 5, tzinfo=ZoneInfo("UTC")),
            )
            summary = json.loads((output / "pipeline_summary.json").read_text())

        self.assertEqual(code, 2)
        self.assertEqual(summary["status"], "operational_failed")
        self.assertFalse(state.exists())

    def test_portable_launcher_help_exposes_bounded_controls(self):
        launcher = ROOT / "go_mmto_photometry_v21.sh"
        completed = subprocess.run(
            [str(launcher), "--help"],
            cwd=Path("/tmp"),
            env=dict(os.environ, VIRTUAL_ENV=str(ROOT / "wrong-environment")),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("--max-images", completed.stdout)
        self.assertIn("--oldest-night", completed.stdout)
        self.assertIn("40", completed.stdout)


if __name__ == "__main__":
    unittest.main()
