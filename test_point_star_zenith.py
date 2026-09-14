"""Known photometric zenith and failure cases without location or date inputs."""
import unittest
import numpy as np


def photometric_field(extinction=.23, noise=.015, vignette=0.):
    rng = np.random.default_rng(3307)
    n = np.array([.16, -.12, 1.]); n /= np.linalg.norm(n)
    east = np.cross([0, 1, 0], n); east /= np.linalg.norm(east)
    north = np.cross(n, east)
    altitude = rng.uniform(20, 80, 240)
    azimuth = rng.uniform(-np.pi, np.pi, 240)
    rays = (np.sin(np.deg2rad(altitude))[:, None]*n +
            np.cos(np.deg2rad(altitude))[:, None]*(np.cos(azimuth)[:, None]*east + np.sin(azimuth)[:, None]*north))
    z = 90-altitude
    x = 1/(np.cos(np.deg2rad(z))+.50572*(96.07995-z)**-1.6364)
    radial = np.arccos(rays[:, 2])**2
    dimming = -9.4+extinction*x+vignette*radial+rng.normal(0, noise, len(x))
    return rays, dimming, radial, n


class ZenithTests(unittest.TestCase):
    def test_recovers_tilted_zenith_and_unknown_regression(self):
        from point_star_zenith import fit_photometric_zenith
        rays, dimming, radial, truth = photometric_field()
        answer = fit_photometric_zenith(rays, dimming, radial)
        self.assertEqual(answer['status'], 'conditional_zenith')
        estimated = np.array(answer['zenith_unit_vector'])
        self.assertLess(np.rad2deg(np.arccos(np.clip(estimated@truth, -1, 1))), 1.)
        self.assertAlmostEqual(answer['extinction_mag_per_airmass'], .23, delta=.025)
        self.assertEqual(answer['fitted_count'], len(rays))
        self.assertFalse(answer['metadata_used'])
        self.assertEqual(answer['withheld_count'], 0)

    def test_no_extinction_does_not_establish_zenith(self):
        from point_star_zenith import fit_photometric_zenith
        rays, dimming, radial, _ = photometric_field(extinction=0.)
        answer = fit_photometric_zenith(rays, dimming, radial)
        self.assertEqual(answer['status'], 'not_identifiable')

    def test_vignetting_alone_is_not_claimed_as_atmospheric_zenith(self):
        from point_star_zenith import fit_photometric_zenith
        rays, dimming, radial, _ = photometric_field(extinction=0., vignette=.5)
        answer = fit_photometric_zenith(rays, dimming, radial)
        self.assertEqual(answer['status'], 'not_identifiable')

    def test_insufficient_sources_return_unresolved_without_guessing(self):
        from point_star_zenith import fit_photometric_zenith
        rays, dimming, radial, _ = photometric_field()
        answer = fit_photometric_zenith(rays[:8], dimming[:8], radial[:8])
        self.assertEqual(answer['status'], 'not_identifiable')
        self.assertIsNone(answer['zenith_unit_vector'])

    def test_many_stars_with_no_spatial_coverage_are_unresolved(self):
        from point_star_zenith import fit_photometric_zenith
        rng=np.random.default_rng(91)
        rays=np.tile([0.,0.,1.],(80,1))
        result=fit_photometric_zenith(rays,rng.normal(-9,.01,80),np.zeros(80))
        self.assertEqual(result['status'],'not_identifiable')

    def test_nearly_collinear_sky_coverage_cannot_claim_precise_zenith(self):
        from point_star_zenith import fit_photometric_zenith
        rng=np.random.default_rng(123)
        alt=rng.uniform(20,80,100); az=np.deg2rad(rng.uniform(-.00001,.00001,100))
        z=np.deg2rad(90-alt)
        rays=np.c_[np.sin(z)*np.cos(az),np.sin(z)*np.sin(az),np.cos(z)]
        x=1/(np.cos(z)+.50572*(96.07995-(90-alt))**-1.6364)
        result=fit_photometric_zenith(rays,-9+.23*x+rng.normal(0,1e-5,100),z*z)
        self.assertEqual(result['status'],'not_identifiable')

    def test_best_fit_at_artificial_search_bound_is_unresolved(self):
        from point_star_zenith import fit_photometric_zenith
        rng=np.random.default_rng(123)
        alt=rng.uniform(12,20,100); az=np.deg2rad(rng.uniform(-15,15,100))
        z=np.deg2rad(90-alt)
        rays=np.c_[np.sin(z)*np.cos(az),np.sin(z)*np.sin(az),np.cos(z)]
        x=1/(np.cos(z)+.50572*(96.07995-(90-alt))**-1.6364)
        result=fit_photometric_zenith(rays,-9+.23*x+rng.normal(0,.0001,100),z*z)
        self.assertEqual(result['status'],'not_identifiable')

    def test_profile_and_result_can_be_saved(self):
        import json,tempfile
        from pathlib import Path
        from point_star_zenith import fit_photometric_zenith,write_zenith_products
        rays,dimming,radial,_=photometric_field()
        result=fit_photometric_zenith(rays,dimming,radial)
        with tempfile.TemporaryDirectory() as tmp:
            write_zenith_products(tmp,result)
            loaded=json.loads((Path(tmp)/'photometric_zenith.json').read_text())
            self.assertEqual(loaded['status'],'conditional_zenith')
            self.assertTrue((Path(tmp)/'photometric_zenith_profile.png').is_file())
