"""V23 acquisition must prefer unseen remote images to cached leftovers."""
from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from allsky_download.http import DownloadedFile
from allsky_download.manifest import Manifest
from allsky_download.model import Candidate
from allsky_download.registry import SourceRegistry
from scripts import run_mmto_photometry_pipeline_v23 as PIPELINE
from scripts.mmto_weather import MmtoWeatherHistory, WeatherDecision, WeatherSample


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


class WeatherByNight:
    def __init__(self, by_night: dict[date, MmtoWeatherHistory]):
        self.by_night = by_night
        self.calls: list[date] = []

    def __call__(self, start_utc, _end_utc):
        night = start_utc.astimezone(ARIZONA).date()
        self.calls.append(night)
        return self.by_night.get(night, MmtoWeatherHistory())


def humidity_history(item: Candidate, humidity_percent: float) -> MmtoWeatherHistory:
    return MmtoWeatherHistory(
        (
            WeatherSample(
                "vaisala2_relative_humidity",
                item.observed_at,
                humidity_percent,
            ),
        )
    )


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
        self.assertEqual(len(plan.selected), 1)
        self.assertEqual(plan.selected[0].candidate.filename, "unseen.fits.bz2")
        self.assertFalse(plan.selected[0].downloaded)


class V23WeatherSelectionTests(unittest.TestCase):
    def build_plan(
        self,
        root: Path,
        *,
        current: date,
        cursor: date,
        listing: Listing,
        weather: WeatherByNight,
        max_images: int,
    ):
        archive = root / "archive"
        archive.mkdir()
        PIPELINE.write_backfill_state_atomic(
            root / "state.json",
            archive,
            cursor,
            latest_current_night=current,
        )
        return PIPELINE.build_acquisition_plan(
            archive,
            root / "stars.sqlite",
            state_path=root / "state.json",
            current_night=current,
            oldest_night=date(2026, 6, 30),
            max_images=max_images,
            adapter=listing,
            client=object(),
            site=SITE,
            weather_fetcher=weather,
        )

    def test_fresh_humidity_below_80_is_selected(self):
        night = date(2026, 10, 21)
        item = candidate(night, 0, "good")
        listing = Listing({night: (item,)})
        weather = WeatherByNight({night: humidity_history(item, 79.9)})

        with tempfile.TemporaryDirectory() as temporary:
            plan = self.build_plan(
                Path(temporary),
                current=night,
                cursor=night,
                listing=listing,
                weather=weather,
                max_images=1,
            )

        self.assertEqual([entry.candidate.filename for entry in plan.selected], ["good.fits.bz2"])
        self.assertEqual(plan.weather_accepted, 1)
        self.assertEqual(plan.weather_skipped, 0)

    def test_fresh_humidity_at_80_is_skipped_but_unknown_is_selected(self):
        night = date(2026, 10, 21)
        humid = candidate(night, 0, "humid")
        unknown = candidate(night, 20, "unknown")
        listing = Listing({night: (humid, unknown)})
        weather = WeatherByNight({night: humidity_history(humid, 80.0)})

        with tempfile.TemporaryDirectory() as temporary:
            plan = self.build_plan(
                Path(temporary),
                current=night,
                cursor=night,
                listing=listing,
                weather=weather,
                max_images=1,
            )

        self.assertEqual(
            [entry.candidate.filename for entry in plan.selected],
            ["unknown.fits.bz2"],
        )
        self.assertEqual(plan.weather_skipped, 1)
        self.assertEqual(plan.weather_unknown, 1)

    def test_weather_skips_do_not_consume_cap_and_older_night_fills_it(self):
        current = date(2026, 10, 22)
        cursor = date(2026, 10, 21)
        humid = candidate(cursor, 0, "humid")
        older = candidate(date(2026, 10, 20), 0, "older-good")
        listing = Listing({cursor: (humid,), date(2026, 10, 20): (older,)})
        weather = WeatherByNight(
            {
                cursor: humidity_history(humid, 88.0),
                date(2026, 10, 20): humidity_history(older, 42.0),
            }
        )

        with tempfile.TemporaryDirectory() as temporary:
            plan = self.build_plan(
                Path(temporary),
                current=current,
                cursor=cursor,
                listing=listing,
                weather=weather,
                max_images=1,
            )

        self.assertEqual(
            [entry.candidate.filename for entry in plan.selected],
            ["older-good.fits.bz2"],
        )
        self.assertIn(date(2026, 10, 20), listing.calls)
        self.assertEqual(plan.weather_skipped, 1)
        self.assertEqual(plan.weather_accepted, 1)

    def test_weather_audit_is_sorted_and_complete_without_manual_review(self):
        night = date(2026, 10, 21)
        later = candidate(night, 20, "later")
        earlier = candidate(night, 0, "earlier")
        decisions = (
            PIPELINE.CandidateWeatherDecision(
                later,
                WeatherDecision(
                    "unknown", None, None, None, None, "no_fresh_sample"
                ),
                ("vaisala2_relative_humidity: TimeoutError: unavailable",),
            ),
            PIPELINE.CandidateWeatherDecision(
                earlier,
                WeatherDecision(
                    "skip",
                    80.0,
                    earlier.observed_at,
                    3.5,
                    "vaisala2_relative_humidity",
                    "humidity_at_or_above_limit",
                ),
            ),
        )

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "weather-decisions.jsonl"
            PIPELINE._write_weather_decisions_atomic(path, decisions)
            records = [json.loads(line) for line in path.read_text().splitlines()]

        self.assertEqual([record["candidate_url"] for record in records], [earlier.url, later.url])
        self.assertEqual(
            set(records[0]),
            {
                "candidate_observed_utc",
                "candidate_url",
                "status",
                "humidity_percent",
                "sensor",
                "sample_utc",
                "age_seconds",
                "reason",
                "source_errors",
            },
        )
        self.assertEqual(records[0]["humidity_percent"], 80.0)
        self.assertEqual(records[0]["status"], "skip")
        self.assertNotIn("manual_review", records[0])
        self.assertEqual(records[1]["status"], "unknown")
        self.assertEqual(
            records[1]["source_errors"],
            ["vaisala2_relative_humidity: TimeoutError: unavailable"],
        )

    def test_weather_summary_records_policy_counts_and_audit_path(self):
        night = date(2026, 10, 21)
        item = candidate(night, 0, "humid")
        listing = Listing({night: (item,)})
        weather = WeatherByNight({night: humidity_history(item, 80.0)})
        with tempfile.TemporaryDirectory() as temporary:
            plan = self.build_plan(
                Path(temporary),
                current=night,
                cursor=night,
                listing=listing,
                weather=weather,
                max_images=1,
            )
            audit = Path(temporary) / "run" / "weather-decisions.jsonl"
            summary = PIPELINE._weather_summary(
                plan,
                max_humidity_percent=80.0,
                weather_max_age_seconds=120.0,
                audit_path=audit,
            )

        self.assertEqual(summary["accepted"], 0)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["unknown_fail_open"], 0)
        self.assertEqual(summary["max_humidity_percent"], 80.0)
        self.assertEqual(summary["max_age_seconds"], 120.0)
        self.assertEqual(summary["missing_data_policy"], "accept")
        self.assertEqual(summary["audit"], str(audit))

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
