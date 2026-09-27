"""Planet light curves use authoritative identities, UTC times and count rates."""
from contextlib import closing
import bz2
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import numpy as np
from PIL import ExifTags, Image
from PIL.PngImagePlugin import PngInfo
from astropy.io import fits

from scripts.plot_planet_photometry import load_planet_measurements


TEST_CATALOGUE_SHA = "c" * 64


def write_nightly_sidecar(
    directory,
    *,
    source_sha256="a" * 64,
    catalogue_sha256=TEST_CATALOGUE_SHA,
    night="2026-09-19",
    channel="G",
    extinction=0.2,
    scaled_mad=0.03,
    zero_point=-6.0,
    zero_uncertainty=0.04,
    duplicate_zero_point=False,
):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "nightly_extinction_coefficients.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "night", "channel", "catalogue_sha256", "model", "status",
                "extinction_mag_per_airmass", "scaled_mad_mag_per_airmass",
                "minimum_mag_per_airmass", "maximum_mag_per_airmass",
                "accepted_image_count",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "night": night,
            "channel": channel,
            "catalogue_sha256": catalogue_sha256,
            "model": "reference_theil_sen",
            "status": "accepted",
            "extinction_mag_per_airmass": extinction,
            "scaled_mad_mag_per_airmass": scaled_mad,
            "minimum_mag_per_airmass": extinction - 0.02,
            "maximum_mag_per_airmass": extinction + 0.02,
            "accepted_image_count": 10,
        })
    with (directory / "image_zero_points.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        fields = [
            "night", "channel", "observed_utc", "source_sha256",
            "catalogue_sha256", "model", "status", "zero_point_magnitude",
            "uncertainty_magnitude", "rms_magnitude", "star_count",
            "extinction_mag_per_airmass",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        record = {
            "night": night,
            "channel": channel,
            "observed_utc": "2026-09-20T01:00:00+00:00",
            "source_sha256": source_sha256,
            "catalogue_sha256": catalogue_sha256,
            "model": "reference_theil_sen",
            "status": "accepted",
            "zero_point_magnitude": zero_point,
            "uncertainty_magnitude": zero_uncertainty,
            "rms_magnitude": 0.1,
            "star_count": 40,
            "extinction_mag_per_airmass": extinction,
        }
        writer.writerow(record)
        if duplicate_zero_point:
            writer.writerow(record)


class PlanetPhotometryModuleTests(unittest.TestCase):
    def test_module_exposes_readonly_loader(self):
        spec = importlib.util.find_spec("scripts.plot_planet_photometry")
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(module.load_planet_measurements))

    def test_inverse_square_distance_correction_has_the_right_sign(self):
        import scripts.plot_planet_photometry as planet_plot

        correct = getattr(planet_plot, "_distance_corrected_magnitude", None)
        self.assertTrue(callable(correct))
        if not callable(correct):
            return
        corrected = correct(10.0, 2.0, 3.0)
        self.assertAlmostEqual(corrected, 6.109243748081781, places=12)

    def test_stellar_calibration_uses_saved_offset_extinction_and_distance_signs(self):
        import scripts.plot_planet_photometry as planet_plot

        calibrate = getattr(
            planet_plot, "_stellar_calibrated_distance_magnitude", None
        )
        airmass = getattr(planet_plot, "_kasten_young_airmass", None)
        self.assertTrue(callable(calibrate))
        self.assertTrue(callable(airmass))
        if not callable(calibrate) or not callable(airmass):
            return

        self.assertAlmostEqual(
            calibrate(-5.0, -10.0, 0.0, 45.0, 1.0, 1.0),
            5.0,
            places=12,
        )
        expected = 5.0 - 0.25 * airmass(30.0) - 5.0 * np.log10(2.0 * 3.0)
        self.assertAlmostEqual(
            calibrate(-5.0, -10.0, 0.25, 30.0, 2.0, 3.0),
            expected,
            places=12,
        )

    def test_stellar_calibration_rejects_invalid_airmass_geometry(self):
        import scripts.plot_planet_photometry as planet_plot

        calibrate = getattr(
            planet_plot, "_stellar_calibrated_distance_magnitude", None
        )
        self.assertTrue(callable(calibrate))
        if not callable(calibrate):
            return

        self.assertIsNone(calibrate(-5.0, -10.0, 0.2, -0.01, 1.0, 1.0))
        self.assertIsNone(calibrate(-5.0, -10.0, 0.2, 90.01, 1.0, 1.0))

    def test_background_uncertainty_uses_aperture_and_median_annulus_noise(self):
        import scripts.plot_planet_photometry as planet_plot

        estimate = getattr(planet_plot, "_background_only_aperture_uncertainty", None)
        self.assertTrue(callable(estimate))
        if not callable(estimate):
            return
        pixels = np.full((25, 25), 10.0)
        yy, xx = np.mgrid[:25, :25]
        radius = np.hypot(xx - 12.0, yy - 12.0)
        annulus = (radius >= 5.0) & (radius <= 9.0)
        annulus_indices = np.flatnonzero(annulus)
        pixels.flat[annulus_indices[:92]] = 9.0
        pixels.flat[annulus_indices[92:]] = 11.0

        result = estimate(pixels, x=12.0, y=12.0, aperture_radius=2.0)

        self.assertEqual(result["aperture_pixels"], 13)
        self.assertEqual(result["background_annulus_pixels"], 184)
        self.assertAlmostEqual(result["background_noise_adu"], 1.4826, places=12)
        self.assertAlmostEqual(result["flux_uncertainty_adu"],
                               5.634414935390579, places=12)

    def test_planet_photometry_fails_closed_without_measurement_method(self):
        import scripts.plot_planet_photometry as planet_plot

        rate, magnitude, reason = planet_plot._quality(
            {
                "exposure_seconds": "20",
                "saturation_known": "True",
                "G_saturated": "False",
                "G_count_rate_adu_per_s": "100",
            },
            "G",
        )

        self.assertEqual(rate, 100.0)
        self.assertIsNone(magnitude)
        self.assertEqual(reason, "G_measurement_not_aperture")

    def test_horizons_parser_retains_exact_jd_and_both_distances(self):
        import scripts.plot_planet_photometry as planet_plot

        parse = getattr(planet_plot, "_parse_horizons_distance_response", None)
        self.assertTrue(callable(parse))
        if not callable(parse):
            return
        response = """header
$$SOE
2461296.583332998, , ,  2.687504422387, -1.3,  2.86973005318477,-22.8,
$$EOE
footer
"""

        self.assertEqual(
            parse(response),
            [(2461296.583332998, 2.687504422387, 2.86973005318477)],
        )

    def test_horizons_lookup_batches_large_exact_date_lists(self):
        import scripts.plot_planet_photometry as planet_plot

        calls = []

        class FakeResponse:
            def __init__(self, text):
                self.text = text

            def raise_for_status(self):
                return None

        class FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, *unused):
                return False

            def get(self, unused_url, *, params, timeout):
                julian_dates = [
                    float(value) for value in params["TLIST"].strip("'").split()
                ]
                calls.append(julian_dates)
                body = "\n".join(
                    f"{value:.9f}, , ,2.0,0.0,3.0,0.0," for value in julian_dates
                )
                return FakeResponse(f"$$SOE\n{body}\n$$EOE")

        start = datetime(2026, 9, 20, tzinfo=timezone.utc)
        rows = [{
            "planet": "Saturn",
            "observation_time_utc": (
                start + timedelta(minutes=index)
            ).isoformat().replace("+00:00", "Z"),
        } for index in range(82)]

        with mock.patch("requests.Session", FakeSession):
            lookup = planet_plot._horizons_distance_lookup(rows)

        self.assertEqual(len(lookup), 82)
        self.assertGreater(len(calls), 1)
        self.assertLessEqual(max(map(len, calls)), 50)

    def test_distance_corrected_figure_draws_uncertainty_bars_and_group_line(self):
        import matplotlib.pyplot as plt
        from matplotlib.container import ErrorbarContainer
        import scripts.plot_planet_photometry as planet_plot

        builder = getattr(planet_plot, "_build_distance_corrected_figure", None)
        self.assertTrue(callable(builder))
        if not callable(builder):
            return
        rows = [
            {
                "planet": "Mars", "camera_label": "MMTO skycam",
                "observation_time_utc": "2026-09-20T01:00:00Z",
                "distance_corrected_magnitude": -8.0,
                "machine_magnitude_uncertainty": 0.1,
            },
            {
                "planet": "Mars", "camera_label": "MMTO skycam",
                "observation_time_utc": "2026-09-20T02:00:00Z",
                "distance_corrected_magnitude": -8.2,
                "machine_magnitude_uncertainty": 0.2,
            },
        ]
        figure, axis = builder(
            rows,
            {"MMTO skycam": "o"},
            {"Mars": planet_plot.PLANET_COLOURS["Mars"]},
            channel="G",
        )
        self.addCleanup(plt.close, figure)

        errorbars = [item for item in axis.containers
                     if isinstance(item, ErrorbarContainer)]
        self.assertEqual(len(axis.lines), 1)
        self.assertEqual(len(errorbars), 1)
        segments = errorbars[0].lines[2][0].get_segments()
        self.assertEqual(len(segments), 2)
        np.testing.assert_allclose(segments[0][:, 1], [-8.1, -7.9])
        np.testing.assert_allclose(segments[1][:, 1], [-8.4, -8.0])


class PlanetPhotometryLoadingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "stars.sqlite"
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE runs (
                    run_id TEXT, recorded_at_utc TEXT, source_path TEXT,
                    source_sha256 TEXT, catalogue_sha256 TEXT,
                    exit_code INTEGER
                );
                CREATE TABLE products (run_id TEXT, product TEXT, content BLOB);
                CREATE TABLE measurements (
                    run_id TEXT, product TEXT, row_number INTEGER,
                    star_id TEXT, detection_id TEXT, values_json TEXT
                );
                """
            )

    def add_run(self, run_id, image, recorded, *, exit_code=0,
                catalogue_sha256=TEST_CATALOGUE_SHA,
                observation="2026-09-18T21:59:46.397 UTC", source_path=None):
        planet_epoch = {
            "metadata_planet_association": {
                "status": "metadata_time_associated",
                "time_utc": observation,
            }
        }
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?,?)",
                (
                    run_id, recorded, source_path or f"/{image}.fits", image,
                    catalogue_sha256, exit_code,
                ),
            )
            connection.execute(
                "INSERT INTO products VALUES (?,?,?)",
                (run_id, "planet_epoch.json", json.dumps(planet_epoch)),
            )

    def add_planet(self, run_id, row_number, planet, *, status="metadata_time_match",
                   rate=100.0, flux=None, exposure=20.0, saturated="False",
                   saturation_known="True", method="aperture"):
        if flux is None and rate is not None and exposure is not None:
            flux = rate * exposure
        values = {
            "identity_type": "major_planet",
            "identity_name": planet,
            "identity_status": status,
            "candidate_rank": "1",
            "epoch_tdb": "1937-10-27T14:58:05.394",
            "detection_id": str(row_number),
            "source_class": "compact",
            "saturated": saturated,
            "saturation_known": saturation_known,
            "exposure_seconds": "" if exposure is None else str(exposure),
            "exposure_status": "unavailable" if exposure is None else "available",
            "exposure_source": "" if exposure is None else "test:exposure",
            "G_count_rate_adu_per_s": "nan" if rate is None else str(rate),
            "G_flux": "nan" if flux is None else str(flux),
            "G_saturated": saturated,
            "G_measurement_method": method,
        }
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                "INSERT INTO measurements VALUES (?,?,?,?,?,?)",
                (run_id, "identified_source_photometry.csv", row_number, "", str(row_number),
                 json.dumps(values)),
            )

    def add_stellar_calibration(
        self,
        run_id,
        *,
        planet="Mars",
        detection_id="1",
        altitude_deg=30.0,
        channel="G",
        intercept=-10.0,
        extinction=0.25,
        rms=0.2,
        fitted_count=40,
        identity_status="metadata_time_match",
    ):
        fit = {
            "intercept_mag": intercept,
            "coefficient_mag_per_airmass": extinction,
            "rms_mag": rms,
            "fitted_count": fitted_count,
            "status": "fitted",
            "relation": (
                f"{channel}_machine - catalogue_mag = intercept + k * airmass"
            ),
            "catalogue_passband": "test catalogue magnitude",
        }
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                "INSERT INTO products VALUES (?,?,?)",
                (
                    run_id,
                    "photometry_summary.json",
                    json.dumps({"extinction_by_channel": {channel: fit}}),
                ),
            )
            saved = connection.execute(
                "SELECT rowid,content FROM products "
                "WHERE run_id=? AND product='planet_epoch.json'",
                (run_id,),
            ).fetchone()
            payload = json.loads(saved[1])
            matches = [{
                "planet": planet,
                "detection_id": int(detection_id),
                "measured_altitude_deg": altitude_deg,
            }]
            if identity_status == "selected_planet_match":
                payload["matches"] = matches
            else:
                payload["metadata_planet_association"]["matches"] = matches
            connection.execute(
                "UPDATE products SET content=? WHERE rowid=?",
                (json.dumps(payload), saved[0]),
            )

    def test_loader_joins_same_run_stellar_fit_and_planet_altitude(self):
        self.add_run("run", "image", "2026-09-20T01:00:00Z")
        self.add_planet("run", 1, "Mars", rate=100.0)
        self.add_stellar_calibration("run")

        rows, _ = load_planet_measurements(self.database)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["stellar_calibration_status"], "available")
        self.assertEqual(row["stellar_intercept_mag"], -10.0)
        self.assertEqual(row["stellar_extinction_mag_per_airmass"], 0.25)
        self.assertEqual(row["stellar_fit_rms_mag"], 0.2)
        self.assertEqual(row["stellar_fit_count"], 40)
        self.assertEqual(row["planet_measured_altitude_deg"], 30.0)
        self.assertAlmostEqual(
            row["planet_airmass"],
            1.0 / (np.cos(np.deg2rad(60.0)) + 0.50572 * 36.07995 ** -1.6364),
            places=12,
        )
        self.assertAlmostEqual(
            row["stellar_calibration_offset_mag"],
            -10.0 + 0.25 * row["planet_airmass"],
            places=12,
        )

    def test_loader_marks_missing_channel_fit_and_altitude_without_guessing(self):
        self.add_run("missing-fit", "image1", "2026-09-20T01:00:00Z")
        self.add_planet("missing-fit", 1, "Mars", rate=100.0)

        self.add_run("wrong-channel", "image2", "2026-09-20T02:00:00Z")
        self.add_planet("wrong-channel", 1, "Mars", rate=100.0)
        self.add_stellar_calibration("wrong-channel", channel="R")

        self.add_run("missing-altitude", "image3", "2026-09-20T03:00:00Z")
        self.add_planet("missing-altitude", 1, "Mars", rate=100.0)
        self.add_stellar_calibration("missing-altitude", altitude_deg=None)

        rows, _ = load_planet_measurements(self.database, channel="G")
        status = {row["run_id"]: row["stellar_calibration_status"] for row in rows}

        self.assertEqual(status["missing-fit"], "stellar_fit_unavailable")
        self.assertEqual(status["wrong-channel"], "stellar_fit_unavailable")
        self.assertEqual(status["missing-altitude"], "planet_altitude_unavailable")

    def test_checksum_matched_nested_exif_recovers_missing_count_rate_only(self):
        matched = Path(self.temporary.name) / "matched.jpg"
        exif = Image.Exif()
        exif[ExifTags.IFD.Exif] = {33434: (15, 1)}
        Image.new("RGB", (12, 10)).save(matched, exif=exif)
        digest = hashlib.sha256(matched.read_bytes()).hexdigest()
        self.add_run(
            "matched", digest, "2026-09-20T01:00:00Z", source_path=str(matched)
        )
        self.add_planet(
            "matched", 1, "Vesta", rate=None, flux=150.0, exposure=None
        )

        changed = Path(self.temporary.name) / "changed.jpg"
        Image.new("RGB", (12, 10)).save(changed, exif=exif)
        self.add_run(
            "changed", "not-the-file-digest", "2026-09-20T02:00:00Z",
            source_path=str(changed),
        )
        self.add_planet(
            "changed", 1, "Saturn", rate=None, flux=150.0, exposure=None
        )

        rows, _ = load_planet_measurements(self.database)
        by_planet = {row["planet"]: row for row in rows}

        self.assertTrue(by_planet["Vesta"]["photometry_usable"])
        self.assertEqual(by_planet["Vesta"]["exposure_seconds"], 15.0)
        self.assertEqual(by_planet["Vesta"]["count_rate_adu_per_s"], 10.0)
        self.assertAlmostEqual(by_planet["Vesta"]["machine_magnitude"], -2.5)
        self.assertEqual(
            by_planet["Vesta"]["exposure_source"],
            "source_exif:ExifIFD:ExposureTime (SHA-256 verified)",
        )
        self.assertFalse(by_planet["Saturn"]["photometry_usable"])
        self.assertEqual(
            by_planet["Saturn"]["exclusion_reason"],
            "missing_or_nonpositive_exposure",
        )

    def test_camera_identity_distinguishes_olympus_from_nikon(self):
        import scripts.plot_planet_photometry as planet_plot

        olympus, _ = planet_plot._camera_identity(
            "/images/MilkyWay_GC124890-1-5_with_planets_no_trails.jpg"
        )
        nikon, _ = planet_plot._camera_identity(
            "/images/FishEye18-1012w_Espenak.jpg"
        )

        self.assertEqual(olympus, "Olympus E-M1 Mark II")
        self.assertEqual(nikon, "Nikon D750 / Espenak")

    def test_source_metadata_search_covers_xmp_png_text_and_all_fits_hdus(self):
        import scripts.plot_planet_photometry as planet_plot

        inspect = getattr(planet_plot, "_inspect_source_exposure", None)
        self.assertTrue(callable(inspect), "source exposure inspection must be comprehensive")
        if not callable(inspect):
            return

        xmp_path = Path(self.temporary.name) / "xmp.jpg"
        xmp = (
            b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
            b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            b'<rdf:Description xmlns:exif="http://ns.adobe.com/exif/1.0/" '
            b'exif:ExposureTime="3/2"/></rdf:RDF></x:xmpmeta>'
        )
        Image.new("RGB", (12, 10)).save(xmp_path, xmp=xmp)

        png_path = Path(self.temporary.name) / "text.png"
        png_info = PngInfo()
        png_info.add_text("ExposureTime", "2.5")
        Image.new("RGB", (12, 10)).save(png_path, pnginfo=png_info)

        fits_path = Path(self.temporary.name) / "extension.fits"
        science = fits.ImageHDU(name="SCI")
        science.header["EXPTIME"] = 12.5
        fits.HDUList([fits.PrimaryHDU(), science]).writeto(fits_path)
        compressed_path = Path(self.temporary.name) / "extension.fits.bz2"
        compressed_path.write_bytes(bz2.compress(fits_path.read_bytes()))

        cases = [
            (xmp_path, 1.5, "source_xmp:ExposureTime (SHA-256 verified)"),
            (png_path, 2.5, "source_raster_text:ExposureTime (SHA-256 verified)"),
            (compressed_path, 12.5,
             "source_fits:HDU1:SCI:EXPTIME (SHA-256 verified)"),
        ]
        for path, seconds, provenance in cases:
            with self.subTest(path=path.name):
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                result = inspect(path, digest)
                self.assertEqual(result["status"], "accepted")
                self.assertEqual(result["accepted_seconds"], seconds)
                self.assertEqual(result["accepted_source"], provenance)
                self.assertGreaterEqual(len(result["candidates"]), 1)

    def test_source_metadata_search_rejects_conflicting_fits_exposures(self):
        import scripts.plot_planet_photometry as planet_plot

        inspect = getattr(planet_plot, "_inspect_source_exposure", None)
        self.assertTrue(callable(inspect), "source exposure inspection must report conflicts")
        if not callable(inspect):
            return
        path = Path(self.temporary.name) / "conflict.fits"
        primary = fits.PrimaryHDU()
        primary.header["EXPTIME"] = 10.0
        extension = fits.ImageHDU(name="SCI")
        extension.header["EXPOSURE"] = 20.0
        fits.HDUList([primary, extension]).writeto(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()

        result = inspect(path, digest)

        self.assertEqual(result["status"], "conflicting_exposure_metadata")
        self.assertIsNone(result["accepted_seconds"])
        self.assertEqual(
            {candidate["seconds"] for candidate in result["candidates"]},
            {10.0, 20.0},
        )

    def test_latest_successful_run_per_image_is_selected_before_identity_filter(self):
        self.add_run("old", "image1", "2026-09-20T01:00:00Z")
        self.add_planet("old", 1, "Saturn")
        self.add_run("new", "image1", "2026-09-20T02:00:00Z")
        self.add_planet("new", 1, "Jupiter")
        self.add_run("good", "image2", "2026-09-20T01:00:00Z")
        self.add_planet("good", 1, "Mars")
        self.add_run("failed", "image2", "2026-09-20T03:00:00Z", exit_code=1)
        self.add_planet("failed", 1, "Venus")
        self.add_run("alias", "image3", "2026-09-20T04:00:00Z")
        self.add_planet("alias", 1, "Mercury", status="selected_planet_match")
        self.add_run("candidate", "image4", "2026-09-20T05:00:00Z")
        self.add_planet("candidate", 1, "Venus", status="planet_candidate")

        rows, audit = load_planet_measurements(self.database)

        self.assertEqual([row["planet"] for row in rows], ["Jupiter", "Mars", "Mercury"])
        self.assertEqual({row["run_id"] for row in rows}, {"new", "good", "alias"})
        self.assertEqual(rows[0]["observation_time_utc"], "2026-09-18T21:59:46.397Z")
        self.assertNotEqual(rows[0]["observation_time_utc"], rows[0]["recorded_at_utc"])
        self.assertEqual(audit["failed_runs_omitted"], 1)
        self.assertEqual(audit["duplicate_successful_runs_omitted"], 1)
        self.assertEqual(audit["non_detection_identity_rows_omitted"], 1)
        self.assertEqual(audit["selected_planet_match_rows"], 1)

    def test_detected_rows_are_retained_when_photometry_is_unusable(self):
        self.add_run("run", "image", "2026-09-20T01:00:00Z")
        self.add_planet("run", 1, "Mars", rate=100.0)
        self.add_planet("run", 2, "Saturn", rate=80.0, saturated="True")
        self.add_planet("run", 3, "Uranus", rate=-1.0)
        self.add_planet("run", 4, "Neptune", rate=50.0, method="saturated_aperture_lower_bound")

        rows, audit = load_planet_measurements(self.database)

        by_planet = {row["planet"]: row for row in rows}
        self.assertEqual(set(by_planet), {"Mars", "Saturn", "Uranus", "Neptune"})
        self.assertTrue(by_planet["Mars"]["photometry_usable"])
        self.assertAlmostEqual(by_planet["Mars"]["machine_magnitude"], -5.0)
        self.assertFalse(by_planet["Saturn"]["photometry_usable"])
        self.assertEqual(by_planet["Saturn"]["exclusion_reason"], "G_saturated")
        self.assertIsNone(by_planet["Saturn"]["machine_magnitude"])
        self.assertEqual(by_planet["Uranus"]["exclusion_reason"],
                         "nonpositive_or_nonfinite_G_count_rate")
        self.assertEqual(by_planet["Neptune"]["exclusion_reason"],
                         "G_measurement_not_aperture")
        self.assertEqual(audit["detected_planet_rows"], 4)
        self.assertEqual(audit["usable_photometry_rows"], 1)

    def test_outputs_separate_complete_plot_rows_from_detection_audit(self):
        import scripts.plot_planet_photometry as planet_plot

        self.assertTrue(hasattr(planet_plot, "write_outputs"))
        self.add_run("run", "image", "2026-09-20T01:00:00Z")
        self.add_planet("run", 1, "Mars", rate=100.0)
        self.add_planet("run", 2, "Saturn", rate=80.0, saturated="True")
        rows, audit = load_planet_measurements(self.database)
        output = Path(self.temporary.name) / "output"

        summary = planet_plot.write_outputs(
            rows, audit, output, database=self.database, channel="G"
        )

        with (output / "planet_measurements.csv").open(newline="", encoding="utf-8") as stream:
            exported = list(csv.DictReader(stream))
        self.assertEqual([row["planet"] for row in exported], ["Mars"])
        with (output / "planet_detection_audit.csv").open(newline="", encoding="utf-8") as stream:
            audited = list(csv.DictReader(stream))
        self.assertEqual([row["planet"] for row in audited], ["Mars", "Saturn"])
        self.assertEqual(audited[1]["exclusion_reason"], "G_saturated")
        self.assertGreater((output / "planet_machine_magnitude_vs_time.png").stat().st_size, 1000)
        self.assertGreater((output / "planet_machine_magnitude_vs_time.pdf").stat().st_size, 1000)
        self.assertGreater((output / "exposure_metadata_audit.csv").stat().st_size, 100)
        saved = json.loads((output / "summary.json").read_text())
        self.assertEqual(saved["audit"]["detected_planet_rows"], 2)
        self.assertEqual(summary["audit"]["usable_photometry_rows"], 1)
        self.assertEqual(summary["machine_magnitude_definition"],
                         "-2.5 log10(G count rate [ADU/s])")
        self.assertIn("plotted_counts", summary)
        if "plotted_counts" in summary:
            self.assertEqual(summary["plotted_counts"]["measurements"], 1)
            self.assertEqual(summary["plotted_counts"]["unique_source_images"], 1)

    def test_outputs_can_skip_five_earliest_observations_without_splitting_an_image(self):
        import scripts.plot_planet_photometry as planet_plot

        for index in range(6):
            run_id = f"run-{index}"
            self.add_run(
                run_id,
                f"image-{index}",
                f"2026-09-20T0{index}:00:00Z",
                observation=f"2026-09-20T0{index}:00:00 UTC",
            )
            self.add_planet(run_id, 1, "Mars", rate=100.0 + index)
            if index == 0:
                self.add_planet(run_id, 2, "Uranus", rate=90.0)
        rows, audit = load_planet_measurements(self.database)
        output = Path(self.temporary.name) / "skip-output"

        summary = planet_plot.write_outputs(
            rows,
            audit,
            output,
            database=self.database,
            channel="G",
            skip_earliest_observations=5,
        )

        with (output / "planet_measurements.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            exported = list(csv.DictReader(stream))
        with (output / "planet_detection_audit.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            audited = list(csv.DictReader(stream))
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0]["observation_time_utc"], "2026-09-20T05:00:00Z")
        self.assertEqual(len(audited), 7)
        self.assertEqual(summary["plot_selection"]["skip_earliest_observations"], 5)
        self.assertEqual(summary["plot_selection"]["measurements_omitted"], 6)
        self.assertEqual(summary["plot_selection"]["earliest_retained_time_utc"],
                         "2026-09-20T05:00:00Z")
        self.assertEqual(summary["plotted_counts"]["measurements"], 1)

    def test_distance_corrected_output_requires_distances_and_uncertainty(self):
        import scripts.plot_planet_photometry as planet_plot

        writer = getattr(planet_plot, "write_distance_corrected_outputs", None)
        self.assertTrue(callable(writer))
        if not callable(writer):
            return
        self.add_run(
            "run", "image", "2026-09-20T01:00:00Z",
            observation="2026-09-20T01:00:00 UTC",
        )
        self.add_planet("run", 1, "Mars", rate=100.0)
        self.add_planet("run", 2, "Uranus", rate=80.0)
        rows, audit = load_planet_measurements(self.database)
        output = Path(self.temporary.name) / "corrected-output"
        distances = {
            ("Mars", "2026-09-20T01:00:00Z"): {
                "sun_planet_distance_au": 2.0,
                "earth_planet_distance_au": 3.0,
                "distance_ephemeris_source": "test ephemeris",
            }
        }
        uncertainties = {
            ("run", "1"): {
                "machine_magnitude_uncertainty": 0.1,
                "count_rate_uncertainty_adu_per_s": 9.210340371976184,
                "uncertainty_status": "available",
                "uncertainty_source": "test background",
            }
        }

        summary = writer(
            rows,
            audit,
            output,
            database=self.database,
            channel="G",
            skip_earliest_observations=0,
            distance_lookup=distances,
            uncertainty_lookup=uncertainties,
        )

        with (output / "planet_distance_corrected_measurements.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            exported = list(csv.DictReader(stream))
        self.assertEqual([row["planet"] for row in exported], ["Mars"])
        self.assertAlmostEqual(float(exported[0]["distance_corrected_magnitude"]),
                               -8.89075625191822, places=12)
        self.assertEqual(summary["plotted_counts"]["measurements"], 1)
        self.assertEqual(summary["excluded_incomplete_corrected_rows"], 1)
        self.assertTrue(
            (output / "planet_distance_corrected_magnitude_vs_time.png").is_file()
        )

    def test_stellar_calibrated_output_applies_same_run_fit_and_total_uncertainty(self):
        import matplotlib.pyplot as plt
        import scripts.plot_planet_photometry as planet_plot

        writer = getattr(
            planet_plot, "write_stellar_calibrated_distance_outputs", None
        )
        builder = getattr(
            planet_plot, "_build_stellar_calibrated_distance_figure", None
        )
        self.assertTrue(callable(writer))
        self.assertTrue(callable(builder))
        if not callable(writer) or not callable(builder):
            return
        self.add_run(
            "run", "image", "2026-09-20T01:00:00Z",
            observation="2026-09-20T01:00:00 UTC",
        )
        self.add_planet("run", 1, "Mars", rate=100.0)
        self.add_planet("run", 2, "Uranus", rate=80.0)
        self.add_stellar_calibration("run", planet="Mars", detection_id="1")
        rows, audit = load_planet_measurements(self.database)
        output = Path(self.temporary.name) / "stellar-calibrated-output"
        distances = {
            (planet, "2026-09-20T01:00:00Z"): {
                "sun_planet_distance_au": 2.0,
                "earth_planet_distance_au": 3.0,
                "distance_ephemeris_source": "test ephemeris",
            }
            for planet in ("Mars", "Uranus")
        }
        uncertainties = {
            ("run", detection_id): {
                "machine_magnitude_uncertainty": 0.1,
                "count_rate_uncertainty_adu_per_s": 9.210340371976184,
                "uncertainty_status": "available",
                "uncertainty_source": "test background",
            }
            for detection_id in ("1", "2")
        }

        summary = writer(
            rows,
            audit,
            output,
            database=self.database,
            channel="G",
            skip_earliest_observations=0,
            distance_lookup=distances,
            uncertainty_lookup=uncertainties,
        )

        csv_path = output / "planet_stellar_calibrated_distance_measurements.csv"
        with csv_path.open(newline="", encoding="utf-8") as stream:
            exported = list(csv.DictReader(stream))
        self.assertEqual([row["planet"] for row in exported], ["Mars"])
        mars = exported[0]
        expected = planet_plot._stellar_calibrated_distance_magnitude(
            -5.0, -10.0, 0.25, 30.0, 2.0, 3.0
        )
        self.assertAlmostEqual(
            float(mars["stellar_calibrated_distance_magnitude"]), expected, places=12
        )
        self.assertAlmostEqual(
            float(mars["distance_corrected_magnitude"]),
            planet_plot._distance_corrected_magnitude(-5.0, 2.0, 3.0),
            places=12,
        )
        self.assertAlmostEqual(
            float(mars["total_magnitude_uncertainty"]), np.hypot(0.1, 0.2), places=12
        )
        self.assertEqual(summary["plotted_counts"]["measurements"], 1)
        self.assertEqual(summary["excluded_incomplete_calibrated_rows"], 1)
        self.assertEqual(
            summary["excluded_calibrated_reasons"],
            {"planet_altitude_unavailable": 1},
        )
        self.assertTrue(
            (output / "planet_stellar_calibrated_distance_magnitude_vs_time.png").is_file()
        )
        self.assertTrue(
            (output / "planet_stellar_calibrated_distance_magnitude_vs_time.pdf").is_file()
        )

        plot_rows = [{
            **rows[0],
            "stellar_calibrated_distance_magnitude": expected,
            "total_magnitude_uncertainty": np.hypot(0.1, 0.2),
        }]
        figure, axis = builder(
            plot_rows,
            {"Unidentified camera": "o"},
            {"Mars": planet_plot.PLANET_COLOURS["Mars"]},
            channel="G",
        )
        self.addCleanup(plt.close, figure)
        self.assertIn("stellar-calibrated", axis.get_ylabel())

    def test_nightly_loader_requires_unique_matching_image_channel(self):
        import scripts.plot_planet_photometry as planet_plot

        loader = getattr(planet_plot, "load_nightly_image_calibrations", None)
        self.assertTrue(callable(loader))
        if not callable(loader):
            return
        sidecar = Path(self.temporary.name) / "nightly-sidecar"
        write_nightly_sidecar(sidecar)

        calibrations = loader(sidecar)

        key = ("a" * 64, TEST_CATALOGUE_SHA, "2026-09-19", "G")
        self.assertEqual(set(calibrations), {key})
        self.assertEqual(calibrations[key]["extinction_mag_per_airmass"], 0.2)
        self.assertEqual(calibrations[key]["zero_point_magnitude"], -6.0)
        self.assertEqual(
            calibrations[key]["observed_utc"], "2026-09-20T01:00:00Z"
        )

        write_nightly_sidecar(sidecar, duplicate_zero_point=True)
        with self.assertRaisesRegex(ValueError, "duplicate image zero point"):
            loader(sidecar)

    def test_planet_uses_star_only_nightly_k_and_fixed_image_zero_point(self):
        import scripts.plot_planet_photometry as planet_plot

        writer = getattr(
            planet_plot,
            "write_extinction_corrected_distance_outputs",
            None,
        )
        self.assertTrue(callable(writer))
        if not callable(writer):
            return
        source_sha = "a" * 64
        self.add_run(
            "run", source_sha, "2026-09-20T01:01:00Z",
            observation="2026-09-20T01:00:00 UTC",
        )
        self.add_planet("run", 1, "Mars", rate=100.0)
        self.add_stellar_calibration(
            "run", planet="Mars", detection_id="1", intercept=-20.0,
            extinction=0.9,
        )
        rows, audit = load_planet_measurements(self.database)
        self.assertNotIn("catalogue_magnitude", rows[0])
        self.assertEqual(rows[0]["catalogue_sha256"], TEST_CATALOGUE_SHA)
        sidecar = Path(self.temporary.name) / "nightly-sidecar"
        write_nightly_sidecar(sidecar, source_sha256=source_sha)
        output = Path(self.temporary.name) / "nightly-output"
        distances = {
            ("Mars", "2026-09-20T01:00:00Z"): {
                "sun_planet_distance_au": 1.0,
                "earth_planet_distance_au": 1.0,
                "distance_ephemeris_source": "test ephemeris",
            }
        }
        uncertainties = {
            ("run", "1"): {
                "machine_magnitude_uncertainty": 0.1,
                "uncertainty_status": "available",
                "uncertainty_source": "test background",
            }
        }

        summary = writer(
            rows,
            audit,
            output,
            database=self.database,
            nightly_calibration=sidecar,
            channel="G",
            distance_lookup=distances,
            uncertainty_lookup=uncertainties,
        )

        with (output / "planet_extinction_corrected_distance_measurements.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            exported = list(csv.DictReader(stream))
        self.assertEqual(len(exported), 1)
        mars = exported[0]
        expected = -5.0 - (-6.0) - 0.2 * rows[0]["planet_airmass"]
        self.assertAlmostEqual(
            float(mars["extinction_corrected_magnitude"]), expected, 12
        )
        self.assertNotAlmostEqual(
            float(mars["extinction_corrected_magnitude"]),
            -5.0 - (-20.0 + 0.9 * rows[0]["planet_airmass"]),
            6,
        )
        self.assertEqual(mars["extinction_correction_status"], "available")
        self.assertEqual(mars["nightly_extinction_night"], "2026-09-19")
        self.assertEqual(summary["plotted_counts"]["measurements"], 1)
        self.assertEqual(
            summary["quantity"],
            "extinction-corrected, distance-corrected magnitude",
        )
        self.assertTrue(
            (output / "planet_extinction_corrected_distance_magnitude_vs_time.png").is_file()
        )

    def test_missing_sidecar_match_has_no_legacy_or_raw_fallback(self):
        import scripts.plot_planet_photometry as planet_plot

        writer = getattr(
            planet_plot,
            "write_extinction_corrected_distance_outputs",
            None,
        )
        self.assertTrue(callable(writer))
        if not callable(writer):
            return
        self.add_run(
            "run", "a" * 64, "2026-09-20T01:01:00Z",
            observation="2026-09-20T01:00:00 UTC",
        )
        self.add_planet("run", 1, "Mars", rate=100.0)
        self.add_stellar_calibration("run", planet="Mars", detection_id="1")
        rows, audit = load_planet_measurements(self.database)
        sidecar = Path(self.temporary.name) / "mismatched-sidecar"
        write_nightly_sidecar(sidecar, source_sha256="b" * 64)
        output = Path(self.temporary.name) / "missing-nightly-output"

        summary = writer(
            rows,
            audit,
            output,
            database=self.database,
            nightly_calibration=sidecar,
            channel="G",
            distance_lookup={},
            uncertainty_lookup={},
        )

        with (output / "planet_extinction_corrected_distance_measurements.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            self.assertEqual(list(csv.DictReader(stream)), [])
        with (output / "planet_extinction_correction_audit.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            audited = list(csv.DictReader(stream))
        self.assertEqual(audited[0]["extinction_correction_status"], "missing_sidecar_match")
        self.assertEqual(audited[0]["extinction_corrected_magnitude"], "")
        self.assertEqual(
            summary["excluded_calibrated_reasons"], {"missing_sidecar_match": 1}
        )

    def test_extinction_corrected_plot_rejects_blind_epoch_identity(self):
        import scripts.plot_planet_photometry as planet_plot

        source_sha = "a" * 64
        self.add_run(
            "run", source_sha, "2026-09-20T01:01:00Z",
            observation="2026-09-20T01:00:00 UTC",
        )
        self.add_planet(
            "run", 1, "Venus", status="selected_planet_match", rate=100.0
        )
        self.add_stellar_calibration(
            "run", planet="Venus", identity_status="selected_planet_match"
        )
        rows, audit = load_planet_measurements(self.database)
        sidecar = Path(self.temporary.name) / "blind-identity-sidecar"
        write_nightly_sidecar(sidecar, source_sha256=source_sha)
        output = Path(self.temporary.name) / "blind-identity-output"

        summary = planet_plot.write_extinction_corrected_distance_outputs(
            rows,
            audit,
            output,
            database=self.database,
            nightly_calibration=sidecar,
            channel="G",
            distance_lookup={
                ("Venus", "2026-09-20T01:00:00Z"): {
                    "sun_planet_distance_au": 1.0,
                    "earth_planet_distance_au": 1.0,
                    "distance_ephemeris_source": "test ephemeris",
                }
            },
            uncertainty_lookup={
                ("run", "1"): {
                    "machine_magnitude_uncertainty": 0.1,
                    "uncertainty_status": "available",
                    "uncertainty_source": "test background",
                }
            },
        )

        with (output / "planet_extinction_correction_audit.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            audited = next(csv.DictReader(stream))
        self.assertEqual(summary["plotted_counts"]["measurements"], 0)
        self.assertEqual(
            audited["extinction_correction_exclusion_reason"],
            "blind_epoch_identity_not_observation_time",
        )

    def test_metadata_time_loader_reassociates_saved_detections_at_sidecar_utc(self):
        import scripts.plot_planet_photometry as planet_plot

        source_sha = "a" * 64
        self.add_run(
            "run", source_sha, "2026-09-20T02:01:00Z",
            observation="1909-12-05T18:41:15 UTC",
            source_path="/raw_allsky_samples/mmto/MMTO.fits",
        )
        self.add_planet(
            "run", 9, "Venus", status="selected_planet_match", rate=10.0
        )
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                "INSERT INTO products VALUES (?,?,?)",
                (
                    "run", "stellar_only_result.json",
                    json.dumps({
                        "camera": {"shape": [100, 120]},
                        "fit": {"rms_arcmin": 5.5},
                    }),
                ),
            )
            connection.execute(
                "INSERT INTO products VALUES (?,?,?)",
                (
                    "run", "photometric_zenith.json",
                    json.dumps({"zenith_unit_vector": [0.0, 0.0, 1.0]}),
                ),
            )
            detection = {
                "detection_id": "3", "x_px": "51.0", "y_px": "42.0",
                "flux_above_background": "2000.0", "saturated": "False",
                "source_class": "compact",
            }
            connection.execute(
                "INSERT INTO measurements VALUES (?,?,?,?,?,?)",
                (
                    "run", "dots/star_candidates.csv", 1, "", "3",
                    json.dumps(detection),
                ),
            )
            photometry = {
                **detection,
                "saturation_known": "True",
                "exposure_seconds": "20.0",
                "exposure_source": "fits:PRIMARY:EXPOSURE",
                "G_flux": "4000.0",
                "G_count_rate_adu_per_s": "200.0",
                "G_saturated": "False",
                "G_measurement_method": "aperture",
            }
            connection.execute(
                "INSERT INTO measurements VALUES (?,?,?,?,?,?)",
                (
                    "run", "source_photometry.csv", 1, "", "3",
                    json.dumps(photometry),
                ),
            )
        sidecar = Path(self.temporary.name) / "metadata-time-sidecar"
        write_nightly_sidecar(sidecar, source_sha256=source_sha)
        calls = []

        def associate(
            camera_record, detections, zenith, observed_utc,
            positional_sigma_arcmin,
        ):
            calls.append((
                camera_record, detections, zenith, observed_utc,
                positional_sigma_arcmin,
            ))
            return {
                "status": "metadata_time_associated",
                "time_utc": observed_utc,
                "epoch_tdb": "2026-09-20T01:01:09.184 TDB",
                "epoch_source": "test manifest UTC",
                "gate_arcmin": 30.0,
                "positional_sigma_arcmin": positional_sigma_arcmin,
                "method": "test exact metadata ephemeris",
                "matches": [{
                    "planet": "Saturn", "detection_id": 3,
                    "measured_altitude_deg": 45.0,
                    "unused_brightness_rank": 1,
                    "source_class": "compact",
                    "jd_tdb": 2461303.5424674,
                    "measured_x_px": 51.0,
                    "measured_y_px": 42.0,
                    "predicted_x_px": 51.2,
                    "predicted_y_px": 42.1,
                    "separation_px": 0.2236,
                    "separation_arcmin": 1.2,
                    "catalogue_residual_px": None,
                    "catalogue_residual_arcmin": None,
                }],
                "predicted_without_source": [{"planet": "Neptune"}],
            }

        rows, audit = planet_plot.load_mmto_metadata_planet_measurements(
            self.database,
            sidecar,
            channel="G",
            association_provider=associate,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["planet"], "Saturn")
        self.assertEqual(rows[0]["identity_status"], "metadata_time_match")
        self.assertEqual(rows[0]["observation_time_utc"], "2026-09-20T01:00:00Z")
        self.assertEqual(rows[0]["count_rate_adu_per_s"], 200.0)
        self.assertAlmostEqual(rows[0]["planet_measured_altitude_deg"], 45.0)
        self.assertNotIn("Venus", audit["planet_counts"])
        self.assertEqual(audit["metadata_time_predicted_without_source"], 1)
        self.assertEqual(calls[0][0], {"shape": [100, 120]})
        self.assertEqual(calls[0][2], [0.0, 0.0, 1.0])
        self.assertEqual(calls[0][3], "2026-09-20T01:00:00Z")
        self.assertEqual(calls[0][4], 5.5)
        self.assertEqual(rows[0]["metadata_association_time_utc"], calls[0][3])
        self.assertEqual(rows[0]["metadata_association_status"],
                         "metadata_time_associated")
        self.assertEqual(rows[0]["metadata_association_method"],
                         "test exact metadata ephemeris")
        self.assertEqual(rows[0]["association_positional_sigma_arcmin"], 5.5)
        self.assertEqual(rows[0]["association_separation_arcmin"], 1.2)

    def test_extinction_audit_retains_unusable_metadata_matches(self):
        import scripts.plot_planet_photometry as planet_plot

        source_sha = "a" * 64
        self.add_run(
            "run", source_sha, "2026-09-20T01:01:00Z",
            observation="2026-09-20T01:00:00 UTC",
        )
        self.add_planet("run", 1, "Mars", rate=100.0)
        self.add_stellar_calibration("run", planet="Mars", detection_id="1")
        rows, audit = load_planet_measurements(self.database)
        saturated = {
            **rows[0],
            "planet": "Saturn",
            "detection_id": "2",
            "photometry_usable": False,
            "machine_magnitude": None,
            "exclusion_reason": "G_saturated",
        }
        invalid_altitude = {
            **rows[0],
            "planet": "Uranus",
            "detection_id": "3",
            "photometry_usable": False,
            "machine_magnitude": None,
            "planet_measured_altitude_deg": None,
            "planet_airmass": None,
            "exclusion_reason": "planet_altitude_invalid",
        }
        sidecar = Path(self.temporary.name) / "complete-audit-sidecar"
        write_nightly_sidecar(sidecar, source_sha256=source_sha)
        output = Path(self.temporary.name) / "complete-audit-output"

        planet_plot.write_extinction_corrected_distance_outputs(
            [rows[0], saturated, invalid_altitude],
            audit,
            output,
            database=self.database,
            nightly_calibration=sidecar,
            channel="G",
            distance_lookup={
                ("Mars", "2026-09-20T01:00:00Z"): {
                    "sun_planet_distance_au": 1.0,
                    "earth_planet_distance_au": 1.0,
                    "distance_ephemeris_source": "test ephemeris",
                }
            },
            uncertainty_lookup={
                ("run", "1"): {
                    "machine_magnitude_uncertainty": 0.1,
                    "uncertainty_status": "available",
                    "uncertainty_source": "test background",
                }
            },
        )

        with (output / "planet_extinction_correction_audit.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            audited = {row["planet"]: row for row in csv.DictReader(stream)}
        self.assertEqual(set(audited), {"Mars", "Saturn", "Uranus"})
        self.assertEqual(
            audited["Saturn"]["extinction_correction_exclusion_reason"],
            "G_saturated",
        )
        self.assertEqual(
            audited["Uranus"]["extinction_correction_exclusion_reason"],
            "planet_altitude_invalid",
        )

    def test_extinction_corrected_plot_rejects_identity_at_wrong_utc(self):
        import scripts.plot_planet_photometry as planet_plot

        source_sha = "a" * 64
        self.add_run(
            "run", source_sha, "2026-09-20T02:01:00Z",
            observation="2026-09-20T02:00:00 UTC",
        )
        self.add_planet("run", 1, "Venus", rate=100.0)
        self.add_stellar_calibration("run", planet="Venus")
        rows, audit = load_planet_measurements(self.database)
        sidecar = Path(self.temporary.name) / "wrong-utc-sidecar"
        write_nightly_sidecar(sidecar, source_sha256=source_sha)
        output = Path(self.temporary.name) / "wrong-utc-output"

        summary = planet_plot.write_extinction_corrected_distance_outputs(
            rows,
            audit,
            output,
            database=self.database,
            nightly_calibration=sidecar,
            channel="G",
            distance_lookup={
                ("Venus", "2026-09-20T02:00:00Z"): {
                    "sun_planet_distance_au": 1.0,
                    "earth_planet_distance_au": 1.0,
                    "distance_ephemeris_source": "test ephemeris",
                }
            },
            uncertainty_lookup={
                ("run", "1"): {
                    "machine_magnitude_uncertainty": 0.1,
                    "uncertainty_status": "available",
                    "uncertainty_source": "test background",
                }
            },
        )

        with (output / "planet_extinction_correction_audit.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            audited = next(csv.DictReader(stream))
        self.assertEqual(summary["plotted_counts"]["measurements"], 0)
        self.assertEqual(
            audited["extinction_correction_exclusion_reason"],
            "identity_time_disagrees_with_manifest_utc",
        )

    def test_distance_correction_is_applied_after_extinction_correction(self):
        import scripts.plot_planet_photometry as planet_plot

        writer = getattr(
            planet_plot,
            "write_extinction_corrected_distance_outputs",
            None,
        )
        self.assertTrue(callable(writer))
        if not callable(writer):
            return
        source_sha = "a" * 64
        self.add_run(
            "run", source_sha, "2026-09-20T01:01:00Z",
            observation="2026-09-20T01:00:00 UTC",
        )
        self.add_planet("run", 1, "Mars", rate=100.0)
        self.add_stellar_calibration("run", planet="Mars", detection_id="1")
        rows, audit = load_planet_measurements(self.database)
        sidecar = Path(self.temporary.name) / "nightly-distance-sidecar"
        write_nightly_sidecar(sidecar, source_sha256=source_sha)
        output = Path(self.temporary.name) / "nightly-distance-output"
        distances = {
            ("Mars", "2026-09-20T01:00:00Z"): {
                "sun_planet_distance_au": 2.0,
                "earth_planet_distance_au": 3.0,
                "distance_ephemeris_source": "test ephemeris",
            }
        }
        uncertainties = {
            ("run", "1"): {
                "machine_magnitude_uncertainty": 0.1,
                "uncertainty_status": "available",
                "uncertainty_source": "test background",
            }
        }

        writer(
            rows,
            audit,
            output,
            database=self.database,
            nightly_calibration=sidecar,
            channel="G",
            distance_lookup=distances,
            uncertainty_lookup=uncertainties,
        )

        with (output / "planet_extinction_corrected_distance_measurements.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            exported = next(csv.DictReader(stream))
        stellar = float(exported["extinction_corrected_magnitude"])
        expected_distance = planet_plot._distance_corrected_magnitude(
            stellar, 2.0, 3.0
        )
        self.assertAlmostEqual(
            float(exported["extinction_corrected_distance_magnitude"]),
            expected_distance,
            12,
        )

    def test_uncertainty_lookup_remeasures_checksum_verified_fits(self):
        import scripts.plot_planet_photometry as planet_plot

        source = Path(self.temporary.name) / "source.fits"
        pixels = np.full((31, 31), 10.0)
        yy, xx = np.mgrid[:31, :31]
        radius = np.hypot(xx - 15.0, yy - 15.0)
        pixels[(xx + yy).astype(int) % 2 == 0] = 9.0
        pixels[(xx + yy).astype(int) % 2 == 1] = 11.0
        aperture = radius <= 3.0
        pixels[aperture] = 10.0 + 1000.0 / int(aperture.sum())
        fits.PrimaryHDU(np.stack([pixels, pixels, pixels])).writeto(source)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        self.add_run(
            "run", digest, "2026-09-20T01:00:00Z", source_path=str(source)
        )
        self.add_planet("run", 1, "Mars", rate=50.0, exposure=20.0)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                "INSERT INTO measurements VALUES (?,?,?,?,?,?)",
                (
                    "run", "dots/star_candidates.csv", 1, "", "1",
                    json.dumps({
                        "x_px": "15.0", "y_px": "15.0",
                        "major_sigma_px": "1.2",
                    }),
                ),
            )
        rows, _ = load_planet_measurements(self.database)

        lookup = planet_plot._photometric_uncertainty_lookup(
            rows, self.database, channel="G"
        )

        estimate = lookup[("run", "1")]
        self.assertEqual(estimate["uncertainty_status"], "available")
        self.assertGreater(estimate["count_rate_uncertainty_adu_per_s"], 0.0)
        self.assertGreater(estimate["machine_magnitude_uncertainty"], 0.0)

    def test_planet_colour_and_camera_marker_encodings_are_independent(self):
        import scripts.plot_planet_photometry as planet_plot

        self.add_run(
            "apicam", "image1", "2026-09-20T01:00:00Z",
            observation="2018-03-01T00:13:02 UTC",
            source_path="/observations/APICAM.2018-03-01T00:13:02.000.fits",
        )
        self.add_planet("apicam", 1, "Uranus", rate=100.0)
        self.add_run(
            "mmto", "image2", "2026-09-20T02:00:00Z",
            observation="2026-01-15T23:46:44.942 UTC",
            source_path="/raw_allsky_samples/mmto/mmto-skycam/MMTO.fits",
        )
        self.add_planet("mmto", 1, "Uranus", rate=200.0)

        rows, audit = load_planet_measurements(self.database)

        self.assertTrue(all("camera_label" in row for row in rows))
        self.assertEqual({row["camera_label"] for row in rows}, {"APICAM", "MMTO skycam"})
        output = Path(self.temporary.name) / "encoding-output"
        summary = planet_plot.write_outputs(
            rows, audit, output, database=self.database, channel="G"
        )
        encoding = summary["visual_encoding"]
        self.assertEqual(encoding["colour"], "planet")
        self.assertEqual(encoding["marker"], "camera")
        self.assertEqual(set(encoding["planet_colours"]), {"Uranus"})
        self.assertNotEqual(
            encoding["camera_markers"]["APICAM"],
            encoding["camera_markers"]["MMTO skycam"],
        )
        with (output / "planet_measurements.csv").open(newline="", encoding="utf-8") as stream:
            exported = list(csv.DictReader(stream))
        self.assertEqual({row["camera_label"] for row in exported}, {"APICAM", "MMTO skycam"})

    def test_lines_connect_only_same_planet_and_camera_in_time_order(self):
        import matplotlib.pyplot as plt
        import scripts.plot_planet_photometry as planet_plot

        usable = [
            {"planet": "Uranus", "camera_label": "APICAM",
             "observation_time_utc": "2026-09-20T02:00:00Z", "machine_magnitude": -2.0},
            {"planet": "Uranus", "camera_label": "APICAM",
             "observation_time_utc": "2026-09-20T01:00:00Z", "machine_magnitude": -1.0},
            {"planet": "Uranus", "camera_label": "MMTO skycam",
             "observation_time_utc": "2026-09-20T04:00:00Z", "machine_magnitude": -4.0},
            {"planet": "Uranus", "camera_label": "MMTO skycam",
             "observation_time_utc": "2026-09-20T03:00:00Z", "machine_magnitude": -3.0},
            {"planet": "Mars", "camera_label": "MMTO skycam",
             "observation_time_utc": "2026-09-20T05:00:00Z", "machine_magnitude": -5.0},
        ]
        camera_markers = planet_plot._camera_marker_map(usable)
        planet_colours = {
            "Mars": planet_plot.PLANET_COLOURS["Mars"],
            "Uranus": planet_plot.PLANET_COLOURS["Uranus"],
        }

        figure, axis = planet_plot._build_figure(
            usable, camera_markers, planet_colours, channel="G"
        )
        self.addCleanup(plt.close, figure)

        self.assertEqual(len(axis.lines), 2)
        self.assertEqual({line.get_color() for line in axis.lines},
                         {planet_plot.PLANET_COLOURS["Uranus"]})
        self.assertTrue(all(len(line.get_xdata()) == 2 for line in axis.lines))
        self.assertTrue(all(
            line.get_xdata()[0] < line.get_xdata()[1] for line in axis.lines
        ))

    def test_legends_do_not_obscure_camera_markers(self):
        import matplotlib.pyplot as plt
        from matplotlib.legend import Legend
        import scripts.plot_planet_photometry as planet_plot

        self.add_run(
            "apicam", "image1", "2026-09-20T01:00:00Z",
            observation="2018-03-01T00:13:02 UTC",
            source_path="/observations/APICAM.2018-03-01T00:13:02.000.fits",
        )
        self.add_planet("apicam", 1, "Uranus", rate=100.0)
        self.add_run(
            "mmto", "image2", "2026-09-20T02:00:00Z",
            observation="2026-01-15T23:46:44.942 UTC",
            source_path="/raw_allsky_samples/mmto/mmto-skycam/MMTO.fits",
        )
        self.add_planet("mmto", 1, "Uranus", rate=200.0)
        rows, _ = load_planet_measurements(self.database)
        usable = [row for row in rows if row["photometry_usable"]]
        builder = getattr(planet_plot, "_build_figure", None)

        self.assertTrue(callable(builder), "plot construction must be inspectable")
        if not callable(builder):
            return
        camera_markers = planet_plot._camera_marker_map(usable)
        planet_colours = {"Uranus": planet_plot.PLANET_COLOURS["Uranus"]}
        figure, data_axis = builder(
            usable, camera_markers, planet_colours, channel="G"
        )
        self.addCleanup(plt.close, figure)
        figure.canvas.draw()

        legends = figure.findobj(Legend)
        data_box = data_axis.get_window_extent(figure.canvas.get_renderer())
        self.assertEqual(len(data_axis.collections), 2)
        self.assertEqual(len(data_axis.texts), 0)
        self.assertEqual(len(legends), 2)
        self.assertTrue(all(
            not legend.get_window_extent(figure.canvas.get_renderer()).overlaps(data_box)
            for legend in legends
        ))

    def test_command_line_entry_point_generates_requested_directory(self):
        import scripts.plot_planet_photometry as planet_plot

        self.assertTrue(hasattr(planet_plot, "main"))
        self.add_run("run", "image", "2026-09-20T01:00:00Z")
        self.add_planet("run", 1, "Mars", rate=100.0)
        output = Path(self.temporary.name) / "cli-output"

        status = planet_plot.main([
            "--database", str(self.database), "--output", str(output), "--channel", "G"
        ])

        self.assertEqual(status, 0)
        self.assertTrue((output / "planet_measurements.csv").is_file())

    def test_command_line_selects_stellar_calibrated_distance_writer(self):
        import scripts.plot_planet_photometry as planet_plot

        self.add_run("run", "image", "2026-09-20T01:00:00Z")
        self.add_planet("run", 1, "Mars", rate=100.0)
        output = Path(self.temporary.name) / "cli-calibrated-output"
        summary = {"plotted_counts": {"measurements": 0}}

        with mock.patch.object(
            planet_plot,
            "write_stellar_calibrated_distance_outputs",
            return_value=summary,
        ) as writer:
            status = planet_plot.main([
                "--database", str(self.database),
                "--output", str(output),
                "--channel", "G",
                "--stellar-calibrated-distance-corrected",
            ])

        self.assertEqual(status, 0)
        writer.assert_called_once()

    def test_command_line_selects_nightly_sidecar_writer_explicitly(self):
        import scripts.plot_planet_photometry as planet_plot

        self.add_run("run", "image", "2026-09-20T01:00:00Z")
        self.add_planet("run", 1, "Mars", rate=100.0)
        output = Path(self.temporary.name) / "cli-nightly-output"
        sidecar = Path(self.temporary.name) / "cli-nightly-sidecar"
        sidecar.mkdir()
        summary = {"plotted_counts": {"measurements": 0}}

        metadata_rows = ([{"planet": "Saturn"}], {"detected_planet_rows": 1})
        with mock.patch.object(
            planet_plot,
            "load_mmto_metadata_planet_measurements",
            return_value=metadata_rows,
        ) as loader, mock.patch.object(
            planet_plot,
            "write_extinction_corrected_distance_outputs",
            return_value=summary,
        ) as writer:
            status = planet_plot.main([
                "--database", str(self.database),
                "--output", str(output),
                "--channel", "G",
                "--extinction-corrected-distance-corrected",
                "--nightly-calibration", str(sidecar),
            ])

        self.assertEqual(status, 0)
        loader.assert_called_once_with(self.database, sidecar, channel="G")
        writer.assert_called_once()
        self.assertEqual(writer.call_args.args[:2], metadata_rows)
        self.assertEqual(
            writer.call_args.kwargs["nightly_calibration"], sidecar
        )


if __name__ == "__main__":
    unittest.main()
