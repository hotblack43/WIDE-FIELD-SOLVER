from datetime import datetime, timezone
from pathlib import Path
import unittest

from allsky_download.cron import cron_download_arguments, processing_cron_lines
from allsky_download.cli import build_parser
from allsky_download.model import Candidate
from allsky_download.registry import SourceRegistry
from allsky_download.solar import filter_by_solar_altitude


class CronTests(unittest.TestCase):
    def test_processing_cron_is_frequent_and_independent_from_acquisition(self):
        marker, command = processing_cron_lines(
            Path("/opt/wide-field-solver"), Path("/opt/uv")
        )
        self.assertEqual(marker, "# WIDE_FIELD_SOLVER_MMTO_PROCESSING_ACTIVE")
        self.assertTrue(command.startswith("*/2 * * * * "))
        self.assertIn("/tmp/wide-field-solver-mmto-processing.lock", command)
        self.assertNotIn("/usr/bin/flock", command)
        self.assertNotIn("/tmp/wide-field-raw-allsky-mmto.lock", command)
        self.assertIn("/opt/uv run --frozen python run_allsky_processing.py", command)
        self.assertIn("/opt/wide-field-solver/results/mmto-automatic", command)

    def test_mmto_uses_same_noon_bounded_night_before_and_after_midnight(self):
        evening = cron_download_arguments(
            "mmto",
            datetime(2026, 9, 19, 2, 30, tzinfo=timezone.utc),
            Path("samples"),
            dry_run=True,
        )
        after_midnight = cron_download_arguments(
            "mmto",
            datetime(2026, 9, 19, 9, 30, tzinfo=timezone.utc),
            Path("samples"),
            dry_run=True,
        )
        for args in (evening, after_midnight):
            self.assertEqual(args[args.index("--night") + 1], "2026-09-18")
            self.assertNotIn("--date", args)

    def test_mmto_backfills_oldest_missing_slot_one_file_and_solar_filter(self):
        args = cron_download_arguments(
            "mmto",
            datetime(2026, 9, 19, 2, 30, tzinfo=timezone.utc),
            Path("samples"),
            dry_run=True,
        )
        self.assertEqual(args[args.index("--cadence") + 1], "20m")
        self.assertEqual(args[args.index("--max-files") + 1], "1")
        self.assertEqual(args[args.index("--sun-below") + 1], "-12")
        self.assertIn("--backfill-missing", args)
        self.assertNotIn("--latest", args)
        self.assertIn("--enqueue-processing", args)
        self.assertIn("--dry-run", args)

    def test_mmto_cron_excludes_failed_dawn_exposure_but_keeps_darker_frame(self):
        args = build_parser().parse_args(cron_download_arguments(
            "mmto", datetime(2026, 9, 19, 13, 30, tzinfo=timezone.utc),
            Path("samples"), dry_run=True,
        ))
        site = SourceRegistry.from_json(
            Path(__file__).resolve().parents[1] / "sources.json"
        ).get_adapter("mmto").sites("mmto-skycam")[0]
        exposures = []
        # Arizona 05:00, 05:20, 06:00: Sun approximately -15.6, -11.4, -2.9 deg.
        for hour, minute in ((12, 0), (12, 20), (13, 0)):
            instant = datetime(2026, 9, 19, hour, minute, 13, tzinfo=timezone.utc)
            name = f"frame-{hour}-{minute}.fits.bz2"
            exposures.append(Candidate(
                "mmto", "mmto-skycam", instant, instant.isoformat(),
                f"https://example.test/{name}", name, None, {},
            ))
        kept = filter_by_solar_altitude(
            exposures, {("mmto", "mmto-skycam"): site},
            sun_below_deg=args.sun_below,
        )
        self.assertEqual(kept, (exposures[0],))

    def test_rubin_continuous_feed_is_refused_not_faked(self):
        with self.assertRaisesRegex(ValueError, "continuing public RAW archive"):
            cron_download_arguments(
                "rubin",
                datetime(2026, 9, 19, tzinfo=timezone.utc),
                Path("samples"),
                dry_run=False,
            )


if __name__ == "__main__":
    unittest.main()
