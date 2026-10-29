"""Content-addressed sealing for completed find-planet output directories."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Mapping, Sequence

from .provenance import sha256_file


@dataclass(frozen=True)
class SealVerification:
    valid: bool
    errors: tuple[str, ...]
    product_count: int


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def seal_output(
    output: Path,
    product_paths: Sequence[Path],
    inputs: Mapping[str, str],
) -> Path:
    output = Path(output).resolve(strict=True)
    seal_path = output / "seal.json"
    if seal_path.exists():
        raise FileExistsError(f"output is already sealed: {seal_path}")
    products: dict[str, dict[str, int | str]] = {}
    for raw_path in product_paths:
        path = Path(raw_path).resolve(strict=True)
        if path.parent != output:
            raise ValueError(f"seal product is outside output directory: {path}")
        if path.name in products or path.name == seal_path.name:
            raise ValueError(f"duplicate or reserved seal product: {path.name}")
        products[path.name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
    manifest = {
        "format": "find-planet-seal-v1",
        "inputs": {str(key): str(value) for key, value in sorted(inputs.items())},
        "products": dict(sorted(products.items())),
    }
    _atomic_json(seal_path, manifest)
    return seal_path


def verify_seal(path: Path) -> SealVerification:
    path = Path(path)
    errors: list[str] = []
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return SealVerification(False, (f"seal cannot be read: {error}",), 0)
    products = manifest.get("products")
    if manifest.get("format") != "find-planet-seal-v1" or not isinstance(products, dict):
        return SealVerification(False, ("invalid seal format",), 0)
    for name, record in sorted(products.items()):
        product = path.parent / name
        if not product.is_file():
            errors.append(f"missing product: {name}")
            continue
        if not isinstance(record, dict) or sha256_file(product) != record.get("sha256"):
            errors.append(f"product hash mismatch: {name}")
        elif product.stat().st_size != record.get("bytes"):
            errors.append(f"product byte-count mismatch: {name}")
    return SealVerification(not errors, tuple(errors), len(products))
