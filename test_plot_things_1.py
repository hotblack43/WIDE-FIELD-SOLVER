import hashlib
import csv
import io
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from astropy.io import fits
from scripts import plot_things_1 as plot


class PlotThingsOneTests(unittest.TestCase):
    def colour_rows(self, **changes):
        base = dict(run_id='run', source_sha256='image', catalogue_sha256='cat',
                    star_id='star', detection_id='d1', gaia_g=5., gaia_bp=6., gaia_rp=4.,
                    utc_mid='2026-09-19T03:00:00Z', local_noon_day='2026-09-18',
                    airmass=1.5, airmass_verified=True)
        base.update(changes)
        return [dict(base, channel=c, count_rate_adu_per_s=rate, machine_mag=999.)
                for c, rate in [('R', 1000.), ('G', 100.), ('B', 10.)]]

    def test_colours_use_same_exposure_rates_and_brightness_cut(self):
        self.assertTrue(hasattr(plot, 'colour_measurements'), 'Colour pairing is not implemented')
        rows = self.colour_rows()
        values = plot.colour_measurements(rows, 5.5)
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]['machine_b_minus_g'], 2.5)
        self.assertEqual(values[0]['machine_g_minus_r'], 2.5)
        self.assertEqual(values[0]['gaia_bp_minus_rp'], 2.)
        self.assertEqual(values[0]['airmass'], 1.5)
        for field in ('run_id', 'source_sha256', 'catalogue_sha256', 'star_id', 'detection_id'):
            with self.subTest(field=field):
                mismatched = [dict(r) for r in rows]
                mismatched[2][field] = 'other'
                self.assertEqual(plot.colour_measurements(mismatched, 5.5), [])
        for changes in ({'gaia_g': 5.6}, {'gaia_bp': None}, {'gaia_rp': float('nan')}):
            self.assertEqual(plot.colour_measurements(self.colour_rows(**changes), 5.5), [])
        for invalid in (None, 0., -1., float('nan')):
            bad = [dict(r) for r in rows]
            bad[2]['count_rate_adu_per_s'] = invalid
            self.assertEqual(plot.colour_measurements(bad, 5.5), [])
        self.assertEqual(plot.colour_measurements(rows[:2], 5.5), [])
        for changes in ({'airmass_verified': False}, {'airmass': None},
                        {'airmass': float('nan')}, {'airmass': .5}):
            self.assertEqual(plot.colour_measurements(self.colour_rows(**changes), 5.5), [])

    def test_colour_page_axes_and_point_colours(self):
        self.assertIn('colours', plot.PLOT_REGISTRY, 'Colour page is not registered')
        rows = self.colour_rows() + self.colour_rows(run_id='second', airmass_verified=False)
        fig = plot.PLOT_REGISTRY['colours'](rows, [], SimpleNamespace(colour_max_mag=5.5))
        self.addCleanup(plot.plt.close, fig)
        left, middle, right = fig.axes[:3]
        self.assertEqual(left.collections[0].get_offsets().tolist(), [[2.5, 2.5]])
        self.assertEqual(list(left.collections[0].get_array()), [2.])
        for axis in (middle, right):
            self.assertEqual(axis.collections[0].get_offsets().tolist(), [[2., 2.5]])
            self.assertEqual(list(axis.collections[0].get_array()), [1.5])
            self.assertEqual(len(axis.collections), 1)
            self.assertIsNone(axis.get_legend())
        empty = plot.PLOT_REGISTRY['colours']([], [], SimpleNamespace(colour_max_mag=5.5))
        self.addCleanup(plot.plt.close, empty)
        self.assertTrue(any('No usable' in t.get_text() for t in empty.axes[0].texts))

    def test_rgb_pages_show_every_selected_star_in_bright_and_faint_blocks(self):
        self.assertIn('lightcurves_RGB', plot.PLOT_REGISTRY, 'RGB page is not registered')
        rows, selected = [], []
        for column in (0, 1):
            for row in range(4):
                sid = f's{column}{row}'
                selected.append(dict(catalogue_sha256='cat', star_id=sid, display_name=sid,
                                     gaia_g=2. if column == 0 else 5., column=column, row=row))
                rows.extend(dict(r, hours_since_local_noon=8., machine_mag=-5.)
                            for r in self.colour_rows(star_id=sid))
        args = SimpleNamespace(catalogue_band='matched', target_mag=5.)
        for key in ('lightcurves_RGB', 'airmass_RGB'):
            fig = plot.PLOT_REGISTRY[key](rows, selected, args)
            self.addCleanup(plot.plt.close, fig)
            self.assertEqual(len(fig.axes), 24)
            for block in (0, 1):
                for row in range(4):
                    sid = f's{block}{row}'
                    for col, channel in enumerate('RGB'):
                        ax = fig.axes[row*6+block*3+col]
                        self.assertIn(sid, ax.get_title(loc='left'))
                        self.assertTrue(ax.get_ylabel().startswith(channel))
                        want = ([8., -5.] if key == 'lightcurves_RGB'
                                else [1.5, (-9., -10., -11.)[col]])
                        self.assertEqual(ax.collections[0].get_offsets().tolist(), [want])

    def test_rgb_time_panels_share_one_magnitude_range(self):
        args = SimpleNamespace(catalogue_band='matched', target_mag=5.)
        selected = [
            dict(catalogue_sha256='cat', star_id='bright', display_name='Bright',
                 gaia_g=2., column=0, row=0),
            dict(catalogue_sha256='cat', star_id='faint', display_name='Faint',
                 gaia_g=5., column=1, row=0),
        ]
        rows = []
        for star_id, magnitude in [('bright', -10.), ('faint', -4.)]:
            rows.extend(dict(row, hours_since_local_noon=8., machine_mag=magnitude)
                        for row in self.colour_rows(star_id=star_id))

        figure = plot.lightcurve_page(rows, selected, args, 'RGB')
        self.addCleanup(plot.plt.close, figure)
        visible = [axis for axis in figure.axes if axis.get_visible()]
        self.assertEqual(len(visible), 6)
        for axis in visible:
            lower, upper = axis.get_ylim()
            self.assertAlmostEqual(lower, -3.7)
            self.assertAlmostEqual(upper, -10.3)
            self.assertTrue(axis.yaxis_inverted())

    def test_rgb_airmass_panels_share_one_residual_magnitude_range(self):
        args = SimpleNamespace(catalogue_band='matched', target_mag=5.)
        selected = [
            dict(catalogue_sha256='cat', star_id='bright', display_name='Bright',
                 gaia_g=2., column=0, row=0),
            dict(catalogue_sha256='cat', star_id='faint', display_name='Faint',
                 gaia_g=5., column=1, row=0),
        ]
        rows = []
        for star_id, magnitude in [('bright', -10.), ('faint', -4.)]:
            rows.extend(dict(row, hours_since_local_noon=8., machine_mag=magnitude)
                        for row in self.colour_rows(star_id=star_id))

        figure = plot.lightcurve_page(rows, selected, args, 'RGB', against_airmass=True)
        self.addCleanup(plot.plt.close, figure)
        visible = [axis for axis in figure.axes if axis.get_visible()]
        self.assertEqual(len(visible), 6)
        for axis in visible:
            lower, upper = axis.get_ylim()
            self.assertAlmostEqual(lower, -16.4)
            self.assertAlmostEqual(upper, -7.6)
            self.assertFalse(axis.yaxis_inverted())

    def test_rates_and_local_noon_clock(self):
        self.assertEqual(plot.machine_magnitude(100), -5.)
        for invalid in (None, 0, -1, float('nan'), float('inf')):
            self.assertTrue(math.isnan(plot.machine_magnitude(invalid)))
        night, hours = plot.local_night('2026-09-19T06:30:00Z')
        self.assertEqual(night, '2026-09-18')
        self.assertAlmostEqual(hours, 11.5)

    def test_loader_validates_clock_hash_rate_and_latest_run_before_channel_cuts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root/'MMTO.fits'
            hdu = fits.PrimaryHDU()
            for k, v in {'SITELAT':'31:41:12:0', 'SITELONG':'-110:53:3:0',
                         'EXPOSURE':20., 'STACKNB':1, 'DATE-OBS':'2026-09-18T20:00:00',
                         'DATE':'2026-09-19T03:00:22'}.items():
                hdu.header[k] = v
            hdu.writeto(image)
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            meta, error = plot.image_metadata(str(image), digest, root)
            self.assertIsNone(error)
            self.assertTrue(meta['utc_mid'].startswith('2026-09-19T03:00:10'))
            self.assertEqual(meta['local_noon_day'], '2026-09-18')
            self.assertIsNone(plot.image_metadata(str(image), 'wrong-hash', root)[0])
            catalogue = root/'gaia.csv'
            catalogue.write_text('source_id,phot_g_mean_mag,phot_rp_mean_mag,phot_bp_mean_mag\n1,5,4,6\n')
            database = root/'stars.sqlite'
            with sqlite3.connect(database) as db:
                db.executescript('''
                    CREATE TABLE runs(run_id, recorded_at_utc, source_path, source_sha256,
                                      catalogue_sha256, exit_code, solver_version,
                                      result_json, source_manifest_json);
                    CREATE TABLE products(run_id, product, content);
                    CREATE TABLE measurements(run_id, product, row_number, star_id, detection_id, values_json);
                ''')
                values = dict(exposure_seconds=20, exposure_status='available', saturation_known=True,
                              airmass='1.75',
                              saturated=True, photometry_usable=False, G_mag=999,
                              G_count_rate_adu_per_s=100, G_saturated=False, G_measurement_method='aperture',
                              R_count_rate_adu_per_s=100, R_saturated=False, R_measurement_method='aperture',
                              B_flux=2000, B_saturated=False, B_measurement_method='aperture')
                for run in ('old', 'new'):
                    db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)',
                               (run, '2026-01-01' if run == 'old' else '2026-01-02', str(image), digest, 'cat', 0,
                                '0.10.0', json.dumps(dict(model='Barghini', epoch_mode='fit', blind=True,
                                                        code_sha256={'solver.py': 'code'})), '{}'))
                    db.execute('INSERT INTO products VALUES (?,?,?)', (run, 'photometry_summary.json',
                               json.dumps(dict(metadata_used=False, airmass_source='blind_photometric_zenith'))))
                    if run == 'new':
                        values['R_saturated'] = True
                    db.execute('INSERT INTO measurements VALUES (?,?,?,?,?,?)',
                               (run, 'stellar_photometry.csv', 1, 'Gaia DR3 1', 'd1', json.dumps(values)))
            rows, audit, images = plot.load_measurements(database, catalogue, root)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['channel'], 'G')
            self.assertEqual(rows[0]['run_id'], 'new')
            self.assertEqual(rows[0]['machine_mag'], -5.)
            self.assertEqual(rows[0]['airmass'], 1.75)
            self.assertTrue(rows[0]['airmass_verified'])
            self.assertEqual(rows[0]['utc_mid'], meta['utc_mid'])
            self.assertEqual(audit['verified_images'], 1)

    def test_selection_has_bright_left_faint_right_and_rejects_sparse_series(self):
        rows = []
        for index, mag in enumerate([1, 2, 2.5, 3, 4.98, 5.01, 5.05, 5.1, .5]):
            for image in range(2 if index == 8 else 10):
                rows.append(dict(channel='G', catalogue_sha256='cat', star_id=str(index),
                                 source_sha256=str(image), display_name='', gaia_g=mag))
        selected = plot.select_stars(rows)
        self.assertEqual([s['gaia_g'] for s in selected if s['column'] == 0], [1, 2, 2.5, 3])
        self.assertEqual(len({s['star_id'] for s in selected}), 8)
        self.assertTrue(all(abs(s['gaia_g']-5) < .11 for s in selected if s['column'] == 1))

    def test_same_gaia_star_combines_nights_across_catalogue_digests(self):
        rows = [dict(channel='G', catalogue_sha256='old-cat' if i < 2 else 'new-cat',
                     star_id='same-star', source_sha256=f'image-{i}', display_name='Same star',
                     gaia_g=2., gaia_rp=1.5, gaia_bp=2.5,
                     local_noon_day=f'2026-09-{17+i:02d}', utc_mid=f'2026-09-{17+i:02d}T03:00:00Z',
                     hours_since_local_noon=8.+i, machine_mag=-5.-i/10)
                for i in range(4)]
        selected = plot.select_stars(rows, minimum=2, coverage=1.)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]['star_id'], 'same-star')
        self.assertEqual(selected[0]['g_measurements'], 4)
        self.assertEqual(selected[0]['catalogue_sha256s'], ['new-cat', 'old-cat'])
        figure = plot.lightcurve_page(
            rows, selected, SimpleNamespace(catalogue_band='matched', target_mag=5.), 'G')
        self.addCleanup(plot.plt.close, figure)
        visible = [axis for axis in figure.axes if axis.get_visible()]
        self.assertEqual(len(visible), 1)
        self.assertEqual(sum(len(collection.get_offsets()) for collection in visible[0].collections), 4)

    def test_figures_use_channel_catalogue_bands_and_actual_local_hours(self):
        rows = [dict(channel=c, catalogue_sha256='cat', star_id='s', display_name='Named star',
                     gaia_g=5., gaia_rp=4., gaia_bp=6., local_noon_day='2026-09-18',
                     utc_mid=f'2026-09-19T0{i}:00:00Z', hours_since_local_noon=float(i+5),
                     machine_mag=-5.-i/10) for c in 'RGB' for i in (2, 3, 4)]
        args = SimpleNamespace(catalogue_band='matched', target_mag=5.)
        figure = plot.catalogue_page(rows, [], args)
        for axis, band, magnitude in zip(figure.axes, ('RP', 'G', 'BP'), (4., 5., 6.)):
            self.assertEqual(axis.get_xlabel(), f'Gaia {band} [mag]')
            self.assertEqual(list(axis.collections[0].get_offsets()[:, 0]), [magnitude]*3)
        plot.plt.close(figure)

        sample = [dict(catalogue_sha256='cat', star_id='s', display_name='Named star',
                       gaia_g=5., row=0, column=1)]
        figure = plot.lightcurve_page(rows, sample, args, 'G')
        self.assertEqual(len(figure.axes), 8)
        right_top = figure.axes[1]
        self.assertEqual(list(right_top.collections[0].get_offsets()[:, 0]), [7., 8., 9.])
        self.assertEqual(list(right_top.collections[0].get_offsets()[:, 1]), [-5.2, -5.3, -5.4])
        plot.plt.close(figure)

    def test_airmass_panels_subtract_correct_band_and_omit_unverified_airmass(self):
        base = dict(catalogue_sha256='cat', star_id='s', gaia_g=5., gaia_rp=4., gaia_bp=6.,
                    local_noon_day='2026-09-18', utc_mid='2026-09-19T03:00:00Z',
                    machine_mag=-5., airmass=1.5, airmass_verified=True)
        sample = [dict(catalogue_sha256='cat', star_id='s', display_name='Named star',
                       gaia_g=5., row=0, column=1)]
        args = SimpleNamespace(catalogue_band='matched', target_mag=5.)
        for channel, expected in [('R', -9.), ('G', -10.), ('B', -11.)]:
            valid = dict(base, channel=channel)
            rows = [valid, dict(valid, airmass=None), dict(valid, airmass=float('nan')),
                    dict(valid, airmass=.5), dict(valid, airmass_verified=False)]
            figure = plot.PLOT_REGISTRY['airmass_'+channel](rows, sample, args)
            axis = figure.axes[1]
            self.assertEqual(axis.collections[0].get_offsets().tolist(), [[1.5, expected]])
            self.assertFalse(axis.yaxis_inverted())
            self.assertIn('omitted=4', axis.get_title(loc='left'))
            plot.plt.close(figure)
        args.catalogue_band = 'G'
        figure = plot.PLOT_REGISTRY['airmass_R']([dict(base, channel='R')], sample, args)
        self.assertEqual(figure.axes[1].collections[0].get_offsets().tolist(), [[1.5, -10.]])
        plot.plt.close(figure)


