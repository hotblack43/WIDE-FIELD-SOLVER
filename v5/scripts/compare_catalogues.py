#!/usr/bin/env python3
"""Run independent Tycho/Gaia solves and paired spatial epoch-fit subsamples."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from point_star_catalogue_comparison import compare

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('image',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--tycho',type=Path,default=ROOT/'data/stars_tycho2_mag75.csv')
    p.add_argument('--gaia',type=Path,default=ROOT/'data/stars_gaia_dr3_g75.csv')
    p.add_argument('--repeats',type=int,default=32)
    p.add_argument('--fraction',type=float,default=.8)
    p.add_argument('--seed',type=int,default=20260914)
    a=p.parse_args()
    compare(a.image,a.tycho,a.gaia,a.output,a.repeats,a.fraction,a.seed)
