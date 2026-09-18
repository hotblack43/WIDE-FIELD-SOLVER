from datetime import datetime, timezone
from pathlib import Path
import unittest

from allsky_download.cron import cron_download_arguments


class CronTests(unittest.TestCase):
    def test_mmto_uses_local_date_newest_slot_and_one_file(self):
        args = cron_download_arguments(
            "mmto",
            datetime(2026, 9, 19, 2, 30, tzinfo=timezone.utc),
            Path("samples"),
            dry_run=True,
        )
        self.assertIn("2026-09-18", args)
        self.assertEqual(args[args.index("--cadence") + 1], "20m")
        self.assertEqual(args[args.index("--max-files") + 1], "1")
        self.assertIn("--latest", args)
        self.assertIn("--dry-run", args)

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
