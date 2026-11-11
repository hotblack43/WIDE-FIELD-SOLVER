"""The Moon corroborates planet dates without becoming a point-source fit."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from point_star_barghini import BarghiniCamera


def _ray(altitude_deg, azimuth_deg=0.0):
    altitude = np.deg2rad(altitude_deg)
    azimuth = np.deg2rad(azimuth_deg)
    return np.array([
        np.cos(altitude) * np.cos(azimuth),
        np.cos(altitude) * np.sin(azimuth),
        np.sin(altitude),
    ])


class LunarPredictionTests(unittest.TestCase):
    def test_image_zenith_recovers_observer_and_topocentric_parallax(self):
        from astropy import units as u
        from astropy.coordinates import AltAz, EarthLocation, ICRS, SkyCoord, get_body
        from astropy.time import Time
        from point_star_lunar import predict_topocentric_moon

        time = Time("2024-01-01T00:00:00", scale="utc")
        location = EarthLocation.from_geodetic(-110 * u.deg, 32 * u.deg, 0 * u.m)
        zenith = SkyCoord(
            alt=90 * u.deg,
            az=0 * u.deg,
            frame=AltAz(obstime=time, location=location, pressure=0 * u.hPa),
        ).transform_to(ICRS()).cartesian.xyz.value

        prediction = predict_topocentric_moon(time.tdb.jd, zenith)
        expected = get_body("moon", time, location=location, ephemeris="builtin")
        expected_vector = expected.cartesian.xyz.value
        expected_vector /= np.linalg.norm(expected_vector)

        self.assertAlmostEqual(prediction["observer_longitude_deg"], -110.0, delta=0.01)
        self.assertAlmostEqual(prediction["observer_latitude_deg"], 32.0, delta=0.01)
        separation = np.rad2deg(np.arccos(np.clip(
            np.dot(prediction["unit_vector"], expected_vector), -1.0, 1.0
        )))
        self.assertLess(separation, 1e-5)
        geocentric = get_body("moon", time, location=None, ephemeris="builtin")
        geocentric_vector = geocentric.cartesian.xyz.value
        geocentric_vector /= np.linalg.norm(geocentric_vector)
        parallax = np.rad2deg(np.arccos(np.clip(
            np.dot(prediction["unit_vector"], geocentric_vector), -1.0, 1.0
        )))
        self.assertGreater(parallax, 0.2)
        self.assertGreater(prediction["illumination_fraction"], 0.0)
        self.assertLess(prediction["illumination_fraction"], 1.0)
        self.assertGreater(prediction["angular_diameter_deg"], 0.45)
        self.assertLess(prediction["angular_diameter_deg"], 0.60)
        self.assertFalse(prediction["metadata_used"])

    def test_offline_prediction_accepts_future_dates_in_supported_interval(self):
        from astropy.time import Time
        from point_star_lunar import predict_topocentric_moon

        for value in ("2026-09-19T02:20:01", "2036-01-01T00:00:00"):
            with self.subTest(value=value):
                prediction = predict_topocentric_moon(
                    Time(value, scale="utc").tdb.jd, [0.0, 0.0, 1.0]
                )
                self.assertTrue(np.isfinite(prediction["unit_vector"]).all())
                self.assertFalse(prediction["metadata_used"])


class LunarBlobClassificationTests(unittest.TestCase):
    def test_requires_both_moon_size_and_high_luminance(self):
        from point_star_lunar import identify_moon_candidates

        camera = BarghiniCamera.initial((1000, 1000), 180.0, np.eye(3))
        detections = [
            {
                "detection_id": 1, "x_px": 500.0, "y_px": 500.0,
                "saturated": True, "source_class": "compact", "area_px": 1,
                "major_sigma_px": 0.3, "axis_ratio": 1.1,
            },
            {
                "detection_id": 2, "x_px": 600.0, "y_px": 500.0,
                "saturated": False, "source_class": "broad_blob", "area_px": 80,
                "major_sigma_px": 3.5, "axis_ratio": 1.25,
                "peak_snr": 10.0,
            },
            {
                "detection_id": 3, "x_px": 600.0, "y_px": 500.0,
                "saturated": False, "source_class": "broad_blob", "area_px": 80,
                "major_sigma_px": 3.5, "axis_ratio": 1.25,
                "peak_snr": 40.0,
            },
        ]

        candidates = identify_moon_candidates(
            camera, detections, [], camera.to_sky([[500.0, 500.0]])[0],
            valid_mask=np.ones(camera.shape, dtype=bool),
        )

        self.assertEqual([row["detection_id"] for row in candidates], [3])
        self.assertGreaterEqual(candidates[0]["minor_angular_diameter_deg"], 0.5)


class LunarEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.camera = BarghiniCamera.initial((240, 320), 180.0, np.eye(3))
        rng = np.random.default_rng(25)
        self.pixels = rng.normal(100, 2, self.camera.shape)
        self.stars = []
        self.detections = []
        yy, xx = np.indices(self.pixels.shape)
        for index, (x, y) in enumerate(
            [(135, 100), (160, 85), (185, 100), (185, 140), (160, 155), (135, 140)],
            1,
        ):
            self.pixels += 60 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 0.9**2))
            self.detections.append({
                "detection_id": index,
                "x_px": x,
                "y_px": y,
                "saturated": False,
                "source_class": "compact",
                "peak_above_background": 60.0,
                "peak_snr": 30.0,
                "major_sigma_px": 0.9,
            })
            self.stars.append({
                "detection_id": index,
                "x_px": x,
                "y_px": y,
                "magnitude": 5.0,
                "residual_px": 0.2,
            })
        self.predicted_point = np.array([160.0, 120.0])
        self.predicted_vector = self.camera.to_sky([self.predicted_point])[0]
        self.zenith = self.predicted_vector.copy()

    def answer(self):
        candidates = []
        for index in range(2):
            candidates.append({
                "jd_tdb": 2459000.0 + index,
                "epoch_tdb": f"date {index}",
                "matches": [
                    {"planet": "Mercury", "detection_id": index + 1},
                    {"planet": "Saturn", "detection_id": index + 3},
                ],
                "match_count": 2,
                "cost_arcmin2": 0.01 + 0.01 * index,
                "cost_px2": 0.01 + 0.01 * index,
                "rms_arcmin": 0.1 + 0.01 * index,
                "rms_px": 0.1 + 0.01 * index,
                "conditional_time_sigma_minutes": 2.0,
                "boundary_limited": False,
                "solar_evidence": {
                    "status": "solar_consistent",
                    "requires_date_refinement": False,
                },
            })
        return {
            "status": "planet_epoch_ambiguous",
            "candidates": candidates,
            "matches": copy.deepcopy(candidates[0]["matches"]),
            "best_candidate_jd_tdb": 2459000.0,
            "best_candidate_epoch_tdb": "date 0",
            "visibility": {
                "zenith_unit_vector": self.zenith.tolist(),
                "zenith_status": "conditional_zenith",
                "zenith_source": "photometric_extinction",
            },
            "positional_sigma_arcmin": 0.5,
        }

    def prediction(self, date, zenith):
        return {
            "jd_tdb": float(date),
            "unit_vector": self.predicted_vector.tolist(),
            "illumination_fraction": 0.75,
            "angular_diameter_deg": 0.5,
            "observer_longitude_deg": -110.0,
            "observer_latitude_deg": 32.0,
            "metadata_used": False,
        }

    def annotate(self, *, pixels=None, detections=None, stars=None, valid_mask=None,
                 prediction_function=None):
        from point_star_lunar import annotate_lunar_evidence
        return annotate_lunar_evidence(
            self.answer(),
            self.camera,
            self.pixels if pixels is None else pixels,
            self.detections if detections is None else detections,
            self.stars if stars is None else stars,
            valid_mask=valid_mask,
            prediction_function=prediction_function or self.prediction,
        )

    def test_unidentified_broad_saturated_source_supports_candidate(self):
        detections = self.detections + [{
            "detection_id": 99,
            "x_px": 220.0,
            "y_px": 120.0,
            "saturated": True,
            "source_class": "broad_blob",
            "area_px": 100,
            "peak_above_background": 1000.0,
            "peak_snr": 200.0,
            "major_sigma_px": 5.0,
            "axis_ratio": 1.2,
        }]
        after = self.annotate(detections=detections)
        row = after["candidates"][0]["lunar_evidence"]
        self.assertEqual(row["status"], "lunar_signal_present")
        self.assertEqual(row["detection_id"], 99)
        self.assertEqual(row["selection_effect"], "support")

    def test_observed_luminous_blob_rejects_date_with_moon_below_horizon(self):
        detections = self.detections + [{
            "detection_id": 99,
            "x_px": 220.0,
            "y_px": 120.0,
            "saturated": True,
            "source_class": "broad_blob",
            "area_px": 100,
            "peak_above_background": 1000.0,
            "peak_snr": 200.0,
            "major_sigma_px": 5.0,
            "axis_ratio": 1.2,
        }]

        def below(date, zenith):
            row = self.prediction(date, zenith)
            row["unit_vector"] = _ray(-30.0).tolist()
            return row

        row = self.annotate(
            detections=detections, prediction_function=below
        )["candidates"][0]["lunar_evidence"]
        self.assertEqual(row["status"], "observed_moon_not_predicted")
        self.assertEqual(row["selection_effect"], "contradict")

    def test_catalogue_star_at_prediction_does_not_excuse_a_missing_moon(self):
        detections = self.detections + [{
            "detection_id": 99,
            "x_px": 160.0,
            "y_px": 120.0,
            "saturated": True,
            "source_class": "broad_blob",
            "area_px": 100,
            "peak_above_background": 1000.0,
            "peak_snr": 200.0,
            "major_sigma_px": 5.0,
            "axis_ratio": 1.2,
        }]
        stars = self.stars + [{
            "detection_id": 99,
            "x_px": 160.0,
            "y_px": 120.0,
            "magnitude": 0.0,
            "residual_px": 0.2,
        }]
        row = self.annotate(detections=detections, stars=stars)["candidates"][0]["lunar_evidence"]
        self.assertEqual(row["status"], "missing_expected_moon")
        self.assertEqual(row["selection_effect"], "contradict")

    def test_clear_locally_supported_blank_rejects_candidate(self):
        after = self.annotate(detections=[], stars=[])
        row = after["candidates"][0]["lunar_evidence"]
        self.assertEqual(row["status"], "missing_expected_moon")
        self.assertEqual(row["selection_effect"], "contradict")

    def test_only_the_five_degree_horizon_guard_blocks_absence(self):
        cases = []

        def low_phase(date, zenith):
            row = self.prediction(date, zenith)
            row["illumination_fraction"] = 0.05
            return row
        cases.append(("missing_expected_moon",
                      dict(prediction_function=low_phase), "contradict"))

        def horizon(date, zenith):
            row = self.prediction(date, zenith)
            row["unit_vector"] = _ray(2.0).tolist()
            return row
        cases.append(("inconclusive_near_horizon",
                      dict(prediction_function=horizon), "neutral"))

        mask = np.ones(self.camera.shape, dtype=bool)
        mask[118:123, 158:163] = False
        cases.append(("missing_expected_moon", dict(valid_mask=mask), "contradict"))

        signal = self.pixels.copy()
        yy, xx = np.indices(signal.shape)
        signal += 70 * np.exp(-((xx - 160) ** 2 + (yy - 120) ** 2) / (2 * 0.9**2))
        cases.append(("missing_expected_moon", dict(pixels=signal), "contradict"))

        for expected, options, effect in cases:
            with self.subTest(expected=expected):
                row = self.annotate(**options)["candidates"][0]["lunar_evidence"]
                self.assertEqual(row["status"], expected)
                self.assertEqual(row["selection_effect"], effect)

    def test_lunar_contradiction_reranks_but_does_not_claim_ambiguous_date(self):
        from point_star_planet_nondetections import apply_evidence

        annotated = self.annotate()
        annotated["candidates"][1]["lunar_evidence"] = {
            "status": "lunar_signal_present",
            "selection_effect": "support",
        }
        after = apply_evidence(annotated, [[], []])
        self.assertEqual(after["candidates"][0]["jd_tdb"], 2459001.0)
        self.assertEqual(after["status"], "planet_epoch_ambiguous")
        self.assertEqual(after["best_candidate_jd_tdb"], 2459001.0)

    def test_writes_audit_without_candidate_carpet_figure(self):
        from PIL import Image
        from point_star_lunar import write_lunar_evidence

        answer = self.annotate()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            image = output / "image.png"
            Image.fromarray(np.uint8(np.clip(self.pixels, 0, 255))).save(image)
            write_lunar_evidence(image, output, answer)
            self.assertTrue((output / "lunar_evidence.json").is_file())
            self.assertFalse((output / "lunar_evidence.png").exists())


class LunarPipelineTests(unittest.TestCase):
    def test_planet_pipeline_exports_lunar_evidence_without_refitting_camera(self):
        import csv
        import json
        from PIL import Image
        from point_star_planets import fit_blind_planet_epoch

        camera = BarghiniCamera.initial((400, 400), 180.0, np.eye(3))
        origin = 2451545.0
        dates = origin + np.arange(4.0)

        def planets(name, trial_dates):
            offset = np.atleast_1d(trial_dates) - origin - 1.5
            points = (
                np.c_[150 + 5 * offset, np.full(len(offset), 150.0)]
                if name == "venus"
                else np.c_[np.full(len(offset), 250.0), 250 + 5 * offset]
            )
            return camera.to_sky(points)

        grid = {name: planets(name, dates) for name in ("venus", "saturn")}
        sources = [
            {"detection_id": index + 1, "x_px": x, "y_px": y, "saturated": False}
            for index, (x, y) in enumerate([(150, 150), (250, 250)])
        ]
        stellar_points = camera.project(np.array([
            _ray(3.0, azimuth) for azimuth in range(0, 360, 45)
        ]))
        stars = []
        for index, (x, y) in enumerate(stellar_points, 3):
            sources.append({
                "detection_id": index,
                "x_px": x,
                "y_px": y,
                "saturated": False,
                "source_class": "compact",
                "peak_above_background": 60.0,
                "peak_snr": 30.0,
                "major_sigma_px": 0.9,
            })
            stars.append({
                "detection_id": index,
                "star_id": str(index),
                "residual_px": 0.0,
                "x_px": x,
                "y_px": y,
                "magnitude": 5.0,
            })
        for source in sources[:2]:
            source.update(
                source_class="compact",
                peak_above_background=60.0,
                peak_snr=30.0,
                major_sigma_px=0.9,
            )

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            (output / "dots").mkdir()
            for name, rows in (
                ("dots/star_candidates.csv", sources),
                ("star_coordinates.csv", stars),
            ):
                with (output / name).open("w", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0])
                    writer.writeheader()
                    writer.writerows(rows)
            (output / "photometric_zenith.json").write_text(json.dumps({
                "status": "not_identifiable",
                "zenith_source": "photometric_extinction",
                "zenith_unit_vector": [0.0, 0.0, 1.0],
                "fitted_detection_ids": [str(row["detection_id"]) for row in stars],
            }))
            image = output / "image.png"
            Image.new("L", (400, 400), 100).save(image)
            result = {
                "status": "point_star_fit_converged",
                "fit": {"count": 8, "rms_px": 0.5},
                "camera": camera.serialise(),
                "causal_epoch_ceiling": {"jd_tdb": origin + 10},
            }
            original = copy.deepcopy(result)
            with patch(
                "point_star_planet_ephemeris.load_ephemeris",
                return_value=(dates, grid, {}),
            ), patch(
                "point_star_planet_ephemeris.planet_vectors", side_effect=planets
            ), patch(
                "point_star_planet_ephemeris.sun_vectors",
                side_effect=lambda values: np.tile(_ray(-30.0), (len(values), 1)),
            ):
                answer = fit_blind_planet_epoch(image, output, result)

            self.assertEqual(result, original)
            self.assertTrue(answer["celestial_horizon_gate"]
                            ["applied_before_exact_planet_refinement"])
            self.assertEqual(answer["celestial_horizon_gate"]["moon_blob_count"], 0)
            self.assertTrue(answer["candidates"])
            self.assertTrue(all("lunar_evidence" in row for row in answer["candidates"]))
            self.assertFalse(answer["lunar_evidence"]["metadata_used"])
            self.assertFalse(answer["lunar_evidence"]["enters_camera_fit"])
            self.assertTrue((output / "lunar_evidence.json").is_file())
            self.assertFalse((output / "lunar_evidence.png").exists())
            with (output / "planet_candidates.csv").open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertTrue(rows)
            self.assertTrue(all(row["lunar_status"] for row in rows))


if __name__ == "__main__":
    unittest.main()
