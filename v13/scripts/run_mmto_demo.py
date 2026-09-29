"""Solve the bundled native-colour MMTO example offline and check it."""
import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def run_demo(output: Path) -> None:
    output = output.resolve()
    subprocess.run([
        sys.executable,
        str(ROOT/"point_star_barghini.py"),
        str(ROOT/"examples/mmto/2026_09_19__02_20_01.fits.bz2"),
        "--output",
        str(output),
        "--catalog",
        str(ROOT/"data/stars_gaia_dr3_g75.csv"),
        "--epoch-mode",
        "fit",
        "--labels",
        "40",
        "--offline",
        "--overwrite",
        "--names-cache",
        str(ROOT/"data/display_names.json"),
    ], check=True)
    subprocess.run([
        sys.executable,
        str(ROOT/"scripts/check_mmto_demo.py"),
        str(output),
    ], check=True)
    print(f"Annotated image: {output/'identified_40_stars.png'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"results/demo")
    args = parser.parse_args()
    run_demo(args.output)


if __name__ == "__main__":
    main()
