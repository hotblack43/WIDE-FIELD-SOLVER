"""Tests for fail-open MMTO summit-weather selection."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import unittest
from urllib.error import URLError
from urllib.parse import parse_qs

from scripts.mmto_weather import MmtoWeatherHistory, WeatherSample


UTC = timezone.utc
OBSERVED = datetime(2026, 10, 22, 6, 40, 16, tzinfo=UTC)


def sample(
    humidity_percent: float,
    *,
    age_seconds: float = 0.0,
    sensor: str = "vaisala2_relative_humidity",
) -> WeatherSample:
    return WeatherSample(
        sensor=sensor,
        observed_utc=OBSERVED - timedelta(seconds=age_seconds),
        humidity_percent=humidity_percent,
    )


class MmtoWeatherDecisionTests(unittest.TestCase):
    def test_humidity_below_threshold_is_accepted(self):
        decision = MmtoWeatherHistory((sample(79.999),)).decide(OBSERVED)

        self.assertEqual(decision.status, "accept")
        self.assertEqual(decision.humidity_percent, 79.999)

    def test_humidity_equal_to_threshold_is_skipped(self):
        decision = MmtoWeatherHistory((sample(80.0),)).decide(OBSERVED)

        self.assertEqual(decision.status, "skip")
        self.assertEqual(decision.reason, "humidity_at_or_above_limit")

    def test_sample_exactly_at_maximum_age_is_fresh(self):
        decision = MmtoWeatherHistory((sample(65.0, age_seconds=120.0),)).decide(
            OBSERVED
        )

        self.assertEqual(decision.status, "accept")
        self.assertEqual(decision.age_seconds, 120.0)

    def test_sample_older_than_maximum_age_fails_open(self):
        decision = MmtoWeatherHistory((sample(95.0, age_seconds=120.001),)).decide(
            OBSERVED
        )

        self.assertEqual(decision.status, "unknown")
        self.assertIsNone(decision.humidity_percent)
        self.assertEqual(decision.reason, "no_fresh_sample")

    def test_larger_of_two_fresh_sensor_readings_controls_decision(self):
        history = MmtoWeatherHistory(
            (
                sample(72.0, sensor="vaisala2_relative_humidity"),
                sample(81.0, sensor="vaisala4_relative_humidity"),
            )
        )

        decision = history.decide(OBSERVED)

        self.assertEqual(decision.status, "skip")
        self.assertEqual(decision.humidity_percent, 81.0)
        self.assertEqual(decision.sensor, "vaisala4_relative_humidity")


class FakeResponse:
    def __init__(self, payload: object):
        self.body = (
            payload
            if isinstance(payload, bytes)
            else json.dumps(payload).encode("utf-8")
        )

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        return False

    def read(self) -> bytes:
        return self.body


class MmtoWeatherRetrievalTests(unittest.TestCase):
    def test_fetch_combines_both_sensor_histories_and_uses_millisecond_epochs(self):
        captured: list[tuple[str, dict[str, list[str]], float]] = []
        payloads = {
            "vaisala2_relative_humidity": [
                {"timestamp": 1792651216224, "value": 72.0}
            ],
            "vaisala4_relative_humidity": [
                {"timestamp": 1792651217224, "value": 81.0}
            ],
        }

        def opener(request, timeout):
            fields = parse_qs(request.data.decode("ascii"))
            sensor = fields["fields"][0]
            captured.append((request.full_url, fields, timeout))
            return FakeResponse(payloads[sensor])

        history = MmtoWeatherHistory.fetch(
            OBSERVED - timedelta(minutes=5),
            OBSERVED + timedelta(minutes=5),
            opener=opener,
            timeout=7.5,
        )

        self.assertEqual(len(history.samples), 2)
        self.assertEqual(
            history.samples[0].observed_utc,
            datetime(2026, 10, 22, 6, 40, 16, 224000, tzinfo=UTC),
        )
        self.assertEqual({call[1]["table"][0] for call in captured}, {"measurements"})
        self.assertEqual({call[2] for call in captured}, {7.5})
        self.assertTrue(
            all(
                url == "https://api.mmto.arizona.edu/APIv1/history"
                for url, _fields, _timeout in captured
            )
        )

    def test_one_failed_sensor_keeps_the_other_sensor_available(self):
        def opener(request, _timeout):
            sensor = parse_qs(request.data.decode("ascii"))["fields"][0]
            if sensor == "vaisala4_relative_humidity":
                raise URLError("sensor unavailable")
            return FakeResponse(
                [{"timestamp": int(OBSERVED.timestamp() * 1000), "value": 55.0}]
            )

        history = MmtoWeatherHistory.fetch(
            OBSERVED - timedelta(minutes=1),
            OBSERVED + timedelta(minutes=1),
            opener=opener,
        )

        self.assertEqual(history.decide(OBSERVED).status, "accept")
        self.assertEqual(len(history.errors), 1)
        self.assertIn("vaisala4_relative_humidity", history.errors[0])

    def test_both_failed_sensors_produce_unknown_decision(self):
        def opener(_request, _timeout):
            raise TimeoutError("weather timeout")

        history = MmtoWeatherHistory.fetch(
            OBSERVED - timedelta(minutes=1),
            OBSERVED + timedelta(minutes=1),
            opener=opener,
        )

        self.assertEqual(history.decide(OBSERVED).status, "unknown")
        self.assertEqual(len(history.errors), 2)

    def test_malformed_json_and_invalid_values_fail_open(self):
        calls = 0

        def opener(_request, _timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                return FakeResponse(b"not-json")
            return FakeResponse(
                [
                    {"timestamp": int(OBSERVED.timestamp() * 1000), "value": -1},
                    {"timestamp": int(OBSERVED.timestamp() * 1000), "value": 101},
                    {"timestamp": "bad", "value": 50},
                    {"timestamp": int(OBSERVED.timestamp() * 1000), "value": "nan"},
                ]
            )

        history = MmtoWeatherHistory.fetch(
            OBSERVED - timedelta(minutes=1),
            OBSERVED + timedelta(minutes=1),
            opener=opener,
        )

        self.assertEqual(history.decide(OBSERVED).status, "unknown")
        self.assertEqual(history.samples, ())
        self.assertEqual(len(history.errors), 5)

    def test_empty_sensor_arrays_produce_unknown_decision(self):
        history = MmtoWeatherHistory.fetch(
            OBSERVED - timedelta(minutes=1),
            OBSERVED + timedelta(minutes=1),
            opener=lambda _request, _timeout: FakeResponse([]),
        )

        self.assertEqual(history.decide(OBSERVED).status, "unknown")
        self.assertEqual(history.errors, ())


if __name__ == "__main__":
    unittest.main()
