"""Sun and Moon horizon state prune planet proposals before exact refinement."""
from __future__ import annotations

import unittest

import numpy as np


def ray(altitude_deg):
    altitude = np.deg2rad(float(altitude_deg))
    return np.array([np.cos(altitude), 0.0, np.sin(altitude)])


def moon_above(date, zenith):
    return {"jd_tdb": float(date), "unit_vector": ray(30.0).tolist()}


def moon_below(date, zenith):
    return {"jd_tdb": float(date), "unit_vector": ray(-30.0).tolist()}


class CelestialHorizonGateTests(unittest.TestCase):
    def solar(self, altitude_deg):
        from point_star_planet_solar import SolarConstraint, zenith_envelope

        stars = np.array([ray(3.0) @ np.array([
            [np.cos(a), -np.sin(a), 0.0],
            [np.sin(a), np.cos(a), 0.0],
            [0.0, 0.0, 1.0],
        ]) for a in np.deg2rad(np.arange(0, 360, 45))])
        return SolarConstraint(
            {"status": "night_supported"}, zenith_envelope(stars),
            zenith_unit_vector=[0.0, 0.0, 1.0],
            sun_function=lambda dates: np.tile(ray(altitude_deg),
                                                (len(np.atleast_1d(dates)), 1)),
        )

    def gate(self, *, sun_altitude=-30.0, moon_present=False,
             moon_prediction=moon_above):
        from point_star_celestial_gate import CelestialHorizonGate

        return CelestialHorizonGate(
            solar_constraint=self.solar(sun_altitude),
            zenith_unit_vector=[0.0, 0.0, 1.0],
            observed_moon_present=moon_present,
            moon_prediction_function=moon_prediction,
        )

    def test_requires_night_and_matching_binary_moon_horizon_state(self):
        self.assertTrue(self.gate(moon_present=True).assess(2451545.0)["eligible"])
        self.assertFalse(self.gate(sun_altitude=30.0, moon_present=True)
                         .assess(2451545.0)["eligible"])
        self.assertFalse(self.gate(moon_present=True, moon_prediction=moon_below)
                         .assess(2451545.0)["eligible"])
        self.assertFalse(self.gate(moon_present=False, moon_prediction=moon_above)
                         .assess(2451545.0)["eligible"])
        self.assertTrue(self.gate(moon_present=False, moon_prediction=moon_below)
                        .assess(2451545.0)["eligible"])

    def test_moon_phase_does_not_enter_the_binary_horizon_gate(self):
        def thin_crescent(date, zenith):
            return {"jd_tdb": float(date), "unit_vector": ray(30.0).tolist(),
                    "illumination_fraction": 0.001}

        evidence = self.gate(
            moon_present=False, moon_prediction=thin_crescent).assess(2451545.0)
        self.assertFalse(evidence["eligible"])
        self.assertNotIn("illumination_fraction", evidence["lunar"])

    def test_solar_rejection_must_cover_the_whole_positional_interval(self):
        class IntervalAwareSolar:
            def assess(self, date, interval=None):
                return {"status": ("solar_unresolved" if interval is not None
                                   else "solar_inconsistent")}

        from point_star_celestial_gate import CelestialHorizonGate
        gate = CelestialHorizonGate(
            solar_constraint=IntervalAwareSolar(),
            zenith_unit_vector=[0.0, 0.0, 1.0],
            observed_moon_present=True,
            moon_prediction_function=moon_above,
        )
        evidence = gate.assess(2451545.0, (2451544.5, 2451545.5))
        self.assertTrue(evidence["eligible"])
        self.assertEqual(evidence["solar"]["status"], "solar_unresolved")


