"""Robust constrained nightly extinction with per-exposure grey terms."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Sequence

import numpy as np
from scipy.optimize import least_squares

from scripts.nightly_extinction import StarKey, StellarMeasurement


MODEL = "v21_star_intercepts_shared_extinction_per_image_grey_soft_l1"


@dataclass(frozen=True)
class GreyExtinctionFit:
    status: str
    model: str = MODEL
    extinction_mag_per_airmass: float | None = None
    extinction_uncertainty: float | None = None
    star_intercepts: dict[StarKey, float] = field(default_factory=dict)
    image_offsets: dict[str, float] = field(default_factory=dict)
    image_offset_uncertainties: dict[str, float | None] = field(default_factory=dict)
    residuals: tuple[float, ...] = ()
    sample_count: int = 0
    star_count: int = 0
    image_count: int = 0
    design_rank: int = 0
    parameter_count: int = 0
    airmass_leverage_norm: float = 0.0
    rms_magnitude: float | None = None


def _rejected(status: str, rows: Sequence[StellarMeasurement], stars=(), images=(), *, rank=0, parameters=0, leverage=0.0) -> GreyExtinctionFit:
    return GreyExtinctionFit(
        status=status, sample_count=len(rows), star_count=len(stars), image_count=len(images),
        design_rank=rank, parameter_count=parameters, airmass_leverage_norm=leverage,
    )


def fit_grey_extinction(
    measurements: Sequence[StellarMeasurement], *, min_stars: int = 20,
    min_images: int = 3, loss_scale_mag: float = 0.1,
) -> GreyExtinctionFit:
    """Fit ``delta_m(s,i)=a_s+k X(s,i)+Z_i`` with ``sum Z_i=0``.

    The supplied measurement membership is fixed. Robust soft-L1 weighting
    limits outliers without clipping or changing which stars enter the fit.
    """

    rows = tuple(measurements)
    if loss_scale_mag <= 0 or not math.isfinite(loss_scale_mag):
        raise ValueError("loss_scale_mag must be positive and finite")
    if not rows:
        return _rejected("no_measurements", rows)
    identities = {(row.night, row.channel) for row in rows}
    if len(identities) != 1:
        raise ValueError("grey extinction fit requires one night and one channel")
    keys = [(row.star_key, row.source_sha256) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate star/image measurement")
    stars = tuple(sorted({row.star_key for row in rows}))
    images = tuple(sorted({row.source_sha256 for row in rows}))
    if len(stars) < min_stars:
        return _rejected("insufficient_stars", rows, stars, images)
    if len(images) < min_images:
        return _rejected("insufficient_images", rows, stars, images)
    if any(sum(row.source_sha256 == image for row in rows) < 2 for image in images):
        return _rejected("image_has_insufficient_stars", rows, stars, images)

    star_index = {key: index for index, key in enumerate(stars)}
    image_index = {key: index for index, key in enumerate(images)}
    nstar, nimage, nrow = len(stars), len(images), len(rows)
    nuisance = np.zeros((nrow, nstar + nimage - 1), dtype=float)
    x = np.asarray([row.airmass for row in rows], dtype=float)
    y = np.asarray([row.delta_magnitude for row in rows], dtype=float)
    for row_index, row in enumerate(rows):
        nuisance[row_index, star_index[row.star_key]] = 1.0
        image = image_index[row.source_sha256]
        if image < nimage - 1:
            nuisance[row_index, nstar + image] = 1.0
        else:
            nuisance[row_index, nstar:] = -1.0
    design = np.column_stack((nuisance[:, :nstar], x, nuisance[:, nstar:]))
    nuisance_rank = int(np.linalg.matrix_rank(nuisance))
    design_rank = int(np.linalg.matrix_rank(design))
    parameter_count = design.shape[1]
    projected_x = x - nuisance @ np.linalg.lstsq(nuisance, x, rcond=None)[0]
    leverage = float(np.linalg.norm(projected_x))
    if design_rank <= nuisance_rank or leverage < 1e-8:
        return _rejected("deficient_airmass_leverage", rows, stars, images, rank=design_rank, parameters=parameter_count, leverage=leverage)
    if design_rank != parameter_count:
        return _rejected("deficient_design_rank", rows, stars, images, rank=design_rank, parameters=parameter_count, leverage=leverage)

    initial = np.linalg.lstsq(design, y, rcond=None)[0]
    solution = least_squares(
        lambda parameters: design @ parameters - y,
        initial, loss="soft_l1", f_scale=loss_scale_mag, x_scale="jac",
        ftol=1e-12, xtol=1e-12, gtol=1e-12, max_nfev=5000,
    )
    residual = design @ solution.x - y
    weights = 1.0 / np.sqrt(1.0 + (residual / loss_scale_mag) ** 2)
    weighted = design * np.sqrt(weights)[:, None]
    dof = max(nrow - parameter_count, 1)
    variance = float(np.sum(weights * residual**2) / dof)
    covariance = variance * np.linalg.pinv(weighted.T @ weighted)
    slope_index = nstar
    image_start = nstar + 1
    offsets = list(map(float, solution.x[image_start:]))
    offsets.append(-sum(offsets))
    offset_uncertainties: list[float | None] = []
    for image in range(nimage):
        contrast = np.zeros(parameter_count)
        if image < nimage - 1:
            contrast[image_start + image] = 1.0
        else:
            contrast[image_start:] = -1.0
        value = float(contrast @ covariance @ contrast)
        offset_uncertainties.append(math.sqrt(max(0.0, value)))
    return GreyExtinctionFit(
        status="accepted",
        extinction_mag_per_airmass=float(solution.x[slope_index]),
        extinction_uncertainty=math.sqrt(max(0.0, float(covariance[slope_index, slope_index]))),
        star_intercepts={key: float(solution.x[index]) for index, key in enumerate(stars)},
        image_offsets=dict(zip(images, offsets)),
        image_offset_uncertainties=dict(zip(images, offset_uncertainties)),
        residuals=tuple(map(float, residual)), sample_count=nrow, star_count=nstar,
        image_count=nimage, design_rank=design_rank, parameter_count=parameter_count,
        airmass_leverage_norm=leverage,
        rms_magnitude=float(np.sqrt(np.mean(residual**2))),
    )
