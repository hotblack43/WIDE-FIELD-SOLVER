"""Append-only visible-sky calibration registry tests."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image
from astropy.io import fits

from scripts.build_visible_sky_mask import main as calibration_main
from visible_sky_calibration import artifact_inventory_sha256
from visible_sky_automatic import canonical_acceptance_payload
from visible_sky_registry import (
    activate_installation,
    active_installation,
    assign_source,
    assignment_for_source,
    load_registry,
    register_calibration,
    resolve_source_calibration,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_approved_manifest(
    root: Path,
    *,
    installation_id: str = "installation-a",
    mask_id: str = "mask-a",
    source_id: str = "source-a",
    camera_id: str = "camera-a",
    visible_column: int = 3,
    instrument: str = "CAMERA-A",
) -> Path:
    directory = root / installation_id
    directory.mkdir(parents=True, exist_ok=True)
    mask_path = directory / f"{mask_id}.png"
    pixels = np.zeros((7, 9), dtype=np.uint8)
    pixels[:, :visible_column] = 255
    Image.fromarray(pixels, mode="L").save(mask_path)
    manifest = {
        "schema": "wide-field-solver-visible-sky-mask-v1",
        "status": "approved",
        "source_id": source_id,
        "camera_id": camera_id,
        "mask_id": mask_id,
        "installation_id": installation_id,
        "instrument": instrument,
        "detector_shape": [7, 9],
        "plane_layout": "two_dimensional",
        "plane_names": ["L"],
        "orientation": "detector-native",
        "coordinate_convention": "array[y, x]; origin top-left",
        "mask_file": mask_path.name,
        "mask_sha256": _sha256(mask_path),
        "approval": {"approved_by": "Peter", "approved_utc": "2026-11-15T00:00:00Z"},
    }
    path = directory / f"{mask_id}.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path


def _write_source(
    root: Path,
    name: str,
    *,
    instrument: str = "CAMERA-A",
    shape: tuple[int, ...] = (7, 9),
) -> tuple[Path, str]:
    path = root / name
    offset = sum(name.encode("utf-8")) % 1000
    hdu = fits.PrimaryHDU(
        (np.arange(np.prod(shape), dtype=np.uint16) + offset).reshape(shape)
    )
    hdu.header["INSTRUME"] = instrument
    hdu.writeto(path)
    return path, _sha256(path)


def _write_automatic_acceptance(root: Path, manifest: dict[str, object]) -> tuple[Path, str]:
    total = int(np.prod(manifest["detector_shape"]))
    visible = int((np.asarray(Image.open(root / manifest["installation_id"] / manifest["mask_file"])) == 255).sum())
    metrics = {
        "total_date_count": 10,
        "calibration_date_count": 8,
        "held_out_date_count": 2,
        "held_out_source_count": 20,
        "detector_signature_count": 1,
        "proposal_visible_pixel_count": visible,
        "proposal_pixel_count": total,
        "proposal_connected_component_count": 1,
        "finalized_visible_pixel_count": visible,
        "finalized_pixel_count": total,
        "finalized_connected_component_count": 1,
        "held_out_footprint_iou_median_numerator": 9,
        "held_out_footprint_iou_median_denominator": 10,
        "held_out_footprint_iou_minimum_numerator": 4,
        "held_out_footprint_iou_minimum_denominator": 5,
        "held_out_unmasked_detection_count": 100,
        "held_out_boundary_intersection_count": 0,
    }
    folds = [
        {
            "fold_index": index,
            "mask_intersection_count": 95,
            "mask_union_count": 100,
            "boundary_distance_mean_pixels": 0.0,
            "boundary_distance_p95_pixels": 0.0,
        }
        for index in range(5)
    ]
    payload = canonical_acceptance_payload(
        identity={
            "source_id": manifest["source_id"],
            "camera_id": manifest["camera_id"],
            "installation_id": manifest["installation_id"],
            "orientation": manifest["orientation"],
            "detector_signature_sha256": "d" * 64,
        },
        sources=[{"source_sha256": "a" * 64, "observed_bytes": 1}],
        metrics=metrics,
        fold_metrics=folds,
        artifact_sha256={"proposal-seal.json": "b" * 64},
        code_sha256={"visible_sky_auto_workflow.py": "c" * 64},
        finalized_mask_sha256=manifest["mask_sha256"],
    )
    receipt_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(receipt_bytes).hexdigest()
    receipt = root / "automatic-acceptance" / manifest["installation_id"] / f"{digest}.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_bytes(receipt_bytes)
    return receipt, digest


def _write_sealed_proposal(root: Path) -> tuple[Path, str]:
    proposal = root / "proposal"
    proposal.mkdir()
    draft_name = "cli-installation.draft.png"
    pixels = np.zeros((9, 11), dtype=np.uint8)
    pixels[2:8, 2:9] = 255
    Image.fromarray(pixels, mode="L").save(proposal / draft_name)
    reference = np.repeat(np.uint8(np.arange(99).reshape(9, 11))[..., None], 3, axis=2)
    for name, image in (
        ("temporal_reference.png", reference),
        ("boundary_review.png", reference),
        ("boundary_review_inverted.png", 255 - reference),
    ):
        Image.fromarray(image, mode="RGB").save(proposal / name)
    artifacts = {
        path.name: _sha256(path)
        for path in sorted(proposal.iterdir())
        if path.is_file()
    }
    selection = {
        "status": "draft_not_approved",
        "production_eligible": False,
        "draft_id": "cli-installation-draft",
        "source_id": "source-a",
        "camera_id": "camera-a",
        "installation_id": "cli-installation",
        "orientation": "detector-native",
        "coordinate_convention": "array[y, x]; origin top-left",
        "spatial_shape": [9, 11],
        "detector_signature": {
            "spatial_shape": [9, 11],
            "channel_layout": "two_dimensional",
            "plane_names": ["L"],
            "instrument": "CAMERA-A",
            "orientation": "detector-native",
        },
        "selection": {"method": "fixture", "source_count": 3, "sources": []},
        "proposal": {"method": "fixture"},
        "generation_code_sha256": "1" * 64,
        "artifacts": artifacts,
    }
    from visible_sky_calibration import seal_artifact_inventory
    selection["seal"] = seal_artifact_inventory(artifacts, selection)
    selection_path = proposal / "selection.json"
    selection_path.write_text(json.dumps(selection, indent=2, sort_keys=True) + "\n")
    return selection_path, artifacts[draft_name]


class RegistryTests(unittest.TestCase):
    def test_incomplete_generic_assignment_never_resolves_as_wildcard(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = _write_approved_manifest(root)
            registry = root / "registry.jsonl"
            register_calibration(
                registry, manifest, source_id="source-a", camera_id="camera-a"
            )
            digest = "a" * 64
            assignments = root / "assignments.jsonl"
            assignments.write_text(json.dumps({
                "schema": "wide-field-solver-source-installation-assignment-v1",
                "source_sha256": digest,
            }) + "\n")

            with self.assertRaisesRegex(ValueError, r"assignments\.jsonl:1.*missing"):
                resolve_source_calibration((registry,), assignments, digest)

    def test_generic_assignment_validates_source_identity_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = _write_approved_manifest(
                root, instrument="CAMERA-A (123)"
            )
            registry = root / "registry.jsonl"
            register_calibration(
                registry, manifest, source_id="source-a", camera_id="camera-a"
            )
            source, digest = _write_source(root, "source.fits", instrument="CAMERA-A")
            assignments = root / "assignments.jsonl"

            first = assign_source(
                assignments,
                source,
                digest,
                source_id="source-a",
                camera_id="camera-a",
                registry_paths=(registry,),
                installation_id="installation-a",
                orientation="detector-native",
            )
            second = assign_source(
                assignments,
                source,
                digest,
                source_id="source-a",
                camera_id="camera-a",
                registry_paths=(registry,),
                installation_id="installation-a",
                orientation="detector-native",
            )

            self.assertEqual(first, second)
            self.assertEqual(len(assignments.read_text().splitlines()), 1)
            self.assertEqual(assignment_for_source(assignments, digest), first)
            resolved = resolve_source_calibration((registry,), assignments, digest)
            self.assertEqual(resolved["installation_id"], "installation-a")
            self.assertEqual(resolved["source_id"], "source-a")

    def test_generic_assignment_rejects_checksum_and_detector_identity_mismatches(self):
        variants = ("checksum", "instrument", "shape", "layout", "orientation")
        for variant in variants:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manifest = _write_approved_manifest(
                    root, instrument="CAMERA-A (123)"
                )
                registry = root / "registry.jsonl"
                register_calibration(
                    registry, manifest, source_id="source-a", camera_id="camera-a"
                )
                instrument = "CAMERA-A (999)" if variant == "instrument" else "CAMERA-A"
                shape = (
                    (8, 9)
                    if variant == "shape"
                    else ((3, 7, 9) if variant == "layout" else (7, 9))
                )
                source, digest = _write_source(
                    root, "source.fits", instrument=instrument, shape=shape
                )
                supplied_digest = "0" * 64 if variant == "checksum" else digest
                orientation = "rotated-180" if variant == "orientation" else "detector-native"

                with self.assertRaisesRegex(ValueError, "checksum|instrument|shape|layout|orientation"):
                    assign_source(
                        root / "assignments.jsonl",
                        source,
                        supplied_digest,
                        source_id="source-a",
                        camera_id="camera-a",
                        registry_paths=(registry,),
                        installation_id="installation-a",
                        orientation=orientation,
                    )

    def test_conflicting_reassignment_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.jsonl"
            first_manifest = _write_approved_manifest(
                root, installation_id="installation-a", mask_id="mask-a"
            )
            second_manifest = _write_approved_manifest(
                root, installation_id="installation-b", mask_id="mask-b"
            )
            register_calibration(
                registry, first_manifest, source_id="source-a", camera_id="camera-a"
            )
            register_calibration(
                registry, second_manifest, source_id="source-a", camera_id="camera-a"
            )
            source, digest = _write_source(root, "source.fits")
            assignments = root / "assignments.jsonl"
            assign_source(
                assignments,
                source,
                digest,
                source_id="source-a",
                camera_id="camera-a",
                registry_paths=(registry,),
                installation_id="installation-a",
                orientation="detector-native",
            )

            with self.assertRaisesRegex(ValueError, "conflicting.*reassignment"):
                assign_source(
                    assignments,
                    source,
                    digest,
                    source_id="source-a",
                    camera_id="camera-a",
                    registry_paths=(registry,),
                    installation_id="installation-b",
                    orientation="detector-native",
                )

    def test_active_installation_changes_do_not_repoint_existing_assignments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.jsonl"
            for installation, mask in (("installation-a", "mask-a"), ("installation-b", "mask-b")):
                manifest = _write_approved_manifest(
                    root, installation_id=installation, mask_id=mask
                )
                register_calibration(
                    registry, manifest, source_id="source-a", camera_id="camera-a"
                )
            assignments = root / "assignments.jsonl"
            source_a, digest_a = _write_source(root, "source-a.fits")
            source_b, digest_b = _write_source(root, "source-b.fits")

            activate_installation(
                registry,
                source_id="source-a",
                camera_id="camera-a",
                installation_id="installation-a",
            )
            active_a = active_installation(
                (registry,), source_id="source-a", camera_id="camera-a"
            )
            assign_source(
                assignments,
                source_a,
                digest_a,
                source_id="source-a",
                camera_id="camera-a",
                registry_paths=(registry,),
                installation_id=active_a["installation_id"],
                orientation="detector-native",
            )
            activate_installation(
                registry,
                source_id="source-a",
                camera_id="camera-a",
                installation_id="installation-b",
            )
            active_b = active_installation(
                (registry,), source_id="source-a", camera_id="camera-a"
            )
            assign_source(
                assignments,
                source_b,
                digest_b,
                source_id="source-a",
                camera_id="camera-a",
                registry_paths=(registry,),
                installation_id=active_b["installation_id"],
                orientation="detector-native",
            )

            self.assertEqual(
                resolve_source_calibration((registry,), assignments, digest_a)["installation_id"],
                "installation-a",
            )
            self.assertEqual(
                resolve_source_calibration((registry,), assignments, digest_b)["installation_id"],
                "installation-b",
            )

    def test_cli_approval_registers_but_only_activate_selects_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proposal, draft_hash = _write_sealed_proposal(root)
            calibration_root = root / "calibrations"

            self.assertEqual(
                calibration_main(
                    [
                        "approve",
                        "--proposal",
                        str(proposal),
                        "--reviewed-draft-sha256",
                        draft_hash,
                        "--mask-id",
                        "cli-mask-v1",
                        "--approved-by",
                        "Peter",
                        "--safety-margin-pixels",
                        "1",
                        "--calibration-root",
                        str(calibration_root),
                    ]
                ),
                0,
            )
            registry = calibration_root / "registry.jsonl"
            self.assertTrue(registry.is_file())
            self.assertIsNone(
                active_installation(
                    (registry,), source_id="source-a", camera_id="camera-a"
                )
            )

            self.assertEqual(
                calibration_main(
                    [
                        "activate",
                        "--calibration-registry",
                        str(registry),
                        "--source",
                        "source-a",
                        "--camera",
                        "camera-a",
                        "--installation-id",
                        "cli-installation",
                    ]
                ),
                0,
            )
            self.assertEqual(
                active_installation(
                    (registry,), source_id="source-a", camera_id="camera-a"
                )["installation_id"],
                "cli-installation",
            )

    def test_registration_is_append_only_idempotent_and_resolves_relative_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = _write_approved_manifest(root)
            registry = root / "registry.jsonl"

            first = register_calibration(
                registry, manifest, source_id="source-a", camera_id="camera-a"
            )
            original = registry.read_bytes()
            second = register_calibration(
                registry, manifest, source_id="source-a", camera_id="camera-a"
            )
            records = load_registry((registry,))

            self.assertEqual(registry.read_bytes(), original)
            self.assertEqual(first["installation_id"], second["installation_id"])
            self.assertEqual(len(records), 1)
            self.assertEqual(Path(records[0]["manifest_path"]), manifest.resolve())
            self.assertEqual(
                Path(records[0]["mask_path"]), manifest.parent / "mask-a.png"
            )

    def test_registry_revalidates_automated_receipt_hash_and_relative_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = _write_approved_manifest(root)
            manifest = json.loads(manifest_path.read_text())
            receipt, digest = _write_automatic_acceptance(root, manifest)
            receipt_bytes = receipt.read_bytes()
            manifest["approval"] = {
                "approval_mode": "automated_validation",
                "approved_by": "wide-field-solver-v26-auto",
                "approved_utc": "2026-11-16T00:00:00Z",
                "automatic_acceptance": {
                    "path": f"automatic-acceptance/installation-a/{digest}.json",
                    "sha256": digest,
                },
            }
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            registry = root / "registry.jsonl"
            register_calibration(
                registry, manifest_path, source_id="source-a", camera_id="camera-a"
            )
            self.assertEqual(len(load_registry((registry,))), 1)

            receipt.write_bytes(receipt_bytes + b"changed")
            with self.assertRaisesRegex(ValueError, "automatic acceptance checksum"):
                load_registry((registry,))

    def test_conflicting_identifiers_and_layers_fail_without_changing_prior_bytes(self):
        mutations = ("mask", "source-camera")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                bundled_root = root / "bundled"
                user_root = root / "user"
                first = _write_approved_manifest(bundled_root)
                bundled = bundled_root / "registry.jsonl"
                register_calibration(
                    bundled, first, source_id="source-a", camera_id="camera-a"
                )
                if mutation == "mask":
                    second = _write_approved_manifest(
                        user_root,
                        installation_id="installation-b",
                        mask_id="mask-a",
                        visible_column=4,
                    )
                    source, camera = "source-a", "camera-a"
                else:
                    second = _write_approved_manifest(
                        user_root,
                        installation_id="installation-a",
                        mask_id="mask-a",
                        source_id="source-b",
                        camera_id="camera-b",
                    )
                    source, camera = "source-b", "camera-b"
                user = user_root / "registry.jsonl"
                register_calibration(user, second, source_id=source, camera_id=camera)
                before = user.read_bytes()

                with self.assertRaisesRegex(ValueError, "conflicting calibration registry"):
                    load_registry((bundled, user))

                self.assertEqual(user.read_bytes(), before)

    def test_manifest_checksum_change_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = _write_approved_manifest(root)
            registry = root / "registry.jsonl"
            register_calibration(
                registry, manifest, source_id="source-a", camera_id="camera-a"
            )
            before = registry.read_bytes()
            manifest.write_text(manifest.read_text() + "\n")

            with self.assertRaisesRegex(ValueError, "manifest checksum mismatch"):
                load_registry((registry,))

            self.assertEqual(registry.read_bytes(), before)

    def test_truncated_line_reports_registry_and_line_number(self):
        with tempfile.TemporaryDirectory() as temporary:
            registry = Path(temporary) / "registry.jsonl"
            registry.write_text('{"schema":"wide-field-solver-calibration-registry-v1"\n')

            with self.assertRaisesRegex(ValueError, r"registry\.jsonl:1"):
                load_registry((registry,))

    def test_concurrent_identical_registration_has_one_logical_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = _write_approved_manifest(root)
            registry = root / "registry.jsonl"

            def register() -> dict[str, object]:
                return register_calibration(
                    registry, manifest, source_id="source-a", camera_id="camera-a"
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                records = tuple(executor.map(lambda _index: register(), range(2)))

            self.assertEqual(len(load_registry((registry,))), 1)
            self.assertEqual(records[0]["manifest_sha256"], records[1]["manifest_sha256"])
            self.assertEqual(len(registry.read_text().splitlines()), 1)

    def test_registration_does_not_activate_and_activation_history_is_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.jsonl"
            first = _write_approved_manifest(root, installation_id="installation-a", mask_id="mask-a")
            second = _write_approved_manifest(root, installation_id="installation-b", mask_id="mask-b")
            register_calibration(
                registry, first, source_id="source-a", camera_id="camera-a"
            )
            register_calibration(
                registry, second, source_id="source-a", camera_id="camera-a"
            )
            self.assertIsNone(
                active_installation(
                    (registry,), source_id="source-a", camera_id="camera-a"
                )
            )

            activate_installation(
                registry,
                source_id="source-a",
                camera_id="camera-a",
                installation_id="installation-a",
            )
            activate_installation(
                registry,
                source_id="source-a",
                camera_id="camera-a",
                installation_id="installation-b",
            )
            active = active_installation(
                (registry,), source_id="source-a", camera_id="camera-a"
            )

            self.assertEqual(active["installation_id"], "installation-b")
            records = load_registry((registry,))
            self.assertEqual(
                [record["installation_id"] for record in records if record["record_type"] == "activation"],
                ["installation-a", "installation-b"],
            )

    def test_activation_rejects_missing_or_unapproved_target_without_append(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.jsonl"
            manifest = _write_approved_manifest(root)
            register_calibration(
                registry, manifest, source_id="source-a", camera_id="camera-a"
            )
            before = registry.read_bytes()

            with self.assertRaisesRegex(ValueError, "not registered"):
                activate_installation(
                    registry,
                    source_id="source-a",
                    camera_id="camera-a",
                    installation_id="missing-installation",
                )

            self.assertEqual(registry.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
