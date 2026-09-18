from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo

from ..http import HttpClient
from ..model import Candidate, DateRange, Site
from .common import parse_directory_index


UTC = timezone.utc
ARIZONA = ZoneInfo("America/Phoenix")
_RAW_NAME = re.compile(
    r"(?P<year>\d{4})_(?P<month>\d{2})_(?P<day>\d{2})__"
    r"(?P<hour>\d{2})_(?P<minute>\d{2})_(?P<second>\d{2})\."
    r"(?:fits|fit|fts)\.bz2"
)
_DEFAULT_SITE = Site(
    "mmto",
    "mmto-skycam",
    "MMT Observatory all-sky camera",
    "America/Phoenix",
    31.6866666667,
    -110.8841666667,
    2616.0,
)


class MmtoAdapter:
    def __init__(self, archive_root: str, sites: tuple[Site, ...] | None = None) -> None:
        self.archive_root = archive_root.rstrip("/") + "/"
        self._sites = sites or (_DEFAULT_SITE,)

    def sites(self, camera_id: str | None) -> tuple[Site, ...]:
        if camera_id is None:
            return self._sites
        matches = tuple(site for site in self._sites if site.camera_id == camera_id)
        if not matches:
            raise ValueError(f"unknown MMTO camera: {camera_id}")
        return matches

    def parse_listing(self, html: str, archive_date: date) -> tuple[Candidate, ...]:
        listing_url = f"{self.archive_root}{archive_date.isoformat()}/"
        bucket_start = datetime.combine(archive_date, time(12), ARIZONA)
        bucket_end = bucket_start + timedelta(days=1)
        candidates: list[Candidate] = []
        for entry in parse_directory_index(html, listing_url):
            match = _RAW_NAME.fullmatch(entry.name)
            if match is None:
                continue
            values = {key: int(value) for key, value in match.groupdict().items()}
            observed_local = datetime(
                values["year"],
                values["month"],
                values["day"],
                values["hour"],
                values["minute"],
                values["second"],
                tzinfo=ARIZONA,
            )
            if not bucket_start <= observed_local < bucket_end:
                continue
            candidates.append(
                Candidate(
                    "mmto",
                    "mmto-skycam",
                    observed_local.astimezone(UTC),
                    observed_local.isoformat(),
                    entry.url.rstrip("/"),
                    entry.name,
                    entry.size_bytes,
                    {
                        "archive_bucket": archive_date.isoformat(),
                        "compression": "bzip2",
                        "timestamp_convention": (
                            "filename local America/Phoenix; FITS DATE-OBS "
                            "verified separately"
                        ),
                    },
                )
            )
        return tuple(sorted(candidates, key=lambda item: (item.observed_at, item.url)))

    def _bucket_dates(self, date_range: DateRange) -> tuple[date, ...]:
        local_start = date_range.start_utc.astimezone(ARIZONA)
        bucket_date = local_start.date()
        if local_start.timetz().replace(tzinfo=None) < time(12):
            bucket_date -= timedelta(days=1)
        dates: list[date] = []
        while True:
            bucket_start = datetime.combine(bucket_date, time(12), ARIZONA)
            if bucket_start.astimezone(UTC) >= date_range.end_utc:
                break
            if (bucket_start + timedelta(days=1)).astimezone(UTC) > date_range.start_utc:
                dates.append(bucket_date)
            bucket_date += timedelta(days=1)
        return tuple(dates)

    def list_candidates(
        self, client: HttpClient, site: Site, date_range: DateRange
    ) -> tuple[Candidate, ...]:
        if site not in self._sites:
            raise ValueError(f"site is not configured for MMTO: {site.camera_id}")
        items: list[Candidate] = []
        for bucket_date in self._bucket_dates(date_range):
            url = f"{self.archive_root}{bucket_date.isoformat()}/"
            items.extend(self.parse_listing(client.get_text(url), bucket_date))
        return tuple(
            item
            for item in items
            if date_range.start_utc <= item.observed_at < date_range.end_utc
        )
