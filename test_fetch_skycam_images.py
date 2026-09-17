import io
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from scripts import fetch_skycam_images as skycam


JPEG = b"\xff\xd8payload\xff\xd9"


class FakeResponse:
    def __init__(self, body=JPEG, content_type="image/jpeg"):
        self.body = body
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        if size < 0:
            return self.body
        return self.body[:size]


class CliTests(unittest.TestCase):
    def test_defaults(self):
        config = skycam.parse_args([])

        self.assertEqual(config.interval_minutes, 20.0)
        self.assertEqual(config.output_dir, Path("skycam-images"))
        self.assertFalse(config.once)

    def test_custom_values(self):
        config = skycam.parse_args(
            [
                "--interval-minutes",
                "2.5",
                "--output-dir",
                "/tmp/captures",
                "--once",
            ]
        )

        self.assertEqual(config.interval_minutes, 2.5)
        self.assertEqual(config.output_dir, Path("/tmp/captures"))
        self.assertTrue(config.once)

    def test_interval_must_be_positive_and_finite(self):
        for value in ("0", "-1", "nan", "inf", "1e308"):
            with self.subTest(value=value), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    skycam.parse_args(["--interval-minutes", value])


class CapturePathTests(unittest.TestCase):
    def test_dangling_symlink_counts_as_a_filename_collision(self):
        acquired_at = datetime(2026, 9, 16, 7, 20, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            first = output_dir / "subaru_maunakea_20260916T072030Z.jpg"
            first.symlink_to(output_dir / "missing-target.jpg")

            self.assertEqual(
                skycam.capture_path(output_dir, acquired_at),
                output_dir / "subaru_maunakea_20260916T072030Z_1.jpg",
            )

    def test_uses_utc_timestamp_and_collision_suffix(self):
        acquired_at = datetime(2026, 9, 16, 7, 20, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            first = output_dir / "subaru_maunakea_20260916T072030Z.jpg"
            first.touch()

            self.assertEqual(
                skycam.capture_path(output_dir, acquired_at),
                output_dir / "subaru_maunakea_20260916T072030Z_1.jpg",
            )


class DownloadTests(unittest.TestCase):
    def test_rejects_response_larger_than_configured_limit(self):
        oversized_jpeg = b"\xff\xd8" + (b"x" * 20) + b"\xff\xd9"
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            with mock.patch.object(skycam, "MAX_IMAGE_BYTES", 8):
                with self.assertRaisesRegex(
                    skycam.DownloadError, "exceeds 8-byte limit"
                ):
                    skycam.download_once(
                        output_dir,
                        opener=lambda *args, **kwargs: FakeResponse(
                            oversized_jpeg
                        ),
                    )

            self.assertEqual(list(output_dir.iterdir()), [])

    def test_publication_race_uses_suffix_without_overwriting_competitor(self):
        acquired_at = datetime(2026, 9, 16, 7, 20, 30, tzinfo=timezone.utc)
        real_link = skycam.os.link
        attempts = []

        def racing_link(source, destination):
            attempts.append(Path(destination))
            if len(attempts) == 1:
                Path(destination).write_bytes(b"competing capture")
                raise FileExistsError
            return real_link(source, destination)

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            with mock.patch.object(skycam.os, "link", side_effect=racing_link):
                result = skycam.download_once(
                    output_dir,
                    opener=lambda *args, **kwargs: FakeResponse(),
                    now=lambda: acquired_at,
                )

            self.assertEqual(attempts[0].read_bytes(), b"competing capture")
            self.assertEqual(
                result.name, "subaru_maunakea_20260916T072030Z_1.jpg"
            )
            self.assertEqual(result.read_bytes(), JPEG)

    def test_publication_error_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            with mock.patch.object(
                skycam.os, "link", side_effect=OSError("filesystem offline")
            ):
                with self.assertRaisesRegex(OSError, "filesystem offline"):
                    skycam.download_once(
                        output_dir,
                        opener=lambda *args, **kwargs: FakeResponse(),
                    )

            self.assertEqual(list(output_dir.iterdir()), [])

    def test_saves_valid_jpeg_with_expected_request_and_name(self):
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            return FakeResponse()

        acquired_at = datetime(2026, 9, 16, 7, 20, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)

            result = skycam.download_once(
                output_dir, opener=opener, now=lambda: acquired_at
            )

            self.assertEqual(result.read_bytes(), JPEG)
            self.assertEqual(
                result.name, "subaru_maunakea_20260916T072030Z.jpg"
            )
            self.assertEqual(requests[0][0].full_url, skycam.IMAGE_URL)
            self.assertEqual(requests[0][1], 30)
            self.assertFalse(
                any(path.suffix == ".tmp" for path in output_dir.iterdir())
            )

    def test_existing_capture_gets_suffix_without_overwrite(self):
        acquired_at = datetime(2026, 9, 16, 7, 20, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            existing = output_dir / "subaru_maunakea_20260916T072030Z.jpg"
            existing.write_bytes(b"existing")

            result = skycam.download_once(
                output_dir,
                opener=lambda *args, **kwargs: FakeResponse(),
                now=lambda: acquired_at,
            )

            self.assertEqual(existing.read_bytes(), b"existing")
            self.assertEqual(
                result.name, "subaru_maunakea_20260916T072030Z_1.jpg"
            )
            self.assertEqual(result.read_bytes(), JPEG)

    def test_rejects_invalid_responses_and_removes_temporary_file(self):
        cases = (
            (b"not jpeg", "text/html"),
            (b"\xff\xd8truncated", "image/jpeg"),
        )
        for body, content_type in cases:
            with self.subTest(content_type=content_type):
                with tempfile.TemporaryDirectory() as directory:
                    output_dir = Path(directory)

                    with self.assertRaises(skycam.DownloadError):
                        skycam.download_once(
                            output_dir,
                            opener=lambda *args, **kwargs: FakeResponse(
                                body, content_type
                            ),
                        )

                    self.assertEqual(list(output_dir.iterdir()), [])


class FakeClock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


class RunTests(unittest.TestCase):
    def test_main_converts_keyboard_interrupt_to_clean_exit(self):
        err = io.StringIO()

        def interrupt(_config):
            raise KeyboardInterrupt

        result = skycam.main([], runner=interrupt, stderr=err)

        self.assertEqual(result, 130)
        self.assertEqual(err.getvalue(), "Stopped.\n")

    def test_once_failure_returns_nonzero(self):
        err = io.StringIO()
        config = skycam.Config(20.0, Path("unused"), True)

        def offline(_output_dir):
            raise OSError("offline")

        result = skycam.run(config, downloader=offline, stderr=err)

        self.assertEqual(result, 1)
        self.assertIn("offline", err.getvalue())

    def test_recurring_mode_retries_on_schedule_after_failure(self):
        clock = FakeClock()
        starts = []

        def downloader(output_dir):
            starts.append(clock.value)
            if len(starts) == 1:
                raise OSError("temporary failure")
            if len(starts) == 3:
                raise KeyboardInterrupt
            return output_dir / "capture.jpg"

        config = skycam.Config(1.0, Path("captures"), False)
        with self.assertRaises(KeyboardInterrupt):
            skycam.run(
                config,
                downloader=downloader,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(starts, [0.0, 60.0, 120.0])
        self.assertEqual(clock.sleeps, [60.0, 60.0])

    def test_slow_attempt_starts_next_attempt_immediately_without_replay(self):
        clock = FakeClock()
        starts = []

        def downloader(output_dir):
            starts.append(clock.value)
            if len(starts) == 1:
                clock.value += 90.0
            elif len(starts) == 3:
                raise KeyboardInterrupt
            return output_dir / "capture.jpg"

        config = skycam.Config(1.0, Path("captures"), False)
        with self.assertRaises(KeyboardInterrupt):
            skycam.run(
                config,
                downloader=downloader,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(starts, [0.0, 90.0, 150.0])
        self.assertEqual(clock.sleeps, [0.0, 60.0])


if __name__ == "__main__":
    unittest.main()
