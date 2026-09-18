from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .model import Candidate


RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class TransferError(RuntimeError):
    """A bounded HTTP operation could not be completed."""


class PermanentHttpError(TransferError):
    """The server rejected a request in a way that should not be retried."""


@dataclass(frozen=True, slots=True)
class DownloadedFile:
    path: Path
    size_bytes: int
    sha256: str


class HttpClient:
    def __init__(
        self,
        timeout: float = 45,
        retries: int = 3,
        delay: float = 0.5,
        user_agent: str = "WIDE-FIELD-SOLVER-raw-allsky/0.1",
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if retries < 0:
            raise ValueError("retries must be nonnegative")
        if delay < 0:
            raise ValueError("delay must be nonnegative")
        self.timeout = timeout
        self.retries = retries
        self.delay = delay
        self.user_agent = user_agent

    def _request(self, url: str):
        request = Request(
            url,
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "identity"},
        )
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                return urlopen(request, timeout=self.timeout)
            except HTTPError as exc:
                if exc.code not in RETRYABLE_STATUS:
                    raise PermanentHttpError(f"HTTP {exc.code} for {url}") from exc
                last_error = exc
            except (TimeoutError, URLError, OSError) as exc:
                last_error = exc
            if attempt < self.retries:
                time.sleep(min(self.delay * (2**attempt), 16))
        raise TransferError(f"request failed after {self.retries + 1} attempts: {url}: {last_error}") from last_error

    def get_text(self, url: str) -> str:
        with self._request(url) as response:
            body = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
        return body.decode(charset)

    def download_atomic(self, candidate: Candidate, destination: Path) -> DownloadedFile:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with self._request(candidate.url) as response:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    delete=False,
                    dir=destination.parent,
                    prefix=destination.name + ".part-",
                ) as output:
                    temporary = Path(output.name)
                    digest = hashlib.sha256()
                    size = 0
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                    output.flush()
                    os.fsync(output.fileno())
            if candidate.size_bytes is not None and size != candidate.size_bytes:
                raise ValueError(
                    f"size mismatch for {candidate.url}: expected {candidate.size_bytes}, got {size}"
                )
            os.replace(temporary, destination)
            temporary = None
            return DownloadedFile(destination, size, digest.hexdigest())
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
