"""Structured, non-scientific telemetry for the v7 planet search."""
from __future__ import annotations

from dataclasses import dataclass, field
import time


@dataclass
class PlanetSearchPerformance:
    requested_workers: int = 1
    used_workers: int = 1
    cache: dict = field(default_factory=dict)
    clock: object = time.perf_counter
    seconds: dict[str, float] = field(default_factory=dict)
    providers: dict[str, int] = field(default_factory=lambda: {
        'interpolated_calls': 0, 'interpolated_dates': 0,
        'exact_calls': 0, 'exact_dates': 0})
    counts: dict[str, int] = field(default_factory=lambda: {
        'refined_visits': 0, 'joint_trials': 0,
        'source_candidates': 0, 'retained_candidates': 0})
    _started: dict[str, float] = field(default_factory=dict, init=False)

    def start(self, stage: str) -> None:
        if stage in self._started:
            raise ValueError(f'Performance stage is already running: {stage}')
        self._started[stage] = float(self.clock())

    def finish(self, stage: str) -> float:
        if stage not in self._started:
            raise ValueError(f'Performance stage was not started: {stage}')
        elapsed = float(self.clock())-self._started.pop(stage)
        self.seconds[stage] = self.seconds.get(stage, 0.)+elapsed
        return elapsed

    def merge_worker(self, result) -> None:
        for key, value in result.counters.items():
            self.providers[key] = self.providers.get(key, 0)+int(value)

    def serialise(self, *, total_planet_stage: float | None = None) -> dict:
        if self._started:
            raise ValueError('Cannot serialize performance while a stage is running')
        seconds = {key: float(value) for key, value in self.seconds.items()}
        if total_planet_stage is not None:
            seconds['total_planet_stage'] = float(total_planet_stage)
        return {
            'schema_version': 1,
            'cache': dict(self.cache),
            'workers': {'requested': int(self.requested_workers),
                        'used': int(self.used_workers)},
            'seconds': seconds,
            'providers': {key: int(value) for key, value in self.providers.items()},
            'counts': {key: int(value) for key, value in self.counts.items()},
        }
