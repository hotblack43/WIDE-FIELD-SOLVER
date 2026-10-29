from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np


PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT / "tests/fixtures/openorb"


class OpenOrbParserTests(unittest.TestCase):
    def test_official_ranging_cartesian_samples_and_source_lines(self) -> None:
        from find_planet_openorb.openorb_parse import parse_ranging

        rows = parse_ranging(FIXTURES / "official-ranging.orb")
        self.assertEqual(len(rows), 20)
        self.assertEqual(rows[0].element_type, "cartesian")
        self.assertEqual(rows[0].epoch_mjd_tt, 54617.0)
        self.assertEqual(rows[0].line_number, 5)
        self.assertEqual(len(rows[0].source_sha256), 64)

    def test_lsl_has_full_symmetric_covariance_and_support_gate(self) -> None:
        from find_planet_openorb.openorb_parse import covariance_support, parse_lsl

        orbit = parse_lsl(FIXTURES / "official-lsl.orb")[0]
        covariance = np.asarray(orbit.covariance)
        self.assertEqual(orbit.element_type, "cartesian")
        self.assertEqual(covariance.shape, (6, 6))
        self.assertTrue(np.allclose(covariance, covariance.T))
        self.assertTrue(covariance_support(covariance).supported)
        self.assertEqual(covariance_support(np.zeros((6, 6))).reason, "not_positive_definite")
        self.assertEqual(covariance_support(np.diag([1e-20, 1, 1, 1, 1, 1])).reason, "ill_conditioned")

    def test_ephemeris_wrap_units_and_residual_signs(self) -> None:
        from find_planet_openorb.openorb_parse import parse_ephemeris, parse_residuals

        rows = parse_ephemeris(FIXTURES / "official-ephemeris.eph")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].observatory_code, "568")
        self.assertTrue(0.0 <= rows[0].ra_deg < 360.0)
        residuals = parse_residuals(FIXTURES / "residuals.ls")
        self.assertEqual((residuals[0].ra_residual_arcsec, residuals[0].dec_residual_arcsec), (-0.125, 0.25))
        self.assertEqual((residuals[1].ra_residual_arcsec, residuals[1].dec_residual_arcsec), (0.375, -0.5))

    def test_keplerian_header_and_changed_or_nonfinite_rows_are_rejected(self) -> None:
        from find_planet_openorb.openorb_parse import parse_ephemeris, parse_lsl, parse_ranging

        source = (FIXTURES / "official-lsl.orb").read_text()
        keplerian = source.replace("Ecliptic x", "Semimajor axis a", 1)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kep = root / "kep.orb"; kep.write_text(keplerian)
            self.assertEqual(parse_lsl(kep)[0].element_type, "keplerian")
            truncated = root / "truncated.orb"; truncated.write_text("\n".join(source.splitlines()[:4]) + "\n")
            with self.assertRaises(ValueError): parse_lsl(truncated)
            bad = root / "bad.orb"; bad.write_text((FIXTURES / "official-ranging.orb").read_text().replace("-0.60298241283824E+00", "nan", 1))
            with self.assertRaises(ValueError): parse_ranging(bad)
            changed = root / "changed.eph"; changed.write_text("# unknown format\n1 2 3\n")
            with self.assertRaises(ValueError): parse_ephemeris(changed)


if __name__ == "__main__":
    unittest.main()
