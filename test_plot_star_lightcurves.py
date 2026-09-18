"""Guard count-rate magnitudes, UTC provenance, reruns and star selection."""
from contextlib import closing
import csv
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.plot_star_lightcurves import load_measurements, select_stars


class LightcurveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root/'stars.sqlite'
        self.manifest = self.root/'manifest.csv'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript('''
                CREATE TABLE runs (run_id TEXT, recorded_at_utc TEXT,
                  source_path TEXT, source_sha256 TEXT, catalogue_sha256 TEXT, exit_code INTEGER);
                CREATE TABLE products (run_id TEXT, product TEXT, content BLOB);
                CREATE TABLE measurements (run_id TEXT, product TEXT, row_number INTEGER,
                  star_id TEXT, detection_id TEXT, values_json TEXT);
            ''')
        with self.manifest.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['sha256','utc_mid','source_url'])
            writer.writeheader()
            writer.writerows([{'sha256':'image1','utc_mid':'2026-01-17T02:00:00Z','source_url':'https://skycam.mmto.arizona.edu/skycam/archive/night/image1'},
                              {'sha256':'image2','utc_mid':'2026-01-17T02:10:00Z','source_url':'https://skycam.mmto.arizona.edu/skycam/archive/night/image2'}])

    def add(self, run, image, flux=2000, seconds=20, saturated='False', mag=4.0,
            star='Gaia DR3 123', exit_code=0, channel_saturated=None):
        values = dict(star_id=star, detection_id='1', G_flux=str(flux),
                      exposure_seconds=str(seconds), exposure_status='available',
                      saturation_known='True', saturated=saturated,
                      G_saturated=saturated if channel_saturated is None else channel_saturated,
                      G_measurement_method='aperture', catalogue_magnitude=str(mag))
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?)',
                       (run, '2026-09-18T'+run+':00:00Z', '/image.fits',image,'catalogue',exit_code))
            db.execute('INSERT INTO products VALUES (?,?,?)',
                       (run,'display_names.json',json.dumps({star:{'display_name':'Test star',
                        'aliases':'HD  219134|HIP 114622'}})))
            db.execute('INSERT INTO measurements VALUES (?,?,?,?,?,?)',
                       (run,'stellar_photometry.csv',1,star,'1',json.dumps(values)))

    def test_midpoint_utc_and_exposure_normalization_not_processing_time(self):
        self.add('01','image1')
        self.add('02','image2',flux=4000,seconds=40)
        rows, audit = load_measurements(self.db,self.manifest,'G')
        self.assertEqual([r['utc_mid'] for r in rows],
                         ['2026-01-17T02:00:00Z','2026-01-17T02:10:00Z'])
        self.assertEqual([r['machine_magnitude'] for r in rows],[-5.0,-5.0])
        self.assertEqual(audit['selected_runs'],2)

    def test_latest_successful_rerun_replaces_old_measurement_before_quality_cut(self):
        self.add('01','image1')
        self.add('02','image1',saturated='True')
        self.add('03','image2',flux=-20)
        rows,audit=load_measurements(self.db,self.manifest,'G')
        self.assertEqual(rows,[])
        self.assertEqual(audit['duplicate_runs_omitted'],1)
        self.assertEqual(audit['quality_rows_omitted'],2)

    def test_failed_runs_missing_time_and_missing_exposure_do_not_become_points(self):
        self.add('01','image1',exit_code=1)
        self.add('02','unknown-image')
        self.add('03','image2',seconds=0)
        rows,audit=load_measurements(self.db,self.manifest,'G')
        self.assertEqual(rows,[])
        self.assertEqual(audit['failed_runs_omitted'],1)
        self.assertEqual(audit['runs_without_manifest_time'],1)

    def test_channel_saturation_does_not_reject_clean_other_channel(self):
        self.add('01','image1',saturated='True',channel_saturated='False')
        rows,_=load_measurements(self.db,self.manifest,'G')
        self.assertEqual(len(rows),1)

    def test_bright_well_observed_selection_and_exact_saved_alias_lookup(self):
        self.add('01','image1')
        rows,_=load_measurements(self.db,self.manifest,'G')
        # Independent example: faint star and sparse star cannot enter default pool.
        rows += [dict(rows[0],star_id='faint',catalogue_magnitude=7.4,aliases=[]),
                 dict(rows[0],star_id='sparse',catalogue_magnitude=4.0,aliases=[])]
        rows += [dict(rows[0],source_sha256='image2',utc_mid='2026-01-17T02:10:00Z')]
        chosen=select_stars(rows,count=4,min_points=2,min_mag=2,max_mag=6,coverage=0.75,seed=1,stars=[])
        self.assertEqual([key[1] for key,_ in chosen],['Gaia DR3 123'])
        chosen=select_stars(rows,count=4,min_points=2,min_mag=2,max_mag=6,coverage=0.75,seed=1,stars=['HD219134'])
        self.assertEqual([key[1] for key,_ in chosen],['Gaia DR3 123'])
        with self.assertRaisesRegex(ValueError,'not found'):
            select_stars(rows,count=4,min_points=2,min_mag=2,max_mag=6,coverage=0.75,seed=1,stars=['unknown'])

    def test_conflicting_hash_times_are_rejected(self):
        self.add('01','image1')
        with self.manifest.open('a') as f:
            f.write('image1,2026-01-17T03:00:00Z,https://skycam.mmto.arizona.edu/skycam/archive/night/image1\n')
        with self.assertRaisesRegex(ValueError,'Conflicting'):
            load_measurements(self.db,self.manifest,'G')

    def test_non_mmto_manifest_entry_is_excluded_even_with_matching_image_hash(self):
        self.add('01','image1')
        self.add('02','other-camera')
        with self.manifest.open('a') as f:
            f.write('other-camera,2026-01-17T02:20:00Z,https://other-camera.example/image.fits\n')
        rows,audit=load_measurements(self.db,self.manifest,'G')
        self.assertEqual([row['source_sha256'] for row in rows],['image1'])
        self.assertEqual(audit['runs_without_manifest_time'],1)

    def test_fractional_midpoints_sort_in_physical_time_order(self):
        self.add('01','image1')
        self.add('02','image2')
        text=self.manifest.read_text().replace('2026-01-17T02:10:00Z','2026-01-17T02:00:00.500000Z')
        self.manifest.write_text(text)
        rows,_=load_measurements(self.db,self.manifest,'G')
        self.assertEqual([r['source_sha256'] for r in rows],['image1','image2'])


