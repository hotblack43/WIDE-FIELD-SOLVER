import unittest
import numpy as np
from point_star_epoch import Catalogue
from point_star_gaia import convert_rows, supplement_bright


def row(source='9007199254740993', ra=0., dec=0., pmra='1000', pmdec='0'):
    return dict(source_id=source, ra=str(ra), dec=str(dec), ref_epoch='2016.0',
                pmra=pmra, pmdec=pmdec, phot_g_mean_mag='6.3')


class GaiaCatalogueTests(unittest.TestCase):
    def test_exact_identifier_native_epoch_and_cosdec_motion(self):
        rows=convert_rows([row(dec=60.)])
        self.assertEqual(rows[0]['star_id'], 'Gaia DR3 9007199254740993')
        self.assertEqual(float(rows[0]['reference_epoch_jyear']),2016.)
        cat=Catalogue.from_rows(rows)
        from astropy.coordinates import SkyCoord
        from astropy.time import Time
        import astropy.units as u
        expected=SkyCoord(ra=0*u.deg,dec=60*u.deg,pm_ra_cosdec=1000*u.mas/u.yr,
                          pm_dec=0*u.mas/u.yr,obstime=Time(2016.,format='jyear')).apply_space_motion(new_obstime=Time(2020.,format='jyear'))
        np.testing.assert_allclose(cat.at_year(2020.)[0],SkyCoord(ra=expected.ra,dec=expected.dec).cartesian.xyz.value,atol=1e-10)

    def test_missing_motion_remains_available(self):
        rows=convert_rows([row(pmra='',pmdec='')])
        self.assertEqual(len(rows),1)
        self.assertFalse(Catalogue.from_rows(rows).has_motion[0])

    def test_bright_supplement_is_deduplicated_at_common_epoch(self):
        gaia=convert_rows([row(ra=16/3600,pmra='1000')])
        old=[dict(star_id='HIP 000001',ra_deg='0',dec_deg='0',mag='1',
                  reference_epoch_jyear='2000',pm_ra_cosdec_mas_per_year='1000',pm_dec_mas_per_year='0'),
             dict(star_id='HIP 000002',ra_deg='30',dec_deg='0',mag='2',
                  reference_epoch_jyear='1991.25',pm_ra_cosdec_mas_per_year='',pm_dec_mas_per_year='')]
        combined,audit=supplement_bright(gaia,old)
        self.assertEqual([r['star_id'] for r in combined],['Gaia DR3 9007199254740993','HIP 000002'])
        self.assertEqual(audit['supplement_count'],1)
        self.assertEqual(combined[1]['reference_epoch_jyear'],'1991.25')

    def test_rejects_bad_or_duplicate_identifiers(self):
        for rows in ([row(source='9.007199254740993e15')],[row(),row()]):
            with self.assertRaises(ValueError): convert_rows(rows)
