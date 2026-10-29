from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


EXPECTED_RELEASE = "v1.3.0"
EXPECTED_COMMIT = "945178476f016dae8f3981b54a937f61de81360f"
EXPECTED_LICENSE = "GPL-3.0-only"


@dataclass(frozen=True)
class OpenOrbInstallation:
    root: Path
    executable: Path
    data_directory: Path
    configuration: Path
    executable_sha256: str
    build_receipt: Path
    data_receipt: Path
    release: str
    commit: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def open_sqlite_read_only(path: Path) -> sqlite3.Connection:
    resolved = path.resolve(strict=True)
    return sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro&immutable=1", uri=True)


def new_output_directory(root: Path, run_id: str) -> Path:
    if not run_id or run_id in {".", ".."} or Path(run_id).name != run_id:
        raise ValueError(f"invalid run identifier: {run_id!r}")
    root.mkdir(parents=True, exist_ok=True)
    output = root / run_id
    output.mkdir(mode=0o755)
    return output


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _verify_receipt(vendor_root: Path, receipt_path: Path) -> dict[str, Any]:
    receipt = _load_json_object(receipt_path)
    if receipt.get("release") != EXPECTED_RELEASE:
        raise ValueError(f"unexpected OpenOrb release in {receipt_path}")
    if receipt.get("commit") != EXPECTED_COMMIT:
        raise ValueError(f"unexpected OpenOrb commit in {receipt_path}")
    if receipt.get("license") != EXPECTED_LICENSE:
        raise ValueError(f"unexpected OpenOrb license in {receipt_path}")
    files = receipt.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError(f"missing file hashes in {receipt_path}")
    for relative_name, expected_sha in files.items():
        if not isinstance(relative_name, str) or not isinstance(expected_sha, str):
            raise ValueError(f"malformed file hash in {receipt_path}")
        candidate = (vendor_root / relative_name).resolve()
        try:
            candidate.relative_to(vendor_root.resolve())
        except ValueError as error:
            raise ValueError(f"receipt path escapes vendor root: {relative_name}") from error
        if not candidate.is_file() or sha256_file(candidate) != expected_sha:
            raise ValueError(f"OpenOrb file hash mismatch: {relative_name}")
    return receipt


def verify_installation(vendor_root: Path, sources_manifest: Path) -> OpenOrbInstallation:
    vendor_root = vendor_root.resolve(strict=True)
    manifest = _load_json_object(sources_manifest.resolve(strict=True))
    if manifest.get("release") != EXPECTED_RELEASE or manifest.get("commit") != EXPECTED_COMMIT:
        raise ValueError("source manifest does not pin the approved OpenOrb release")
    license_record = manifest.get("license")
    if not isinstance(license_record, dict) or license_record.get("spdx") != EXPECTED_LICENSE:
        raise ValueError("source manifest does not pin the approved OpenOrb license")
    build_receipt = vendor_root / "openorb-build-receipt.json"
    data_receipt = vendor_root / "openorb-data-receipt.json"
    build = _verify_receipt(vendor_root, build_receipt)
    data = _verify_receipt(vendor_root, data_receipt)
    if build.get("upstream_tests") not in {"passed", "passed_with_compute_version_test_excluded"}:
        raise ValueError("OpenOrb upstream tests were not recorded as passed")
    if data.get("de441_test") != "passed":
        raise ValueError("DE441 validation was not recorded as passed")
    executable = vendor_root / "bin" / "oorb"
    data_directory = vendor_root / "data"
    configuration = vendor_root / "oorb.conf"
    bundled_data = manifest.get("bundled_data")
    if not isinstance(bundled_data, dict):
        raise ValueError("source manifest has no bundled-data hashes")
    for name in ("OBSCODE.dat", "TAI-UTC.dat", "ET-UT.dat"):
        path = data_directory / name
        if bundled_data.get(name) != sha256_file(path):
            raise ValueError(f"source manifest data hash mismatch: {name}")
    if not executable.is_file() or not executable.stat().st_mode & 0o111:
        raise ValueError("receipt-hashed local OpenOrb executable is absent or not executable")
    if not configuration.is_file():
        raise ValueError("receipt-hashed local OpenOrb configuration is absent")
    for required in ("OBSCODE.dat", "TAI-UTC.dat", "ET-UT.dat", "de441.dat"):
        if not (data_directory / required).is_file():
            raise ValueError(f"required OpenOrb data file is absent: {required}")
    executable_sha256 = sha256_file(executable)
    hashed_files = build.get("files", {}) | data.get("files", {})
    if hashed_files.get("bin/oorb") != executable_sha256:
        raise ValueError("local OpenOrb executable is not covered by its receipts")
    if hashed_files.get("oorb.conf") != sha256_file(configuration):
        raise ValueError("local OpenOrb configuration is not covered by its receipts")
    return OpenOrbInstallation(
        root=vendor_root,
        executable=executable,
        data_directory=data_directory,
        configuration=configuration,
        executable_sha256=executable_sha256,
        build_receipt=build_receipt,
        data_receipt=data_receipt,
        release=EXPECTED_RELEASE,
        commit=EXPECTED_COMMIT,
    )
