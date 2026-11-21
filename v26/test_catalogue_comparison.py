import unittest
import numpy as np
from point_star_catalogue_comparison import spatial_samples, residual_comparison, summarise_resamples


class ComparisonTests(unittest.TestCase):
    def test_paired_blocks_keep_nearby_different_catalogue_stars_together(self):
        positions={}
        for i, angle in enumerate(np.linspace(0,2*np.pi,16,endpoint=False)+.05):
            x,y=200+140*np.cos(angle),200+140*np.sin(angle)
            positions[2*i]=[x,y]; positions[2*i+1]=[x+.01,y+.01]
        samples=spatial_samples(positions,(400,400),repeats=12,seed=4)
        self.assertEqual(samples,spatial_samples(positions,(400,400),repeats=12,seed=4))
        for sample in samples:
            ids=set(sample['detection_ids'])
            self.assertGreater(len(ids),0);self.assertLess(len(ids),len(positions))
            for i in range(16): self.assertEqual(2*i in ids,2*i+1 in ids)
        self.assertGreater(len({tuple(s['detection_ids']) for s in samples}),1)

    def test_shared_residuals_compare_the_same_detections(self):
        a={1:1.,2:2.,3:9.}; b={1:3.,2:4.,4:20.}
        score=residual_comparison(a,b)
        self.assertEqual(score['shared_count'],2)
        self.assertAlmostEqual(score['tycho_shared_rms_px'],np.sqrt(2.5))
        self.assertAlmostEqual(score['gaia_shared_rms_px'],np.sqrt(12.5))
        self.assertEqual(residual_comparison({1:1.},{2:2.})['shared_count'],0)

    def test_summary_retains_failures_and_unresolved_epochs(self):
        runs=[dict(status='ok',epoch_difference_years=2.,shared_rms_difference_px=-.1,
                   tycho_status='conditional_epoch',gaia_status='conditional_epoch'),
              dict(status='ok',epoch_difference_years=20.,shared_rms_difference_px=.3,
                   tycho_status='not_identifiable',gaia_status='conditional_epoch'),
              dict(status='failed',reason='optimizer failed')]
        summary=summarise_resamples(runs)
        self.assertEqual(summary['requested'],3)
        self.assertEqual(summary['failed'],1)
        self.assertEqual(summary['both_epochs_conditional'],1)
        self.assertEqual(summary['epoch_difference_years']['median'],11.)
        self.assertFalse(summary['epoch_difference_years']['calibrated_confidence_interval'])
