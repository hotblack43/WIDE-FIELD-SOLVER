import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from point_star_names import choose_display_name, resolve_names


class StarNameTests(unittest.TestCase):
    def test_offline_names_use_cache_and_fallback_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)/'names.json'
            cache.write_text(json.dumps({'HIP 27989': {
                'display_name': 'α Ori', 'name_source': 'SIMBAD'}}))
            with patch.dict('sys.modules', {'astroquery.simbad': None}):
                names = resolve_names(['HIP 27989', 'TYC 1-2-1'],
                                      cache_path=cache, offline=True)
            self.assertEqual(names['HIP 27989']['display_name'], 'α Ori')
            self.assertEqual(names['TYC 1-2-1']['display_name'], 'TYC 1-2-1')

    def test_offline_without_cache_retains_identifiers(self):
        with patch.dict('sys.modules', {'astroquery.simbad': None}):
            names = resolve_names(['TYC 1-2-1'], offline=True)
        self.assertEqual(names['TYC 1-2-1']['name_source'], 'catalogue_identifier_fallback')

    def test_prefers_bayer_designation(self):
        self.assertEqual(choose_display_name('HD 39801|NAME Betelgeuse|* alf Ori', 'HIP 27989'), 'α Ori')

    def test_preserves_numbered_bayer_component(self):
        self.assertEqual(choose_display_name('* alf02 Cap|* 6 Cap', 'HD 192947'), 'α² Cap')

    def test_flamsteed_and_catalogue_fallback(self):
        self.assertEqual(choose_display_name('HD 217014|* 51 Peg', 'TYC 1717-2193-1'), '51 Peg')
        self.assertEqual(choose_display_name('Gaia DR3 123|HD 12345', 'TYC 1-2-1'), 'HD 12345')
        self.assertEqual(choose_display_name('', 'TYC 1-2-1'), 'TYC 1-2-1')
