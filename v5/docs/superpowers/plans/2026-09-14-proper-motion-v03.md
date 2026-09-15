# Proper-motion version 0.3.0 Implementation Plan

> Execute inline, task by task, using the executing-plans and test-driven-development guidance. User has approved implementation and isolation.

**Goal:** Fit proper motions and stellar epoch into the saved point-source astrometric solution.
**Architecture:** A catalogue/epoch module feeds the existing Barghini solver before product generation. The baseline has an explicit catalogue replay mode. Science consumes the integrated solution.
**Tech Stack:** Locked Python 3.12, NumPy, SciPy, Astropy; no new dependencies.
**Spec:** docs/superpowers/specs/2026-09-14-proper-motion-v03.md

## Global constraints

Preserve v0.1.0, original checkout, frozen catalogue/input/reference; no withheld stars; no saved-identity bootstrap; all corrections in the model and saved coordinates; keep uv.lock; no Gaia changes yet.

## Tasks

- [x] Establish clean baseline with `uv run --frozen python -m unittest discover -v`.
- [x] Add failing `test_point_star_epoch.py` cases for independent Astropy propagation, mixed epochs, missing-motion flags and invalid inputs. Implement `Catalogue.from_rows(rows)`, `Catalogue.at_year(year)`, and `Catalogue.subset(indices)` in `point_star_epoch.py`.
- [x] Add synthetic epoch/camera recovery and unidentifiable-motion tests. Implement `fit_epoch(camera, xy, catalogue, year_limits, fixed_year=None)` returning `(camera, final_fit, epoch_record)`. Score consistent associations with the fitter's robust objective and return bounded conditional profile intervals or explicit unresolved provenance.
- [x] Add solver integration test exercising real propagation/fitting/product generation with controlled detector and bootstrap boundaries. Extend `run(..., epoch_mode='fit', epoch_year=None, epoch_limits=(1850.,2150.))`, associate to convergence, and export final/original coordinates and epoch metadata. Protect outputs by default in v0.3.
- [x] Route `analyse_image.py` to the new mode and reuse `result['stellar_epoch']` in `point_star_science.py`; update report wording and epoch profile product. Preserve baseline using `--epoch-mode catalog` in `scripts/run_demo.py`.
- [x] Set version 0.3.0 in pyproject.toml and uv.lock, document commands, numerical assumptions, and limitations in README and method/version notes.
- [x] Run targeted tests, complete unit discovery, and `./demo.sh --output results/check-v03-legacy` before committing. Run a fresh blind new-mode example in a unique output directory, check saved coordinate reconstruction, review the diff, and commit only this worktree.
