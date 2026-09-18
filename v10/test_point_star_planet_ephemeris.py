"""Reference ephemerides remain independent of measured images and metadata."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings

import numpy as np

import point_star_planet_ephemeris as ephemeris


class PlanetVectorsTests(unittest.TestCase):
    def test_j2000_apparent_directions_and_scalar_shape(self):
        # Frozen Astropy 7.2 builtin, geocentric apparent GCRS, JD 2451545 TDB.
        # Catches changed origin, frame, time scale, normalization and body mapping.
        expected = {
            'mercury': [0.033011867090003, -0.909938040553874, -0.413428323877560],
            'venus': [-0.475793081418516, -0.820642708726298, -0.316490897639470],
            'mars': [0.847600550998594, -0.479136161821497, -0.228039129058687],
            'jupiter': [0.904238576382822, 0.400021119080345, 0.149451334122100],
            'saturn': [0.760735763404051, 0.611205911469871, 0.218422599706027],
            'uranus': [0.704734635061023, -0.646268124053745, -0.292722745917464],
            'neptune': [0.547513440138185, -0.769368206613259, -0.329092077572142],
            # JPL Horizons small-body solutions, geocentric ICRF LT+S vectors.
            'ceres': [-0.975773730483936, -0.151377607599360, 0.157957104351018],
            'vesta': [-0.406006906628003, -0.865188052993544, -0.294292413642624],
        }
        self.assertEqual(set(ephemeris.PLANETS), set(expected))
        for name, direction in expected.items():
            actual = ephemeris.planet_vectors(name, 2451545.)
            self.assertEqual(actual.shape, (1, 3))
            tolerance = 1e-9 if name in ('ceres', 'vesta') else 1e-11
            np.testing.assert_allclose(actual[0], direction, rtol=0, atol=tolerance)

    def test_boundary_vectors_finite_without_network_or_epoch_warnings(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                for name in ephemeris.PLANETS:
                    last = 2464694.0 if name in ('ceres', 'vesta') else 2506332.5
                    values = ephemeris.planet_vectors(name, [2396757.5, last])
                    self.assertEqual(values.shape, (2, 3))
                    self.assertTrue(np.isfinite(values).all())
                    np.testing.assert_allclose(np.linalg.norm(values, axis=1), 1., atol=1e-14)
            self.assertEqual(caught, [])

    def test_minor_planets_use_versioned_local_horizons_reference(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
            for name in ('ceres', 'vesta'):
                values = ephemeris.planet_vectors(name, [2451545.125, 2451545.5, 2451545.875])
                self.assertEqual(values.shape, (3, 3))
                np.testing.assert_allclose(np.linalg.norm(values, axis=1), 1., atol=1e-13)
        _, vectors, provenance = ephemeris.load_ephemeris()
        self.assertIn('ceres', vectors)
        self.assertIn('vesta', vectors)
        self.assertEqual(provenance['minor_planets']['authority'], 'JPL Horizons')
        self.assertEqual(provenance['minor_planets']['observer'], 'Earth geocenter')

    def test_minor_planet_cubic_interpolation_matches_withheld_horizons_epochs(self):
        dates = np.array([2397000.125, 2451545.375, 2464000.875])
        expected = {
            'ceres': [[.9526115163592906, .24495580849273405, -.18035506864328513],
                      [-.9755618588539445, -.15284556843194058, .15785211991022954],
                      [.6726459607298048, -.6289366653438887, -.3898539245666092]],
            'vesta': [[-.9744515585730985, .16081688751388307, .15678676182894474],
                      [-.40290633390301095, -.866432691948373, -.2948912959446772],
                      [.9862489992276384, .16030451247573016, -.040191725546436755]],
        }
        for name, authoritative in expected.items():
            interpolated = ephemeris.planet_vectors(name, dates)
            chord = np.linalg.norm(interpolated-np.asarray(authoritative), axis=1)
            arcsec = 2*np.arcsin(np.clip(chord/2, 0, 1))*206264.80624709636
            self.assertLess(float(arcsec.max()), .002)

    def test_bad_name_nonfinite_and_nonvector_times_rejected(self):
        for name, times in [('pluto', [2451545.]), ('mars', [np.nan]),
                            ('mars', [np.inf]), ('mars', [[2451545.]])]:
            with self.subTest(name=name, times=times), self.assertRaises(ValueError):
                ephemeris.planet_vectors(name, times)
        self.assertEqual(ephemeris.planet_vectors('mars', []).shape, (0, 3))

    def test_daily_chords_are_coarse_but_close_to_exact_subday_positions(self):
        for name in ephemeris.PLANETS:
            jd = 2451545. + np.arange(30.)
            ends = ephemeris.planet_vectors(name, jd)
            midpoint = ends[:-1] + ends[1:]
            midpoint /= np.linalg.norm(midpoint, axis=1)[:, None]
            exact = ephemeris.planet_vectors(name, jd[:-1] + .5)
            arcsec = np.linalg.norm(midpoint - exact, axis=1) * 206264.806
            self.assertLess(float(arcsec.max()), 15.)


    def test_mercury_multidecade_curvature_requires_a_wider_coarse_guard(self):
        # Separate from the unchanged J2000 15-arcsecond regression: Mercury
        # accelerates enough that a 30-arcsecond guard is not safe everywhere.
        jd = 2451545. + (np.arange(1850., 2036., 10.) - 2000.) * 365.25
        midpoint = (ephemeris.planet_vectors('mercury', jd)
                    + ephemeris.planet_vectors('mercury', jd + 1.))
        midpoint /= np.linalg.norm(midpoint, axis=1)[:, None]
        exact = ephemeris.planet_vectors('mercury', jd + .5)
        arcsec = np.linalg.norm(midpoint - exact, axis=1) * 206264.806
        self.assertGreater(float(arcsec.max()), 30.)
        self.assertLess(float(arcsec.max()), 120.)


class EphemerisCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = Path(self.directory.name)
        self.start = 2000.
        self.end = 2000. + 2.5 / 365.25

    def load(self):
        return ephemeris.load_ephemeris(self.start, self.end, cache_dir=self.cache)

    def test_default_reference_is_shipped_and_never_generated_at_runtime(self):
        with patch.object(ephemeris, 'planet_vectors',
                          side_effect=AssertionError('shipped reference was regenerated')):
            jd, vectors, provenance = ephemeris.load_ephemeris()
        self.assertEqual(provenance['cache_source'], 'bundled')
        self.assertEqual(Path(provenance['cache_path']), ephemeris.BUNDLED_REFERENCE)
        self.assertEqual(provenance['start_jyear'], 1850.)
        self.assertEqual(provenance['end_jyear'], 2036.)
        self.assertEqual(len(vectors), len(ephemeris.PLANETS))
        self.assertEqual(jd.shape, (67938,))

    def test_daily_grid_includes_fractional_endpoint_and_cache_is_reused(self):
        jd, vectors, provenance = self.load()
        np.testing.assert_allclose(jd, [2451545., 2451546., 2451547., 2451547.5], atol=1e-9, rtol=0)
        self.assertEqual(provenance['frame'], 'geocentric apparent GCRS')
        self.assertEqual(provenance['time_scale'], 'tdb')
        self.assertTrue(provenance['limitations'])
        self.assertEqual(provenance['cache_source'], 'generated')
        self.assertGreaterEqual(provenance['cache_build_seconds'], 0.)
        self.assertGreater(provenance['cache_bytes'], 0)
        with patch.object(ephemeris, 'planet_vectors', side_effect=AssertionError('cache not reused')):
            cached_jd, cached_vectors, cached_provenance = self.load()
        np.testing.assert_array_equal(cached_jd, jd)
        for name in ephemeris.PLANETS:
            np.testing.assert_array_equal(cached_vectors[name], vectors[name])
        self.assertEqual(cached_provenance['content_sha256'], provenance['content_sha256'])
        self.assertEqual(cached_provenance['cache_source'], 'writable_cache')
        self.assertEqual(cached_provenance['cache_build_seconds'], 0.)

    def test_cache_metadata_timestamps_and_vectors_are_validated(self):
        expected_jd, expected_vectors, _ = self.load()
        filename, = self.cache.glob('*.npz')
        with np.load(filename, allow_pickle=False) as source:
            pristine = {key: source[key].copy() for key in source.files}
        cases = ['schema_version', 'astropy_version', 'start_jyear', 'timestamp',
                 'nonfinite', 'wrong_shape', 'finite_corruption']
        for case in cases:
            with self.subTest(case=case):
                arrays = {key: value.copy() for key, value in pristine.items()}
                if case in ('schema_version', 'astropy_version', 'start_jyear'):
                    metadata = json.loads(str(arrays['provenance']))
                    metadata[case] = 'incorrect'
                    arrays['provenance'] = np.asarray(json.dumps(metadata))
                elif case == 'timestamp':
                    arrays['jd_tdb'][1] += .1
                elif case == 'nonfinite':
                    arrays['mars'][0, 0] = np.nan
                elif case == 'wrong_shape':
                    arrays['mars'] = arrays['mars'][:-1]
                else:
                    arrays['mars'][0] *= -1  # Still finite/unit; checksum must catch it.
                np.savez(filename, **arrays)
                actual_jd, actual_vectors, _ = self.load()
                np.testing.assert_array_equal(actual_jd, expected_jd)
                np.testing.assert_array_equal(actual_vectors['mars'], expected_vectors['mars'])

    def test_truncated_cache_rebuilt_and_invalid_ranges_rejected(self):
        expected, _, _ = self.load()
        filename, = self.cache.glob('*.npz')
        filename.write_bytes(b'broken zip')
        actual, _, _ = self.load()
        np.testing.assert_array_equal(actual, expected)
        for start, end in [(2001, 2000), (2000, 2000), (1800, 2000),
                           (2035, 2037), (2000, 2200), (np.nan, 2000)]:
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                ephemeris.load_ephemeris(start, end, cache_dir=self.cache)

    def test_valid_bundle_is_preferred_without_exact_generation(self):
        expected_jd, expected_vectors, _ = self.load()
        bundle, = self.cache.glob('*.npz')
        with tempfile.TemporaryDirectory() as writable:
            with patch.object(ephemeris, 'planet_vectors',
                              side_effect=AssertionError('valid bundle was regenerated')):
                jd, vectors, provenance = ephemeris.load_ephemeris(
                    self.start, self.end, cache_dir=writable, bundled_path=bundle)
        np.testing.assert_array_equal(jd, expected_jd)
        np.testing.assert_array_equal(vectors['mercury'], expected_vectors['mercury'])
        self.assertEqual(provenance['cache_source'], 'bundled')
        self.assertEqual(Path(provenance['cache_path']), bundle)
        self.assertEqual(provenance['cache_build_seconds'], 0.)

    def test_corrupt_explicit_bundle_is_rejected_not_silently_rebuilt(self):
        broken = self.cache/'broken.npz'
        broken.write_bytes(b'not an ephemeris')
        with tempfile.TemporaryDirectory() as writable:
            with self.assertRaisesRegex(ValueError, 'bundled ephemeris'):
                ephemeris.load_ephemeris(self.start, self.end,
                                         cache_dir=writable, bundled_path=broken)

    def test_builder_cli_verifies_valid_content_and_rejects_corruption(self):
        _, _, provenance = self.load()
        bundle, = self.cache.glob('*.npz')
        script = Path(__file__).resolve().parent/'scripts/build_planet_ephemeris_cache.py'
        valid = subprocess.run([sys.executable, str(script), '--verify', str(bundle)],
                               capture_output=True, text=True)
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertIn(provenance['content_sha256'], valid.stdout)
        bundle.write_bytes(b'broken')
        invalid = subprocess.run([sys.executable, str(script), '--verify', str(bundle)],
                                 capture_output=True, text=True)
        self.assertEqual(invalid.returncode, 2)
        self.assertIn('invalid', invalid.stderr.lower())


class EphemerisProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jd = 2451545. + np.arange(32.)
        cls.vectors = {name: ephemeris.planet_vectors(name, cls.jd)
                       for name in ephemeris.PLANETS}

    def test_interpolated_and_exact_paths_have_separate_counters(self):
        calls = []
        def exact(name, dates):
            calls.append((name, np.asarray(dates).copy()))
            return ephemeris.planet_vectors(name, dates)
        provider = ephemeris.EphemerisProvider(self.jd, self.vectors,
                                               exact_function=exact)
        dates = self.jd[5:15] + .37
        estimated = provider.interpolated('mercury', dates)
        authoritative = provider.exact('mercury', dates)
        self.assertEqual(estimated.shape, (10, 3))
        self.assertEqual(authoritative.shape, (10, 3))
        np.testing.assert_allclose(np.linalg.norm(estimated, axis=1), 1., atol=1e-14)
        self.assertEqual(provider.counts(), {
            'interpolated_calls': 1, 'interpolated_dates': 10,
            'exact_calls': 1, 'exact_dates': 10,
        })
        self.assertEqual(calls[0][0], 'mercury')
        np.testing.assert_array_equal(calls[0][1], dates)

    def test_cubic_proposals_stay_inside_five_arcsecond_guard(self):
        dates = self.jd[2:-3] + np.resize([.125, .25, .5, .75, .875], len(self.jd[2:-3]))
        provider = ephemeris.EphemerisProvider(self.jd, self.vectors)
        for name in ephemeris.PLANETS:
            approximate = provider.interpolated(name, dates)
            exact = ephemeris.planet_vectors(name, dates)
            chord = np.linalg.norm(approximate-exact, axis=1)
            arcsec = 2*np.arcsin(np.clip(chord/2, 0, 1))*206264.80624709636
            self.assertLess(float(arcsec.max()), ephemeris.INTERPOLATION_GUARD_ARCSEC)

    def test_cubic_guard_holds_across_shipped_interval_for_every_planet(self):
        jd, vectors, _ = ephemeris.load_ephemeris()
        provider = ephemeris.EphemerisProvider(jd, vectors)
        # Deterministic coverage of every decade and three phases of a day.
        years = np.arange(1850., 2037., 10.)
        dates = np.concatenate([
            np.clip(2451545. + (years-2000.)*365.25 + phase,
                    jd[1], jd[-2]) for phase in (.125, .5, .875)])
        for name in ephemeris.PLANETS:
            approximate = provider.interpolated(name, dates)
            exact = ephemeris.planet_vectors(name, dates)
            chord = np.linalg.norm(approximate-exact, axis=1)
            arcsec = 2*np.arcsin(np.clip(chord/2, 0, 1))*206264.80624709636
            self.assertLess(float(arcsec.max()), ephemeris.INTERPOLATION_GUARD_ARCSEC)

    def test_grid_endpoints_are_returned_exactly(self):
        provider = ephemeris.EphemerisProvider(self.jd, self.vectors)
        for name in ephemeris.PLANETS:
            dates = self.jd[[0, 7, -1]]
            np.testing.assert_array_equal(provider.interpolated(name, dates),
                                          self.vectors[name][[0, 7, -1]])

    def test_interpolation_rejects_unknown_planet_bad_and_out_of_range_dates(self):
        provider = ephemeris.EphemerisProvider(self.jd, self.vectors)
        for name, dates in [('pluto', [self.jd[5]]), ('mars', [np.nan]),
                            ('mars', [self.jd[0]-.1]), ('mars', [self.jd[-1]+.1])]:
            with self.subTest(name=name, dates=dates), self.assertRaises(ValueError):
                provider.interpolated(name, dates)


if __name__ == '__main__':
    unittest.main()
