# Provenance and third-party materials

## Project software

Wide-Field Solver is Copyright (c) 2026 Peter Thejll and Chris Flynn.

The software is distributed under the BSD 3-Clause licence in `LICENSE`. That
licence permits use, modification and redistribution of the software subject to
its attribution and disclaimer conditions. It applies to the project software,
not automatically to photographs, observations, catalogues or other third-party
materials described below.

## Included MMTO example observation

The curated v0.11.0 release contains:

`examples/mmto/2026_09_19__02_20_01.fits.bz2`

SHA-256:
`d7278337c18a87e19b4254dbd053769cc10233732f1ce686a44b235a567fa960`

Required credit: **MMTO all-sky-camera image courtesy of MMT Observatory,
provided with permission from Tim Pickering.**

The BSD 3-Clause software licence does not license the MMTO observation. The
example is included with the stated permission and credit; no claim of software
author copyright over the observation is made.

## Photographs not included

No Fred Espenak photograph, unidentified historical photograph, or annotated
derivative of either is included in the curated v0.11.0 release. Fred Espenak
retains the rights to his separate photograph and is credited when that work is
discussed. Anyone wishing to redistribute such a photograph must obtain the
permission required by its owner.

## Catalogues

The Gaia catalogue uses public Gaia DR3 data from the ESA Gaia Archive. This
work has made use of data from the European Space Agency (ESA) mission Gaia
(https://www.cosmos.esa.int/gaia), processed by the Gaia Data Processing and
Analysis Consortium (DPAC,
https://www.cosmos.esa.int/web/gaia/dpac/consortium). Funding for DPAC has been
provided by national institutions, in particular the institutions participating
in the Gaia Multilateral Agreement.

The local bright-star supplement derives from Tycho-2 and Hipparcos, distributed
by CDS/VizieR. Catalogue query details, source identifiers, selection, epoch
handling and checksums are recorded with the bundled data. Retain those
attributions in derived work.

Display names may include identifiers and aliases retrieved from SIMBAD, which
is operated by CDS, Strasbourg: https://simbad.cds.unistra.fr/simbad/. Names are
labels only and do not supply astrometric positions to the fit.

## Scientific model and software dependencies

The camera model follows Barghini et al. (2019):
https://doi.org/10.1051/0004-6361/201935580.

The blind pattern bootstrap uses ESA tetra3:
https://github.com/esa/tetra3. The complete source repository records the pinned
revision and provenance of its bundled pattern database.

Other software dependencies are declared in `pyproject.toml` and resolved in
`uv.lock`; their upstream licences apply.
