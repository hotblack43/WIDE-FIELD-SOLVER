from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "find_planet_v1"))

from find_planet import __version__
from find_planet.provenance import (
    new_output_directory,
    open_sqlite_read_only,
    sha256_file,
)


class RuntimeBoundaryTests(unittest.TestCase):
    def test_package_version_and_sha256_are_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = Path(directory) / "payload.bin"
            payload.write_bytes(b"Object A\x00measured")

            self.assertEqual(__version__, "1.0.0")
            self.assertEqual(
                sha256_file(payload),
                hashlib.sha256(b"Object A\x00measured").hexdigest(),
            )

    def test_database_is_opened_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "runs.sqlite"
            writable = sqlite3.connect(database)
            writable.execute("CREATE TABLE evidence(value TEXT NOT NULL)")
            writable.execute("INSERT INTO evidence VALUES ('preserved')")
            writable.commit()
            writable.close()

            connection = open_sqlite_read_only(database)
            self.assertEqual(
                connection.execute("SELECT value FROM evidence").fetchone()[0],
                "preserved",
            )
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("INSERT INTO evidence VALUES ('changed')")
            connection.close()

    def test_existing_output_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            results = Path(directory) / "results"
            first = new_output_directory(results, "run-001")
            self.assertEqual(first, results / "run-001")
            self.assertTrue(first.is_dir())

            with self.assertRaises(FileExistsError):
                new_output_directory(results, "run-001")

    def test_launcher_uses_find_planet_v1_frozen_project(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            fake_uv = temporary / "uv"
            fake_uv.write_text(
                "#!/usr/bin/env bash\n"
                "[ -z \"${VIRTUAL_ENV+x}\" ] || exit 99\n"
                "printf '%s\\n' \"$@\"\n",
                encoding="utf-8",
            )
            fake_uv.chmod(0o755)
            environment = dict(os.environ)
            environment["PATH"] = f"{temporary}:{environment['PATH']}"
            environment["VIRTUAL_ENV"] = "/must/be/unset"

            completed = subprocess.run(
                [str(ROOT / "go_find_planet_controlled_v1.sh"), "--grid-size", "7"],
                cwd=temporary,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertEqual(
                completed.stdout.splitlines(),
                [
                    "run",
                    "--project",
                    str(ROOT / "find_planet_v1"),
                    "--frozen",
                    "python",
                    "-m",
                    "find_planet.controlled_cli",
                    "--results-root",
                    str(ROOT / "results" / "find-planet-v1"),
                    "--grid-size",
                    "7",
                ],
            )

    def test_frozen_runtime_paths_are_not_launcher_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            fake_uv = temporary / "uv"
            fake_uv.write_text(
                "#!/usr/bin/env bash\n"
                "[ -z \"${VIRTUAL_ENV+x}\" ] || exit 99\n"
                "printf '%s\\n' \"$@\"\n",
                encoding="utf-8",
            )
            fake_uv.chmod(0o755)
            environment = dict(os.environ)
            environment["PATH"] = f"{temporary}:{environment['PATH']}"

            completed = subprocess.run(
                [str(ROOT / "go_find_planet_controlled_v1.sh")],
                cwd=temporary,
                env=environment,
                text=True,
                capture_output=True,
                check=True,
            )

            forwarded = "\n".join(completed.stdout.splitlines())
            for frozen in ("/v23/", "v23/run.sh", "go23.sh", "go_mmto"):
                self.assertNotIn(frozen, forwarded)


if __name__ == "__main__":
    unittest.main()