class PolynomialTrendTests(unittest.TestCase):
    def fit(self, seconds, mags, **kwargs):
        from scripts.plot_star_lightcurves import fit_polynomial_trend
        return fit_polynomial_trend(seconds,mags,**kwargs)

    def test_quadratic_is_recovered_without_unnecessary_higher_order(self):
        seconds=list(range(20))
        mags=[3 + .2*x + .1*x*x for x in seconds]
        fit=self.fit(seconds,mags,max_degree=6)
        self.assertEqual(fit['degree'],2)
        self.assertLess(max(abs(x) for x in fit['residuals']),1e-10)
        self.assertLess(fit['residual_sd_mag'],1e-10)

    def test_residual_sign_sample_sd_and_degrees_of_freedom(self):
        fit=self.fit([0,1,2,3],[1.,2.,3.,4.],max_degree=0)
        self.assertEqual(fit['degree'],0)
        for actual,expected in zip(fit['residuals'],[-1.5,-.5,.5,1.5]):
            self.assertAlmostEqual(actual,expected)
        self.assertAlmostEqual(fit['residual_sd_mag'],(5/3)**.5)
        self.assertAlmostEqual(fit['residual_standard_error_mag'],(5/3)**.5)
        self.assertAlmostEqual(fit['cv_rmse_mag'],(20/9)**.5)

    def test_leave_one_out_score_matches_actual_independent_refits(self):
        import numpy as np
        times=np.arange(15,dtype=float)
        mags=np.array([1,2,1,2,3,2,4,4,3,5,3,6,5,6,4],dtype=float)
        fit=self.fit(times,mags,max_degree=4)
        for score in fit['candidate_scores']:
            degree=score['degree']
            errors=[]
            for i in range(len(times)):
                keep=np.arange(len(times))!=i
                poly=np.polynomial.Polynomial.fit(times[keep],mags[keep],degree)
                errors.append((mags[i]-poly(times[i]))**2)
            self.assertAlmostEqual(score['cv_mse_mag2'],float(np.mean(errors)),places=8)
        best=min(fit['candidate_scores'],key=lambda row: row['cv_mse_mag2'])
        self.assertEqual(fit['degree'],best['degree'])

    def test_short_and_repeated_times_cannot_interpolate_or_claim_single_point_sd(self):
        fit=self.fit([0,1],[2,3],max_degree=10)
        self.assertEqual(fit['degree'],0)
        self.assertAlmostEqual(fit['residual_sd_mag'],2**-.5)
        fit=self.fit([0,0,0],[2,3,4],max_degree=10)
        self.assertEqual(fit['degree'],0)
        self.assertAlmostEqual(fit['residual_sd_mag'],1)
        fit=self.fit([0],[2],max_degree=10)
        self.assertEqual(fit['degree'],0)
        self.assertIsNone(fit['residual_sd_mag'])
        self.assertIsNone(fit['cv_rmse_mag'])


