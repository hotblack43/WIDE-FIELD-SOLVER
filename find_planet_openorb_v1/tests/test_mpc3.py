from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta
import math
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


def direction(night: str, when: datetime, run_id: str, unit: tuple[float, float, float], rms: float):
    from find_planet_openorb.types import AnonymousDirection

    return AnonymousDirection(
        object_id="Object A", run_id=run_id, source_sha256=f"sha-{run_id}",
        source_path=f"/archive/{run_id}.fits", night=night,
        observation_time_utc=when.isoformat().replace("+00:00", "Z"), detection_id=run_id,
        x_px=100.0, y_px=200.0, icrs_unit=unit, stellar_fit_rms_arcmin=rms,
        source_class="compact", saturated=False, integrated_refraction_status="accepted",
    )


class ObservationTests(unittest.TestCase):
    def test_utc_midpoint_ra_dec_wrap_pole_and_sigma_floor(self) -> None:
        from find_planet_openorb.observations import directions_to_observations

        epoch = datetime(2026, 9, 2, 3, 4, 5, 678900, tzinfo=UTC)
        cases = (
            direction("n1", epoch, "wrap", (math.cos(math.radians(-0.001)), math.sin(math.radians(-0.001)), 0.0), 0.2),
            direction("n1", epoch, "pole", (0.0, 0.0, 1.0), 2.5),
        )
        observations = directions_to_observations(cases)
        by_run = {row.run_id: row for row in observations}
        self.assertEqual(by_run["wrap"].observation_time_utc, epoch)
        self.assertAlmostEqual(by_run["wrap"].ra_deg, 359.999, places=9)
        self.assertAlmostEqual(by_run["wrap"].dec_deg, 0.0, places=12)
        self.assertEqual(by_run["wrap"].sigma_ra_arcsec, 60.0)
        self.assertEqual(by_run["wrap"].sigma_dec_arcsec, 60.0)
        self.assertAlmostEqual(by_run["pole"].dec_deg, 90.0, places=12)
        self.assertEqual(by_run["pole"].sigma_ra_arcsec, 150.0)

    def test_every_fifth_chronological_night_is_wholly_withheld(self) -> None:
        from find_planet_openorb.observations import directions_to_observations, split_nights

        epoch = datetime(2026, 1, 1, tzinfo=UTC)
        rows = []
        for night_index in range(11):
            night = f"2026-01-{night_index + 1:02d}"
            for item in range(2):
                rows.append(direction(night, epoch + timedelta(days=night_index, minutes=item), f"r{night_index}-{item}", (1.0, 0.0, 0.0), 1.0))
        split = split_nights(directions_to_observations(rows), modulus=5)
        self.assertEqual(split.withheld_nights, ("2026-01-05", "2026-01-10"))
        self.assertEqual(len(split.withheld), 4)
        self.assertFalse({row.run_id for row in split.fit} & {row.run_id for row in split.withheld})


class Mpc3Tests(unittest.TestCase):
    def test_exact_two_record_132_column_layout_and_round_trip(self) -> None:
        from find_planet_openorb.mpc3 import parse_mpc3_records, write_mpc3
        from find_planet_openorb.observations import directions_to_observations

        epoch = datetime(2026, 9, 2, 3, 4, 5, 678900, tzinfo=UTC)
        observation = directions_to_observations((direction("n1", epoch, "r1", (0.5, 0.5, math.sqrt(0.5)), 2.5),))[0]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "object-a.mpc3"
            write_mpc3(path, (observation,), designation="OBJ000001")
            lines = path.read_text().splitlines()
            parsed = parse_mpc3_records(path)
        self.assertEqual([len(line) for line in lines], [132, 132])
        self.assertEqual(lines[0][18], "1")
        self.assertEqual(lines[1][18:20], "2+")
        self.assertEqual(lines[0][128:132], "0696")
        self.assertEqual(lines[1][40:46], "15.0E1")
        self.assertEqual(lines[1][47:53], "15.0E1")
        self.assertEqual(parsed[0].designation, "OBJ000001")
        self.assertEqual(parsed[0].obscode, "696")
        self.assertLess(abs(parsed[0].observation_time_utc - epoch), timedelta(microseconds=100))
        self.assertAlmostEqual(parsed[0].ra_deg, 45.0, delta=0.01 / 3600)
        self.assertAlmostEqual(parsed[0].dec_deg, 45.0, delta=0.01 / 3600)
        self.assertEqual(parsed[0].sigma_ra_arcsec, 150.0)
        self.assertEqual(parsed[0].sigma_dec_arcsec, 150.0)

    def test_neutral_boundary_contains_no_identity_or_prediction_terms(self) -> None:
        from find_planet_openorb.mpc3 import write_mpc3
        from find_planet_openorb.observations import AnonymousObservation, directions_to_observations

        names = " ".join(field.name.lower() for field in fields(AnonymousObservation))
        epoch = datetime(2026, 9, 2, tzinfo=UTC)
        observation = directions_to_observations((direction("n1", epoch, "r1", (1.0, 0.0, 0.0), 1.0),))[0]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "anonymous.mpc3"
            write_mpc3(path, (observation,), designation="OBJ000001")
            content = path.read_text().lower()
        for forbidden in ("mars", "planet", "predicted", "horizons", "range", "velocity"):
            self.assertNotIn(forbidden, names)
            self.assertNotIn(forbidden, content)

    def test_native_round_trip_is_explicitly_required_when_vendor_is_absent(self) -> None:
        from find_planet_openorb.mpc3 import validate_mpc3_with_openorb, write_mpc3
        from find_planet_openorb.observations import directions_to_observations
        from find_planet_openorb.provenance import verify_installation

        epoch = datetime(2026, 9, 2, tzinfo=UTC)
        observation = directions_to_observations((direction("n1", epoch, "r1", (1.0, 0.0, 0.0), 1.0),))[0]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "anonymous.mpc3"
            write_mpc3(path, (observation,), designation="OBJ000001")
            vendor = PROJECT / ".vendor" / "openorb-1.3.0"
            if not vendor.exists():
                with self.assertRaisesRegex(FileNotFoundError, "verified OpenOrb installation is required"):
                    validate_mpc3_with_openorb(None, path)
            else:
                installation = verify_installation(vendor, PROJECT / "openorb-sources.json")
                validation = validate_mpc3_with_openorb(installation, path)
                self.assertEqual(validation.accepted_records, 1)
                self.assertTrue(validation.converted_path.is_file())


if __name__ == "__main__":
    unittest.main()
