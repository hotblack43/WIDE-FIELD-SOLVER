"""Measured/predicted overlays and centre-to-edge residuals, without refitting."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image


def radial_statistics(measured, predicted, shape, bin_width=200.):
    measured, predicted = np.asarray(measured, dtype=float), np.asarray(predicted, dtype=float)
    if measured.ndim != 2 or measured.shape[1:] != (2,) or not len(measured):
        raise ValueError('At least one measured x/y pair is required')
    if predicted.shape != measured.shape or not np.isfinite([measured, predicted]).all():
        raise ValueError('Measured and predicted positions must be finite paired x/y arrays')
    if not np.isfinite(bin_width) or bin_width <= 0:
        raise ValueError('Radial bin width must be positive and finite')
    centre = (np.array(shape[::-1])-1)/2
    offset = measured-centre
    radius = np.linalg.norm(offset, axis=1)
    delta = predicted-measured
    residual = np.linalg.norm(delta, axis=1)
    noncentral = radius > 0
    radial = np.zeros(len(radius))
    radial[noncentral] = np.sum(delta[noncentral]*offset[noncentral], axis=1)/radius[noncentral]
    limit = max(np.linalg.norm(centre), float(radius.max()))
    bins = []
    for low in np.arange(int(np.floor(limit/bin_width))+1)*bin_width:
        keep = (radius >= low) & (radius < low+bin_width)
        radial_keep = keep & noncentral
        count = int(keep.sum())
        bins.append(dict(radius_low_px=float(low), radius_high_px=float(low+bin_width),
            count=count,
            rms_px=float(np.sqrt(np.mean(residual[keep]**2))) if count else None,
            median_px=float(np.median(residual[keep])) if count else None,
            p90_px=float(np.percentile(residual[keep], 90)) if count else None,
            maximum_px=float(residual[keep].max()) if count else None,
            mean_radial_offset_px=float(np.mean(radial[radial_keep])) if radial_keep.any() else None))
    return dict(centre_xy_px=centre.tolist(), radius_definition='distance from geometric image centre',
        count=len(measured), rms_px=float(np.sqrt(np.mean(residual**2))),
        maximum_residual_px=float(residual.max()), maximum_measured_radius_px=float(radius.max()),
        radial_sign='predicted minus measured; positive points away from image centre',
        selection='All fitted associations, with no extra clipping; no stars withheld. '
                  'The solver selected associations with a 3-pixel gate before its final fit. '
                  'Unmatched sources and empty radial regions have no evaluated residual.',
        bins=bins)


def create_overlay(rgb, measured, predicted, *, unmatched=None):
    fig, ax = plt.subplots(figsize=(14, 13), layout='constrained')
    ax.imshow(rgb)
    if unmatched is not None and len(unmatched):
        ax.scatter(*np.asarray(unmatched).T, marker='x', s=26, c='#ff70d5',
                   linewidths=.9, label='Unmatched detections')
    ax.scatter(*np.asarray(predicted).T, marker='o', s=28, facecolors='none',
               edgecolors='#ff9933', linewidths=.65, label='Catalogue predictions')
    ax.scatter(*np.asarray(measured).T, marker='+', s=16, c='#40e9ff',
               linewidths=.65, label='Measured centroids')
    ax.set_xlim(-.5, rgb.shape[1]-.5)
    ax.set_ylim(rgb.shape[0]-.5, -.5)
    ax.set_xlabel('x [pixel]')
    ax.set_ylabel('y [pixel]')
    ax.set_title(f'Barghini: measured and predicted positions — {len(measured):,} fitted pairs\n'
                 'True positions; offsets are not magnified. Zoom in to inspect individual pairs.')
    ax.legend(loc='upper right', facecolor='black', labelcolor='white', framealpha=.9)
    return fig


def write_diagnostics(image_path, measured, predicted, output, *, unmatched=None):
    output = Path(output)
    rgb = np.asarray(Image.open(image_path).convert('RGB'))
    measured, predicted = np.asarray(measured), np.asarray(predicted)
    report = radial_statistics(measured, predicted, rgb.shape[:2])
    report['unmatched_detections_shown'] = len(unmatched) if unmatched is not None else 0
    fig = create_overlay(rgb, measured, predicted, unmatched=unmatched)
    fig.savefig(output/'astrometry_overlay.png', dpi=220)
    plt.close(fig)
    centre = np.asarray(report['centre_xy_px'])
    radius = np.linalg.norm(measured-centre, axis=1)
    delta = predicted-measured
    residual = np.linalg.norm(delta, axis=1)
    fig, axes = plt.subplots(1, 2, figsize=(15, 7), layout='constrained')
    ax = axes[0]
    ax.imshow(rgb, alpha=.65)
    vectors = ax.quiver(*measured.T, *delta.T, angles='xy', scale_units='xy',
                       scale=.05, color='#00d9ed', width=.0014)
    ax.quiverkey(vectors, .12, .96, 1., '1 px residual (×20)', coordinates='axes',
                 labelpos='E', color='black')
    ax.set_xlim(-.5, rgb.shape[1]-.5)
    ax.set_ylim(rgb.shape[0]-.5, -.5)
    ax.set_title('Residual direction: measured → predicted\nArrows magnified ×20')
    ax.set_xlabel('x [pixel]')
    ax.set_ylabel('y [pixel]')
    ax = axes[1]
    ax.scatter(radius, residual, s=5, alpha=.24, c='#32659b', label='Every fitted association')
    populated = [b for b in report['bins'] if b['count']]
    midpoints = [(b['radius_low_px']+b['radius_high_px'])/2 for b in populated]
    for name, label, colour in [('rms_px', 'RMS', '#c54c00'), ('median_px', 'Median', '#006852'),
                                ('p90_px', '90th percentile', '#7952a0')]:
        ax.plot(midpoints, [b[name] for b in populated], 'o-', color=colour, label=label)
    limit = np.linalg.norm(centre)
    ax.set_xlim(0, max(limit, radius.max()))
    ax.set_ylim(0, max(1., float(residual.max())*1.1))
    for b in report['bins']:
        if not b['count']:
            continue
        midpoint = (b['radius_low_px']+b['radius_high_px'])/2
        ax.text(midpoint, .97, f"n={b['count']}", transform=ax.get_xaxis_transform(),
                ha='center', va='top', fontsize=9)
    if radius.max() < limit:
        ax.axvspan(radius.max(), limit, facecolor='.9', hatch='///', edgecolor='.7',
                   label='No matched sources at these radii')
    ax.set_title(f"Centre-to-edge residuals — RMS {report['rms_px']:.3f} px\n"
                 'Distance from geometric image centre; 200-pixel bins')
    ax.set_xlabel('Distance from image centre [pixel]')
    ax.set_ylabel('Predicted − measured separation [pixel]')
    ax.grid(alpha=.2)
    ax.legend(loc='upper left', bbox_to_anchor=(0, .91), fontsize=9)
    fig.supxlabel('Fitted associations only; no additional clipping. Empty regions and unmatched detections are untested.', fontsize=10)
    fig.savefig(output/'astrometry_residuals.png', dpi=180)
    plt.close(fig)
    (output/'radial_residuals.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    with (output/'radial_residuals.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(report['bins'][0]))
        writer.writeheader()
        writer.writerows(report['bins'])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--solution', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    image = args.image.expanduser().resolve()
    result = json.loads((args.solution/'result.json').read_text())
    if hashlib.sha256(image.read_bytes()).hexdigest() != result['source_sha256']:
        parser.error('The image does not match this astrometric solution')
    with (args.solution/'star_coordinates.csv').open() as handle:
        rows = list(csv.DictReader(handle))
    measured = np.array([[float(r['x_px']), float(r['y_px'])] for r in rows])
    predicted = np.array([[float(r['predicted_x_px']), float(r['predicted_y_px'])] for r in rows])
    unmatched = None
    candidates = args.solution/'dots/star_candidates.csv'
    if candidates.exists():
        matched_ids = {r['detection_id'] for r in rows}
        with candidates.open() as handle:
            unmatched = np.array([[float(r['x_px']), float(r['y_px'])]
                                  for r in csv.DictReader(handle) if r['detection_id'] not in matched_ids])
    args.output.mkdir(parents=True, exist_ok=False)
    report = write_diagnostics(image, measured, predicted, args.output, unmatched=unmatched)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
