"""Export must preserve pixels, measured positions and the fixed camera solution."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from PIL import Image
from point_star_barghini import BarghiniCamera, vectors


class FitsExportTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('point_star_fits'), 'FITS exporter is not implemented')
        import point_star_fits
        self.api = point_star_fits
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        self.camera = BarghiniCamera.initial((180, 240), 110., np.eye(3))
        self.result = {'camera': self.camera.serialise(), 'source': 'not-used', 'metadata': {'date': '1900'}}
        self.science = {'planets': {'status': 'planet_epoch_ambiguous', 'best_candidate_epoch_tdb': '2026-01-01',
            'matches': [{'planet': 'Mars', 'measured_x_px': 81.25, 'measured_y_px': 92.5}],
            'predicted_planets': [{'planet': 'Saturn', 'predicted_x_px': 180.75, 'predicted_y_px': 113.5}]}}
        (self.out/'labelled_stars.json').write_text(json.dumps({'stars':[
            {'display_name':'Vega','star_id':'1','x_px':80.5,'y_px':90.25},
            {'display_name':'Deneb','star_id':'2','x_px':81.5,'y_px':91.25}]}))

    def export(self, rgb=False):
        pixels = np.arange(180*240*(3 if rgb else 1), dtype=np.uint8).reshape((180,240,3) if rgb else (180,240))
        image = self.out/'input.png'
        Image.fromarray(pixels).save(image)
        record = self.api.write_fits(image, self.out, self.result, self.science)
        self.assertEqual(record['status'], 'exported')
        return pixels, self.out/record['file']

    def test_one_bit_monochrome_pixels_are_preserved(self):
        pixels=np.indices((180,240)).sum(axis=0)%2 == 0
        image=self.out/'binary.png'
        Image.fromarray(pixels).save(image)
        record=self.api.write_fits(image,self.out,self.result,self.science)
        self.assertEqual(record['status'],'exported')
        with fits.open(self.out/record['file']) as hdus:
            np.testing.assert_array_equal(hdus[0].data,pixels.astype('uint8'))

    def test_mono_pixels_wcs_and_original_camera_are_preserved(self):
        before=json.dumps(self.result, sort_keys=True)
        pixels, path=self.export()
        with fits.open(path) as hdus:
            np.testing.assert_array_equal(hdus[0].data,pixels)
            wcs=WCS(hdus[0].header)
            xy=np.array([[0.,0.],[239.,179.],[119.5,89.5],[15.31,160.27]])
            world=wcs.all_pix2world(xy,0)
            np.testing.assert_allclose(self.camera.project(vectors(world[:,0],world[:,1])),xy,atol=.05)
            self.assertLess(hdus[0].header['ZPNERR'],.05)
        self.assertEqual(json.dumps(self.result,sort_keys=True),before)

    def test_rgb_keeps_three_channels_with_identical_wcs(self):
        pixels,path=self.export(rgb=True)
        with fits.open(path) as hdus:
            self.assertIsNone(hdus[0].data)
            for i,name in enumerate(['RED','GREEN','BLUE']):
                np.testing.assert_array_equal(hdus[name].data,pixels[:,:,i])
                self.assertEqual(hdus[name].header['CTYPE1'],'RA---ZPN')
                self.assertEqual(hdus[name].header['CRPIX1'],hdus['RED'].header['CRPIX1'])

    def test_overlays_keep_measured_and_predicted_positions_distinct(self):
        _,path=self.export()
        with fits.open(path) as hdus:
            record=json.loads(bytes(hdus['WFSINFO'].data).decode('utf8'))
            rows={r['label']:r for r in record['overlays']}
            self.assertEqual([rows['Mars (candidate)']['x'],rows['Mars (candidate)']['y']],[81.25,92.5])
            self.assertEqual(rows['Mars (candidate)']['kind'],'matched_planet')
            self.assertEqual([rows['Saturn (predicted)']['x'],rows['Saturn (predicted)']['y']],[180.75,113.5])
            text=bytes(hdus['DS9TEXT'].data).decode('utf8')
            self.assertIn('text={Mars (candidate)}',text)
            self.assertIn('text={Saturn (predicted)}',text)
            self.assertIn('fill=0',text)
            self.assertIn('width=2',text)
            self.assertIn('width=1',text)
            # Native FITS region positions use one-based coordinates.
            self.assertAlmostEqual(hdus['REGION'].data['X'][0][0],81.5)
            self.assertAlmostEqual(hdus['REGION'].data['Y'][0][0],91.25)

    def test_colour_metadata_does_not_change_wcs_or_annotations(self):
        _,path=self.export(rgb=True)
        with fits.open(path) as hdus:
            before=(WCS(hdus['RED'].header).to_header().tostring(), bytes(hdus['DS9TEXT'].data), bytes(hdus['WFSINFO'].data))
        self.result['metadata']={'date':'2099','latitude':89.9}
        self.export(rgb=True)
        with fits.open(path) as hdus:
            after=(WCS(hdus['RED'].header).to_header().tostring(), bytes(hdus['DS9TEXT'].data), bytes(hdus['WFSINFO'].data))
        self.assertEqual(after,before)

    def test_bad_domain_does_not_publish_misleading_wcs(self):
        self.camera=BarghiniCamera.initial((180,240),10.,np.eye(3))
        self.result['camera']=self.camera.serialise()
        image=self.out/'input.png'
        Image.fromarray(np.zeros((180,240),dtype='uint8')).save(image)
        record=self.api.write_fits(image,self.out,self.result,self.science)
        self.assertEqual(record['status'],'unavailable')
        self.assertFalse((self.out/'solution.fits').exists())
        self.assertIn('reason',record)

    def test_wrong_original_image_is_rejected_even_if_dimensions_match(self):
        import hashlib
        image=self.out/'input.png'
        Image.fromarray(np.zeros((180,240),dtype='uint8')).save(image)
        self.result['source_sha256']=hashlib.sha256(image.read_bytes()).hexdigest()
        Image.fromarray(np.ones((180,240),dtype='uint8')).save(image)
        record=self.api.write_fits(image,self.out,self.result,self.science)
        self.assertEqual(record['status'],'unavailable')
        self.assertFalse((self.out/'solution.fits').exists())

    def test_refused_reexport_archives_previous_file(self):
        _,path=self.export()
        previous=path.read_bytes()
        record=self.api.write_fits(self.out/'missing.png',self.out,self.result,self.science)
        self.assertEqual(record['status'],'unavailable')
        self.assertFalse(path.exists(), 'A refused export must not leave an old current FITS')
        self.assertEqual((self.out/record['previous_file']).read_bytes(),previous)

    def test_ambiguous_planet_is_visibly_qualified(self):
        _,path=self.export()
        with fits.open(path) as hdus:
            text=bytes(hdus['DS9TEXT'].data).decode('utf8')
        self.assertIn('text={Mars (candidate)}',text)

    def test_nonlinear_displaced_rotated_camera_wcs(self):
        from scipy.spatial.transform import Rotation
        camera=BarghiniCamera.initial((900,1200),500.,np.eye(3))
        camera.p=np.array([.31,570/camera.scale,410/camera.scale,615/camera.scale,455/camera.scale,
                           np.log(.0017*camera.scale),.15,.002*camera.scale])
        axis=camera.to_sky([[570.,410.]])[0]
        target=vectors([359.95],[70.])[0]
        cross=np.cross(axis,target)
        camera.reference_rotation=Rotation.from_rotvec(cross/np.linalg.norm(cross)*np.arctan2(np.linalg.norm(cross),axis@target)).as_matrix()
        before=json.dumps(camera.serialise(),sort_keys=True)
        header,record=self.api.validated_header(camera)
        self.assertGreater(record['order'],3)
        xy=np.vstack([np.random.default_rng(2048).uniform([0,0],[1199,899],(300,2)),
                      [[570.,410.],[0,0],[1199,899]],camera.project([[0.,0.,1.]])])
        wcs=WCS(header)
        world=wcs.all_pix2world(xy,0)
        predicted=camera.project(vectors(world[:,0],world[:,1]))
        self.assertLess(np.linalg.norm(predicted-xy,axis=1).max(),.05)
        true_sky=camera.to_sky(xy)
        ra=np.rad2deg(np.arctan2(true_sky[:,1],true_sky[:,0]))%360
        dec=np.rad2deg(np.arctan2(true_sky[:,2],np.hypot(true_sky[:,0],true_sky[:,1])))
        self.assertLess(np.linalg.norm(wcs.all_world2pix(np.c_[ra,dec],0)-xy,axis=1).max(),.05)
        self.assertEqual(json.dumps(camera.serialise(),sort_keys=True),before)

    def test_nonfinite_intermediate_zpn_trial_does_not_block_later_valid_order(self):
        camera = BarghiniCamera(
            (925, 925),
            np.array([
                [-0.47680083379748056, 0.3402823293262998, -0.8104744914174015],
                [0.8788155082017073, 0.16507522929188856, -0.44769796874500756],
                [-0.01855444513324982, -0.9257203168465615, -0.37775339514463546],
            ]),
            np.array([0.000050593241300934104, 0.7166585334594529,
                      0.7078672406123203, 0.7060688498578288,
                      0.7058174984673419, 0.7090900783228151,
                      0.007102067074746285, 5.0]),
        )
        _, record = self.api.validated_header(camera)
        attempts = {row['order']: row for row in record['attempts']}
        self.assertEqual(record['order'], 13)
        self.assertIsNone(attempts[7]['maximum_error_px'])
        self.assertLess(record['maximum_error_px'], self.api.LIMIT_PX)

    def test_missing_image_does_not_export_a_rendered_overlay(self):
        record=self.api.write_fits(self.out/'missing.png',self.out,self.result,self.science)
        self.assertEqual(record['status'],'unavailable')
        self.assertFalse((self.out/'solution.fits').exists())

    def test_clustered_labels_do_not_overlap_and_centres_stay_fixed(self):
        rows=[{'x':100.+i*.1,'y':80.+i*.1,'label':'Long star name '+str(i),'kind':'star'} for i in range(8)]
        original=json.loads(json.dumps(rows))
        layout=self.api.layout_labels(rows,(180,240))
        self.assertEqual(rows,original)
        boxes=[r['bbox'] for r in layout]
        for i,a in enumerate(boxes):
            for b in boxes[i+1:]:
                self.assertFalse(a[0]<b[2] and b[0]<a[2] and a[1]<b[3] and b[1]<a[3])

if __name__=='__main__': unittest.main()
