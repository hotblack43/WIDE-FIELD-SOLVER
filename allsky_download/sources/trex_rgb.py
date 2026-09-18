from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import re

from ..http import HttpClient
from ..model import Candidate, DateRange, Site
from .common import parse_directory_index


UTC = timezone.utc
_CAMERA_NAME = re.compile(r"[a-z0-9]+_rgb-\d+")
_HOUR_NAME = re.compile(r"ut(?P<hour>\d{2})")
_DEFAULT_SITES = (
    Site("trex_rgb", "atha_rgb-07", "Athabasca, AB, Canada", "America/Edmonton", 54.6, -113.64, None),
    Site("trex_rgb", "fsmi_rgb-09", "Fort Smith, NWT, Canada", "America/Yellowknife", 60.03, -111.93, None),
    Site("trex_rgb", "gill_rgb-04", "Gillam, MB, Canada", "America/Winnipeg", 56.38, -94.64, None),
    Site("trex_rgb", "luck_rgb-03", "Lucky Lake, SK, Canada", "America/Regina", 51.15, -107.26, None),
    Site("trex_rgb", "pina_rgb-02", "Pinawa, MB, Canada", "America/Winnipeg", 50.26, -95.87, None),
    Site("trex_rgb", "pina_rgb-05", "Pinawa, MB, Canada", "America/Winnipeg", 50.26, -95.87, None),
    Site("trex_rgb", "rabb_rgb-06", "Rabbit Lake, SK, Canada", "America/Regina", 58.23, -103.68, None),
    Site("trex_rgb", "yknf_rgb-08", "Yellowknife, NWT, Canada", "America/Yellowknife", 62.52, -114.31, None),
)


class TrexRgbAdapter:
    def __init__(self, archive_root: str, sites: tuple[Site, ...] | None = None) -> None:
        self.archive_root = archive_root.rstrip("/") + "/"
        self._sites = sites or _DEFAULT_SITES

    def sites(self, camera_id: str | None) -> tuple[Site, ...]:
        if camera_id is None:
            return self._sites
        matches = tuple(site for site in self._sites if site.camera_id == camera_id)
        if not matches:
            raise ValueError(f"unknown TREx-RGB camera: {camera_id}")
        return matches

    def parse_day_listing(self, html: str, listing_url: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                entry.name
                for entry in parse_directory_index(html, listing_url)
                if entry.is_directory and _CAMERA_NAME.fullmatch(entry.name)
            )
        )

    def parse_camera_listing(self, html: str, listing_url: str) -> tuple[int, ...]:
        hours: list[int] = []
        for entry in parse_directory_index(html, listing_url):
            match = _HOUR_NAME.fullmatch(entry.name) if entry.is_directory else None
            if match is not None and 0 <= int(match.group("hour")) <= 23:
                hours.append(int(match.group("hour")))
        return tuple(sorted(set(hours)))

    def parse_hour_listing(
        self, html: str, camera_id: str, listing_url: str
    ) -> tuple[Candidate, ...]:
        pattern = re.compile(
            rf"(?P<stamp>\d{{8}}_\d{{4}})_{re.escape(camera_id)}_full\.h5"
        )
        candidates: list[Candidate] = []
        for entry in parse_directory_index(html, listing_url):
            match = pattern.fullmatch(entry.name)
            if match is None:
                continue
            observed = datetime.strptime(match.group("stamp"), "%Y%m%d_%H%M").replace(
                tzinfo=UTC
            )
            expected_suffix = (
                f"/{observed:%Y/%m/%d}/{camera_id}/ut{observed:%H}/"
            )
            if not listing_url.rstrip("/").endswith(expected_suffix.rstrip("/")):
                continue
            candidates.append(
                Candidate(
                    "trex_rgb",
                    camera_id,
                    observed,
                    match.group("stamp") + " UTC",
                    entry.url,
                    entry.name,
                    entry.size_bytes,
                    {
                        "dataset": "TREX_RGB_RAW_NOMINAL",
                        "timestamp_convention": "filename UTC; one-minute HDF5 bundle",
                    },
                )
            )
        return tuple(sorted(candidates, key=lambda item: (item.observed_at, item.url)))

    @staticmethod
    def _utc_dates(date_range: DateRange) -> tuple[date, ...]:
        current = date_range.start_utc.astimezone(UTC).date()
        final = (date_range.end_utc.astimezone(UTC) - timedelta(microseconds=1)).date()
        dates: list[date] = []
        while current <= final:
            dates.append(current)
            current += timedelta(days=1)
        return tuple(dates)

    def list_candidates(
        self, client: HttpClient, site: Site, date_range: DateRange
    ) -> tuple[Candidate, ...]:
        if site not in self._sites:
            raise ValueError(f"site is not configured for TREx-RGB: {site.camera_id}")
        items: list[Candidate] = []
        for utc_date in self._utc_dates(date_range):
            day_url = f"{self.archive_root}{utc_date:%Y/%m/%d}/"
            cameras = self.parse_day_listing(client.get_text(day_url), day_url)
            if site.camera_id not in cameras:
                continue
            camera_url = f"{day_url}{site.camera_id}/"
            hours = self.parse_camera_listing(client.get_text(camera_url), camera_url)
            for hour in hours:
                hour_start = datetime.combine(utc_date, time(hour), UTC)
                if not (
                    hour_start < date_range.end_utc
                    and hour_start + timedelta(hours=1) > date_range.start_utc
                ):
                    continue
                hour_url = f"{camera_url}ut{hour:02d}/"
                items.extend(
                    self.parse_hour_listing(
                        client.get_text(hour_url), site.camera_id, hour_url
                    )
                )
        return tuple(
            item
            for item in items
            if date_range.start_utc <= item.observed_at < date_range.end_utc
        )
