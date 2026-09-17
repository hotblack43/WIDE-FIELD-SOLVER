"""Negative evidence must concern bright detectable planets, not arbitrary blanks."""
import importlib.util
import unittest
import numpy as np
from point_star_planet_brightness import planet_brightness,visual_magnitude

class BrightnessTests(unittest.TestCase):
    def test_published_zero_phase_coefficients(self):
        for name,value in [('mercury',-.613),('venus',-4.384),('mars',-1.601),('jupiter',-9.395),('saturn',-8.95)]:
            self.assertAlmostEqual(float(visual_magnitude(name,1,1,0)),value)
        self.assertAlmostEqual(float(visual_magnitude('jupiter',5,4,0)),-2.889850021680094)

    def test_faint_planets_and_outside_formula_domain_are_unassessed(self):
        for name in ['uranus','neptune','pluto']:
            self.assertTrue(np.isnan(planet_brightness(name,[2459000.])).all())
        self.assertTrue(np.isnan(visual_magnitude('saturn',9,8,10)))
        self.assertTrue(np.isnan(visual_magnitude('jupiter',-1,1,0)))

    def test_jupiter_published_skyfield_example_and_batch_consistency(self):
        # Skyfield's documented 2020-07-31 example gives -2.73 V mag.
        from astropy.time import Time
        jd=Time('2020-07-31',scale='utc').tdb.jd
        values=planet_brightness('jupiter',[jd,jd+100])
        self.assertAlmostEqual(values[0],-2.73,delta=.03)
        self.assertAlmostEqual(values[1],planet_brightness('jupiter',[jd+100])[0],places=10)


class NonDetectionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('point_star_planet_nondetections'), 'Missing-planet evidence is not implemented')
        from point_star_planet_nondetections import LocalDetectability
        self.api=LocalDetectability
        rng=np.random.default_rng(25)
        self.pixels=rng.normal(100,2,(240,320))
        self.stars=[]
        self.detections=[]
        for i,(x,y) in enumerate([(135,100),(160,85),(185,100),(185,140),(160,155),(135,140)]):
            yy,xx=np.indices(self.pixels.shape)
            self.pixels+=60*np.exp(-((xx-x)**2+(yy-y)**2)/(2*.9**2))
            self.stars.append(dict(detection_id=i+1,x_px=x,y_px=y,magnitude=5.,residual_px=.2))
            self.detections.append(dict(detection_id=i+1,x_px=x,y_px=y,saturated=False,
                source_class='compact',peak_above_background=60.,peak_snr=30.,major_sigma_px=.9))

    def checker(self,pixels=None,detections=None,stars=None,**kwargs):
        return self.api(self.pixels if pixels is None else pixels,
                        self.detections if detections is None else detections,
                        self.stars if stars is None else stars,**kwargs)

    def test_bright_planet_on_supported_blank_sky_is_negative_evidence(self):
        row=self.checker().assess('jupiter',[160,120],-2.)
        self.assertEqual(row['status'],'missing_bright_planet')
        self.assertGreaterEqual(row['supporting_stars'],5)
        self.assertGreater(row['reference_peak_lower_adu'],row['required_peak_adu'])

    def test_faint_planet_and_bright_planet_below_local_depth_are_not_penalised(self):
        for name in ['uranus','neptune','pluto']:
            self.assertEqual(self.checker().assess(name,[160,120],7.)['status'],'not_tested_faint_planet')
        self.assertNotEqual(self.checker().assess('mercury',[160,120],6.)['status'],'missing_bright_planet')

    def test_raw_source_blocks_penalty_even_when_detector_missed_it(self):
        pixels=self.pixels.copy()
        yy,xx=np.indices(pixels.shape)
        pixels+=70*np.exp(-((xx-163)**2+(yy-120)**2)/(2*.9**2))
        self.assertEqual(self.checker(pixels=pixels).assess('jupiter',[160,120],-2.)['status'],'pixel_signal_present')

    def test_any_detected_source_including_saturated_blob_blocks_penalty(self):
        detections=self.detections+[dict(detection_id=99,x_px=163.,y_px=120.,saturated=True,source_class='broad_blob')]
        self.assertEqual(self.checker(detections=detections).assess('jupiter',[160,120],-2.)['status'],'source_present')

    def test_obstruction_cloud_noise_edges_and_missing_support_are_inconclusive(self):
        for kind in ['dark_obstruction','bright_cloud','noisy','masked']:
            with self.subTest(kind=kind):
                pixels=self.pixels.copy()
                options={}
                if kind=='dark_obstruction': pixels[105:135,145:175]=0
                elif kind=='bright_cloud': pixels[105:135,145:175]+=80
                elif kind=='noisy': pixels[105:135,145:175]+=np.random.default_rng(9).normal(0,35,(30,30))
                else:
                    mask=np.ones(pixels.shape,bool);mask[119:122,159:162]=False
                    options['valid_mask']=mask
                self.assertNotEqual(self.checker(pixels=pixels,**options).assess('jupiter',[160,120],-2.)['status'],'missing_bright_planet')
        self.assertNotEqual(self.checker().assess('jupiter',[1,1],-2.)['status'],'missing_bright_planet')
        self.assertNotEqual(self.checker(stars=self.stars[:2]).assess('jupiter',[160,120],-2.)['status'],'missing_bright_planet')

    def test_saved_sky_footprint_makes_frame_pixels_inconclusive(self):
        import tempfile
        from pathlib import Path
        from point_star_planets import _load_sky_footprint
        with tempfile.TemporaryDirectory() as folder:
            dots = Path(folder)/'dots'
            dots.mkdir()
            mask = np.ones(self.pixels.shape, dtype=bool)
            mask[110:131, 150:171] = False
            np.savez_compressed(dots/'sky_footprint.npz', valid_mask=mask)
            loaded = _load_sky_footprint(folder)
            row = self.checker(valid_mask=loaded).assess('jupiter', [160,120], -2.)
        self.assertEqual(row['status'], 'inconclusive_mask_or_edge')

    def test_candidate_absence_reads_signal_above_255_in_native_fits(self):
        import tempfile
        from pathlib import Path
        from astropy.io import fits
        from point_star_barghini import BarghiniCamera
        from point_star_planet_nondetections import check_candidate_absences
        camera = BarghiniCamera.initial(self.pixels.shape, 180., np.eye(3))
        answer = RankingTests().answer()
        answer['visibility'].update(zenith_unit_vector=[0., 0., 1.])
        answer['searched_planets'] = ['jupiter']
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'native.fits'
            native = self.pixels*16
            yy, xx = np.indices(native.shape)
            native += 70*16*np.exp(-((xx-163)**2+(yy-120)**2)/(2*.9**2))
            planes = np.stack([native, native, native]).astype(np.uint16)
            fits.PrimaryHDU(planes).writeto(path)
            after = check_candidate_absences(
                path, answer, camera, self.detections, self.stars,
                lambda name, dates: camera.to_sky(np.tile([160., 120.], (len(dates), 1))),
                magnitude_function=lambda name, dates: np.full(len(dates), -2.))
        statuses = [candidate['non_detection_evidence'][0]['status']
                    for candidate in after['candidates']]
        self.assertEqual(statuses, ['pixel_signal_present', 'pixel_signal_present'])

    def test_each_candidate_uses_its_own_epoch_and_regenerates_visible_predictions(self):
        import tempfile, json, copy
        from pathlib import Path
        from PIL import Image
        from point_star_barghini import BarghiniCamera
        from point_star_planets import predict_other_planets
        from point_star_planet_nondetections import check_candidate_absences, write_evidence
        camera=BarghiniCamera.initial(self.pixels.shape,180.,np.eye(3))
        answer=RankingTests().answer()
        answer['visibility'].update(zenith_unit_vector=[0.,0.,1.])
        answer['searched_planets']=['mercury','jupiter','venus','saturn','neptune']
        for candidate in answer['candidates']:
            candidate['matches'].append(dict(planet='Saturn',detection_id=99))
            candidate['match_count']=2
        original=copy.deepcopy(answer); fixed_camera=camera.serialise()
        calls=[]
        def vectors(name,dates):
            calls.append((name,list(dates)))
            if name=='venus': return np.tile([0.,0.,-1.],(len(dates),1))
            if name=='neptune': return camera.to_sky(np.tile([195.,125.],(len(dates),1)))
            points=[[160.,120.] if jd==2459000. else [135.,100.] for jd in dates]
            return camera.to_sky(points)
        def magnitudes(name,dates):
            self.assertEqual(list(dates),[2459000.,2459001.])
            return np.full(len(dates),-2.)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'not-a-date.png'
            Image.fromarray(np.uint8(np.clip(self.pixels,0,255))).save(path)
            after=check_candidate_absences(path,answer,camera,self.detections,self.stars,vectors,magnitude_function=magnitudes)
            self.assertEqual(answer,original)
            self.assertEqual(camera.serialise(),fixed_camera)
            self.assertEqual(after['best_candidate_jd_tdb'],2459001.)
            self.assertEqual(after['status'],'planet_epoch_ambiguous')
            self.assertEqual(after['match_count'],2)
            evidence={r['planet']:r for r in after['candidates'][1]['non_detection_evidence']}
            self.assertEqual(evidence['Jupiter']['status'],'missing_bright_planet')
            self.assertEqual(evidence['Venus']['status'],'outside_visible_image')
            self.assertEqual(evidence['Mercury']['status'],'matched')
            self.assertEqual(evidence['Saturn']['status'],'matched')
            self.assertEqual(evidence['Neptune']['status'],'not_tested_faint_planet')
            self.assertTrue(all(dates==[2459000.,2459001.] for _,dates in calls))
            after['predicted_planets']=predict_other_planets(camera,after,vectors)
            self.assertEqual({r['planet'] for r in after['predicted_planets']},{'Jupiter','Neptune'})
            self.assertTrue(all(r['jd_tdb']==2459001. for r in after['predicted_planets']))
            jupiter=next(r for r in after['predicted_planets'] if r['planet']=='Jupiter')
            np.testing.assert_allclose([jupiter['predicted_x_px'],jupiter['predicted_y_px']],[135.,100.],atol=1e-5)
            write_evidence(folder,after)
            self.assertEqual(json.loads((Path(folder)/'planet_non_detections.json').read_text())['candidates'][1]['missing_bright_planets'],['Jupiter'])

    def test_nonzero_dark_core_is_an_obstruction(self):
        pixels=self.pixels.copy()
        yy,xx=np.indices(pixels.shape)
        pixels[np.hypot(xx-160,yy-120)<=9]=10
        self.assertEqual(self.checker(pixels=pixels).assess('jupiter',[160,120],-2.)['status'],
                         'inconclusive_background_or_obstruction')

    def test_psf_wings_inside_wider_probe_conservatively_block_absence(self):
        pixels=self.pixels.copy()
        yy,xx=np.indices(pixels.shape)
        pixels+=500*np.exp(-((xx-169)**2+(yy-120)**2)/(2*1.5**2))
        self.assertEqual(self.checker(pixels=pixels).assess('jupiter',[160,120],-2.)['status'],
                         'pixel_signal_present')

    def test_stars_on_only_one_side_do_not_establish_transparency(self):
        stars=[s for s in self.stars if s['x_px']<=160]
        self.assertNotEqual(self.checker(stars=stars).assess('jupiter',[170,120],-2.)['status'],'missing_bright_planet')

