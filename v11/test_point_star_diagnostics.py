"""Catch swapped/duplicated plotted coordinates and incorrect radial summaries."""
import tempfile
from pathlib import Path
import unittest

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

from point_star_barghini import BarghiniCamera
from point_star_diagnostics import create_overlay, radial_statistics, write_diagnostics


class DiagnosticTests(unittest.TestCase):
    def test_radial_statistics_report_physical_angular_residuals_when_camera_is_available(self):
        camera = BarghiniCamera.initial((101, 101), 50., np.eye(3))
        measured = np.array([[50., 50.]])
        angle = np.deg2rad(10./60.)
        reference = camera.to_sky(measured)
        reference = reference @ np.array([
            [np.cos(angle), 0., np.sin(angle)],
            [0., 1., 0.],
            [-np.sin(angle), 0., np.cos(angle)],
        ]).T
        predicted = camera.project(reference)

        report = radial_statistics(measured, predicted, camera.shape, camera=camera)

        self.assertAlmostEqual(report['rms_arcmin'], 10., places=9)
        self.assertAlmostEqual(report['bins'][0]['rms_arcmin'], 10., places=9)
        self.assertIn('rms_px', report)

    def test_overlay_uses_actual_measured_and_predicted_positions(self):
        measured = np.array([[10., 20.], [30., 40.]])
        predicted = np.array([[10.5, 19.], [32., 40.2]])
        fig = create_overlay(np.zeros((60, 70, 3)), measured, predicted,
                             unmatched=np.array([[50., 50.]]))
        try:
            plotted = {item.get_label(): item for item in fig.axes[0].collections}
            np.testing.assert_allclose(plotted['Measured centroids'].get_offsets(), measured)
            np.testing.assert_allclose(plotted['Catalogue predictions'].get_offsets(), predicted)
            np.testing.assert_allclose(plotted['Unmatched detections'].get_offsets(), [[50., 50.]])
            self.assertGreater(fig.axes[0].get_ylim()[0], fig.axes[0].get_ylim()[1])
        finally:
            plt.close(fig)

    def test_radial_bins_keep_all_pairs_and_report_empty_regions(self):
        measured = np.array([[50., 50.], [53., 54.], [65., 50.], [75., 50.]])
        predicted = measured+[[0., 0.], [3., 4.], [0., 2.], [-1., 0.]]
        report = radial_statistics(measured, predicted, (101, 101), bin_width=10.)
        bins = report['bins']
        self.assertEqual(sum(b['count'] for b in bins), 4)
        self.assertEqual([b['count'] for b in bins[:4]], [2, 1, 1, 0])
        self.assertAlmostEqual(bins[0]['rms_px'], np.sqrt(12.5))
        self.assertAlmostEqual(bins[0]['mean_radial_offset_px'], 5.)
        self.assertAlmostEqual(bins[1]['rms_px'], 2.)
        self.assertAlmostEqual(bins[2]['mean_radial_offset_px'], -1.)
        self.assertIsNone(bins[3]['rms_px'])
        self.assertEqual(report['maximum_residual_px'], 5.)

    def test_radial_bins_stop_at_the_bin_containing_the_image_corner(self):
        report = radial_statistics([[50., 50.]], [[50., 50.]], (101, 101), bin_width=10.)
        self.assertEqual(report['bins'][-1]['radius_low_px'], 70.)
        self.assertEqual(report['bins'][-1]['radius_high_px'], 80.)

    def test_writes_inspectable_plots_and_numeric_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root/'image.png'
            Image.fromarray(np.zeros((101, 101, 3), dtype=np.uint8)).save(image)
            measured = np.array([[30., 30.], [70., 70.]])
            write_diagnostics(image, measured, measured+.2, root)
            for name in ('astrometry_overlay.png', 'astrometry_residuals.png'):
                with Image.open(root/name) as plot:
                    plot.verify()
            self.assertTrue((root/'radial_residuals.json').is_file())
            self.assertTrue((root/'radial_residuals.csv').is_file())


if __name__ == '__main__':
    unittest.main()
