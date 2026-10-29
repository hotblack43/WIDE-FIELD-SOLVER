"""Read-only input and fresh-output guards for find-planet runs."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_sqlite_read_only(path: Path) -> sqlite3.Connection:
    resolved = Path(path).resolve(strict=True)
    return sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)


def new_output_directory(results_root: Path, run_id: str) -> Path:
    output = Path(results_root) / run_id
    output.mkdir(parents=True, exist_ok=False)
    return output
