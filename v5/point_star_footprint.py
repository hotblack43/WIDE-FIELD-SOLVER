"""Conservative image-only support masks for framed fisheye photographs."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from scipy.ndimage import (
    binary_closing,
    binary_fill_holes,
    gaussian_filter,
    label,
)


def _luminance(image):
    pixels = np.asarray(image, dtype=float)
    if pixels.ndim == 3 and pixels.shape[2] >= 3:
        pixels = pixels[..., :3] @ np.array([.2126, .7152, .0722])
    if pixels.ndim != 2 or min(pixels.shape) < 15 or not np.isfinite(pixels).all():
        raise ValueError('A finite greyscale or RGB image at least 15 pixels wide is required')
    return pixels


def _full_image(shape, reason, **details):
    audit = dict(
        status='full_image',
        method='image_luminance_connected_footprint',
        valid_pixel_fraction=1.,
        threshold_adu=None,
        inside_median_adu=None,
        outside_median_adu=None,
        reason=reason,
        metadata_used=False,
        ocr_used=False,
        code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    audit.update(details)
    return np.ones(shape, dtype=bool), audit


def infer_sky_footprint(image):
    """Return a Boolean sky-support mask inferred only from image luminance.

    Ambiguous images deliberately fall back to the complete detector.  The
    mask separates a coherent illuminated field from a darker surrounding
    frame; it is not a semantic sky, obstruction, or text classifier.
    """
    pixels = _luminance(image)
    h, w = pixels.shape
    band = max(2, round(min(h, w)/40))
    border = np.zeros((h, w), dtype=bool)
    border[:band] = border[-band:] = True
    border[:, :band] = border[:, -band:] = True
    inset_y, inset_x = max(band, h//4), max(band, w//4)
    interior = pixels[inset_y:h-inset_y, inset_x:w-inset_x]
    if not interior.size:
        return _full_image(pixels.shape, 'Image has no interior sample')
    outside_level = float(np.median(pixels[border]))
    inside_level = float(np.median(interior))
    contrast = inside_level-outside_level
    spread = float(np.percentile(pixels, 95)-np.percentile(pixels, 5))
    required = max(2., .08*max(spread, 1.))
    if contrast <= required:
        return _full_image(pixels.shape, 'No darker surrounding frame was established',
                           border_median_adu=outside_level,
                           interior_median_adu=inside_level,
                           boundary_contrast_adu=contrast)

    sigma = max(1.5, min(h, w)/160.)
    smooth = gaussian_filter(pixels, sigma)
    threshold = outside_level+.35*contrast
    components, count = label(smooth > threshold)
    if not count:
        return _full_image(pixels.shape, 'No coherent illuminated footprint was found',
                           border_median_adu=outside_level,
                           interior_median_adu=inside_level,
                           boundary_contrast_adu=contrast)
    sizes = np.bincount(components.ravel())
    sizes[0] = 0
    chosen = int(np.argmax(sizes))
    mask = components == chosen
    closing_iterations = max(1, round(sigma/2))
    mask = binary_closing(mask, iterations=closing_iterations)
    mask = binary_fill_holes(mask)
    fraction = float(mask.mean())
    if not .1 <= fraction <= .97:
        return _full_image(pixels.shape, 'Candidate footprint area was not credible',
                           border_median_adu=outside_level,
                           interior_median_adu=inside_level,
                           boundary_contrast_adu=contrast,
                           candidate_valid_pixel_fraction=fraction)
    inside_median = float(np.median(pixels[mask]))
    outside_median = float(np.median(pixels[~mask]))
    if inside_median-outside_median <= required:
        return _full_image(pixels.shape, 'Candidate footprint lacked exterior contrast',
                           border_median_adu=outside_level,
                           interior_median_adu=inside_level,
                           boundary_contrast_adu=contrast,
                           candidate_valid_pixel_fraction=fraction)
    return mask.astype(bool), dict(
        status='framed_footprint',
        method='image_luminance_connected_footprint',
        valid_pixel_fraction=fraction,
        threshold_adu=float(threshold),
        inside_median_adu=inside_median,
        outside_median_adu=outside_median,
        border_median_adu=outside_level,
        interior_median_adu=inside_level,
        boundary_contrast_adu=contrast,
        smoothing_sigma_px=float(sigma),
        connected_components=int(count),
        reason='Dominant illuminated field separated from a darker surrounding frame',
        metadata_used=False,
        ocr_used=False,
        code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )
