#!/usr/bin/env python3
"""Build deterministic, allowlisted v0.11.0 release archives."""
from __future__ import annotations

import argparse
import gzip
import hashlib
from pathlib import Path, PurePosixPath
import stat
import tarfile
import zipfile


VERSION = "0.11.0"
ARCHIVE_ROOT = f"wide-field-solver-v{VERSION}"
TAR_NAME = f"{ARCHIVE_ROOT}.tar.gz"
ZIP_NAME = f"{ARCHIVE_ROOT}.zip"
CHECKSUM_NAME = "SHA256SUMS"

ROOT_MAPPINGS = (
    (Path("v11/README.md"), "README.md"),
    (Path("v11/LICENSE"), "LICENSE"),
    (Path("v11/NOTICE.md"), "NOTICE.md"),
    (Path("CITATION.cff"), "CITATION.cff"),
    (Path("go11.sh"), "go11.sh"),
    (Path("go_v0.11.0.sh"), "go_v0.11.0.sh"),
    (Path("v11/demo.sh"), "demo.sh"),
)

V11_SHELL_FILES = (
    "analyse.sh",
    "run.sh",
    "solve.sh",
    "view_fits.sh",
)

V11_PRODUCTION_MODULES = (
    "analyse_image.py",
    "barghini_model.py",
    "point_star_barghini.py",
    "point_star_catalogue_comparison.py",
    "point_star_database.py",
    "point_star_detection.py",
    "point_star_diagnostics.py",
    "point_star_epoch.py",
    "point_star_fits.py",
    "point_star_footprint.py",
    "point_star_gaia.py",
    "point_star_image.py",
    "point_star_joint_epoch.py",
    "point_star_joint_report.py",
    "point_star_metadata.py",
    "point_star_names.py",
    "point_star_photometry.py",
    "point_star_planet_brightness.py",
    "point_star_planet_ephemeris.py",
    "point_star_planet_nondetections.py",
    "point_star_planet_performance.py",
    "point_star_planet_refinement.py",
    "point_star_planet_solar.py",
    "point_star_planets.py",
    "point_star_plotting.py",
    "point_star_raw.py",
    "point_star_refraction.py",
    "point_star_report.py",
    "point_star_science.py",
    "point_star_storage.py",
    "point_star_time_bounds.py",
    "point_star_zenith.py",
)

V11_DATA_FILES = (
    "README.md",
    "display_names.json",
    "minor-planet-reference-1850-2036.npz",
    "planet-reference-1850-2036.npz",
    "stars_gaia_dr3_g75.csv",
    "stars_gaia_dr3_g75.gaia-source.csv",
    "stars_gaia_dr3_g75.provenance.json",
    "stars_tycho2_mag75.csv",
)

V11_DEMO_SCRIPTS = (
    "check_mmto_demo.py",
    "run_mmto_demo.py",
)

V11_DEMO_FILES = (
    "2026_09_19__02_20_01.fits.bz2",
    "baseline.json",
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_DISCOVERED_MODULES = {
    path.name
    for path in (_REPOSITORY_ROOT / "v11").glob("*.py")
    if not path.name.startswith("test_")
}
if _DISCOVERED_MODULES != set(V11_PRODUCTION_MODULES):
    missing = sorted(_DISCOVERED_MODULES - set(V11_PRODUCTION_MODULES))
    stale = sorted(set(V11_PRODUCTION_MODULES) - _DISCOVERED_MODULES)
    raise RuntimeError(
        "review the v0.11.0 production-module allowlist; "
        f"unlisted={missing}, absent={stale}"
    )


def _v11_mapping(relative: str) -> tuple[Path, str]:
    return Path("v11", relative), f"v11/{relative}"


def _all_mappings() -> tuple[tuple[Path, str], ...]:
    mappings = list(ROOT_MAPPINGS)
    mappings.extend(
        _v11_mapping(name)
        for name in (".python-version", "pyproject.toml", "uv.lock")
    )
    mappings.extend(_v11_mapping(name) for name in V11_SHELL_FILES)
    mappings.extend(_v11_mapping(name) for name in V11_PRODUCTION_MODULES)
    mappings.extend(
        _v11_mapping(f"data/{name}") for name in V11_DATA_FILES
    )
    mappings.extend(
        _v11_mapping(f"scripts/{name}") for name in V11_DEMO_SCRIPTS
    )
    mappings.extend(
        _v11_mapping(f"examples/mmto/{name}") for name in V11_DEMO_FILES
    )
    return tuple(mappings)


def _safe_member_name(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name)
        and not name.startswith("/")
        and ".." not in path.parts
        and path.parts[0] == ARCHIVE_ROOT
    )


