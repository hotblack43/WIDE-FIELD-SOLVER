"""Automatic visible-sky calibration resolution at the v25 launcher boundary."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from analyse_image import (
    parser,
    resolve_visible_sky_configuration,
    validate_arguments,
)


class LauncherResolutionTests(unittest.TestCase):
    def parse(self, root: Path, *extra: str):
        return parser().parse_args(
            [str(root / "image.fits"), "--output", str(root / "output"), *extra]
        )

    def test_explicit_automatic_and_unconfigured_modes_are_exclusive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.joinpath("image.fits").write_bytes(b"source")
            valid_auto = (
                "--calibration-registry", str(root / "registry.jsonl"),
                "--installation-assignments", str(root / "assignments.jsonl"),
            )
            validate_arguments(parser(), self.parse(root))
            validate_arguments(parser(), self.parse(root, *valid_auto))
            validate_arguments(
                parser(), self.parse(
                    root, *valid_auto, "--allow-unconfigured-visible-sky"
                )
            )
            invalid = (
                ("--calibration-registry", str(root / "registry.jsonl")),
                ("--installation-assignments", str(root / "assignments.jsonl")),
                (
                    "--visible-sky-mask-manifest", str(root / "mask.json"),
                    "--camera-installation-id", "installation-a",
                    *valid_auto,
                ),
                ("--allow-unconfigured-visible-sky",),
            )
            for options in invalid:
                with self.subTest(options=options), self.assertRaisesRegex(
                    ValueError, "automatic|unconfigured"
                ):
                    validate_arguments(parser(), self.parse(root, *options))

    def test_assignment_resolves_exact_manifest_and_records_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "image.fits"
            source.write_bytes(b"source")
            registry = root / "registry.jsonl"
            registry.write_text("")
            root.joinpath("assignments.jsonl").write_text("assignment\n")
            manifest = root / "mask.json"
            manifest.write_text("manifest\n")
            args = self.parse(
                root,
                "--calibration-registry", str(registry),
                "--installation-assignments", str(root / "assignments.jsonl"),
            )
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            assignment = {
                "source_sha256": digest,
                "source_id": "source-a",
                "camera_id": "camera-a",
                "installation_id": "installation-a",
                "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "mask_sha256": "a" * 64,
            }
            calibration = {
                "installation_id": "installation-a",
                "mask_id": "mask-a",
                "manifest_path": str(manifest),
                "manifest_sha256": assignment["manifest_sha256"],
                "mask_sha256": assignment["mask_sha256"],
                "assignment": assignment,
            }
            with mock.patch(
                "visible_sky_registry.assignment_for_source",
                return_value=assignment,
            ), mock.patch(
                "visible_sky_registry.resolve_source_calibration",
                return_value=calibration,
            ):
                evidence = resolve_visible_sky_configuration(args)
            self.assertEqual(args.visible_sky_mask_manifest, manifest.resolve())
            self.assertEqual(args.camera_installation_id, "installation-a")
            self.assertEqual(evidence["source_id"], "source-a")
            self.assertEqual(evidence["camera_id"], "camera-a")
            self.assertEqual(evidence["source_sha256"], digest)
            self.assertEqual(
                evidence["registry_layers"][0]["sha256"],
                hashlib.sha256(registry.read_bytes()).hexdigest(),
            )

    def test_only_missing_assignment_may_use_unconfigured_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.joinpath("image.fits").write_bytes(b"source")
            root.joinpath("registry.jsonl").write_text("")
            args = self.parse(
                root,
                "--calibration-registry", str(root / "registry.jsonl"),
                "--installation-assignments", str(root / "assignments.jsonl"),
                "--allow-unconfigured-visible-sky",
            )
            with mock.patch(
                "visible_sky_registry.assignment_for_source", return_value=None
            ):
                evidence = resolve_visible_sky_configuration(args)
            self.assertEqual(evidence["status"], "not_configured")
            self.assertIsNone(args.visible_sky_mask_manifest)
            self.assertFalse(root.joinpath("output").exists())

            with mock.patch(
                "visible_sky_registry.assignment_for_source",
                return_value={"source_sha256": "x"},
            ), mock.patch(
                "visible_sky_registry.resolve_source_calibration",
                side_effect=ValueError("registry checksum mismatch"),
            ), self.assertRaisesRegex(ValueError, "checksum mismatch"):
                resolve_visible_sky_configuration(args)
            self.assertFalse(root.joinpath("output").exists())

    def test_unconfigured_fallback_still_rejects_malformed_registry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.joinpath("image.fits").write_bytes(b"source")
            registry = root / "registry.jsonl"
            registry.write_text("not-json\n")
            args = self.parse(
                root,
                "--calibration-registry", str(registry),
                "--installation-assignments", str(root / "assignments.jsonl"),
                "--allow-unconfigured-visible-sky",
            )
            with self.assertRaisesRegex(ValueError, "registry.*:1"):
                resolve_visible_sky_configuration(args)
            self.assertFalse(root.joinpath("output").exists())

if __name__ == "__main__":
    unittest.main()
