"""Append saved evidence to SQLite after analysis; never a solver input.

Every call creates a new run, even for identical inputs or products. CSV values
remain strings in JSON so catalogue IDs, NaN spellings and quality flags survive
exactly. Raw JSON/CSV/TXT bytes and queryable CSV bodies are physically shared
between identical products, without eliminating any logical run or measurement.
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

# Keep user_version=1 and the original public column order: preserved solvers
# use fixed-arity INSERTs. These views/triggers need only stock SQLite, no UDFs.
COMPACT_SCHEMA = (
    'CREATE TABLE storage_format (version INTEGER PRIMARY KEY CHECK(version=1))',
    'INSERT INTO storage_format VALUES (1)',
    '''CREATE TABLE product_content (
        sha256 TEXT PRIMARY KEY, content BLOB NOT NULL
    )''',
    '''CREATE TABLE product_refs (
        run_id TEXT NOT NULL REFERENCES runs(run_id), product TEXT NOT NULL,
        sha256 TEXT NOT NULL REFERENCES product_content(sha256),
        PRIMARY KEY (run_id, product)
    )''',
    '''CREATE TABLE measurement_content (
        sha256 TEXT NOT NULL REFERENCES product_content(sha256),
        row_number INTEGER NOT NULL, values_json TEXT NOT NULL,
        PRIMARY KEY (sha256, row_number)
    )''',
    '''CREATE TABLE measurement_refs (
        run_id TEXT NOT NULL, product TEXT NOT NULL, row_number INTEGER NOT NULL,
        star_id TEXT, detection_id TEXT,
        PRIMARY KEY (run_id, product, row_number),
        FOREIGN KEY (run_id, product) REFERENCES product_refs(run_id, product)
    )''',
    'CREATE INDEX compact_measurement_star ON measurement_refs(star_id, product, run_id)',
    'CREATE INDEX compact_measurement_detection ON measurement_refs(run_id, product, detection_id)',
    '''CREATE VIEW products AS
        SELECT p.run_id, p.product, p.sha256, c.content
        FROM product_refs p JOIN product_content c USING(sha256)''',
    '''CREATE VIEW measurements AS
        SELECT m.run_id, m.product, m.row_number, m.star_id, m.detection_id, c.values_json
        FROM measurement_refs m JOIN product_refs p USING(run_id, product)
        JOIN measurement_content c ON c.sha256=p.sha256 AND c.row_number=m.row_number''',
    '''CREATE TRIGGER compact_product_insert INSTEAD OF INSERT ON products BEGIN
        SELECT CASE WHEN EXISTS (
            SELECT 1 FROM product_content WHERE sha256=NEW.sha256 AND content!=NEW.content
        ) THEN RAISE(ABORT, 'Conflicting product content for SHA-256') END;
        INSERT INTO product_content VALUES (NEW.sha256, NEW.content)
            ON CONFLICT(sha256) DO NOTHING;
        INSERT INTO product_refs VALUES (NEW.run_id, NEW.product, NEW.sha256);
    END''',
    '''CREATE TRIGGER compact_measurement_insert INSTEAD OF INSERT ON measurements BEGIN
        SELECT CASE WHEN NOT EXISTS (
            SELECT 1 FROM product_refs WHERE run_id=NEW.run_id AND product=NEW.product
        ) THEN RAISE(ABORT, 'Measurement has no product') END;
        SELECT CASE WHEN EXISTS (
            SELECT 1 FROM measurement_content c JOIN product_refs p USING(sha256)
            WHERE p.run_id=NEW.run_id AND p.product=NEW.product
                AND c.row_number=NEW.row_number AND c.values_json!=json(NEW.values_json)
        ) THEN RAISE(ABORT, 'Conflicting measurement for identical product') END;
        INSERT INTO measurement_content
            SELECT sha256, NEW.row_number, json(NEW.values_json) FROM product_refs
            WHERE run_id=NEW.run_id AND product=NEW.product
            ON CONFLICT(sha256, row_number) DO NOTHING;
        INSERT INTO measurement_refs VALUES
            (NEW.run_id, NEW.product, NEW.row_number, NEW.star_id, NEW.detection_id);
    END''',
)


def _initialize(db):
    """Initialize or migrate under the caller's IMMEDIATE transaction."""
    app_id = db.execute('PRAGMA application_id').fetchone()[0]
    version = db.execute('PRAGMA user_version').fetchone()[0]
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if app_id == 0 and version == 0 and not tables:
        for statement in (SCHEMA[0], SCHEMA[-2], *COMPACT_SCHEMA, SCHEMA[-1]):
            db.execute(statement)
        db.execute(f'PRAGMA application_id={APPLICATION_ID}')
        db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
    elif app_id != APPLICATION_ID or version != SCHEMA_VERSION:
        raise ValueError('Unrecognized database or unsupported database schema version')
    elif 'storage_format' in tables:
        if db.execute('SELECT version FROM storage_format').fetchall() != [(1,)]:
            raise ValueError('Unsupported compact database schema version')
    else:
        # Refuse extensions rather than accidentally dropping somebody's custom
        # trigger/index/table during a schema migration.
        schema_query = "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"
        with closing(sqlite3.connect(':memory:')) as reference:
            for statement in SCHEMA:
                reference.execute(statement)
            expected = reference.execute(schema_query).fetchall()
        if db.execute(schema_query).fetchall() != expected:
            raise ValueError('Unrecognized legacy database schema')
        db.execute('DROP VIEW star_measurements')
        db.execute('ALTER TABLE products RENAME TO legacy_products')
        db.execute('ALTER TABLE measurements RENAME TO legacy_measurements')
        for statement in COMPACT_SCHEMA:
            db.execute(statement)
        db.execute('INSERT INTO products SELECT * FROM legacy_products')
        db.execute('INSERT INTO measurements SELECT * FROM legacy_measurements')
        db.execute('DROP TABLE legacy_measurements')
        db.execute('DROP TABLE legacy_products')
        db.execute(SCHEMA[-1])


def compact_database(database):
    """Losslessly migrate a database, then reclaim free pages in place.

    SQLite serializes the migration and VACUUM with other writers; never copy and
    swap a live database, which could lose a concurrent writer's committed run.
    """
    database = Path(database).resolve(strict=True)
    before = database.stat().st_size
    with closing(sqlite3.connect(database, timeout=60)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        with db:
            db.execute('BEGIN IMMEDIATE')
            _initialize(db)
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Database foreign key check failed')
        db.execute('VACUUM')
        if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise ValueError('Database integrity check failed')
    return {'before_bytes': before, 'after_bytes': database.stat().st_size}


def append_run(database, analysis, image, *, exit_code=0, error=None):
    """Atomically append one run and every available textual scientific product.

Partial/failed analyses are recorded too. No logical de-duplication, quality cut, or
catalogue/name reassignment is performed. Binary image/FITS/PDF files remain in
the analysis directory identified by runs.analysis_path.
"""
    database, analysis, image = (Path(p).resolve() for p in (database, analysis, image))
    if database == analysis or analysis in database.parents:
        raise ValueError('Keep the database outside the analysis directory')
    from point_star_storage import text_snapshots
    snapshots = text_snapshots(analysis)
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
            _initialize(db)
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
