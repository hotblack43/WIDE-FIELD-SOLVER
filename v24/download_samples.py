#!/usr/bin/env python3
"""Download native all-sky samples with optional v24 mask assignment."""
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from v24.allsky_download_v24.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