class TrendOutputTests(unittest.TestCase):
    setUp = LightcurveTests.setUp
    add = LightcurveTests.add
    def test_cached_resolved_alias_can_select_the_star(self):
        from scripts.plot_star_lightcurves import apply_cached_names
        self.add('01','image1')
        rows,_=load_measurements(self.db,self.manifest)
        cache=self.root/'names.json'
        cache.write_text(json.dumps({'Gaia DR3 123':{'display_name':'16 UMa',
                                                  'aliases':'* 16 UMa|HD 79028'}}))
        apply_cached_names(rows,cache)
        selected=select_stars(rows,stars=['16 UMa'])
        self.assertEqual(selected[0][0][1],'Gaia DR3 123')
        self.assertEqual(rows[0]['machine_magnitude'],-5.0)

    def test_exports_model_and_signed_residuals_with_reconstructable_fit(self):
        from argparse import Namespace
        from scripts.plot_star_lightcurves import write_outputs
        import numpy as np
        self.add('01','image1')
        self.add('02','image2',flux=8000)
        rows,audit=load_measurements(self.db,self.manifest)
        selected=select_stars(rows,stars=['Test star'])
        args=Namespace(database=self.db,manifest=self.manifest,channel='G',offline_names=True,
                       max_degree=0,min_mag=2.5,max_mag=6.,min_points=1,coverage=.75,seed=42,star=['Test star'])
        output=self.root/'output'
        summary=write_outputs(selected,output,audit,args)
        with (output/'residuals.csv').open() as f:
            residuals=list(csv.DictReader(f))
        self.assertEqual(len(residuals),2)
        self.assertAlmostEqual(float(residuals[0]['residual_mag']),.752574989159953)
        self.assertAlmostEqual(float(residuals[1]['residual_mag']),-.752574989159953)
        fit=summary[0]['polynomial_fit']
        for row in residuals:
            fitted=np.polynomial.chebyshev.chebval(0,fit['coefficients'])
            self.assertAlmostEqual(fitted,float(row['fitted_magnitude']))
            self.assertAlmostEqual(float(row['machine_magnitude'])-fitted,float(row['residual_mag']))
        self.assertTrue((output/'lightcurves.png').stat().st_size>1000)
        self.assertTrue((output/'lightcurves.pdf').stat().st_size>1000)
        self.assertTrue((output/'sd_vs_magnitude.png').stat().st_size>1000)
        with (output/'sd_vs_magnitude.csv').open() as f:
            scatter=list(csv.DictReader(f))
        self.assertEqual(len(scatter),1)
        self.assertAlmostEqual(float(scatter[0]['residual_sd_mag']),fit['residual_sd_mag'])


class EnsembleScatterTests(unittest.TestCase):
    def test_ensemble_sd_is_detrended_not_raw_and_uses_all_eligible_stars(self):
        from scripts.plot_star_lightcurves import scatter_statistics
        rows=[]
        for star,mag,slope in [('first',4.,.2),('second',5.,.3),('faint',7.4,.4)]:
            for i in range(12):
                rows.append(dict(star_id=star,catalogue_sha256='cat',catalogue_magnitude=mag,
                                 machine_magnitude=-5+slope*i,utc_mid=f'2026-01-17T02:{i:02d}:00Z',
                                 aliases=[star],display_name=star,channel='G'))
        groups=select_stars(rows,count=len(rows),min_points=10,min_mag=2.5,max_mag=6.)
        points=scatter_statistics(groups,max_degree=3)
        self.assertEqual({r['star_id'] for r in points},{'first','second'})
        for row in points:
            self.assertEqual(row['polynomial_degree'],1)
            self.assertLess(row['residual_sd_mag'],1e-12)
            self.assertEqual(row['measurements'],12)

    def test_latest_pointer_updates_without_overwriting_old_plots(self):
        from scripts.plot_star_lightcurves import update_latest
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('run1','run2'):
                out=root/name
                out.mkdir()
                (out/'lightcurves.png').write_bytes(name.encode())
                update_latest(out)
            self.assertEqual((root/'latest/lightcurves.png').read_bytes(),b'run2')
            self.assertEqual((root/'run1/lightcurves.png').read_bytes(),b'run1')
