"""Regression tests for the curated v0.11.0 release assets."""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import stat
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parent
TOP = "wide-field-solver-v0.11.0"


class V11ReleaseInventoryTests(unittest.TestCase):
    def test_inventory_is_explicit_complete_and_curated(self):
        from scripts import build_v11_release as release

        inventory = release.release_inventory(ROOT)
        destinations = set(inventory.values())
        required = {
            f"{TOP}/README.md",
            f"{TOP}/LICENSE",
            f"{TOP}/NOTICE.md",
            f"{TOP}/CITATION.cff",
            f"{TOP}/go11.sh",
            f"{TOP}/go_v0.11.0.sh",
            f"{TOP}/demo.sh",
            f"{TOP}/v11/uv.lock",
            f"{TOP}/v11/pyproject.toml",
            f"{TOP}/v11/point_star_barghini.py",
            f"{TOP}/v11/point_star_joint_epoch.py",
            f"{TOP}/v11/data/stars_gaia_dr3_g75.csv",
            f"{TOP}/v11/scripts/run_mmto_demo.py",
            f"{TOP}/v11/scripts/check_mmto_demo.py",
            f"{TOP}/v11/examples/mmto/baseline.json",
            f"{TOP}/v11/examples/mmto/2026_09_19__02_20_01.fits.bz2",
        }
        self.assertTrue(required <= destinations)
        self.assertEqual(len(inventory), len(destinations))

        forbidden = (
            "/test",
            "/docs/",
            "milky_way/input.jpeg",
            ".sqlite",
            "__pycache__",
            "/results/",
            "gobig",
        )
        for destination in destinations:
            folded = destination.lower()
            self.assertTrue(destination.startswith(f"{TOP}/"), destination)
            for fragment in forbidden:
                self.assertNotIn(fragment, folded, destination)
            versions = {
                part for part in PurePosixPath(destination).parts
                if part.startswith("v") and part[1:].isdigit()
            }
            self.assertLessEqual(versions, {"v11"}, destination)

    def test_missing_required_source_fails_closed(self):
        from scripts import build_v11_release as release

        missing = Path("v11/required-but-missing.dat")
        mappings = release.ROOT_MAPPINGS + ((missing, "missing.dat"),)
        with mock.patch.object(release, "ROOT_MAPPINGS", mappings):
            with self.assertRaisesRegex(FileNotFoundError, str(missing)):
                release.release_inventory(ROOT)


class V11ReleaseArchiveTests(unittest.TestCase):
    def test_builds_are_byte_reproducible_and_checksums_verify(self):
        from scripts.build_v11_release import build_assets

        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            assets_a = build_assets(ROOT, Path(first))
            assets_b = build_assets(ROOT, Path(second))
            for a, b in zip(assets_a, assets_b, strict=True):
                self.assertEqual(a.read_bytes(), b.read_bytes(), a.name)

            checksum_lines = assets_a[2].read_text(encoding="ascii").splitlines()
            self.assertEqual(len(checksum_lines), 2)
            for line in checksum_lines:
                digest, filename = line.split("  ", 1)
                payload = Path(first, filename).read_bytes()
                self.assertEqual(digest, hashlib.sha256(payload).hexdigest())

    def test_archives_have_exact_members_one_root_and_executable_entry_points(self):
        from scripts.build_v11_release import build_assets, release_inventory

        expected = set(release_inventory(ROOT).values())
        with tempfile.TemporaryDirectory() as work:
            tar_path, zip_path, _ = build_assets(ROOT, Path(work))
            with tarfile.open(tar_path, "r:gz") as archive:
                members = [member for member in archive.getmembers() if member.isfile()]
                self.assertEqual({member.name for member in members}, expected)
                modes = {member.name: member.mode for member in members}
            with zipfile.ZipFile(zip_path) as archive:
                infos = [info for info in archive.infolist() if not info.is_dir()]
                self.assertEqual({info.filename for info in infos}, expected)
                zip_modes = {
                    info.filename: (info.external_attr >> 16) & 0o777 for info in infos
                }

            self.assertEqual(
                {PurePosixPath(name).parts[0] for name in expected}, {TOP}
            )
            entry_points = {
                name for name in expected
                if name.endswith(".sh") or PurePosixPath(name).name in {"go11.sh", "go_v0.11.0.sh"}
            }
            for name in entry_points:
                self.assertTrue(modes[name] & stat.S_IXUSR, name)
                self.assertTrue(zip_modes[name] & stat.S_IXUSR, name)

    def test_validator_rejects_unexpected_and_unsafe_members(self):
        from scripts.build_v11_release import validate_archive

        cases = (
            ("unexpected.sqlite", {f"{TOP}/unexpected.sqlite"}),
            ("parent.zip", {f"{TOP}/../escape"}),
            ("absolute.zip", {"/absolute"}),
        )
        with tempfile.TemporaryDirectory() as work:
            for filename, names in cases:
                path = Path(work, filename)
                with zipfile.ZipFile(path, "w") as archive:
                    for name in names:
                        archive.writestr(name, b"payload")
                with self.subTest(filename=filename):
                    with self.assertRaises(ValueError):
                        validate_archive(path, set())

            tar_path = Path(work, "unsafe.tar.gz")
            with tarfile.open(tar_path, "w:gz") as archive:
                info = tarfile.TarInfo(f"{TOP}/../escape")
                info.size = 0
                archive.addfile(info)
            with self.assertRaises(ValueError):
                validate_archive(tar_path, set())

    def test_builder_refuses_to_overwrite_assets(self):
        from scripts.build_v11_release import build_assets

        with tempfile.TemporaryDirectory() as work:
            output = Path(work)
            build_assets(ROOT, output)
            with self.assertRaises(FileExistsError):
                build_assets(ROOT, output)


if __name__ == "__main__":
    unittest.main()
