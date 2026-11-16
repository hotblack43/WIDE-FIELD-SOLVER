"""Camera-neutral visible-sky calibration selection tests."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from astropy.io import fits
import numpy as np
from PIL import Image

from visible_sky_calibration import (
    CalibrationSource,
    DetectorSignature,
    approve_proposal,
    detector_signature,
    draft_filename,
    finalize_binary_mask,
    partition_dates,
    seal_artifact_inventory,
    require_single_detector_signature,
    revise_proposal,
    verified_sources_from_manifest,
)
from visible_sky_automatic import canonical_acceptance_payload


DOWNLOADS_SCHEMA = """
CREATE TABLE downloads (
  remote_url TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  camera_id TEXT NOT NULL,
  observed_utc TEXT NOT NULL,
  local_path TEXT,
  observed_bytes INTEGER,
  sha256 TEXT,
  download_status TEXT NOT NULL,
  validation_status TEXT NOT NULL
)
"""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _insert_download(
    connection: sqlite3.Connection,
    *,
    url: str,
    source: str = "example-source",
    camera: str = "example-camera",
    observed: str = "2026-01-01T01:00:00Z",
    local_path: str | None,
    size: int | None,
    digest: str | None,
    download_status: str = "downloaded",
    validation_status: str = "verified",
) -> None:
    connection.execute(
        """
        INSERT INTO downloads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            url,
            source,
            camera,
            observed,
            local_path,
            size,
            digest,
            download_status,
            validation_status,
        ),
    )