class EarlyRefinementGateTests(unittest.TestCase):
    def test_surviving_passage_retains_its_own_visit_bracket(self):
        from point_star_barghini import BarghiniCamera
        from point_star_planet_ephemeris import EphemerisProvider, planet_vectors
        from point_star_planet_refinement import (
            RefinementContext, Visit, refine_planet_visits,
        )

        jd = 2451545.0 + np.arange(10.0)
        camera = BarghiniCamera.initial((300, 400), 180.0, np.eye(3))
        targets = (jd[2] + 0.2, jd[6] + 0.2)
        xy = np.array([
            camera.project(planet_vectors("mercury", [target]))[0]
            for target in targets
        ])
        visits = tuple(
            Visit("mercury", source, target - 0.7, target + 0.7,
                  target - 0.7, target + 0.7)
            for source, target in enumerate(targets)
        )

        class KeepSecondVisit:
            def assess(self, date, positional_interval=None):
                eligible = positional_interval[0] > jd[4]
                return {
                    "eligible": eligible,
                    "solar": {
                        "status": ("solar_compatible" if eligible
                                   else "solar_inconsistent"),
                        "reason": "literal test decision",
                    },
                    "lunar": {
                        "status": "moon_horizon_compatible",
                        "selection_effect": "neutral",
                    },
                    "metadata_used": False,
                }

        provider = EphemerisProvider(
            jd, {"mercury": planet_vectors("mercury", jd)},
            exact_function=planet_vectors,
        )
        result = refine_planet_visits(
            "mercury", visits,
            RefinementContext(camera, xy, np.array([0.0, 0.0, 1.0]),
                              celestial_gate=KeepSecondVisit()),
            provider,
        )

        self.assertEqual(result.rejected_by_celestial_gate, 1)
        self.assertEqual(result.retained_visits, (visits[1],))
        self.assertEqual([passage.source for passage in result.passages], [1])
        self.assertEqual(len(result.gate_rejections), 1)
        rejection = result.gate_rejections[0]
        self.assertEqual(rejection.name, "mercury")
        self.assertEqual(rejection.source, 0)
        self.assertEqual(rejection.refinement_interval, (visits[0].start,
                                                         visits[0].stop))
        self.assertEqual(rejection.positional_interval,
                         (visits[0].visit_start, visits[0].visit_stop))
        self.assertEqual(rejection.assessment["solar"]["status"],
                         "solar_inconsistent")

    def test_incompatible_proposal_never_reaches_exact_planet_ephemeris(self):
        from point_star_barghini import BarghiniCamera
        from point_star_celestial_gate import CelestialHorizonGate
        from point_star_planet_refinement import (
            RefinementContext, Visit, refine_planet_visits,
        )
        from test_point_star_planet_refinement import RecordingProvider

        camera = BarghiniCamera.initial((300, 400), 180.0, np.eye(3))
        solar = self._solar_below()
        gate = CelestialHorizonGate(
            solar_constraint=solar,
            zenith_unit_vector=[0.0, 0.0, 1.0],
            observed_moon_present=False,
            moon_prediction_function=moon_above,
        )
        provider = RecordingProvider()
        result = refine_planet_visits(
            "mercury", [Visit("mercury", 0, 0.0, 1.0, 0.0, 1.0)],
            RefinementContext(
                camera, np.array([[150.0, 130.0]]), np.array([0.0, 0.0, 1.0]),
                celestial_gate=gate,
            ),
            provider,
        )

        self.assertEqual(result.passages, [])
        self.assertEqual(result.rejected_by_celestial_gate, 1)
        self.assertEqual(provider.counts()["exact_dates"], 0)
        self.assertGreater(provider.counts()["interpolated_dates"], 0)

    def test_blind_search_passes_combined_gate_to_visit_refinement(self):
        from point_star_barghini import BarghiniCamera
        from point_star_celestial_gate import CelestialHorizonGate
        from point_star_planets import search_planet_epochs

        camera = BarghiniCamera.initial((300, 400), 180.0, np.eye(3))
        dates = 2451545.0 + np.arange(10.0)

        def planets(name, values):
            values = np.atleast_1d(values)
            return camera.to_sky(np.c_[
                150.0 + 4.0 * (values - dates[4]),
                np.full(len(values), 130.0),
            ])

        gate = CelestialHorizonGate(
            solar_constraint=self._solar_below(),
            zenith_unit_vector=[0.0, 0.0, 1.0],
            observed_moon_present=False,
            moon_prediction_function=moon_above,
        )
        answer = search_planet_epochs(
            camera,
            [{"detection_id": 1, "x_px": 150.0, "y_px": 130.0}],
            dates,
            {"mars": planets("mars", dates)},
            planets,
            gate_arcmin=40.0,
            zenith_unit_vector=[0.0, 0.0, 1.0],
            latest_jd_tdb=dates[-1],
            planet_workers=1,
            celestial_gate=gate,
        )

        self.assertGreater(answer["planet_search_performance"]["counts"]
                           ["celestial_gate_rejected_visits"], 0)
        self.assertEqual(answer["planet_search_performance"]["counts"]
                         ["celestial_gate_solar_rejected_visits"], 0)
        self.assertGreater(answer["planet_search_performance"]["counts"]
                           ["celestial_gate_lunar_rejected_visits"], 0)
        self.assertEqual(answer["planet_search_performance"]["providers"]
                         ["exact_dates"], 0)
        self.assertEqual(answer["source_candidates"], [])
        self.assertGreater(len(answer["celestial_gate_rejections"]), 0)
        rejection = answer["celestial_gate_rejections"][0]
        self.assertEqual(rejection["planet"], "Mars")
        self.assertEqual(rejection["detection_id"], 1)
        self.assertIn("proposal_jd_tdb", rejection)
        self.assertIn("refinement_interval_jd_tdb", rejection)
        self.assertIn("positional_interval_jd_tdb", rejection)
        self.assertEqual(rejection["solar"]["status"], "solar_consistent")
        self.assertEqual(rejection["lunar"]["status"],
                         "moon_horizon_contradiction")

    @staticmethod
    def _solar_below():
        from point_star_planet_solar import SolarConstraint, zenith_envelope

        stars = np.array([
            [np.cos(np.deg2rad(3.0)) * np.cos(a),
             np.cos(np.deg2rad(3.0)) * np.sin(a),
             np.sin(np.deg2rad(3.0))]
            for a in np.deg2rad(np.arange(0, 360, 45))
        ])
        return SolarConstraint(
            {"status": "night_supported"}, zenith_envelope(stars),
            zenith_unit_vector=[0.0, 0.0, 1.0],
            sun_function=lambda dates: np.tile(ray(-30.0),
                                                (len(np.atleast_1d(dates)), 1)),
        )


if __name__ == "__main__":
    unittest.main()
