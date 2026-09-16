"""Standalone dot finding: image pixels -> candidate star centroids, no trails.

Uses a spatial background estimate and thresholded intensity barycentres.
Pixel centres have integer coordinates, x rightwards and y downwards.
Candidates are not catalogue identifications or an astrometric solution.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, label, maximum_filter

from point_star_footprint import infer_sky_footprint
from point_star_plotting import save_png


def detect_stars(image, detection_sigma=6., background_sigma=10., *, valid_mask=None):
    source_pixels = np.asarray(image)
    if valid_mask is None:
        valid_mask, footprint = infer_sky_footprint(source_pixels)
    else:
        valid_mask = np.asarray(valid_mask, dtype=bool)
        if valid_mask.shape != source_pixels.shape[:2]:
            raise ValueError('Sky-footprint mask shape differs from image')
        footprint = dict(status='supplied_mask', method='caller_supplied_boolean_mask',
                         valid_pixel_fraction=float(valid_mask.mean()),
                         reason='Caller supplied the image-domain validity mask',
                         metadata_used=False, ocr_used=False)
    pixels = np.asarray(image, dtype=float)
    saturated_pixels = pixels >= 250
    if pixels.ndim == 3 and pixels.shape[2] >= 3:
        saturated_pixels = np.any(pixels[..., :3] >= 250, axis=2)
        pixels = pixels[..., :3] @ np.array([.2126, .7152, .0722])
    if pixels.ndim != 2 or min(pixels.shape) < 15 or not np.isfinite(pixels).all():
        raise ValueError('A finite greyscale or RGB image at least 15 pixels wide is required')
    if detection_sigma <= 0 or background_sigma <= 0:
        raise ValueError('Detection and background scales must be positive')
    background = gaussian_filter(pixels, background_sigma)
    signal = pixels-background
    global_noise = max(float(1.4826*np.median(abs(signal-np.median(signal)))), .05)
    noise = np.maximum(global_noise, 1.2533*gaussian_filter(
        np.minimum(abs(signal), 3*global_noise), background_sigma))
    smooth = gaussian_filter(signal, .6)
    peaks = (smooth == maximum_filter(smooth, size=7)) & (smooth > detection_sigma*noise)
    yy, xx = np.nonzero(peaks)
    stars, rejected = [], []
    for y, x in zip(yy, xx):
        reason = 'unmeasured'
        # Grow the measurement window when a source is too wide for a stellar core.
        # Saturated blobs are retained as measurements, never classified as planets.
        for half in (4, 8, 16, 32):
            if min(x, y, pixels.shape[1]-1-x, pixels.shape[0]-1-y) < half+1:
                reason = 'image_edge_or_blob_truncated'
                break
            grid_y, grid_x = np.mgrid[-half:half+1, -half:half+1]
            annulus = np.maximum(abs(grid_x), abs(grid_y)) == half
            cut = signal[y-half:y+half+1, x-half:x+half+1].copy()
            cut -= np.median(cut[annulus])
            peak = float(cut[half, half])
            component, _ = label(cut > max(3*noise[y, x], .15*peak))
            centre_label = component[half, half]
            mask = (component == centre_label) if centre_label else np.zeros(cut.shape, bool)
            area = int(mask.sum())
            if area < 3:
                reason = 'too_small'
                if peak < 3*noise[y, x]:
                    # A small window samples the flat top of a broad source as sky.
                    # Try a wider annulus before deciding there is no source.
                    continue
                break
            if np.any(mask[annulus]) or (half == 4 and area > 55):
                reason = 'extended_or_blended'
                continue
            weights = np.where(mask, cut, 0)
            flux = float(weights.sum())
            cx, cy = float((weights*grid_x).sum()/flux), float((weights*grid_y).sum()/flux)
            dx, dy = grid_x-cx, grid_y-cy
            covariance = np.array([[(weights*dx*dx).sum(), (weights*dx*dy).sum()],
                                   [(weights*dx*dy).sum(), (weights*dy*dy).sum()]])/flux
            minor2, major2 = np.linalg.eigvalsh(covariance)
            ratio = float(np.sqrt(major2/max(minor2, 1e-12)))
            width = float(np.sqrt(max(major2, 0)))
            saturated = bool(np.any(saturated_pixels[y-half:y+half+1, x-half:x+half+1][mask]))
            if minor2 < .16:
                reason = 'too_sharp'
                break
            elif ratio > (6. if saturated else 2.5):
                reason = 'elongated'
                break
            elif half == 4 and width > 2.2:
                reason = 'extended_or_blended'
                continue
            elif np.hypot(cx, cy) > max(2, half*.75):
                reason = 'off_centre_or_blended'
                continue
            else:
                stars.append(dict(x_px=float(x+cx), y_px=float(y+cy),
                    flux_above_background=flux, peak_above_background=peak,
                    peak_snr=float(peak/noise[y, x]), area_px=area,
                    major_sigma_px=width, axis_ratio=ratio, saturated=saturated,
                    source_class='compact' if half == 4 else 'broad_blob',
                    measurement_half_window_px=half))
                reason = None
                break
        if reason:
            rejected.append(dict(x_px=int(x), y_px=int(y), reason=reason))
    stars.sort(key=lambda s: -s['flux_above_background'])
    # Saturation can create several maxima around one plateau. Keep one centroid.
    unique = []
    for candidate in stars:
        duplicate = any(
            (s['source_class'] == 'broad_blob' or candidate['source_class'] == 'broad_blob') and
            np.hypot(s['x_px']-candidate['x_px'], s['y_px']-candidate['y_px']) <
            max(3., min(16., 2*max(s['major_sigma_px'], candidate['major_sigma_px'])))
            for s in unique)
        if duplicate:
            rejected.append(dict(x_px=candidate['x_px'], y_px=candidate['y_px'],
                                 reason='duplicate_peak_in_blob'))
        else:
            unique.append(candidate)
    stars = []
    outside = []
    for candidate in unique:
        x = int(np.clip(round(candidate['x_px']), 0, valid_mask.shape[1]-1))
        y = int(np.clip(round(candidate['y_px']), 0, valid_mask.shape[0]-1))
        if valid_mask[y, x]:
            stars.append(candidate)
        else:
            outside.append(dict(x_px=candidate['x_px'], y_px=candidate['y_px'],
                                reason='outside_sky_footprint'))
    rejected.extend(outside)
    for i, star in enumerate(stars, 1):
        star['detection_id'] = i
    return stars, dict(background=background, signal=signal, noise=noise,
                      global_noise=global_noise, rejected=rejected,
                      local_maxima_count=len(xx), valid_mask=valid_mask,
                      footprint=footprint, frame_sources_rejected=len(outside))


def write_products(image_path, output, detection_sigma=6., background_sigma=10.):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    image_path = Path(image_path).expanduser().resolve()
    output = Path(output)
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite output directory: {output}')
    rgb = np.asarray(Image.open(image_path).convert('RGB'))
    stars, audit = detect_stars(rgb, detection_sigma, background_sigma)
    output.mkdir(parents=True)
    fields = ['detection_id', 'x_px', 'y_px', 'flux_above_background',
              'peak_above_background', 'peak_snr', 'area_px', 'major_sigma_px',
              'axis_ratio', 'saturated', 'source_class', 'measurement_half_window_px']
    with (output/'star_candidates.csv').open('w') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(stars)
    with (output/'rejected_candidates.csv').open('w') as handle:
        writer = csv.DictWriter(handle, fieldnames=['x_px', 'y_px', 'reason'])
        writer.writeheader()
        writer.writerows(audit['rejected'])
    summary = dict(status='point_sources_detected' if stars else 'no_point_sources',
        source=str(image_path), source_sha256=hashlib.sha256(image_path.read_bytes()).hexdigest(),
        code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        width_px=rgb.shape[1], height_px=rgb.shape[0], candidates=len(stars),
        compact_sources=sum(s['source_class'] == 'compact' for s in stars),
        broad_blobs=sum(s['source_class'] == 'broad_blob' for s in stars),
        saturated_sources=sum(s['saturated'] for s in stars),
        local_maxima=audit['local_maxima_count'], rejected=len(audit['rejected']),
        detection_sigma=detection_sigma, background_sigma_px=background_sigma,
        global_noise_adu=audit['global_noise'], source_resized=False,
        footprint_status=audit['footprint']['status'],
        footprint_method=audit['footprint']['method'],
        sky_footprint=audit['footprint'],
        valid_sky_pixel_fraction=audit['footprint']['valid_pixel_fraction'],
        frame_sources_rejected=audit['frame_sources_rejected'],
        footprint_reason=audit['footprint']['reason'],
        ocr_used=False,
        metadata_used=False, coordinate_convention='integer pixel centres; x right, y down',
        astrometry_attempted=False,
        limitation='Detection is restricted to an image-only sky footprint; no OCR or semantic '
                   'obstruction recognition is attempted, and text inside the field is unsupported. '
                   'Measured candidates are not verified stars or planets; foreground lights can survive. '
                   'Close blends, strongly distorted stars and faint stars may be omitted. '
                   'Flux is a thresholded JPEG intensity diagnostic, not calibrated photometry.')
    (output/'detection.json').write_text(json.dumps(summary, indent=2)+'\n')
    fig, ax = plt.subplots(figsize=(12, 11))
    ax.imshow(rgb)
    valid_mask = audit['valid_mask']
    if not valid_mask.all():
        ax.contour(valid_mask.astype(float), levels=[.5], colors=['#ffeb3b'],
                   linewidths=.8)
    if stars:
        xy = np.array([[s['x_px'], s['y_px']] for s in stars])
        for source_class, color in [('compact', 'cyan'), ('broad_blob', 'orange')]:
            select = np.array([s['source_class'] == source_class for s in stars])
            ax.scatter(*xy[select].T, s=18 if source_class == 'compact' else 65,
                       facecolors='none', edgecolors=color, linewidths=.6,
                       label=f'{source_class}: {int(select.sum())}')
        ax.legend(fontsize=8)
        for s in stars[:60]:
            ax.annotate(str(s['detection_id']), (s['x_px'], s['y_px']),
                        xytext=(4, 4), textcoords='offset points', color='yellow', fontsize=6)
    ax.set_title(f'{len(stars)} candidates; orange = broad blobs; brightest 60 numbered')
    ax.set_xlim(-.5, rgb.shape[1]-.5)
    ax.set_ylim(rgb.shape[0]-.5, -.5)
    fig.tight_layout()
    save_png(fig, output/'dots_overlay.png', dpi=180)
    plt.close(fig)
    np.savez_compressed(output/'sky_footprint.npz', valid_mask=valid_mask.astype(bool))
    fig, ax = plt.subplots(figsize=(12, 11))
    ax.imshow(rgb)
    if not valid_mask.all():
        shade = np.zeros((*valid_mask.shape, 4), dtype=float)
        shade[~valid_mask] = [1., 0., 0., .42]
        ax.imshow(shade)
        ax.contour(valid_mask.astype(float), levels=[.5], colors=['#ffeb3b'],
                   linewidths=1.)
    ax.set(xlim=(-.5, rgb.shape[1]-.5), ylim=(rgb.shape[0]-.5, -.5),
           title=('Accepted sky footprint; red pixels are excluded'
                  if not valid_mask.all() else 'Accepted sky footprint: complete image'))
    ax.axis('off')
    fig.tight_layout()
    save_png(fig, output/'sky_footprint.png', dpi=160)
    plt.close(fig)
    # Sample the complete brightness distribution, not just the most obvious stars.
    if stars:
        selected = np.unique(np.linspace(0, len(stars)-1, min(64, len(stars))).astype(int))
        fig, axes = plt.subplots(8, 8, figsize=(12, 12))
        for ax in axes.flat:
            ax.axis('off')
        for ax, i in zip(axes.flat, selected):
            s = stars[i]
            x, y = round(s['x_px']), round(s['y_px'])
            x0, x1 = max(0, x-12), min(rgb.shape[1], x+13)
            y0, y1 = max(0, y-12), min(rgb.shape[0], y+13)
            ax.imshow(rgb[y0:y1, x0:x1], extent=(x0-.5, x1-.5, y1-.5, y0-.5))
            ax.plot(s['x_px'], s['y_px'], '+', color='cyan', ms=7, mew=.7)
            ax.set_title(f"#{s['detection_id']} {s['source_class']}" + (' SAT' if s['saturated'] else ''), fontsize=6)
        fig.suptitle('Candidate cutouts spanning the brightness ranking')
        fig.tight_layout()
        save_png(fig, output/'candidate_cutouts.png', dpi=140)
        plt.close(fig)
    np.savez_compressed(output/'background_diagnostics.npz',
                        background=audit['background'].astype('float32'),
                        noise=audit['noise'].astype('float32'))
    print(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--detection-sigma', type=float, default=6.)
    parser.add_argument('--background-sigma', type=float, default=10.)
    args = parser.parse_args()
    write_products(args.image, args.output, args.detection_sigma, args.background_sigma)


if __name__ == '__main__':
    main()