def _forbidden_member(name: str) -> bool:
    folded = name.lower()
    forbidden = (
        "/test",
        "/docs/",
        "milky_way/input.jpeg",
        ".sqlite",
        "__pycache__",
        "/results/",
        "gobig",
    )
    if any(fragment in folded for fragment in forbidden):
        return True
    versions = {
        part
        for part in PurePosixPath(name).parts
        if part.startswith("v") and part[1:].isdigit()
    }
    return not versions <= {"v11"}


def release_inventory(repo_root: Path) -> dict[Path, str]:
    """Return the reviewed source-to-archive file mapping, failing closed."""
    repo_root = Path(repo_root).resolve()
    inventory: dict[Path, str] = {}
    destinations: set[str] = set()
    for relative_source, relative_destination in _all_mappings():
        source = repo_root / relative_source
        destination = f"{ARCHIVE_ROOT}/{relative_destination}"
        if not source.is_file():
            raise FileNotFoundError(f"required release source is missing: {relative_source}")
        if source in inventory:
            raise ValueError(f"duplicate release source: {relative_source}")
        if destination in destinations:
            raise ValueError(f"duplicate release destination: {destination}")
        if not _safe_member_name(destination) or _forbidden_member(destination):
            raise ValueError(f"unsafe or forbidden release destination: {destination}")
        inventory[source] = destination
        destinations.add(destination)
    return dict(sorted(inventory.items(), key=lambda item: item[1]))


def _source_mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _write_tar(path: Path, inventory: dict[Path, str]) -> None:
    with path.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                for source, destination in inventory.items():
                    info = tarfile.TarInfo(destination)
                    info.size = source.stat().st_size
                    info.mode = _source_mode(source)
                    info.mtime = 0
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    with source.open("rb") as payload:
                        archive.addfile(info, payload)


def _write_zip(path: Path, inventory: dict[Path, str]) -> None:
    with zipfile.ZipFile(
        path, mode="x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for source, destination in inventory.items():
            info = zipfile.ZipInfo(destination, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | _source_mode(source)) << 16
            with source.open("rb") as payload:
                archive.writestr(info, payload.read(), compresslevel=9)


def _archive_names(path: Path) -> list[str]:
    if path.name.endswith(".zip"):
        with zipfile.ZipFile(path) as archive:
            return [info.filename for info in archive.infolist() if not info.is_dir()]
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            return [member.name for member in archive.getmembers() if member.isfile()]
    raise ValueError(f"unsupported archive type: {path}")


def validate_archive(path: Path, expected_names: set[str]) -> None:
    """Independently enforce safe names and an exact archive inventory."""
    names = _archive_names(Path(path))
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate archive member in {path}")
    for name in names:
        if not _safe_member_name(name):
            raise ValueError(f"unsafe archive member: {name}")
        if _forbidden_member(name):
            raise ValueError(f"forbidden archive member: {name}")
    actual = set(names)
    if actual != expected_names:
        missing = sorted(expected_names - actual)
        unexpected = sorted(actual - expected_names)
        raise ValueError(
            f"archive inventory mismatch: missing={missing}, unexpected={unexpected}"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_assets(repo_root: Path, output_dir: Path) -> tuple[Path, Path, Path]:
    """Build and validate the tar, ZIP and checksum assets."""
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        raise NotADirectoryError(f"output directory must already exist: {output_dir}")
    tar_path = output_dir / TAR_NAME
    zip_path = output_dir / ZIP_NAME
    checksum_path = output_dir / CHECKSUM_NAME
    assets = (tar_path, zip_path, checksum_path)
    existing = [path for path in assets if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite release asset: {existing[0]}")

    inventory = release_inventory(Path(repo_root))
    expected = set(inventory.values())
    try:
        _write_tar(tar_path, inventory)
        _write_zip(zip_path, inventory)
        validate_archive(tar_path, expected)
        validate_archive(zip_path, expected)
        lines = [
            f"{_sha256(path)}  {path.name}\n"
            for path in sorted((tar_path, zip_path), key=lambda item: item.name)
        ]
        checksum_path.write_text("".join(lines), encoding="ascii")
    except Exception:
        for path in assets:
            if path.exists():
                path.unlink()
        raise
    return assets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    for path in build_assets(repo_root, args.output_dir):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
