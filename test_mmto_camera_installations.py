"""Immutable MMTO source-to-installation assignment tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from astropy.io import fits
import numpy as np
from PIL import Image

from scripts.mmto_camera_installations import assign_source, assignment_for_source


class CameraInstallationAssignmentsTests(unittest.TestCase):
    def fixture(self, root: Path):
        source = root/'image.fits'
        hdu = fits.PrimaryHDU(np.zeros((3, 20, 24), dtype=np.uint16))
        hdu.header['INSTRUME'] = 'ZWO ASI294MC Pro (21599760)'
        hdu.writeto(source)
        mask = root/'mask.png'
        Image.fromarray(np.full((20, 24), 255, dtype=np.uint8)).save(mask)
        manifest = root/'mask.json'
        manifest.write_text(json.dumps({
            'schema': 'wide-field-solver-visible-sky-mask-v1',
            'status': 'approved', 'mask_id': 'mask-a',
            'installation_id': 'installation-a',
            'instrument': 'ZWO ASI294MC Pro (21599760)',
            'detector_shape': [20, 24], 'plane_layout': 'plane_first',
            'orientation': 'detector_native_top_left_xy_right_y_down',
            'mask_file': mask.name,
            'mask_sha256': hashlib.sha256(mask.read_bytes()).hexdigest(),
        }))
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        return source, digest, manifest

    def test_assignment_is_append_only_and_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, digest, manifest = self.fixture(root)
            registry = root/'assignments.jsonl'
            first = assign_source(registry, source, digest, manifest, 'installation-a')
            second = assign_source(registry, source, digest, manifest, 'installation-a')
            self.assertEqual(first, second)
            self.assertEqual(len(registry.read_text().splitlines()), 1)
            self.assertEqual(assignment_for_source(registry, digest), first)

    def test_conflicting_reassignment_and_source_checksum_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, digest, manifest = self.fixture(root)
            registry = root/'assignments.jsonl'
            assign_source(registry, source, digest, manifest, 'installation-a')
            payload = json.loads(manifest.read_text())
            payload['installation_id'] = 'installation-b'
            other = root/'other.json'
            other.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, 'reassignment'):
                assign_source(registry, source, digest, other, 'installation-b')
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                assign_source(root/'new.jsonl', source, '0'*64, manifest, 'installation-a')


if __name__ == '__main__':
    unittest.main()
