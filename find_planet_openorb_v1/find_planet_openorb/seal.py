from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_anonymous_seal(path: Path, files: Iterable[Path], status: str) -> str:
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    records = []
    for candidate in sorted((Path(value).resolve() for value in files), key=str):
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        records.append({"path": str(candidate), "bytes": candidate.stat().st_size, "sha256": sha256_file(candidate)})
    payload = {"schema": 1, "anonymous_status": status, "files": records}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    seal = hashlib.sha256(canonical).hexdigest()
    payload["seal_sha256"] = seal
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)
    return seal
