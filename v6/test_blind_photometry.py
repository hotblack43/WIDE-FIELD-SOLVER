"""No metadata is allowed to determine the blind photometric airmasses."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from astropy.io import fits
from PIL import Image

from point_star_barghini import BarghiniCamera
from point_star_science import measure_photometry, fit_planet_epoch
from point_star_image import load_scientific_image


class BlindPhotometryTests(unittest.TestCase):
    def test_four_plane_fits_keeps_g1_g2_and_uses_their_mean_for_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'dots').mkdir()
            planes = np.full((4, 400, 400), 10, dtype=np.uint16)
            x = y = 200
            planes[:, y-1:y+2, x-1:x+2] = np.array([100, 200, 400, 800])[:, None, None]
            source = root/'stack.fits'
            fits.PrimaryHDU(planes).writeto(source)
            loaded = load_scientific_image(source, saturation_level=4095)
            (root/'dots/input_image.json').write_text(json.dumps(loaded.provenance()))
            camera = BarghiniCamera.initial((400, 400), 130, np.eye(3))
            coordinate = dict(detection_id='1', star_id='1', x_px=x, y_px=y,
                              magnitude=5., residual_px=.1)
            detection = dict(detection_id='1', saturated='False', saturation_known='True',
                             saturated_channels='', source_class='compact', major_sigma_px=1.)
            for path, rows in ((root/'star_coordinates.csv', [coordinate]),
                               (root/'dots/star_candidates.csv', [detection])):
                with path.open('w') as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                    writer.writeheader(); writer.writerows(rows)
            unresolved = dict(status='not_identifiable', zenith_unit_vector=None,
                              reason='Too few sources', fitted_count=1)
            with patch('point_star_zenith.fit_photometric_zenith', return_value=unresolved):
                measure_photometry(source, root, {'camera': camera.serialise()}, {})
            with (root/'stellar_photometry.csv').open() as handle:
                row = next(csv.DictReader(handle))
        self.assertAlmostEqual(float(row['G1_flux']), 9*(200-10))
        self.assertAlmostEqual(float(row['G2_flux']), 9*(400-10))
        self.assertAlmostEqual(float(row['G_flux']),
                               (float(row['G1_flux'])+float(row['G2_flux']))/2.)
        self.assertEqual(row['saturation_known'], 'True')
        self.assertIn('G1_saturated', row)

    def test_photometry_does_not_read_site_or_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'warwick_20260101T000000Z.png'
            image = np.full((400, 400, 3), 10, dtype=np.uint8)
            # An equidistant 180-degree fisheye has its 90-degree horizon at
            # radius pi/2 * scale: this mask is a physical horizon, not a vignette.
            camera = BarghiniCamera.initial((400, 400), 195/(np.pi/2), np.eye(3))
            coordinates, detections = [], []
            for i, (x, y) in enumerate(( (x,y) for x in range(80, 321, 48) for y in range(80, 321, 48))):
                image[y-1:y+2, x-1:x+2] = 50+i
                sky = camera.to_sky(np.array([[x, y]]))[0]
                ra,dec=np.rad2deg(np.arctan2(sky[1],sky[0]))%360,np.rad2deg(np.arcsin(sky[2]))
                coordinates.append(dict(detection_id=str(i),star_id=str(i),x_px=x,y_px=y,
                                        magnitude=5.,catalog_ra_deg=ra,catalog_dec_deg=dec,residual_px=.1))
                detections.append(dict(detection_id=str(i),saturated='False',source_class='compact',major_sigma_px=1.))
            Image.fromarray(image).save(source)
            for output in ('one','two'):
                destination=root/output; (destination/'dots').mkdir(parents=True)
                yy, xx = np.mgrid[:400, :400]
                np.savez_compressed(destination/'dots/sky_footprint.npz',
                                    valid_mask=(xx-199.5)**2+(yy-199.5)**2 <= 195**2)
                for path,rows in ((destination/'star_coordinates.csv',coordinates),
                                  (destination/'dots/star_candidates.csv',detections)):
                    with path.open('w') as handle:
                        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
            result=dict(source=str(source),camera=camera.serialise())
            poisoned=dict(result,observation=dict(time_utc='not-a-date',latitude_deg=999,longitude_deg=-999))
            (root/'manifest.jsonl').write_text(json.dumps(dict(filename=source.name,feed='warwick',captured_at='not-a-date'))+'\n')
            with patch('point_star_science.observation_metadata',side_effect=AssertionError('Metadata used in blind fit')):
                first=measure_photometry(source,root/'one',result,{})
                second=measure_photometry(source,root/'two',poisoned,{})
            self.assertEqual(first['photometric_zenith'],second['photometric_zenith'])
            self.assertEqual(first['airmass_source'],'blind_centred_full_horizon_geometry')
            self.assertFalse(first['metadata_used'])
            zenith = first['photometric_zenith']
            self.assertEqual(zenith['zenith_source'], 'centred_full_horizon_geometry')
            np.testing.assert_allclose(
                zenith['zenith_unit_vector'], camera.to_sky(np.array([[199.5, 199.5]]))[0],
                atol=1e-12)
            green = first['extinction_by_channel']['G']
            self.assertEqual(green['coefficient_mag_per_airmass'], zenith['extinction_mag_per_airmass'])
            self.assertEqual(green['intercept_mag'], zenith['intercept_mag'])
            self.assertEqual(green['fitted_count'], len(zenith['fitted_detection_ids']))
            self.assertEqual(green['fit_role'], 'adopted_geometric_zenith_diagnostic')
            self.assertEqual((root/'one/stellar_photometry.csv').read_text(),(root/'two/stellar_photometry.csv').read_text())

    def test_round_vignette_inside_a_narrower_camera_is_not_called_a_horizon(self):
        from point_star_science import _full_horizon_geometric_zenith
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'dots').mkdir()
            yy, xx = np.mgrid[:400, :400]
            np.savez_compressed(root/'dots/sky_footprint.npz',
                                valid_mask=(xx-199.5)**2+(yy-199.5)**2 <= 195**2)
            camera = BarghiniCamera.initial((400, 400), 210, np.eye(3))
            vector, evidence = _full_horizon_geometric_zenith(root, camera)
            self.assertIsNone(vector)
            self.assertEqual(evidence['status'], 'not_established')
            self.assertIn('90 degrees', evidence['reason'])

    def test_unsaturated_identified_sources_enter_fixed_sample_with_explicit_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'dots').mkdir()
            image = np.full((400, 400, 3), 10, dtype=np.uint8)
            camera = BarghiniCamera.initial((400, 400), 130, np.eye(3))
            coordinates, detections = [], []
            for i, (x, y) in enumerate([(25, 200), (375, 200), (200, 25), (200, 375), (200, 200)]):
                if i != 4:
                    image[y-1:y+2, x-1:x+2] = 90
                coordinates.append(dict(detection_id=str(i), star_id=str(i), x_px=x, y_px=y,
                                        magnitude=5., residual_px=3.))
                detections.append(dict(detection_id=str(i), saturated='True' if i == 0 else 'False',
                                       source_class='broad', major_sigma_px=1.))
            Image.fromarray(image).save(root/'source.png')
            for path, rows in ((root/'star_coordinates.csv', coordinates),
                               (root/'dots/star_candidates.csv', detections)):
                with path.open('w') as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                    writer.writeheader(); writer.writerows(rows)
            unresolved = dict(status='not_identifiable', zenith_unit_vector=None,
                              reason='Too few sources for this fixture', fitted_count=3)
            with patch('point_star_zenith.fit_photometric_zenith', return_value=unresolved) as fit:
                answer = measure_photometry(root/'source.png', root, {'camera': camera.serialise()}, {})
            self.assertEqual(len(fit.call_args.args[0]), 3)
            self.assertEqual(answer['photometric_zenith']['fitted_detection_ids'], ['1', '2', '3'])
            with (root/'stellar_photometry.csv').open() as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 5)
            self.assertEqual(rows[0]['saturated'], 'True')
            self.assertEqual(rows[0]['photometric_zenith_exclusion_reason'], 'saturated')
            self.assertEqual(rows[0]['photometry_usable'], 'False')
            self.assertEqual(rows[0]['G_used_for_extinction'], 'False')
            self.assertTrue(np.isnan(float(rows[0]['G_mag'])))
            self.assertEqual(rows[1]['photometry_usable'], 'True')
            with (root/'star_coordinates.csv').open() as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 5)
            self.assertEqual(rows[4]['photometric_zenith_exclusion_reason'], 'nonpositive_or_nonfinite_G_flux')

    def test_default_planet_path_cannot_use_a_metadata_search_centre(self):
        with tempfile.TemporaryDirectory() as tmp:
            expected = {'status': 'planet_epoch_ambiguous', 'metadata_used': False}
            with patch('point_star_science.observation_metadata', side_effect=AssertionError('Metadata used')), \
                 patch('point_star_planets.fit_blind_planet_epoch', return_value=expected) as search:
                result = fit_planet_epoch('unused', tmp, {'observation': {'time_utc': 'poison'}}, {'epoch_jyear': 2100})
            self.assertEqual(result, expected)
            self.assertEqual(len(search.call_args.args), 3)

    def test_blind_report_hides_metadata_until_explicit_reveal(self):
        from point_star_report import observation_metadata
        result=dict(blind=True, source='/unused/warwick_20260101T000000Z.png',
                    observation=dict(time_utc='2026-01-01',latitude_deg=28.,longitude_deg=-17.))
        self.assertEqual(observation_metadata(result),{})
        revealed=observation_metadata(result,reveal=True)
        self.assertEqual(revealed['latitude'],28.)
        self.assertEqual(revealed['observation_time'],'2026-01-01')

    def test_post_fit_latitude_comparison_does_not_change_the_fit(self):
        from copy import deepcopy
        from point_star_science import compare_metadata
        result=dict(blind=True,source='/unused/photo.png',coordinate_epoch_jyear=2000.,
                    stellar_epoch=dict(status='conditional_epoch',epoch_jyear=2000.),
                    observation=dict(time_utc='2020-01-01',latitude_deg=30.,longitude_deg=0.))
        science=dict(photometry=dict(photometric_zenith=dict(status='conditional_zenith',
                    zenith_unit_vector=[np.sqrt(3)/2,0,.5])))
        original=deepcopy(result)
        comparison=compare_metadata(result,science)
        self.assertAlmostEqual(comparison['derived_latitude_deg'],30.,delta=.001)
        self.assertAlmostEqual(comparison['stellar_epoch_minus_metadata_years'],-20.,delta=.01)
        self.assertEqual(result,original)
        self.assertFalse(comparison['used_in_fit'])
