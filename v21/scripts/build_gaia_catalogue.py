#!/usr/bin/env python3
"""Download the all-sky Gaia bright catalogue into the local solver CSV format."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from point_star_gaia import build

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--supplement-catalogue',type=Path,default=ROOT/'data/stars_tycho2_mag75.csv')
    p.add_argument('--magnitude-limit',type=float,default=7.5)
    a=p.parse_args()
    build(a.output,a.supplement_catalogue,a.magnitude_limit)
