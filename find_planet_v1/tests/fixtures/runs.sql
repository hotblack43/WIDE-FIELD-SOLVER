CREATE TABLE runs (
    run_id TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 TEXT,
    exit_code INTEGER NOT NULL,
    solver_version TEXT,
    result_json TEXT
);

INSERT INTO runs VALUES (
    'run-a', '/archive/image-a.fits', 'sha-a', 0, '0.23.0',
    '{"camera":{"model":"Barghini_2019_equations_5_6_11","parameters":{"a0":0.001},"reference_rotation":[[1,0,0],[0,1,0],[0,0,1]],"shape":[1000,1000]},"final_fit":{"rms_arcmin":2.0}}'
);
INSERT INTO runs VALUES (
    'run-c', '/archive/image-c.fits', 'sha-c', 0, '0.21.0',
    '{"camera":{"model":"Barghini_2019_equations_5_6_11","parameters":{"a0":0.001},"reference_rotation":[[1,0,0],[0,1,0],[0,0,1]],"shape":[1000,1000]},"final_fit":{"rms_arcmin":3.0}}'
);
