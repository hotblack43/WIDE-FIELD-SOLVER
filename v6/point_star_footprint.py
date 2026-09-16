"""Conservative image-only support masks for framed fisheye photographs."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from scipy.ndimage import (
    binary_closing,
    binary_erosion,
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


def centred_full_horizon(valid_mask):
    """Recognise a closed, near-circular horizon centred on the detector.

    This is deliberately stricter than the general sky-footprint inference:
    cropped, off-centre and elliptical fields remain valid detection domains,
    but they do not establish that the physical zenith is the image centre.
    """
    mask = np.asarray(valid_mask, dtype=bool)
    if mask.ndim != 2 or min(mask.shape) < 15:
        raise ValueError('A two-dimensional footprint at least 15 pixels wide is required')
    h, w = mask.shape
    image_centre = np.array([(w-1)/2., (h-1)/2.])
    result = dict(status='not_established', centre_px=image_centre.tolist(),
                  method='closed centred circular sky-footprint geometry',
                  reason='Saved sky footprint does not show a closed centred circular horizon',
                  metadata_used=False)
    yy, xx = np.nonzero(mask)
    if not len(xx) or mask.all():
        return result
    x0, x1 = int(xx.min()), int(xx.max())
    y0, y1 = int(yy.min()), int(yy.max())
    bbox_width, bbox_height = x1-x0+1, y1-y0+1
    bbox_centre = np.array([(x0+x1)/2., (y0+y1)/2.])
    offset = float(np.linalg.norm(bbox_centre-image_centre))
    aspect = float(bbox_width/bbox_height)
    fill = float(mask.sum()/(bbox_width*bbox_height))
    boundary = mask & ~binary_erosion(mask)
    by, bx = np.nonzero(boundary)
    design = np.column_stack([2.*bx, 2.*by, np.ones(len(bx))])
    circle_x, circle_y, constant = np.linalg.lstsq(
        design, bx.astype(float)**2+by.astype(float)**2, rcond=None)[0]
    circle_radius = float(np.sqrt(max(0., constant+circle_x**2+circle_y**2)))
    circle_distance = np.hypot(bx-circle_x, by-circle_y)
    circle_residual = (circle_distance-circle_radius)/max(circle_radius, 1e-12)
    circle_rms = float(np.sqrt(np.mean(circle_residual**2)))
    circle_p95 = float(np.percentile(np.abs(circle_residual), 95))
    bin_count = 72
    azimuth = np.mod(np.arctan2(by-circle_y, bx-circle_x), 2*np.pi)
    bins = np.minimum((azimuth/(2*np.pi)*bin_count).astype(int), bin_count-1)
    populated_bins = int(len(np.unique(bins)))
    circle_centre = np.array([circle_x, circle_y])
    circle_offset = float(np.linalg.norm(circle_centre-image_centre))
    closed = not (mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any())
    broad = min(bbox_width, bbox_height) >= .7*min(h, w)
    centred = circle_offset <= .03*min(h, w)
    round_enough = (.9 <= aspect <= 1.1 and .68 <= fill <= .86
                    and circle_radius >= .35*min(h, w)
                    and circle_rms <= .02 and circle_p95 <= .04
                    and populated_bins == bin_count)
    result.update(bounding_box_px=[x0, y0, x1, y1],
                  bounding_box_centre_px=bbox_centre.tolist(),
                  centre_offset_px=offset, bounding_box_aspect_ratio=aspect,
                  bounding_box_fill_fraction=fill, boundary_closed=bool(closed),
                  fitted_circle_centre_px=circle_centre.tolist(),
                  fitted_circle_centre_offset_px=circle_offset,
                  fitted_circle_radius_px=circle_radius,
                  circle_rms_fraction=circle_rms,
                  circle_p95_absolute_residual_fraction=circle_p95,
                  azimuth_bin_count=bin_count,
                  populated_azimuth_bins=populated_bins)
    if closed and broad and centred and round_enough and mask[round(image_centre[1]), round(image_centre[0])]:
        result.update(status='centred_full_horizon',
                      reason='Closed near-circular sky footprint is centred on the detector')
    elif closed and broad and mask[round(image_centre[1]), round(image_centre[0])]:
        result['reason'] = ('Footprint boundary circle fit, centring, or azimuth coverage is '
                            'inconsistent with a closed centred circular horizon')
    return result


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
