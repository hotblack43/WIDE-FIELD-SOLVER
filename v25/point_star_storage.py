"""Lossless post-analysis storage maintenance; never a scientific input."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import zipfile


INTERMEDIATES = ('joint_candidate_solution', 'stellar_only_products')
ARCHIVE = 'intermediate_products.zip'
TEXT_SUFFIXES = ('.json', '.csv', '.txt')


def _archive_names(archive):
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise ValueError('Duplicate intermediate archive members')
    for name in names:
        parts = PurePosixPath(name).parts
        if (len(parts) < 2 or parts[0] not in INTERMEDIATES or
                '..' in parts or str(PurePosixPath(name)) != name or name.endswith('/')):
            raise ValueError(f'Invalid intermediate archive member: {name}')
    return names


def text_snapshots(analysis):
    """Read loose and archived text with the same original logical paths."""
    analysis = Path(analysis)
    snapshots = {}
    path = analysis/ARCHIVE
    if path.is_symlink():
        raise ValueError('Refusing symlink intermediate archive')
    if path.is_file():
        with zipfile.ZipFile(path) as archive:
            for name in _archive_names(archive):
                if PurePosixPath(name).suffix in TEXT_SUFFIXES:
                    snapshots[name] = archive.read(name)
    for path in sorted(analysis.rglob('*')):
        if path.is_file() and not path.is_symlink() and path.suffix in TEXT_SUFFIXES:
            name, content = path.relative_to(analysis).as_posix(), path.read_bytes()
            if name in snapshots and snapshots[name] != content:
                raise ValueError(f'Loose/archived product conflict: {name}')
            snapshots[name] = content
    return sorted(snapshots.items())


def _digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def archive_intermediates(analysis):
    """Archive adopted, completed staging; verify bytes before removing originals.

    Call only after all scientific writers and database recording finish. Failed
    or unadopted staging stays loose. An existing archive is never overwritten:
    an interrupted cleanup can resume only for byte-identical remaining files.
    Final products, report and original observations are not touched.
    """
    analysis = Path(analysis).resolve()
    record = analysis/'joint_epoch.json'
    if not record.is_file() or json.loads(record.read_text()).get('adopted') is not True:
        return {'before_bytes': 0, 'after_bytes': 0, 'archived': False}
    files, directories = [], []
    for name in INTERMEDIATES:
        directory = analysis/name
        if directory.is_symlink():
            raise ValueError('Refusing symlink intermediate directory')
        if not directory.exists():
            continue
        if not directory.is_dir():
            raise ValueError('Intermediate path is not a directory')
        directories.append(directory)
        for path in sorted(directory.rglob('*')):
            if path.is_symlink():
                raise ValueError('Refusing symlink in intermediate evidence')
            if path.is_file():
                files.append(path)
            elif path.is_dir():
                directories.append(path)
            else:
                raise ValueError('Unsupported intermediate file type')
    if not files:
        return {'before_bytes': 0, 'after_bytes': 0, 'archived': False}
    target = analysis/ARCHIVE
    if target.is_symlink():
        raise ValueError('Refusing symlink intermediate archive')
    hashes = {p.relative_to(analysis).as_posix(): _digest(p) for p in files}
    before = sum(p.stat().st_size for p in files)
    temporary = None
    try:
        if target.exists():
            candidate = target
        else:
            fd, name = tempfile.mkstemp(prefix='.intermediate-', suffix='.zip', dir=analysis)
            os.close(fd)
            temporary = candidate = Path(name)
            with zipfile.ZipFile(candidate, 'w', compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=6, allowZip64=True) as archive:
                for path in files:
                    archive.write(path, path.relative_to(analysis).as_posix())
            with candidate.open('rb') as handle:
                os.fsync(handle.fileno())
        with zipfile.ZipFile(candidate) as archive:
            names = set(_archive_names(archive))
            if temporary is not None and names != set(hashes):
                raise ValueError('Incomplete intermediate archive')
            for name, digest in hashes.items():
                if name not in names or hashlib.sha256(archive.read(name)).hexdigest() != digest:
                    raise ValueError(f'Intermediate archive verification failed: {name}')
        for path in files:
            if path.is_symlink() or _digest(path) != hashes[path.relative_to(analysis).as_posix()]:
                raise ValueError('Intermediate evidence changed while archiving')
        if temporary is not None:
            # Exclusive publication: no overwrite if another archiver got here.
            os.link(temporary, target)
            directory_fd = os.open(analysis, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        for path in files:
            path.unlink()
        for path in sorted(directories, key=lambda p: len(p.parts), reverse=True):
            path.rmdir()
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {'before_bytes': before, 'after_bytes': target.stat().st_size, 'archived': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, help='Migrate/deduplicate and VACUUM this existing database')
    parser.add_argument('--analysis', type=Path, help='Archive intermediate evidence in this completed run')
    args = parser.parse_args()
    if not args.database and not args.analysis:
        parser.error('provide --database and/or --analysis')
    result = {}
    if args.database:
        from point_star_database import compact_database
        result['database'] = compact_database(args.database)
    if args.analysis:
        result['intermediates'] = archive_intermediates(args.analysis)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