class RankingTests(unittest.TestCase):
    def answer(self):
        import copy
        candidates=[]
        for i in range(2):
            candidates.append(dict(jd_tdb=2459000.+i,epoch_tdb=f'date {i}',matches=[dict(planet='Mercury',detection_id=i+1)],
                match_count=1,cost_px2=.01+i*.01,rms_px=.1+i*.01,conditional_time_sigma_minutes=2.,boundary_limited=False))
        return dict(status='planet_epoch_ambiguous',candidates=candidates,matches=copy.deepcopy(candidates[0]['matches']),
            best_candidate_jd_tdb=2459000.,best_candidate_epoch_tdb='date 0',
            predicted_planets=[dict(planet='Jupiter',epoch_tdb='date 0')],
            visibility=dict(zenith_status='conditional_zenith'),positional_sigma_px=.5)

    def test_single_planet_aliases_are_audited_without_selecting_an_epoch(self):
        import copy
        from point_star_planet_nondetections import apply_evidence
        before=self.answer(); original=copy.deepcopy(before)
        after=apply_evidence(before,[[dict(planet='Jupiter',status='missing_bright_planet')],[]])
        self.assertEqual(before,original)
        self.assertIsNone(after['best_candidate_jd_tdb'])
        self.assertIsNone(after['best_candidate_epoch_tdb'])
        self.assertEqual(after['status'],'planet_epoch_not_identifiable')
        self.assertEqual(after['confidence'],'single_planet_aliases')
        self.assertEqual(after['matches'],[])
        self.assertEqual(after['match_count'],0)
        self.assertEqual(after['single_planet_candidate_count'],2)
        self.assertEqual(after['candidates'][0]['positional_rank'],2)
        for candidate in after['candidates']:
            expected=original['candidates'][candidate['positional_rank']-1]
            for key,value in expected.items(): self.assertEqual(candidate[key],value)
        self.assertEqual(after.get('predicted_planets',[]),[], 'Old-epoch overlays must be invalidated before reranking')

    def test_all_contradicted_has_no_supported_epoch_or_overlay(self):
        from point_star_planet_nondetections import apply_evidence
        missing=[dict(planet='Jupiter',status='missing_bright_planet')]
        after=apply_evidence(self.answer(),[missing,missing])
        self.assertEqual(after['status'],'planet_epoch_inconsistent')
        self.assertIsNone(after['best_candidate_jd_tdb'])
        self.assertEqual(after['matches'],[])
        self.assertFalse(after.get('predicted_planets'))
        self.assertEqual(len(after['candidates']),2)

    def test_no_candidates_needs_no_image_or_ephemeris(self):
        from point_star_planet_nondetections import check_candidate_absences
        after=check_candidate_absences('/missing/image',dict(status='no_planet_match',candidates=[]),None,[],[],None)
        self.assertEqual(after['status'],'no_planet_match')

    def test_plot_handles_no_supported_epoch(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        from point_star_planets import _plot_candidates
        from point_star_planet_nondetections import apply_evidence
        missing=[dict(planet='Jupiter',status='missing_bright_planet')]
        answer=apply_evidence(self.answer(),[missing,missing])
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder); path=folder/'image.png'
            Image.new('L',(40,40)).save(path)
            _plot_candidates(path,folder,answer)
            self.assertTrue((folder/'planet_candidates.png').is_file())

if __name__=='__main__': unittest.main()