class ManagedSourceSelectionTests(unittest.TestCase):
    def test_selects_only_verified_matching_downloads_and_rehashes_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_path = root / "example-source" / "example-camera" / "valid.fits"
            source_path.parent.mkdir(parents=True)
            source_path.write_bytes(b"verified native bytes")
            manifest = root / "manifest.sqlite"
            with sqlite3.connect(manifest) as connection:
                connection.execute(DOWNLOADS_SCHEMA)
                _insert_download(
                    connection,
                    url="https://example.test/valid",
                    local_path=source_path.relative_to(root).as_posix(),
                    size=source_path.stat().st_size,
                    digest=_sha256(source_path),
                )
                _insert_download(
                    connection,
                    url="https://example.test/unverified",
                    local_path="missing-unverified.fits",
                    size=10,
                    digest="0" * 64,
                    validation_status="pending",
                )
                _insert_download(
                    connection,
                    url="https://example.test/wrong-source",
                    source="another-source",
                    local_path="missing-wrong-source.fits",
                    size=10,
                    digest="1" * 64,
                )
                _insert_download(
                    connection,
                    url="https://example.test/wrong-camera",
                    camera="another-camera",
                    local_path="missing-wrong-camera.fits",
                    size=10,
                    digest="2" * 64,
                )

            selected = verified_sources_from_manifest(
                manifest, root, "example-source", "example-camera"
            )

            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0].path, source_path.resolve())
            self.assertEqual(selected[0].source_sha256, _sha256(source_path))
            self.assertEqual(selected[0].observation_date, "2026-01-01")
            self.assertEqual(selected[0].remote_url, "https://example.test/valid")

    def test_missing_matching_file_names_the_manifest_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "manifest.sqlite"
            with sqlite3.connect(manifest) as connection:
                connection.execute(DOWNLOADS_SCHEMA)
                _insert_download(
                    connection,
                    url="https://example.test/missing",
                    local_path="example-source/example-camera/missing.fits",
                    size=10,
                    digest="a" * 64,
                )

            with self.assertRaisesRegex(
                FileNotFoundError, "https://example.test/missing.*missing.fits"
            ):
                verified_sources_from_manifest(
                    manifest, root, "example-source", "example-camera"
                )

    def test_size_and_checksum_mismatches_name_the_manifest_record(self):
        for field in ("size", "checksum"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source_path = root / "native.fits"
                source_path.write_bytes(b"native bytes")
                manifest = root / "manifest.sqlite"
                with sqlite3.connect(manifest) as connection:
                    connection.execute(DOWNLOADS_SCHEMA)
                    _insert_download(
                        connection,
                        url=f"https://example.test/{field}-mismatch",
                        local_path="native.fits",
                        size=(source_path.stat().st_size + 1 if field == "size" else source_path.stat().st_size),
                        digest=("f" * 64 if field == "checksum" else _sha256(source_path)),
                    )

                with self.assertRaisesRegex(ValueError, f"{field}.*{field}-mismatch"):
                    verified_sources_from_manifest(
                        manifest, root, "example-source", "example-camera"
                    )

    def test_manifest_path_cannot_escape_the_archive_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "archive"
            root.mkdir()
            outside = parent / "outside.fits"
            outside.write_bytes(b"outside")
            manifest = root / "manifest.sqlite"
            with sqlite3.connect(manifest) as connection:
                connection.execute(DOWNLOADS_SCHEMA)
                _insert_download(
                    connection,
                    url="https://example.test/escape",
                    local_path="../outside.fits",
                    size=outside.stat().st_size,
                    digest=_sha256(outside),
                )

            with self.assertRaisesRegex(ValueError, "outside archive root.*escape"):
                verified_sources_from_manifest(
                    manifest, root, "example-source", "example-camera"
                )


class DetectorSignatureTests(unittest.TestCase):
    def _write_fits(
        self,
        path: Path,
        values: np.ndarray,
        *,
        instrument: str | None = "CAMERA-A",
    ) -> None:
        hdu = fits.PrimaryHDU(values)
        if instrument is not None:
            hdu.header["INSTRUME"] = instrument
        hdu.writeto(path)

    def test_signature_uses_native_shape_layout_planes_instrument_and_orientation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "image.fits"
            self._write_fits(path, np.ones((8, 10), dtype=np.uint16))

            signature = detector_signature(path, orientation="detector-native")

            self.assertEqual(
                signature,
                DetectorSignature(
                    spatial_shape=(8, 10),
                    channel_layout="two_dimensional",
                    plane_names=("L",),
                    instrument="CAMERA-A",
                    orientation="detector-native",
                ),
            )

    def test_mixed_shape_layout_instrument_or_orientation_is_rejected(self):
        baseline = DetectorSignature(
            (8, 10), "two_dimensional", ("L",), "CAMERA-A", "detector-native"
        )
        variants = {
            "shape": replace(baseline, spatial_shape=(9, 10)),
            "layout": replace(baseline, channel_layout="plane_first", plane_names=("R", "G", "B")),
            "instrument": replace(baseline, instrument="CAMERA-B"),
            "orientation": replace(baseline, orientation="rotated-180"),
        }
        for field, variant in variants.items():
            with self.subTest(field=field), self.assertRaisesRegex(
                ValueError, f"mixed detector signatures.*{field}"
            ):
                require_single_detector_signature(
                    ((Path("first.fits"), baseline), (Path(f"{field}.fits"), variant))
                )

    def test_same_model_missing_serial_is_compatible_but_different_serial_is_not(self):
        recorded = DetectorSignature(
            (1411, 1422), "plane_first", ("R", "G", "B"),
            "ZWO ASI294MC Pro (21599760)", "detector-native",
        )
        missing = replace(recorded, instrument="ZWO ASI294MC Pro")
        self.assertEqual(
            require_single_detector_signature(
                ((Path("serial.fits"), recorded), (Path("model.fits"), missing))
            ),
            recorded,
        )
        different = replace(recorded, instrument="ZWO ASI294MC Pro (99999999)")
        with self.assertRaisesRegex(ValueError, "mixed detector signatures.*instrument"):
            require_single_detector_signature(
                ((Path("serial.fits"), recorded), (Path("different.fits"), different))
            )

    def test_draft_filename_rejects_path_like_installation_ids(self):
        self.assertEqual(draft_filename("camera-installation.v1"), "camera-installation.v1.draft.png")
        for invalid in ("", "../camera", "camera/name", "camera name"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                draft_filename(invalid)


class DatePartitionTests(unittest.TestCase):
    def _source(self, root: Path, date: str, hour: int) -> CalibrationSource:
        path = root / date / f"{date.replace('-', '_')}__{hour:02d}_00_00.fits"
        return CalibrationSource(
            path=path,
            source_sha256=f"{date}{hour:02d}".encode().hex().ljust(64, "0")[:64],
            observed_bytes=1,
            source_id="example-source",
            camera_id="example-camera",
            observed_utc=f"{date}T{hour:02d}:00:00Z",
            observation_date=date,
            remote_url=f"https://example.test/{path.name}",
        )

    def test_partition_holds_out_every_fifth_date_before_phase_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dates = [f"2026-01-{day:02d}" for day in range(1, 13)]
            sources = tuple(
                self._source(root, date, hour)
                for date in dates
                for hour in (1, 3, 5, 7, 9)
            )

            split = partition_dates(sources)

            self.assertEqual(split.holdout_dates, (dates[0], dates[5], dates[10]))
            self.assertEqual(set(split.calibration_dates) & set(split.holdout_dates), set())
            self.assertGreaterEqual(len(split.holdout_dates) * 5, len(dates))
            self.assertEqual(
                {source.observation_date for source in split.selected_calibration_sources},
                set(split.calibration_dates),
            )
            self.assertEqual(
                [source.path.name.split("__")[1] for source in split.selected_calibration_sources[:3]],
                ["03_00_00.fits", "05_00_00.fits", "07_00_00.fits"],
            )
            self.assertFalse(
                set(split.selected_calibration_sources) & set(split.holdout_sources)
            )

    def test_partition_keeps_one_holdout_when_fewer_than_five_dates_exist(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = tuple(
                self._source(root, f"2026-02-{day:02d}", 1) for day in range(1, 5)
            )

            split = partition_dates(sources)

            self.assertEqual(split.holdout_dates, ("2026-02-01",))

    def test_custom_modulus_still_reserves_at_least_one_fifth_of_dates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = tuple(
                self._source(root, f"2026-03-{day:02d}", 1)
                for day in range(1, 13)
            )
            split = partition_dates(sources, holdout_modulus=10)
            self.assertGreaterEqual(len(split.holdout_dates), 3)


class ProposalLifecycleTests(unittest.TestCase):
    def _automatic_acceptance_bytes(
        self, proposal_path: Path, *, safety_margin_pixels: int
    ) -> bytes:
        selection = json.loads(proposal_path.read_text())
        draft_name = next(
            name for name in selection["artifacts"] if name.endswith(".draft.png")
        )
        preview = proposal_path.parent.parent / "preview-mask.png"
        finalization = finalize_binary_mask(
            proposal_path.parent / draft_name,
            preview,
            safety_margin_pixels=safety_margin_pixels,
        )
        preview.unlink()
        signature = selection["detector_signature"]
        signature_sha256 = hashlib.sha256(
            json.dumps(signature, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        approved = int(finalization["approved_visible_pixels"])
        total = int(np.prod(signature["spatial_shape"]))
        metrics = {
            "total_date_count": 10,
            "calibration_date_count": 8,
            "held_out_date_count": 2,
            "held_out_source_count": 20,
            "detector_signature_count": 1,
            "proposal_visible_pixel_count": int(selection["proposal"]["visible_pixels"]),
            "proposal_pixel_count": total,
            "proposal_connected_component_count": 1,
            "finalized_visible_pixel_count": approved,
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
                "source_id": selection["source_id"],
                "camera_id": selection["camera_id"],
                "installation_id": selection["installation_id"],
                "orientation": signature["orientation"],
                "detector_signature_sha256": signature_sha256,
            },
            sources=[{"source_sha256": "a" * 64, "observed_bytes": 1}],
            metrics=metrics,
            fold_metrics=folds,
            artifact_sha256={"proposal-seal.json": "b" * 64},
            code_sha256={"visible_sky_auto_workflow.py": "c" * 64},
            finalized_mask_sha256=finalization["approved_sha256"],
        )
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    def _write_valid_proposal(self, root: Path) -> Path:
        proposal = root / "proposal"
        proposal.mkdir()
        draft_name = "example-installation-v1.draft.png"
        pixels = np.zeros((21, 23), dtype=np.uint8)
        pixels[3:18, 4:20] = 255
        Image.fromarray(pixels, mode="L").save(proposal / draft_name)
        reference = np.repeat(np.arange(21 * 23, dtype=np.uint16).reshape(21, 23)[..., None], 3, axis=2)
        reference = np.uint8(reference % 251)
        Image.fromarray(reference, mode="RGB").save(proposal / "temporal_reference.png")
        Image.fromarray(reference, mode="RGB").save(proposal / "boundary_review.png")
        Image.fromarray(255 - reference, mode="RGB").save(proposal / "boundary_review_inverted.png")
        artifacts = {
            name: _sha256(proposal / name)
            for name in (
                draft_name,
                "temporal_reference.png",
                "boundary_review.png",
                "boundary_review_inverted.png",
            )
        }
        inventory = hashlib.sha256(
            json.dumps(artifacts, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        selection = {
            "status": "draft_not_approved",
            "production_eligible": False,
            "draft_id": "example-installation-v1-temporal-consensus-draft",
            "source_id": "example-source",
            "camera_id": "example-camera",
            "installation_id": "example-installation-v1",
            "orientation": "detector-native",
            "coordinate_convention": "array[y, x]; origin top-left",
            "spatial_shape": [21, 23],
            "detector_signature": {
                "spatial_shape": [21, 23],
                "channel_layout": "two_dimensional",
                "plane_names": ["L"],
                "instrument": "CAMERA-A",
                "orientation": "detector-native",
            },
            "selection": {"method": "fixture", "source_count": 3, "sources": []},
            "proposal": {"method": "fixture", "visible_pixels": int((pixels == 255).sum())},
            "generation_code_sha256": "1" * 64,
            "artifacts": artifacts,
        }
        selection["seal"] = seal_artifact_inventory(artifacts, selection)
        selection_path = proposal / "selection.json"
        selection_path.write_text(json.dumps(selection, indent=2, sort_keys=True) + "\n")
        return selection_path

    def test_approval_rejects_identity_metadata_changed_after_sealing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proposal = self._write_valid_proposal(root)
            payload = json.loads(proposal.read_text())
            draft_hash = payload["artifacts"]["example-installation-v1.draft.png"]
            payload["source_id"] = "wrong-source"
            proposal.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

            with self.assertRaisesRegex(ValueError, "metadata seal mismatch"):
                approve_proposal(
                    proposal,
                    root / "calibrations",
                    reviewed_draft_sha256=draft_hash,
                    mask_id="example-mask-v1",
                    approved_by="Peter",
                    safety_margin_pixels=1,
                )

    def test_revision_is_new_sealed_proposal_with_parent_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = self._write_valid_proposal(root)
            parent_bytes = parent.read_bytes()
            edited = root / "edited.png"
            pixels = np.asarray(Image.open(parent.parent / "example-installation-v1.draft.png")).copy()
            pixels[10, 10] = 0
            Image.fromarray(pixels, mode="L").save(edited)
            output = root / "revision"

            selection_path = revise_proposal(parent, edited, output)

            self.assertEqual(parent.read_bytes(), parent_bytes)
            self.assertEqual(selection_path, output / "selection.json")
            revised = json.loads(selection_path.read_text())
            self.assertEqual(revised["revision"]["parent_selection_sha256"], _sha256(parent))
            self.assertEqual(revised["revision"]["edited_mask_sha256"], _sha256(edited))
            self.assertEqual(
                revised["revision"]["parent_artifact_inventory"],
                json.loads(parent.read_text())["artifacts"],
            )
            self.assertEqual(revised["seal"]["status"], "sealed")
            for name, digest in revised["artifacts"].items():
                self.assertEqual(_sha256(output / name), digest)
            self.assertTrue((output / "boundary_review.png").is_file())
            self.assertTrue((output / "boundary_review_inverted.png").is_file())
            with self.assertRaises(FileExistsError):
                revise_proposal(parent, edited, output)

    def test_revision_rejects_nonbinary_and_wrong_shape_edits_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = self._write_valid_proposal(root)
            variants = {
                "non-binary": np.full((21, 23), 127, dtype=np.uint8),
                "shape": np.zeros((20, 23), dtype=np.uint8),
            }
            for name, pixels in variants.items():
                with self.subTest(name=name):
                    edited = root / f"{name}.png"
                    Image.fromarray(pixels, mode="L").save(edited)
                    output = root / f"revision-{name}"
                    with self.assertRaisesRegex(ValueError, "binary|shape"):
                        revise_proposal(parent, edited, output)
                    self.assertFalse(output.exists())

    def test_approval_writes_a_valid_immutable_production_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proposal = self._write_valid_proposal(root)
            selection = json.loads(proposal.read_text())
            draft_name = next(name for name in selection["artifacts"] if name.endswith(".draft.png"))
            draft_hash = selection["artifacts"][draft_name]

            manifest_path = approve_proposal(
                proposal,
                root / "calibrations",
                reviewed_draft_sha256=draft_hash,
                mask_id="example-mask-v1",
                approved_by="Peter",
                safety_margin_pixels=2,
            )

            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(manifest["schema"], "wide-field-solver-visible-sky-mask-v1")
            self.assertEqual(manifest["status"], "approved")
            self.assertEqual(manifest["mask_id"], "example-mask-v1")
            self.assertEqual(manifest["approval"]["approved_by"], "Peter")
            self.assertEqual(manifest["approval"]["approval_mode"], "human_review")
            self.assertEqual(manifest["review"]["selection_sha256"], _sha256(proposal))
            self.assertEqual(manifest["review"]["reviewed_draft_sha256"], draft_hash)
            self.assertEqual(_sha256(manifest_path.parent / manifest["mask_file"]), manifest["mask_sha256"])
            approved = np.asarray(Image.open(manifest_path.parent / manifest["mask_file"]))
            self.assertEqual(set(np.unique(approved)), {0, 255})

    def test_approval_rejects_wrong_hash_tampering_missing_identity_and_unsealed_draft(self):
        mutations = ("wrong-hash", "tampered", "missing-identity", "unsealed")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                proposal = self._write_valid_proposal(root)
                selection = json.loads(proposal.read_text())
                draft_name = next(name for name in selection["artifacts"] if name.endswith(".draft.png"))
                reviewed = selection["artifacts"][draft_name]
                if mutation == "wrong-hash":
                    reviewed = "f" * 64
                elif mutation == "tampered":
                    (proposal.parent / "boundary_review.png").write_bytes(b"changed")
                elif mutation == "missing-identity":
                    del selection["camera_id"]
                    proposal.write_text(json.dumps(selection, indent=2, sort_keys=True) + "\n")
                else:
                    del selection["seal"]
                    proposal.write_text(json.dumps(selection, indent=2, sort_keys=True) + "\n")

                with self.assertRaises((ValueError, FileNotFoundError)):
                    approve_proposal(
                        proposal,
                        root / "calibrations",
                        reviewed_draft_sha256=reviewed,
                        mask_id="example-mask-v1",
                        approved_by="Peter",
                        safety_margin_pixels=2,
                    )

    def test_approval_rejects_negative_margin_and_duplicate_output_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proposal = self._write_valid_proposal(root)
            selection = json.loads(proposal.read_text())
            draft_name = next(name for name in selection["artifacts"] if name.endswith(".draft.png"))
            reviewed = selection["artifacts"][draft_name]
            with self.assertRaisesRegex(ValueError, "non-negative"):
                approve_proposal(
                    proposal,
                    root / "calibrations",
                    reviewed_draft_sha256=reviewed,
                    mask_id="example-mask-v1",
                    approved_by="Peter",
                    safety_margin_pixels=-1,
                )
            approve_proposal(
                proposal,
                root / "calibrations",
                reviewed_draft_sha256=reviewed,
                mask_id="example-mask-v1",
                approved_by="Peter",
                safety_margin_pixels=2,
            )
            with self.assertRaises((FileExistsError, ValueError)):
                approve_proposal(
                    proposal,
                    root / "calibrations",
                    reviewed_draft_sha256=reviewed,
                    mask_id="example-mask-v1",
                    approved_by="Peter",
                    safety_margin_pixels=2,
                )

    def test_manual_approval_defaults_to_human_review_without_cli_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proposal = self._write_valid_proposal(root)
            selection = json.loads(proposal.read_text())
            draft_hash = selection["artifacts"]["example-installation-v1.draft.png"]
            manifest_path = approve_proposal(
                proposal,
                root / "calibrations",
                reviewed_draft_sha256=draft_hash,
                mask_id="example-mask-v1",
                approved_by="Peter",
                safety_margin_pixels=2,
            )
            approval = json.loads(manifest_path.read_text())["approval"]
            self.assertEqual(approval["approval_mode"], "human_review")
            self.assertEqual(approval["approved_by"], "Peter")
            self.assertNotIn("automatic_acceptance", approval)

    def test_automated_approval_requires_exact_content_addressed_receipt(self):
        variants = ("valid", "wrong-hash", "wrong-name", "outside")
        for variant in variants:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                proposal = self._write_valid_proposal(root)
                selection = json.loads(proposal.read_text())
                draft_hash = selection["artifacts"]["example-installation-v1.draft.png"]
                calibration_root = root / "calibrations"
                receipt_root = calibration_root / "automatic-acceptance" / "example-installation-v1"
                if variant == "outside":
                    receipt_root = root / "outside"
                receipt_root.mkdir(parents=True)
                receipt_bytes = self._automatic_acceptance_bytes(
                    proposal, safety_margin_pixels=2
                )
                digest = hashlib.sha256(receipt_bytes).hexdigest()
                receipt_name = f"{digest}.json" if variant != "wrong-name" else "receipt.json"
                receipt = receipt_root / receipt_name
                receipt.write_bytes(receipt_bytes)
                supplied_hash = "f" * 64 if variant == "wrong-hash" else digest
                call = lambda: approve_proposal(
                    proposal,
                    calibration_root,
                    reviewed_draft_sha256=draft_hash,
                    mask_id="example-mask-v1",
                    approved_by="wide-field-solver-v25-auto",
                    safety_margin_pixels=2,
                    approval_mode="automated_validation",
                    automatic_acceptance_path=receipt,
                    automatic_acceptance_sha256=supplied_hash,
                )
                if variant == "valid":
                    manifest = json.loads(call().read_text())
                    self.assertEqual(
                        manifest["approval"]["automatic_acceptance"],
                        {
                            "path": f"automatic-acceptance/example-installation-v1/{digest}.json",
                            "sha256": digest,
                        },
                    )
                else:
                    with self.assertRaisesRegex(ValueError, "acceptance|inside calibration root"):
                        call()

    def test_automated_actor_cannot_be_overridden(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proposal = self._write_valid_proposal(root)
            selection = json.loads(proposal.read_text())
            draft_hash = selection["artifacts"]["example-installation-v1.draft.png"]
            calibration_root = root / "calibrations"
            receipt_bytes = self._automatic_acceptance_bytes(
                proposal, safety_margin_pixels=2
            )
            digest = hashlib.sha256(receipt_bytes).hexdigest()
            receipt = calibration_root / "automatic-acceptance" / "example-installation-v1" / f"{digest}.json"
            receipt.parent.mkdir(parents=True)
            receipt.write_bytes(receipt_bytes)
            manifest_path = approve_proposal(
                proposal,
                calibration_root,
                reviewed_draft_sha256=draft_hash,
                mask_id="example-mask-v1",
                approved_by="Peter",
                safety_margin_pixels=2,
                approval_mode="automated_validation",
                automatic_acceptance_path=receipt,
                automatic_acceptance_sha256=digest,
            )
            approval = json.loads(manifest_path.read_text())["approval"]
            self.assertEqual(approval["approved_by"], "wide-field-solver-v25-auto")
            self.assertEqual(approval["approval_mode"], "automated_validation")

    def test_human_mode_rejects_automatic_receipt_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proposal = self._write_valid_proposal(root)
            selection = json.loads(proposal.read_text())
            draft_hash = selection["artifacts"]["example-installation-v1.draft.png"]
            receipt = root / "receipt.json"
            receipt.write_text("{}\n")
            with self.assertRaisesRegex(ValueError, "human_review.*automatic"):
                approve_proposal(
                    proposal,
                    root / "calibrations",
                    reviewed_draft_sha256=draft_hash,
                    mask_id="example-mask-v1",
                    approved_by="Peter",
                    safety_margin_pixels=2,
                    automatic_acceptance_path=receipt,
                    automatic_acceptance_sha256=_sha256(receipt),
                )


if __name__ == "__main__":
    unittest.main()
