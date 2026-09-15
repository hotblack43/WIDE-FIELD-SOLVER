"""Reference ephemerides remain independent of measured images and metadata."""
import json
from pathlib import Path
import socket
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
        }
        self.assertEqual(set(ephemeris.PLANETS), set(expected))
        for name, direction in expected.items():
            actual = ephemeris.planet_vectors(name, 2451545.)
            self.assertEqual(actual.shape, (1, 3))
            np.testing.assert_allclose(actual[0], direction, rtol=0, atol=1e-11)

    def test_boundary_vectors_finite_without_network_or_epoch_warnings(self):
        with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                for name in ephemeris.PLANETS:
                    values = ephemeris.planet_vectors(name, [2396757.5, 2506332.5])
                    self.assertEqual(values.shape, (2, 3))
                    self.assertTrue(np.isfinite(values).all())
                    np.testing.assert_allclose(np.linalg.norm(values, axis=1), 1., atol=1e-14)
            self.assertEqual(caught, [])

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
        jd = 2451545. + (np.arange(1850., 2150., 10.) - 2000.) * 365.25
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

    def test_daily_grid_includes_fractional_endpoint_and_cache_is_reused(self):
        jd, vectors, provenance = self.load()
        np.testing.assert_allclose(jd, [2451545., 2451546., 2451547., 2451547.5], atol=1e-9, rtol=0)
        self.assertEqual(provenance['frame'], 'geocentric apparent GCRS')
        self.assertEqual(provenance['time_scale'], 'tdb')
        self.assertTrue(provenance['limitations'])
        with patch.object(ephemeris, 'planet_vectors', side_effect=AssertionError('cache not reused')):
            cached_jd, cached_vectors, cached_provenance = self.load()
        np.testing.assert_array_equal(cached_jd, jd)
        for name in ephemeris.PLANETS:
            np.testing.assert_array_equal(cached_vectors[name], vectors[name])
        self.assertEqual(cached_provenance['content_sha256'], provenance['content_sha256'])

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
                           (2000, 2200), (np.nan, 2000)]:
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                ephemeris.load_ephemeris(start, end, cache_dir=self.cache)


if __name__ == '__main__':
    unittest.main()
