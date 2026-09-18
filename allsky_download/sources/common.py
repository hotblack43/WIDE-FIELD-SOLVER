from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import posixpath
import re
from typing import Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

from ..http import HttpClient
from ..model import Candidate, DateRange, Site


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    name: str
    url: str
    is_directory: bool
    size_bytes: int | None


class SourceAdapter(Protocol):
    def sites(self, camera_id: str | None) -> tuple[Site, ...]: ...

    def list_candidates(
        self, client: HttpClient, site: Site, date_range: DateRange
    ) -> tuple[Candidate, ...]: ...


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str, str]] = []
        self._href: str | None = None
        self._label: list[str] = []
        self._tail: list[str] = []
        self._inside_anchor = False

    def _finish(self) -> None:
        if self._href is not None:
            self.links.append((self._href, "".join(self._label), "".join(self._tail)))
        self._href = None
        self._label = []
        self._tail = []
        self._inside_anchor = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        self._finish()
        values = dict(attrs)
        self._href = values.get("href")
        self._inside_anchor = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a":
            self._inside_anchor = False

    def handle_data(self, data: str) -> None:
        if self._href is None:
            return
        (self._label if self._inside_anchor else self._tail).append(data)

    def close(self) -> None:
        super().close()
        self._finish()


_EXACT_SIZE = re.compile(r"(?:^|[ \t])(\d+)[ \t]*(?:\r?\n|$)")


def parse_directory_index(html: str, listing_url: str) -> tuple[DirectoryEntry, ...]:
    """Return safe direct children from an HTML directory listing.

    Human-readable sizes such as ``6.9M`` are deliberately reported as unknown;
    only integer byte counts are safe to validate after a transfer.
    """

    base = urlsplit(listing_url)
    if base.scheme not in {"http", "https"} or not base.netloc:
        raise ValueError("listing URL must be an absolute HTTP(S) URL")
    base_path = base.path if base.path.endswith("/") else base.path + "/"
    parser = _LinkParser()
    parser.feed(html)
    parser.close()

    entries: list[DirectoryEntry] = []
    for href, _label, tail in parser.links:
        reference = urlsplit(href)
        if reference.query or reference.fragment:
            continue
        resolved = urlsplit(urljoin(listing_url, href))
        if (resolved.scheme.lower(), resolved.netloc.lower()) != (
            base.scheme.lower(),
            base.netloc.lower(),
        ):
            continue
        is_directory = resolved.path.endswith("/")
        child_path = resolved.path.rstrip("/")
        if posixpath.dirname(child_path) + "/" != base_path:
            continue
        name = posixpath.basename(child_path)
        if not name or name in {".", ".."}:
            continue
        sizes = _EXACT_SIZE.findall(tail)
        size_bytes = int(sizes[-1]) if sizes else None
        clean_path = child_path + ("/" if is_directory else "")
        clean_url = urlunsplit((resolved.scheme, resolved.netloc, clean_path, "", ""))
        entries.append(DirectoryEntry(name, clean_url, is_directory, size_bytes))
    return tuple(entries)
