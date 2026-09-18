"""Append saved v7 evidence to SQLite after analysis; never a solver input.

Every call creates a new run, even for identical inputs or products. CSV values
remain strings in JSON so catalogue IDs, NaN spellings and quality flags survive
exactly. Raw JSON/CSV/TXT bytes are retained as well as queryable CSV rows.
"""
from contextlib import closing
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import uuid


APPLICATION_ID = 0x57465336
SCHEMA_VERSION = 1
SCHEMA = (
    '''CREATE TABLE runs (
        run_id TEXT PRIMARY KEY, recorded_at_utc TEXT NOT NULL,
        source_path TEXT NOT NULL, source_sha256 TEXT, analysis_path TEXT NOT NULL,
        exit_code INTEGER NOT NULL, error TEXT, solver_version TEXT,
        catalogue_sha256 TEXT, solver_status TEXT, result_json TEXT,
        recorder_sha256 TEXT NOT NULL, source_manifest_json TEXT
    )''',
    '''CREATE TABLE products (
        run_id TEXT NOT NULL REFERENCES runs(run_id), product TEXT NOT NULL,
        sha256 TEXT NOT NULL, content BLOB NOT NULL,
        PRIMARY KEY (run_id, product)
    )''',
    '''CREATE TABLE measurements (
        run_id TEXT NOT NULL, product TEXT NOT NULL, row_number INTEGER NOT NULL,
        star_id TEXT, detection_id TEXT, values_json TEXT NOT NULL,
        PRIMARY KEY (run_id, product, row_number),
        FOREIGN KEY (run_id, product) REFERENCES products(run_id, product)
    )''',
    'CREATE INDEX measurement_star ON measurements(star_id, product, run_id)',
    'CREATE INDEX measurement_detection ON measurements(run_id, product, detection_id)',
    'CREATE INDEX run_source ON runs(source_sha256)',
    '''CREATE VIEW star_measurements AS
        SELECT a.run_id, a.star_id, a.detection_id, r.source_path, r.source_sha256,
               r.analysis_path, r.recorded_at_utc, r.exit_code, r.catalogue_sha256,
               a.values_json AS astrometry_json,
               p.values_json AS photometry_json, d.values_json AS detection_json
        FROM measurements a JOIN runs r USING(run_id)
        LEFT JOIN measurements p ON p.run_id=a.run_id
            AND p.product='stellar_photometry.csv'
            AND p.detection_id=a.detection_id AND p.star_id=a.star_id
        LEFT JOIN measurements d ON d.run_id=a.run_id
            AND d.product='dots/star_candidates.csv' AND d.detection_id=a.detection_id
        WHERE a.product='star_coordinates.csv'
    ''',
)


def append_run(database, analysis, image, *, exit_code=0, error=None):
    """Atomically append one run and every available textual scientific product.

Partial/failed analyses are recorded too. No de-duplication, quality cut, or
catalogue/name reassignment is performed. Binary image/FITS/PDF files remain in
the analysis directory identified by runs.analysis_path.
"""
    database, analysis, image = (Path(p).resolve() for p in (database, analysis, image))
    if database == analysis or analysis in database.parents:
        raise ValueError('Keep the database outside the analysis directory')
    snapshots = []
    for path in sorted(analysis.rglob('*')):
        if path.is_file() and not path.is_symlink() and path.suffix in ('.json', '.csv', '.txt'):
            snapshots.append((path.relative_to(analysis).as_posix(), path.read_bytes()))
    result_text = next((content.decode('utf-8') for name, content in snapshots
                        if name == 'result.json'), None)
    try:
        result = json.loads(result_text) if result_text else {}
        if not isinstance(result, dict):
            result = {}
    except ValueError:
        result = {}  # Preserve the malformed file as evidence of a failed run.
    source_hash = result.get('source_sha256')
    if not source_hash and image.is_file():
        with image.open('rb') as handle:
            source_hash = hashlib.file_digest(handle, 'sha256').hexdigest()
    manifest = Path(__file__).with_name('SOURCE_MANIFEST.json')
    run_id = str(uuid.uuid4())
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, timeout=60)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        with db:
            db.execute('BEGIN IMMEDIATE')
            app_id = db.execute('PRAGMA application_id').fetchone()[0]
            version = db.execute('PRAGMA user_version').fetchone()[0]
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if app_id == 0 and version == 0 and not tables:
                for statement in SCHEMA:
                    db.execute(statement)
                db.execute(f'PRAGMA application_id={APPLICATION_ID}')
                db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            elif app_id != APPLICATION_ID or version != SCHEMA_VERSION:
                raise ValueError('Unrecognized database or unsupported database schema version')
            db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', (
                run_id, datetime.now(timezone.utc).isoformat(), str(image), source_hash,
                str(analysis), exit_code, error, result.get('solver_version'),
                result.get('catalogue_sha256'), result.get('status'), result_text,
                hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                manifest.read_text() if manifest.is_file() else None))
            for name, content in snapshots:
                db.execute('INSERT INTO products VALUES (?,?,?,?)', (
                    run_id, name, hashlib.sha256(content).hexdigest(), content))
                if name.endswith('.csv'):
                    reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig'), newline=''))
                    for number, row in enumerate(reader, 1):
                        db.execute('INSERT INTO measurements VALUES (?,?,?,?,?,?)', (
                            run_id, name, number, row.get('star_id'), row.get('detection_id'),
                            json.dumps(row, ensure_ascii=False)))
    return run_id