class RunSelectionTests(unittest.TestCase):
    """Catch duplicate observations, mixed reductions and failed-run replacement."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.database = self.root/'stars.sqlite'
        self.catalogue = self.root/'gaia.csv'
        self.catalogue.write_text('source_id,phot_g_mean_mag,phot_rp_mean_mag,phot_bp_mean_mag\n1,5,4,6\n')
        self.image = self.root/'MMTO.fits'
        hdu = fits.PrimaryHDU()
        for key, value in {'SITELAT': '31:41:12:0', 'SITELONG': '-110:53:3:0',
                           'EXPOSURE': 20., 'STACKNB': 1, 'DATE-OBS': '2026-09-18T20:00:00',
                           'DATE': '2026-09-19T03:00:22'}.items():
            hdu.header[key] = value
        hdu.writeto(self.image)
        self.digest = hashlib.sha256(self.image.read_bytes()).hexdigest()
        self.db = sqlite3.connect(self.database)
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE runs(run_id, recorded_at_utc, source_path, source_sha256,
                              catalogue_sha256, exit_code, solver_version,
                              result_json, source_manifest_json);
            CREATE TABLE products(run_id, product, content);
            CREATE TABLE measurements(run_id, product, row_number, star_id, detection_id, values_json);
        ''')

    def add_run(self, run_id, *, day=1, version='0.10.0', catalogue='cat', image=None,
                source=None, exit_code=0, epoch_mode='fit', code='code', result=None,
                database=None):
        database = database or self.db
        data = dict(model='Barghini', epoch_mode=epoch_mode, blind=epoch_mode != 'fixed',
                    metadata_used=epoch_mode == 'fixed', code_sha256={'solver.py': code})
        if epoch_mode == 'fixed':
            data['coordinate_epoch_jyear'] = 2000.
        data.update(result or {})
        database.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)', (
            run_id, f'2026-09-{day:02d}T00:00:00+00:00', source or str(self.image),
            self.digest if image is None else image, catalogue, exit_code, version,
            json.dumps(data), '{}'))
        database.execute('INSERT INTO products VALUES (?,?,?)', (run_id, 'photometry_summary.json',
                        json.dumps(dict(metadata_used=False, airmass_source='blind_photometric_zenith'))))
        values = dict(exposure_seconds=20, exposure_status='available', saturation_known=True,
                      airmass=1.5, G_count_rate_adu_per_s=100, G_saturated=False,
                      G_measurement_method='aperture')
        database.execute('INSERT INTO measurements VALUES (?,?,?,?,?,?)', (
            run_id, 'stellar_photometry.csv', 1, 'Gaia DR3 1', 'd1', json.dumps(values)))
        database.commit()

    def select(self, **options):
        self.assertTrue(hasattr(plot, 'select_mmto_runs'), 'Consistent run selection is missing')
        return plot.select_mmto_runs(self.db, **options)

    def test_latest_success_per_hash_ignores_path_changes_and_newer_failure(self):
        self.add_run('old')
        self.add_run('latest', day=2, source=str(self.root/'moved'/'renamed.fits'))
        self.add_run('failed', day=3, exit_code=1)
        chosen, audit = self.select()
        self.assertEqual([r['run_id'] for r in chosen], ['latest'])
        self.assertEqual(audit['superseded_successful_runs'], 1)
        self.assertEqual(audit['failed_mmto_runs'], 1)

    def test_default_uses_latest_successful_run_per_image_across_all_reductions(self):
        self.add_run('old-v10', day=1, image='image-one')
        self.add_run('latest-v11', day=3, version='0.11.0', image='image-one')
        self.add_run('other-v10', day=2, image='image-two')
        self.add_run('other-config-v11', day=4, version='0.11.0', image='image-three', code='changed')
        self.add_run('newer-fixed-control', day=5, version='0.11.0', image='image-one',
                     epoch_mode='fixed')
        self.add_run('failed', day=6, version='0.11.0', image='image-four', exit_code=1)
        chosen, audit = self.select()
        self.assertEqual({r['run_id'] for r in chosen},
                         {'latest-v11', 'other-v10', 'other-config-v11'})
        self.assertEqual(audit['selection_mode'], 'latest_successful_per_image_across_all_reductions')
        self.assertEqual(audit['selected']['unique_images'], 3)
        self.assertEqual(audit['selected']['solver_versions'], {'0.10.0': 1, '0.11.0': 2})
        self.assertEqual(audit['superseded_successful_runs'], 1)
        self.assertEqual(audit['nonblind_control_runs'], 1)
        self.assertEqual(audit['failed_mmto_runs'], 1)
        self.assertEqual(len(audit['available_reductions']), 4)

    def test_explicit_version_never_merges_versions_configs_or_catalogues(self):
        self.add_run('a')
        self.add_run('a-copy', day=2)
        self.add_run('b', image='second')
        self.add_run('new-version', day=3, version='0.11.0')
        self.add_run('fixed', day=4, epoch_mode='fixed')
        self.add_run('other-code', day=5, code='changed')
        self.add_run('other-catalogue', day=6, catalogue='other')
        chosen, audit = self.select(solver_version='0.10.0')
        self.assertEqual({r['run_id'] for r in chosen}, {'a-copy', 'b'})
        self.assertEqual(audit['selected']['solver_version'], '0.10.0')
        self.assertEqual(audit['selected']['unique_images'], 2)
        self.assertEqual(len(audit['available_reductions']), 4)
        chosen, _ = self.select(solver_version='0.11.0')
        self.assertEqual([r['run_id'] for r in chosen], ['new-version'])
        chosen, _ = self.select(catalogue_sha256='other')
        self.assertEqual([r['run_id'] for r in chosen], ['other-catalogue'])
        fixed = next(r for r in audit['available_reductions']
                     if r['configuration']['epoch_mode'] == 'fixed')
        chosen, _ = self.select(config_sha256=fixed['config_sha256'])
        self.assertEqual([r['run_id'] for r in chosen], ['fixed'])

    def test_configuration_keeps_fixed_epochs_separate_but_not_run_time_ceilings(self):
        for day, ceiling in [(1, 2026.7), (2, 2026.8)]:
            self.add_run(f'fit-{day}', day=day, result=dict(
                stellar_epoch={'search_limits_jyear': [1850., ceiling]},
                causal_epoch_ceiling={'jyear': ceiling, 'source': 'current_system_time_at_run_start'}))
        self.add_run('fixed-2000', epoch_mode='fixed', result={'coordinate_epoch_jyear': 2000.})
        self.add_run('fixed-2010', epoch_mode='fixed', result={'coordinate_epoch_jyear': 2010.})
        _, audit = self.select()
        self.assertEqual(len(audit['available_reductions']), 3)
        fit = next(r for r in audit['available_reductions'] if r['configuration']['epoch_mode'] == 'fit')
        chosen, _ = self.select(config_sha256=fit['config_sha256'])
        self.assertEqual([r['run_id'] for r in chosen], ['fit-2'])

    def test_invalid_identity_or_unknown_config_is_not_combined(self):
        self.add_run('good')
        self.add_run('no-hash', image='')
        self.add_run('no-config', result={'code_sha256': {}, 'epoch_mode': None})
        chosen, audit = self.select()
        self.assertEqual([r['run_id'] for r in chosen], ['good'])
        self.assertEqual(audit['unusable_provenance_runs'], 2)
        for options in ({'solver_version': 'missing'}, {'config_sha256': 'missing'},
                        {'catalogue_sha256': 'missing'}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, 'No successful MMTO'):
                self.select(**options)

    def test_timestamp_ties_are_deterministic(self):
        self.add_run('z')
        self.add_run('a')
        chosen, _ = self.select()
        self.assertEqual([r['run_id'] for r in chosen], ['z'])

    def test_malformed_nested_provenance_is_skipped_not_a_plotter_crash(self):
        self.add_run('good')
        self.add_run('bad-epoch', result={'stellar_epoch': ['invalid']})
        self.add_run('bad-ceiling', result={'stellar_epoch': {'search_limits_jyear': [1850., 2026.]},
                                           'causal_epoch_ceiling': ['invalid']})
        self.add_run('missing-fixed-year', epoch_mode='fixed', result={'coordinate_epoch_jyear': None})
        chosen, audit = self.select()
        self.assertEqual([r['run_id'] for r in chosen], ['good'])
        self.assertEqual(audit['unusable_provenance_runs'], 3)

    def test_list_and_explicit_cli_selection_do_not_use_other_version(self):
        self.add_run('v10')
        self.add_run('v11', version='0.11.0', day=2)
        common = ['--database', str(self.database), '--solver-version', '0.11.0']
        stream = io.StringIO()
        with redirect_stdout(stream):
            plot.main(common+['--list-reductions', '--catalogue', str(self.root/'absent.csv')])
        listing = json.loads(stream.getvalue())
        self.assertEqual(listing['selected_run_ids'], ['v11'])
        selected = listing['selected']
        output = self.root/'explicit-plots'
        with redirect_stdout(io.StringIO()):
            plot.main(common+['--config-sha256', selected['config_sha256'], '--catalogue-sha256', 'cat',
                              '--catalogue', str(self.catalogue), '--image-root', str(self.root),
                              '--output', str(output), '--plots', 'rgb_catalogue'])
        summary = json.loads((output/'summary.json').read_text())
        self.assertEqual(summary['run_selection']['selected_run_ids'], ['v11'])

    def test_saved_explicit_settings_search_limits_and_manifest_changes_separate_groups(self):
        self.add_run('base')
        self.add_run('options', result={'configuration': {'detection_sigma': 7}})
        self.add_run('limits', result={'stellar_epoch': {'search_limits_jyear': [1900., 2000.]}})
        self.add_run('dependency')
        self.db.execute('UPDATE runs SET source_manifest_json=? WHERE run_id=?',
                        (json.dumps({'sha256': {'photometry.py': 'different'}}), 'dependency'))
        self.db.commit()
        _, audit = self.select()
        self.assertEqual(len(audit['available_reductions']), 4)

    def test_loader_and_cli_export_one_observation_and_leave_database_unchanged(self):
        self.add_run('old')
        self.add_run('latest', day=2)
        self.add_run('failed', day=3, exit_code=1)
        self.add_run('new-version', day=4, version='0.11.0')
        before = self.database.read_bytes()
        rows, audit, images = plot.load_measurements(self.database, self.catalogue, self.root)
        self.assertEqual([r['run_id'] for r in rows], ['new-version'])
        self.assertEqual([r['run_id'] for r in images], ['new-version'])
        output = self.root/'plots'
        output.mkdir()
        (output/'99_stale_plot.png').write_bytes(b'old generated plot')
        (output/'01_notes.png').write_bytes(b'unrelated numbered image')
        (output/'keep.txt').write_text('unrelated file')
        (output/'summary.json').write_text(json.dumps(
            {'generated_files': ['99_stale_plot.png', 'summary.json']})+'\n')
        stream = io.StringIO()
        with redirect_stdout(stream):
            plot.main(['--database', str(self.database), '--catalogue', str(self.catalogue),
                       '--image-root', str(self.root), '--output', str(output), '--overwrite',
                       '--plots', 'rgb_catalogue'])
        summary = json.loads((output/'summary.json').read_text())
        self.assertEqual(summary['run_selection']['selected_run_ids'], ['new-version'])
        self.assertEqual(summary['solver_versions'], {'0.11.0': 1})
        self.assertEqual(summary['run_selection']['superseded_successful_runs'], 2)
        self.assertIn('latest successful solution for each image', stream.getvalue())
        self.assertIn('1 unique database image; verified FITS data for 1 across 1 plotted night',
                      stream.getvalue())
        self.assertIn('Excluded: 2 superseded successful runs', stream.getvalue())
        self.assertFalse((output/'99_stale_plot.png').exists())
        self.assertEqual((output/'01_notes.png').read_bytes(), b'unrelated numbered image')
        self.assertEqual((output/'keep.txt').read_text(), 'unrelated file')
        with (output/'measurements.csv').open() as handle:
            exported = list(csv.DictReader(handle))
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0]['solver_version'], '0.11.0')
        self.assertEqual(exported[0]['config_sha256'], summary['image_provenance'][0]['config_sha256'])
        self.assertEqual(self.database.read_bytes(), before)

    def test_loader_merges_databases_and_prefers_latest_solution_per_image(self):
        self.add_run('primary-old')
        second_image = self.root/'MMTO-second.fits'
        with fits.open(self.image) as hdus:
            hdus[0].header['DATE-OBS'] = '2026-09-18T20:20:00'
            hdus[0].header['DATE'] = '2026-09-19T03:20:22'
            hdus.writeto(second_image)
        second_digest = hashlib.sha256(second_image.read_bytes()).hexdigest()
        automatic = self.root/'automatic.sqlite'
        with sqlite3.connect(automatic) as db:
            db.executescript('''
                CREATE TABLE runs(run_id, recorded_at_utc, source_path, source_sha256,
                                  catalogue_sha256, exit_code, solver_version,
                                  result_json, source_manifest_json);
                CREATE TABLE products(run_id, product, content);
                CREATE TABLE measurements(run_id, product, row_number, star_id, detection_id, values_json);
            ''')
            self.add_run('automatic-new', day=2, version='0.11.0', database=db)
            self.add_run('automatic-only', day=2, source=str(second_image),
                         image=second_digest, database=db)
        rows, audit, images = plot.load_measurements(
            [self.database, automatic], self.catalogue, self.root)
        self.assertEqual({row['run_id'] for row in rows},
                         {'automatic-new', 'automatic-only'})
        self.assertEqual({image['run_id'] for image in images},
                         {'automatic-new', 'automatic-only'})
        self.assertEqual(audit['run_selection']['selected']['unique_images'], 2)
        self.assertEqual(audit['run_selection']['superseded_successful_runs'], 1)
        self.assertEqual({Path(row['source_database']).name for row in rows},
                         {'automatic.sqlite'})


if __name__ == '__main__':
    unittest.main()
