"""Physical propagation and end-to-end epoch recovery, independent input fixtures."""
import unittest
import warnings

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time

from point_star_barghini import BarghiniCamera


def row(ra, dec, epoch=2000., pmra=0., pmdec=0., name='star'):
    return dict(star_id=name, ra_deg=str(ra), dec_deg=str(dec), mag='5',
                reference_epoch_jyear=str(epoch), pm_ra_cosdec_mas_per_year=str(pmra),
                pm_dec_mas_per_year=str(pmdec))


class CatalogueTests(unittest.TestCase):
    def catalogue(self, rows):
        import point_star_epoch
        return point_star_epoch.Catalogue.from_rows(rows)

    def test_matches_astropy_across_ra_wrap_poles_and_mixed_epochs(self):
        rows = [row(359.999, 45, 1991.25, 2300, -700),
                row(12, 89.999, 2000, -900, 300), row(90, -70, 2016, 23, 50)]
        cat = self.catalogue(rows)
        for year in (1900., 2000., 2090.):
            reference = SkyCoord(ra=[float(r['ra_deg']) for r in rows]*u.deg,
                                 dec=[float(r['dec_deg']) for r in rows]*u.deg,
                                 pm_ra_cosdec=[float(r['pm_ra_cosdec_mas_per_year']) for r in rows]*u.mas/u.yr,
                                 pm_dec=[float(r['pm_dec_mas_per_year']) for r in rows]*u.mas/u.yr,
                                 obstime=Time([float(r['reference_epoch_jyear']) for r in rows], format='jyear'))
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                expected = reference.apply_space_motion(new_obstime=Time(year, format='jyear')).data.without_differentials().to_cartesian().xyz.value.T
            np.testing.assert_allclose(cat.at_year(year), expected, atol=1e-9, rtol=0)

    def test_missing_motion_stays_available_and_is_flagged(self):
        cat = self.catalogue([row(0, 0, pmra='', pmdec=7), row(90, 0)])
        np.testing.assert_array_equal(cat.has_motion, [False, True])
        np.testing.assert_allclose(cat.at_year(2100), [[1, 0, 0], [0, 1, 0]], atol=1e-14)
        self.assertEqual(cat.subset([0]).rows[0]['star_id'], 'star')

    def test_rejects_invalid_positions_epochs_and_infinite_motion(self):
        for bad in (row('nan', 0), row(0, 91), row(0, 0, epoch=''), row(0, 0, pmra='inf')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.catalogue([bad])


def moving_field(motion_scale=1500., year=2060., noise=.0005):
    """Generate observations with Astropy, not the solver's propagation function."""
    rng = np.random.default_rng(889)
    phase = rng.uniform(-np.pi, np.pi, 80)
    radius = np.sqrt(rng.uniform(.03, 1, 80))*320
    xy = np.c_[499.5+radius*np.cos(phase), 399.5+radius*np.sin(phase)]
    camera = BarghiniCamera.initial((800, 1000), 500., np.eye(3))
    camera.p[6:] = [.012, 1.5]
    sky = camera.to_sky(xy)
    ra = np.rad2deg(np.arctan2(sky[:, 1], sky[:, 0])) % 360
    dec = np.rad2deg(np.arcsin(sky[:, 2]))
    pm = rng.normal(size=(80, 2))*motion_scale
    epochs = np.where(np.arange(80) % 3 == 0, 1991.25, 2000.)
    reference = SkyCoord(ra=ra*u.deg, dec=dec*u.deg,
                         pm_ra_cosdec=pm[:, 0]*u.mas/u.yr, pm_dec=pm[:, 1]*u.mas/u.yr,
                         obstime=Time(epochs, format='jyear'))
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        moved = reference.apply_space_motion(new_obstime=Time(year, format='jyear'))
        target = moved.data.without_differentials().to_cartesian().xyz.value.T
    measured = camera.project(target) + rng.normal(0, noise, (80, 2))
    rows = [row(a, d, e, p[0], p[1], str(i)) for i, (a, d, e, p) in enumerate(zip(ra, dec, epochs, pm))]
    initial = BarghiniCamera(camera.shape, camera.reference_rotation.copy(), camera.p.copy())
    initial.p[1:5] += .0002
    initial.p[5] += .002
    return initial, measured, rows, target


class EpochFitTests(unittest.TestCase):
    def solve(self, motion_scale=1500., year=2060., noise=.0005, fixed_year=None):
        from point_star_epoch import Catalogue, fit_epoch
        camera, xy, rows, target = moving_field(motion_scale, year, noise)
        fitted, info, epoch = fit_epoch(camera, xy, Catalogue.from_rows(rows),
                                        (1900., 2100.), fixed_year=fixed_year)
        return fitted, xy, target, info, epoch

    def test_recovers_epoch_and_camera_using_all_stars(self):
        fitted, xy, target, info, epoch = self.solve()
        self.assertTrue(info['success'])
        self.assertEqual(epoch['status'], 'conditional_epoch')
        self.assertAlmostEqual(epoch['epoch_jyear'], 2060., delta=.5)
        self.assertEqual(epoch['fitted_count'], len(xy))
        self.assertEqual(epoch['withheld_count'], 0)
        self.assertLess(np.max(np.linalg.norm(fitted.project(target)-xy, axis=1)), .003)
        low, high = epoch['conditional_interval_95_jyear']
        self.assertLess(low, 2060.)
        self.assertGreater(high, 2060.)

    def test_zero_and_weak_motion_do_not_claim_an_epoch(self):
        for motion in (0., .1):
            with self.subTest(motion=motion):
                fitted, xy, target, info, epoch = self.solve(motion_scale=motion, noise=.03)
                self.assertEqual(epoch['status'], 'not_identifiable')
                self.assertIsNone(epoch['epoch_jyear'])
                self.assertEqual(epoch['applied_epoch_jyear'], 2000. if motion == 0 else epoch['best_epoch_jyear'])
                self.assertEqual(epoch['withheld_count'], 0)

    def test_boundary_minimum_is_unresolved(self):
        *_, epoch = self.solve(year=2250.)
        self.assertEqual(epoch['status'], 'not_identifiable')
        self.assertTrue(epoch['boundary_limited'])
        self.assertEqual(epoch['applied_epoch_jyear'], epoch['best_epoch_jyear'])
        self.assertTrue(epoch['provisional'])
        import json
        self.assertEqual(json.loads(json.dumps(epoch))['boundary_limited'], True)

    def test_fixed_epoch_propagates_without_claiming_a_measured_date(self):
        fitted, xy, target, info, epoch = self.solve(fixed_year=2060.)
        self.assertEqual(epoch['status'], 'supplied_epoch')
        self.assertEqual(epoch['applied_epoch_jyear'], 2060.)
        self.assertEqual(epoch['profile'], [])
        self.assertLess(np.max(np.linalg.norm(fitted.project(target)-xy, axis=1)), .003)

    def test_epoch_just_inside_search_boundary_is_refined(self):
        *_, epoch = self.solve(year=1901.)
        self.assertEqual(epoch['status'], 'conditional_epoch')
        self.assertAlmostEqual(epoch['epoch_jyear'], 1901., delta=.5)
