"""Recompute the complete Milky Way solution from pixels, then check it."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'results/demo')
    args = parser.parse_args()
    output = args.output.resolve()
    subprocess.run([
        sys.executable, str(ROOT/'point_star_barghini.py'),
        str(ROOT/'examples/milky_way/input.jpeg'), '--output', str(output),
        '--catalog', str(ROOT/'data/stars_tycho2_mag75.csv'),
        '--epoch-mode', 'catalog', '--labels', '40', '--offline', '--names-cache',
        str(ROOT/'examples/milky_way/reference/display_names.json'),
    ], check=True)
    subprocess.run([sys.executable, str(ROOT/'scripts/check_demo.py'), str(output)], check=True)
    print(f"Annotated image: {output/'identified_40_stars.png'}")


if __name__ == '__main__':
    main()
