from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "find_planet_openorb_v1"
sys.path.insert(0, str(PROJECT))


class RuntimeBoundaryTests(unittest.TestCase):
    def test_existing_output_is_refused(self) -> None:
        from find_planet_openorb.provenance import new_output_directory

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            created = new_output_directory(root, "run-001")
            self.assertEqual(created, root / "run-001")
            with self.assertRaises(FileExistsError):
                new_output_directory(root, "run-001")

    def test_database_is_read_only(self) -> None:
        from find_planet_openorb.provenance import open_sqlite_read_only

        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "measurements.sqlite"
            writable = sqlite3.connect(database)
            writable.execute("CREATE TABLE evidence (value TEXT)")
            writable.execute("INSERT INTO evidence VALUES ('kept')")
            writable.commit()
            writable.close()
            connection = open_sqlite_read_only(database)
            self.assertEqual(connection.execute("SELECT value FROM evidence").fetchone(), ("kept",))
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("INSERT INTO evidence VALUES ('changed')")
            connection.close()

    def test_setup_pins_release_commit_and_license(self) -> None:
        manifest = json.loads((PROJECT / "openorb-sources.json").read_text())
        self.assertEqual(manifest["release"], "v1.3.0")
        self.assertEqual(manifest["commit"], "945178476f016dae8f3981b54a937f61de81360f")
        self.assertEqual(manifest["license"]["spdx"], "GPL-3.0-only")
        self.assertEqual(manifest["license"]["source"], "https://github.com/oorb/oorb/blob/v1.3.0/COPYING")
        self.assertEqual(manifest["source_archive"]["url"], "https://github.com/oorb/oorb/archive/945178476f016dae8f3981b54a937f61de81360f.tar.gz")
        self.assertRegex(manifest["source_archive"]["sha256"], r"^[0-9a-f]{64}$")

    def _make_verified_vendor(self, root: Path) -> Path:
        vendor = root / "openorb-1.3.0"
        executable = vendor / "bin" / "oorb"
        data = vendor / "data"
        executable.parent.mkdir(parents=True)
        data.mkdir()
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
        (vendor / "oorb.conf").write_text("planetary_ephemeris_fname: de441.dat\n")
        (data / "OBSCODE.dat").write_text("observatories\n")
        (data / "TAI-UTC.dat").write_text("time\n")
        (data / "ET-UT.dat").write_text("earth time\n")
        (data / "de441.dat").write_text("ephemeris\n")
        files = {}
        for path in (executable, vendor / "oorb.conf", *sorted(data.iterdir())):
            files[str(path.relative_to(vendor))] = hashlib.sha256(path.read_bytes()).hexdigest()
        receipt = {
            "release": "v1.3.0",
            "commit": "945178476f016dae8f3981b54a937f61de81360f",
            "license": "GPL-3.0-only",
            "upstream_tests": "passed",
            "de441_test": "passed",
            "files": files,
        }
        (vendor / "openorb-build-receipt.json").write_text(json.dumps(receipt))
        (vendor / "openorb-data-receipt.json").write_text(json.dumps(receipt))
        return vendor

    def _matching_manifest(self, root: Path, vendor: Path) -> Path:
        manifest = json.loads((PROJECT / "openorb-sources.json").read_text())
        manifest["bundled_data"] = {
            name: hashlib.sha256((vendor / "data" / name).read_bytes()).hexdigest()
            for name in ("OBSCODE.dat", "TAI-UTC.dat", "ET-UT.dat")
        }
        path = root / "sources.json"
        path.write_text(json.dumps(manifest))
        return path

    def test_scientific_launcher_uses_only_receipt_hashed_local_binary(self) -> None:
        from find_planet_openorb.provenance import verify_installation

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vendor = self._make_verified_vendor(root)
            manifest = self._matching_manifest(root, vendor)
            installation = verify_installation(vendor, manifest)
            self.assertEqual(installation.executable, vendor / "bin" / "oorb")
            self.assertEqual(installation.executable_sha256, hashlib.sha256(installation.executable.read_bytes()).hexdigest())
            installation.executable.write_text("#!/bin/sh\nexit 9\n")
            with self.assertRaises(ValueError):
                verify_installation(vendor, manifest)

    def test_manifest_data_hashes_are_enforced(self) -> None:
        from find_planet_openorb.provenance import verify_installation

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vendor = self._make_verified_vendor(root)
            manifest = self._matching_manifest(root, vendor)
            payload = json.loads(manifest.read_text())
            payload["bundled_data"]["OBSCODE.dat"] = "0" * 64
            manifest.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "source manifest data hash mismatch"):
                verify_installation(vendor, manifest)

    def test_path_oorb_is_never_executed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_bin = Path(tmp)
            marker = fake_bin / "path-oorb-ran"
            (fake_bin / "oorb").write_text(f"#!/bin/sh\ntouch {marker}\nexit 88\n")
            (fake_bin / "oorb").chmod(0o755)
            captured = fake_bin / "uv-args.json"
            (fake_bin / "uv").write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, pathlib, sys\n"
                f"pathlib.Path({str(captured)!r}).write_text(json.dumps({{'args': sys.argv[1:], 'virtual_env': os.environ.get('VIRTUAL_ENV')}}))\n"
            )
            (fake_bin / "uv").chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:{env['PATH']}"
            env["VIRTUAL_ENV"] = "/must/be/unset"
            subprocess.run([str(ROOT / "go_find_planet_openorb_v1.sh"), "--dry-run"], env=env, check=True)
            self.assertFalse(marker.exists())
            invocation = json.loads(captured.read_text())
            self.assertIsNone(invocation["virtual_env"])
            self.assertIn("--frozen", invocation["args"])
            self.assertIn(str(PROJECT / ".vendor" / "openorb-1.3.0"), invocation["args"])
            self.assertNotIn("oorb", invocation["args"])

    def test_frozen_or_stopped_launchers_are_not_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_bin = Path(tmp)
            captured = fake_bin / "uv-args.json"
            (fake_bin / "uv").write_text(
                "#!/usr/bin/env python3\n"
                "import json, pathlib, sys\n"
                f"pathlib.Path({str(captured)!r}).write_text(json.dumps(sys.argv[1:]))\n"
            )
            (fake_bin / "uv").chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{fake_bin}:{env['PATH']}"
            subprocess.run([str(ROOT / "go_find_planet_openorb_v1.sh")], env=env, check=True)
            args = json.loads(captured.read_text())
            joined = " ".join(args)
            self.assertIn("find_planet_openorb_v1", joined)
            for forbidden in ("find_planet_v1", "go16.sh", "go17.sh", "go18.sh", "go19.sh", "go20.sh", "go21.sh", "go22.sh", "go23.sh"):
                self.assertNotIn(forbidden, joined)


if __name__ == "__main__":
    unittest.main()
