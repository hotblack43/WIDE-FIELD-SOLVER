#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#   "astropy==7.2.0",
#   "h5py==3.16.0",
#   "numpy==2.4.4",
#   "pillow==12.2.0",
#   "rawpy==0.27.1",
# ]
# ///

from allsky_download.inspect_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
