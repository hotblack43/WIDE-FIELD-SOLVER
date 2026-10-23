"""V23 acquisition must prefer unseen remote images to cached leftovers."""
from __future__ import annotations

from datetime import date, datetime
import hashlib
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from allsky_download.http import DownloadedFile
from allsky_download.manifest import Manifest
from allsky_download.model import Candidate
from allsky_download.registry import SourceRegistry
from scripts import run_mmto_photometry_pipeline_v23 as PIPELINE


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
        self.calls: list[date] = []

    def list_candidates(self, _client, _site, date_range):
        night = date_range.start_utc.astimezone(ARIZONA).date()
        self.calls.append(night)
        return self.by_night.get(night, ())


def record_verified(archive: Path, item: Candidate, payload: bytes) -> None:
    destination = (
        archive
        / "mmto"
        / "mmto-skycam"
        / item.metadata["archive_bucket"]
        / item.filename
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    with Manifest(archive / "manifest.sqlite") as manifest:
        manifest.record_attempt(item)
        manifest.record_success(
            item,
            DownloadedFile(
                destination,
                len(payload),
                hashlib.sha256(payload).hexdigest(),
            ),
            archive,
        )


class V23RemoteFirstSelectionTests(unittest.TestCase):
    def test_planet_stage_passes_verified_manifest_to_v23_plotter(self):
        commands = dict(
            PIPELINE._stage_commands(
                Path("/repo"),
                Path("/results/stars.sqlite"),
                Path("/archive/manifest.sqlite"),
                Path("/output"),
                v21_control=Path("/control"),
            )
        )

        planet = commands["planet_photometry"]
        self.assertEqual(planet[0], "/repo/v23/plot_ALL_planets_v23.sh")
        self.assertIn("--manifest", planet)
        self.assertEqual(
            planet[planet.index("--manifest") + 1],
            "/archive/manifest.sqlite",
        )

    def test_remote_cursor_is_scanned_before_cached_local_backlog(self):
        current = date(2026, 10, 22)
        cursor = date(2026, 10, 21)
        cached = candidate(date(2026, 10, 20), 0, "cached")
        unseen = candidate(cursor, 0, "unseen")
        listing = Listing({cursor: (unseen,)})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            record_verified(archive, cached, b"cached")
            PIPELINE.write_backfill_state_atomic(
                root / "state.json",
                archive,
                cursor,
                latest_current_night=current,
            )

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

        self.assertEqual(listing.calls, [current, cursor])
        self.assertEqual(plan.selected[0].candidate.filename, "unseen.fits.bz2")
        self.assertFalse(plan.selected[0].downloaded)

    def test_unseen_file_precedes_newer_cached_file_on_cursor_night(self):
        current = date(2026, 10, 22)
        cursor = date(2026, 10, 21)
        unseen = candidate(cursor, 20, "unseen")
        cached = candidate(cursor, 40, "cached-newer")
        listing = Listing({cursor: (cached, unseen)})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "archive"
            archive.mkdir()
            record_verified(archive, cached, b"cached")
            PIPELINE.write_backfill_state_atomic(
                root / "state.json",
                archive,
                cursor,
                latest_current_night=current,
            )

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

        self.assertEqual(plan.selected[0].candidate.filename, "unseen.fits.bz2")
        self.assertFalse(plan.selected[0].downloaded)


if __name__ == "__main__":
    unittest.main()
