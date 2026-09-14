import importlib.util
from pathlib import Path
import unittest


class CatalogueBuilder2Tests(unittest.TestCase):
    def test_builder_defaults_to_v2_tycho85_with_bright_hipparcos(self):
        script = Path(__file__).parent / "scripts" / "rebuild_catalogue2.py"
        spec = importlib.util.spec_from_file_location("rebuild_catalogue2", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        args = module.build_parser().parse_args([])
        self.assertEqual(args.magnitude_limit, 8.5)
        self.assertEqual(args.hipparcos_supplement_limit, 2.0)
        self.assertEqual(args.output, Path("data/stars_tycho2_mag85_v2.csv"))


if __name__ == "__main__":
    unittest.main()
