"""Robust constrained nightly extinction with per-exposure grey terms."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Sequence

import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import csr_matrix, hstack
from scipy.sparse.linalg import lsqr

from scripts.nightly_extinction import StarKey, StellarMeasurement


MODEL = "v23_star_intercepts_shared_extinction_per_image_grey_soft_l1"


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
    x = np.asarray([row.airmass for row in rows], dtype=float)
    y = np.asarray([row.delta_magnitude for row in rows], dtype=float)
    row_indices = np.arange(nrow)
    star_columns = np.asarray([star_index[row.star_key] for row in rows])
    star_design = csr_matrix(
        (np.ones(nrow), (row_indices, star_columns)), shape=(nrow, nstar)
    )
    image_rows: list[int] = []
    image_columns: list[int] = []
    image_values: list[float] = []
    for row_index, row in enumerate(rows):
        image = image_index[row.source_sha256]
        if image < nimage - 1:
            image_rows.append(row_index)
            image_columns.append(image)
            image_values.append(1.0)
        else:
            image_rows.extend([row_index] * (nimage - 1))
            image_columns.extend(range(nimage - 1))
            image_values.extend([-1.0] * (nimage - 1))
    image_design = csr_matrix(
        (image_values, (image_rows, image_columns)),
        shape=(nrow, nimage - 1),
    )
    design = hstack((star_design, csr_matrix(x[:, None]), image_design), format="csr")

    parent = list(range(nstar + nimage))

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for row in rows:
        left = find(star_index[row.star_key])
        right = find(nstar + image_index[row.source_sha256])
        if left != right:
            parent[right] = left
    component_count = len({find(node) for node in range(nstar + nimage)})
    nuisance_rank = nstar + nimage - component_count
    parameter_count = design.shape[1]
    image_design_dense = image_design.toarray()
    star_counts = np.bincount(star_columns, minlength=nstar)
    star_mean_x = np.bincount(
        star_columns, weights=x, minlength=nstar
    ) / star_counts
    centered_x = x - star_mean_x[star_columns]
    star_mean_image = np.asarray(star_design.T @ image_design_dense) / star_counts[:, None]
    centered_image = image_design_dense - star_mean_image[star_columns]
    image_projection = np.linalg.lstsq(centered_image, centered_x, rcond=None)[0]
    projected_x = centered_x - centered_image @ image_projection
    leverage = float(np.linalg.norm(projected_x))
    design_rank = nuisance_rank + int(leverage >= 1e-8)
    if design_rank <= nuisance_rank or leverage < 1e-8:
        return _rejected("deficient_airmass_leverage", rows, stars, images, rank=design_rank, parameters=parameter_count, leverage=leverage)
    if design_rank != parameter_count:
        return _rejected("deficient_design_rank", rows, stars, images, rank=design_rank, parameters=parameter_count, leverage=leverage)

    initial_solution = lsqr(
        design, y, atol=1e-12, btol=1e-12,
        iter_lim=max(1000, 10 * parameter_count),
    )
    if initial_solution[1] not in (0, 1, 2, 4, 5):
        raise RuntimeError(
            f"grey extinction LSQR initialization failed with istop={initial_solution[1]}"
        )
    initial = initial_solution[0]
    solution = least_squares(
        lambda parameters: design @ parameters - y,
        initial, jac=lambda _parameters: design, tr_solver="lsmr",
        tr_options={"atol": 1e-12, "btol": 1e-12},
        loss="soft_l1", f_scale=loss_scale_mag, x_scale="jac",
        ftol=1e-12, xtol=1e-12, gtol=1e-12, max_nfev=5000,
    )
    residual = design @ solution.x - y
    weights = 1.0 / np.sqrt(1.0 + (residual / loss_scale_mag) ** 2)
    dof = max(nrow - parameter_count, 1)
    variance = float(np.sum(weights * residual**2) / dof)
    global_design = np.column_stack((x, image_design_dense))
    weighted_star = star_design.multiply(np.sqrt(weights)[:, None])
    weighted_global = global_design * np.sqrt(weights)[:, None]
    star_information = np.asarray(weighted_star.power(2).sum(axis=0)).ravel()
    cross_information = np.asarray(weighted_star.T @ weighted_global)
    global_information = weighted_global.T @ weighted_global
    schur_information = global_information - cross_information.T @ (
        cross_information / star_information[:, None]
    )
    global_covariance = variance * np.linalg.pinv(schur_information)
    slope_index = nstar
    image_start = nstar + 1
    offsets = list(map(float, solution.x[image_start:]))
    offsets.append(-sum(offsets))
    offset_uncertainties: list[float | None] = []
    for image in range(nimage):
        contrast = np.zeros(nimage)
        if image < nimage - 1:
            contrast[1 + image] = 1.0
        else:
            contrast[1:] = -1.0
        value = float(contrast @ global_covariance @ contrast)
        offset_uncertainties.append(math.sqrt(max(0.0, value)))
    return GreyExtinctionFit(
        status="accepted",
        extinction_mag_per_airmass=float(solution.x[slope_index]),
        extinction_uncertainty=math.sqrt(max(0.0, float(global_covariance[0, 0]))),
        star_intercepts={key: float(solution.x[index]) for index, key in enumerate(stars)},
        image_offsets=dict(zip(images, offsets)),
        image_offset_uncertainties=dict(zip(images, offset_uncertainties)),
        residuals=tuple(map(float, residual)), sample_count=nrow, star_count=nstar,
        image_count=nimage, design_rank=design_rank, parameter_count=parameter_count,
        airmass_leverage_norm=leverage,
        rms_magnitude=float(np.sqrt(np.mean(residual**2))),
    )
