import math
import unittest

from point_star_photometric_evidence import (
    matched_planet_evidence,
    measurement_evidence,
)


def row(**changes):
    answer = {
        "detection_id": "7",
        "G_count_rate_adu_per_s": "100",
        "G_saturated": "false",
        "G_measurement_method": "aperture",
        "G_photometry_usable": "true",
        "G_photometry_exclusion_reason": "",
        "G_wing_fit_status": "not_needed",
        "G_wing_fit_count_rate_adu_per_s": "nan",
    }
    answer.update(changes)
    return answer


class MeasurementEvidenceTests(unittest.TestCase):
    def test_unsaturated_aperture_is_a_direct_estimate(self):
        evidence = measurement_evidence(row())
        self.assertEqual(evidence["status"], "available")
        self.assertEqual(evidence["kind"], "direct_aperture")
        self.assertEqual(evidence["relation"], "estimate")
        self.assertEqual(evidence["count_rate_adu_per_s"], 100.0)

    def test_accepted_wing_fit_is_used_for_a_saturated_source(self):
        evidence = measurement_evidence(row(
            G_saturated="true",
            G_measurement_method="saturated_aperture_lower_bound",
            G_wing_fit_status="modelled_from_unsaturated_wings",
            G_wing_fit_count_rate_adu_per_s="250",
        ))
        self.assertEqual(evidence["kind"], "psf_wing_model")
        self.assertEqual(evidence["relation"], "estimate")
        self.assertEqual(evidence["count_rate_adu_per_s"], 250.0)

    def test_rejected_wing_fit_keeps_the_clipped_aperture_as_a_lower_bound(self):
        evidence = measurement_evidence(row(
            G_saturated="true",
            G_measurement_method="saturated_aperture_lower_bound",
            G_wing_fit_status="wing_fit_quality_rejected",
        ))
        self.assertEqual(evidence["kind"], "saturated_aperture_lower_bound")
        self.assertEqual(evidence["relation"], "flux_lower_bound")
        self.assertEqual(evidence["count_rate_adu_per_s"], 100.0)

    def test_unavailable_measurement_is_recorded_with_its_reason(self):
        evidence = measurement_evidence(row(
            G_photometry_usable="false",
            G_photometry_exclusion_reason="visible_sky_mask",
        ))
        self.assertEqual(evidence["status"], "unavailable")
        self.assertEqual(evidence["reason"], "visible_sky_mask")
        self.assertNotIn("cost", evidence)


class MatchedPlanetEvidenceTests(unittest.TestCase):
    calibration = {
        "intercept_mag": 0.0,
        "extinction_mag_per_airmass": 0.0,
        "radial_coefficient_mag": 0.0,
        "rms_mag": 0.0,
    }

    def test_direct_estimate_has_symmetric_residual(self):
        evidence = matched_planet_evidence(
            planet="Venus", predicted_v_mag=-4.0,
            altitude_deg=45.0, radial_squared=0.0,
            photometry=row(), calibration=self.calibration,
        )
        self.assertEqual(evidence["status"], "available")
        self.assertAlmostEqual(evidence["measured_instrumental_mag"], -5.0)
        self.assertAlmostEqual(evidence["magnitude_residual"], 1.0)
        self.assertGreater(evidence["cost"], 0.0)

    def test_lower_bound_is_one_sided_in_magnitude(self):
        saturated = row(
            G_saturated="true",
            G_measurement_method="saturated_aperture_lower_bound",
            G_wing_fit_status="wing_fit_quality_rejected",
        )
        compatible = matched_planet_evidence(
            planet="Venus", predicted_v_mag=-6.0,
            altitude_deg=45.0, radial_squared=0.0,
            photometry=saturated, calibration=self.calibration,
        )
        too_faint = matched_planet_evidence(
            planet="Venus", predicted_v_mag=-4.0,
            altitude_deg=45.0, radial_squared=0.0,
            photometry=saturated, calibration=self.calibration,
        )
        self.assertEqual(compatible["magnitude_residual"], 0.0)
        self.assertEqual(compatible["cost"], 0.0)
        self.assertAlmostEqual(too_faint["magnitude_residual"], 1.0)
        self.assertGreater(too_faint["cost"], 0.0)

    def test_nonfinite_or_below_horizon_geometry_is_unavailable(self):
        evidence = matched_planet_evidence(
            planet="Venus", predicted_v_mag=-4.0,
            altitude_deg=-1.0, radial_squared=0.0,
            photometry=row(), calibration=self.calibration,
        )
        self.assertEqual(evidence["status"], "unavailable")
        self.assertEqual(evidence["reason"], "invalid_photometric_geometry")
        self.assertTrue(math.isfinite(evidence["predicted_v_mag"]))

    def test_unsupported_magnitude_is_json_safe_unavailable_evidence(self):
        evidence = matched_planet_evidence(
            planet="Uranus", predicted_v_mag=float("nan"),
            altitude_deg=45.0, radial_squared=0.0,
            photometry=row(), calibration=self.calibration,
        )
        self.assertEqual(evidence["status"], "unavailable")
        self.assertEqual(evidence["reason"], "photometric_calibration_unavailable")
        self.assertIsNone(evidence["predicted_v_mag"])


if __name__ == "__main__":
    unittest.main()
