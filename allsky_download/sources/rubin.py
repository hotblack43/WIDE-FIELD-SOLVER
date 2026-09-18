from __future__ import annotations

from datetime import datetime, timezone

from ..model import Candidate, DateRange, Site


UTC = timezone.utc
FILE_ID = "1rk3PsfuUj_9HG8YBR8T2doCgGvOYnBkr"
OBSERVED = datetime(2025, 6, 25, 4, 6, 1, tzinfo=UTC)


class RubinPublicSamplesAdapter:
    """The two-file public teaching set, not Rubin's credentialed live archive."""

    def __init__(self, archive_root: str, sites: tuple[Site, ...] | None = None) -> None:
        self.archive_root = archive_root.rstrip("?")
        self._sites = sites or (
            Site("rubin", "rubin-asc", "Rubin Observatory all-sky camera", "America/Santiago", -30.2446, -70.7494, 2682),
        )

    def sites(self, camera_id: str | None) -> tuple[Site, ...]:
        selected = tuple(site for site in self._sites if camera_id is None or site.camera_id == camera_id)
        if not selected:
            raise ValueError(f"unknown Rubin camera: {camera_id}")
        return selected

    def list_candidates(self, client, site: Site, date_range: DateRange) -> tuple[Candidate, ...]:
        if site not in self._sites:
            raise ValueError(f"site is not configured for Rubin: {site.camera_id}")
        if not date_range.start_utc <= OBSERVED < date_range.end_utc:
            return ()
        url = f"{self.archive_root}?id={FILE_ID}&export=download&confirm=t"
        return (
            Candidate(
                "rubin",
                site.camera_id,
                OBSERVED,
                "EXIF DateTimeOriginal 2025:06:25 04:06:01 +00:00",
                url,
                "asc2506240487.cr2",
                28_412_776,
                {
                    "access_scope": "public two-file teaching set; not continuous archive",
                    "timestamp_convention": "EXIF OffsetTimeOriginal +00:00",
                    "google_drive_file_id": FILE_ID,
                },
            ),
        )
